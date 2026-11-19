#!/usr/bin/python3
"""Dedicated Xray UDP transport and owned static L2TPv3 sessions. No shell evaluation."""
import argparse
import base64
import contextlib
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile


class ConfigError(ValueError):
    pass


class Disabled(ConfigError):
    pass


FIELDS = {'enabled', 'role', 'security', 'proxy_port', 'target_address', 'target_port',
          'server', 'server_port', 'server_name', 'uuid', 'flow', 'egress_device',
          'listen_address', 'certificate_file', 'certificate_key_file', 'ca_certificate_file', 'reality_public_key',
          'reality_private_key_file', 'reality_short_id', 'reality_target'}


def parse_uci(text):
    if len(text.encode()) > 65536:
        raise ConfigError('Configuration too large')
    words = shlex.split(text, comments=True)
    if words[:2] == ['package', 'neko-l2vpn']:
        words = words[2:]
    if words[:3] != ['config', 'transport', 'main']:
        raise ConfigError('Expected one named transport section: main')
    words, values = words[3:], {}
    if len(words) % 3:
        raise ConfigError('Invalid UCI options')
    for i in range(0, len(words), 3):
        command, name, value = words[i:i + 3]
        if command != 'option' or name not in FIELDS or name in values:
            raise ConfigError('Unknown or duplicate UCI option')
        values[name] = value
    return values


def text(values, name, default=''):
    value = values.get(name, default)
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ConfigError('Invalid text option: ' + name)
    return value


def required(values, name):
    value = text(values, name)
    if not value:
        raise ConfigError('Missing option: ' + name)
    return value


def number(value, low, high, name):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value) or not low <= int(value) <= high:
        raise ConfigError('Invalid number: ' + name)
    return int(value)


def address(value, name, wildcard=False):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        raise ConfigError('Invalid IP address: ' + name) from None
    if ip.is_multicast or (ip.is_unspecified and not wildcard) or '%' in value:
        raise ConfigError('Invalid endpoint: ' + name)
    return str(ip)


def hostname(value, name):
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if len(value) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in value.rstrip('.').split('.')):
        raise ConfigError('Invalid hostname: ' + name)
    return value


def device(value):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,14}', value):
        raise ConfigError('Invalid Linux device name')
    return value


def key32(value, name):
    try:
        decoded = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except ValueError:
        raise ConfigError('Invalid key: ' + name) from None
    if len(decoded) != 32 or not re.fullmatch(r'[A-Za-z0-9_-]{43}', value):
        raise ConfigError('Invalid key: ' + name)
    return value


def local_file(value, name, check):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or '\n' in value:
        raise ConfigError('Expected absolute local file: ' + name)
    # Certificate renewal symlinks are intentional and are followed here.
    if check and not path.is_file():
        raise ConfigError('Missing local file: ' + name)
    return value


def ip_json(*args):
    return json.loads(subprocess.check_output(['ip', '-j', *args], text=True))


def render_xray(values, check_runtime=False):
    if values.get('enabled', '0') == '0':
        raise Disabled('Transport disabled')
    if values.get('enabled') != '1' or set(values) - FIELDS:
        raise ConfigError('Invalid enable flag or unknown options')
    for name in values:
        text(values, name)
    role, security = required(values, 'role'), required(values, 'security')
    if role not in ('client', 'server') or security not in ('tls', 'reality'):
        raise ConfigError('Unsupported role or security')
    identity = required(values, 'uuid').lower()
    if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', identity):
        raise ConfigError('Invalid VLESS UUID')
    target = address(required(values, 'target_address'), 'target_address')
    target_port = number(required(values, 'target_port'), 1, 65535, 'target_port')
    port = number(text(values, 'server_port', '443'), 1, 65535, 'server_port')
    sni = hostname(required(values, 'server_name'), 'server_name')
    flow = text(values, 'flow')
    if flow not in ('', 'xtls-rprx-vision'):
        raise ConfigError('Unsupported VLESS flow')
    stream = {'network': 'tcp', 'security': security}
    if security == 'tls':
        tls = {'serverName': sni, 'minVersion': '1.2'}
        if role == 'client' and text(values, 'ca_certificate_file'):
            tls['certificates'] = [{'certificateFile': local_file(text(values, 'ca_certificate_file'), 'ca_certificate_file', check_runtime), 'usage': 'verify'}]
        if role == 'server':
            tls['certificates'] = [{
                'certificateFile': local_file(required(values, 'certificate_file'), 'certificate_file', check_runtime),
                'keyFile': local_file(required(values, 'certificate_key_file'), 'certificate_key_file', check_runtime)}]
        stream['tlsSettings'] = tls
    else:
        short_id = text(values, 'reality_short_id')
        if not re.fullmatch(r'(?:[0-9a-fA-F]{2}){0,8}', short_id):
            raise ConfigError('Invalid REALITY short ID')
        if role == 'client':
            reality = {'serverName': sni, 'fingerprint': 'chrome', 'shortId': short_id,
                       'publicKey': key32(required(values, 'reality_public_key'), 'reality_public_key')}
        else:
            path = local_file(required(values, 'reality_private_key_file'), 'reality_private_key_file', True)
            private = key32(Path(path).read_text().strip(), 'reality_private_key_file')
            destination = required(values, 'reality_target')
            host, sep, dest_port = destination.rpartition(':')
            if not sep:
                raise ConfigError('REALITY target must include a port')
            hostname(host.strip('[]'), 'reality_target')
            number(dest_port, 1, 65535, 'reality_target port')
            reality = {'target': destination, 'serverNames': [sni], 'privateKey': private, 'shortIds': [short_id]}
        stream['realitySettings'] = reality
    blocked = {'tag': 'blocked', 'protocol': 'blackhole'}
    if role == 'client':
        egress = device(required(values, 'egress_device'))
        if check_runtime:
            links = ip_json('-d', 'link', 'show', 'dev', egress)
            if len(links) != 1 or 'UP' not in links[0].get('flags', []) or links[0].get('linkinfo', {}).get('info_kind') == 'wireguard':
                raise ConfigError('Choose an active physical WAN or PPP egress device')
        stream['sockopt'] = {'interface': egress}
        server = hostname(required(values, 'server'), 'server')
        inbound = {'tag': 'wg-udp', 'listen': '127.0.0.1',
                   'port': number(text(values, 'proxy_port', '51821'), 1, 65535, 'proxy_port'),
                   'protocol': 'dokodemo-door', 'settings': {'address': target, 'port': target_port, 'network': 'udp'}}
        user = {'id': identity, 'encryption': 'none', 'flow': flow}
        outbound = {'tag': 'vless', 'protocol': 'vless', 'settings': {'vnext': [{'address': server, 'port': port, 'users': [user]}]}, 'streamSettings': stream}
        rules = [{'type': 'field', 'inboundTag': ['wg-udp'], 'network': 'udp', 'outboundTag': 'vless'}]
        outbounds = [blocked, outbound]
    else:
        inbound = {'tag': 'wg-vless', 'listen': address(required(values, 'listen_address'), 'listen_address', wildcard=True),
                   'port': port, 'protocol': 'vless', 'settings': {'decryption': 'none', 'clients': [{'id': identity, 'flow': flow}]}, 'streamSettings': stream}
        mask = '/32' if ':' not in target else '/128'
        rules = [{'type': 'field', 'inboundTag': ['wg-vless'], 'network': 'udp', 'ip': [target + mask], 'port': str(target_port), 'outboundTag': 'wg-target'}]
        outbounds = [blocked, {'tag': 'wg-target', 'protocol': 'freedom'}]
    return {'log': {'loglevel': 'warning'}, 'inbounds': [inbound], 'outbounds': outbounds,
            'routing': {'domainStrategy': 'AsIs', 'rules': rules}}


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise ConfigError('Runtime directory must not be a symlink')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def write_private(path, value):
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ConfigError('Invalid output file')
    fd, temporary = tempfile.mkstemp(prefix='.l2vpn-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, indent=2)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def interface_name(name):
    if not re.fullmatch(r'[A-Za-z0-9_]{1,11}', name):
        raise ConfigError('L2TP interface name must contain 1-11 letters, digits or underscores')
    return 'nl2-' + name


def ip_run(*args):
    subprocess.run(['ip', *map(str, args)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@contextlib.contextmanager
def link_state(root):
    root = private_dir(root)
    fd = os.open(root/'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield root
    finally:
        os.close(fd)


def l2tp_up(args, root):
    ifname = interface_name(args.name)
    underlay = device(args.underlay)
    local = address(args.local, 'local')
    peer = address(args.peer, 'peer')
    if ':' in local or ':' in peer or local == peer:
        raise ConfigError('L2TP underlay requires two distinct IPv4 addresses')
    ids = {name: number(getattr(args, name), 1, 4294967295, name)
           for name in ('tunnel_id', 'peer_tunnel_id', 'session_id', 'peer_session_id')}
    sport, dport = (number(getattr(args, name), 1, 65535, name) for name in ('local_port', 'peer_port'))
    mtu = number(args.mtu, 1280, 9000, 'mtu')
    links = ip_json('-d', 'link', 'show', 'dev', underlay)
    if len(links) != 1 or links[0].get('linkinfo', {}).get('info_kind') != 'wireguard' or 'UP' not in links[0].get('flags', []):
        raise ConfigError('An active kernel WireGuard device is required')
    if mtu + 50 > links[0]['mtu']:
        raise ConfigError('L2 MTU plus 50 bytes exceeds WireGuard MTU')
    addresses = ip_json('address', 'show', 'dev', underlay)
    if not any(a.get('local') == local for link in addresses for a in link.get('addr_info', [])):
        raise ConfigError('Local tunnel address is not assigned to WireGuard')
    route = ip_json('route', 'get', peer, 'from', local)
    if not route or any(row.get('dev') != underlay for row in route):
        raise ConfigError('Peer route must use the selected WireGuard device')
    with link_state(root) as state_dir:
        state = state_dir/(args.name + '.json')
        if state.exists() or state.is_symlink():
            raise ConfigError('Existing session state: bring the old interface down first')
        tunnel_created = session_created = False
        try:
            ip_run('l2tp', 'add', 'tunnel', 'tunnel_id', ids['tunnel_id'], 'peer_tunnel_id', ids['peer_tunnel_id'],
                   'encap', 'udp', 'local', local, 'remote', peer, 'udp_sport', sport, 'udp_dport', dport)
            tunnel_created = True
            ip_run('l2tp', 'add', 'session', 'tunnel_id', ids['tunnel_id'], 'session_id', ids['session_id'],
                   'peer_session_id', ids['peer_session_id'], 'name', ifname, 'l2spec_type', 'none')
            session_created = True
            ip_run('link', 'set', 'dev', ifname, 'mtu', mtu, 'up')
            write_private(state, {'tunnel_id': ids['tunnel_id'], 'session_id': ids['session_id']})
        except BaseException:
            if session_created:
                with contextlib.suppress(subprocess.CalledProcessError):
                    ip_run('l2tp', 'del', 'session', 'tunnel_id', ids['tunnel_id'], 'session_id', ids['session_id'])
            if tunnel_created:
                with contextlib.suppress(subprocess.CalledProcessError):
                    ip_run('l2tp', 'del', 'tunnel', 'tunnel_id', ids['tunnel_id'])
            raise


def l2tp_down(name, root):
    interface_name(name)
    with link_state(root) as state_dir:
        state = state_dir/(name + '.json')
        if state.is_symlink():
            raise ConfigError('Session state must not be a symlink')
        if not state.exists():
            return
        values = json.loads(state.read_text())
        tid = number(str(values['tunnel_id']), 1, 4294967295, 'tunnel_id')
        sid = number(str(values['session_id']), 1, 4294967295, 'session_id')
        with contextlib.suppress(subprocess.CalledProcessError):
            ip_run('l2tp', 'del', 'session', 'tunnel_id', tid, 'session_id', sid)
        ip_run('l2tp', 'del', 'tunnel', 'tunnel_id', tid)
        state.unlink()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    render = sub.add_parser('render')
    render.add_argument('--uci-file', type=Path)
    render.add_argument('--output', required=True, type=Path)
    render.add_argument('--check-runtime', action='store_true')
    up = sub.add_parser('l2tp-up')
    for name in ('name', 'underlay', 'local', 'peer', 'tunnel-id', 'peer-tunnel-id', 'session-id', 'peer-session-id', 'local-port', 'peer-port', 'mtu'):
        up.add_argument('--' + name, required=True)
    down = sub.add_parser('l2tp-down')
    down.add_argument('--name', required=True)
    args = parser.parse_args()
    root = Path(os.environ.get('L2VPN_LINK_RUN', '/var/run/neko-l2vpn-links'))
    if args.command == 'render':
        raw = args.uci_file.read_text() if args.uci_file else subprocess.check_output(['uci', '-q', 'export', 'neko-l2vpn'], text=True)
        write_private(args.output, render_xray(parse_uci(raw), args.check_runtime))
    elif args.command == 'l2tp-up':
        l2tp_up(args, root)
    else:
        l2tp_down(args.name, root)


if __name__ == '__main__':
    try:
        main()
    except Disabled:
        sys.exit(3)
    except ConfigError as exc:
        print('neko-l2vpn: ' + str(exc), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        # Never echo UUIDs, private keys, native parser diagnostics or raw UCI.
        print('neko-l2vpn: configuration or runtime operation failed', file=sys.stderr)
        sys.exit(1)
