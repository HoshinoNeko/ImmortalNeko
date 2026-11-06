#!/usr/bin/python3
"""Translate local legacy UCI into private V2Ray v4-format JSON, without shell evaluation."""
import argparse
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


def parse_uci(text):
    if len(text.encode()) > 2 * 1024 * 1024:
        raise ConfigError('UCI input is too large')
    sections, current, pending = [], None, ''
    for line in text.splitlines(keepends=True):
        pending += line
        try:
            words = shlex.split(pending, comments=True)
        except ValueError:
            continue  # UCI quoted values can contain newlines.
        pending = ''
        if not words:
            continue
        if words[0] == 'package' and words == ['package', 'v2ray_server']:
            continue
        if words[0] == 'config' and len(words) in (2, 3):
            if not all(re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in words[1:]):
                raise ConfigError('Invalid UCI section identifier')
            current = {'type': words[1], 'values': {}}
            sections.append(current)
        elif words[0] in ('option', 'list') and len(words) == 3 and current is not None:
            name, value = words[1:]
            if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
                raise ConfigError('Invalid UCI option identifier')
            values = current['values']
            if words[0] == 'list':
                if name in values and not isinstance(values[name], list):
                    raise ConfigError('Mixed option and list values')
                values.setdefault(name, []).append(value)
            else:
                if name in values:
                    raise ConfigError('Duplicate UCI option')
                values[name] = value
        else:
            raise ConfigError('Unsupported UCI syntax')
    if pending.strip():
        raise ConfigError('Unterminated UCI value')
    return sections


def scalar(values, field, default=None):
    value = values.get(field, default)
    if value is not None and not isinstance(value, str):
        raise ConfigError('Expected a scalar option: ' + field)
    return value


def flag(values, field, default=False):
    value = scalar(values, field)
    if value is None:
        return default
    if value.lower() in ('1', 'true', 'yes', 'on'):
        return True
    if value.lower() in ('0', 'false', 'no', 'off'):
        return False
    raise ConfigError('Invalid boolean option: ' + field)


def integer(values, field, low, high, default=None):
    value = scalar(values, field, default)
    if value is None or not re.fullmatch(r'[0-9]+', value) or not low <= int(value) <= high:
        raise ConfigError('Invalid numeric option: ' + field)
    return int(value)


def required(values, field):
    value = scalar(values, field)
    if value is None or value == '':
        raise ConfigError('Missing required option: ' + field)
    return value


def items(values, field):
    value = values.get(field, [])
    result = value if isinstance(value, list) else [value]
    if not all(isinstance(item, str) and item for item in result):
        raise ConfigError('Invalid list option: ' + field)
    return result


def choice(values, field, allowed, default=None):
    value = scalar(values, field, default)
    if value not in allowed:
        raise ConfigError('Unsupported choice: ' + field)
    return value


def settings(values, protocol):
    level = integer(values, 'level', 0, 255 if protocol == 'shadowsocks' else 2**32 - 1, '0')
    if protocol == 'shadowsocks':
        return {'method': choice(values, 'method', {'aes-128-gcm', 'aes-256-gcm', 'chacha20-poly1305', 'chacha20-ietf-poly1305'}),
                'password': required(values, 'password'),
                'network': choice(values, 'ss_network', {'tcp', 'udp', 'tcp,udp'}, 'tcp,udp'),
                'level': level}
    if protocol in ('vmess', 'vless'):
        identities = items(values, 'uuid')
        if not identities or any(not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', item) for item in identities):
            raise ConfigError('A valid UUID is required')
        clients = [{'id': item, 'level': level} for item in identities]
        if protocol == 'vmess':
            for client in clients:
                client['alterId'] = integer(values, 'alter_id', 0, 65535, '0')
            return {'clients': clients}
        return {'clients': clients, 'decryption': 'none'}
    if protocol == 'trojan':
        return {'clients': [{'password': required(values, 'password'), 'level': level}]}
    result = {'accounts': [{'user': required(values, 'username'), 'pass': required(values, 'password')}], 'userLevel': level}
    if protocol == 'socks':
        result.update(auth='password', udp=flag(values, 'socks_udp'))
    return result


def stream(values, check_files=False):
    transport = choice(values, 'transport', {'tcp', 'ws', 'h2', 'kcp', 'quic', 'grpc'}, 'tcp')
    result = {'network': transport, 'security': 'tls' if flag(values, 'tls') else 'none'}
    if transport == 'tcp':
        result['tcpSettings'] = {'header': {'type': choice(values, 'tcp_guise', {'none', 'http'}, 'none')}}
    elif transport == 'ws':
        result['wsSettings'] = {'path': scalar(values, 'ws_path', '/')}
        if scalar(values, 'ws_host'):
            result['wsSettings']['headers'] = {'Host': scalar(values, 'ws_host')}
    elif transport == 'h2':
        result['httpSettings'] = {'path': scalar(values, 'h2_path', '/')}
        if items(values, 'h2_host'):
            result['httpSettings']['host'] = items(values, 'h2_host')
    elif transport == 'grpc':
        result['grpcSettings'] = {'serviceName': scalar(values, 'grpc_service_name', '')}
    else:
        guise = choice(values, transport + '_guise', {'none', 'srtp', 'utp', 'wechat-video', 'dtls', 'wireguard'}, 'none')
        detail = {'header': {'type': guise}}
        if transport == 'kcp':
            fields = {'kcp_mtu': ('mtu', 576, 1460), 'kcp_tti': ('tti', 10, 100),
                      'kcp_uplink': ('uplinkCapacity', 0, 10000), 'kcp_downlink': ('downlinkCapacity', 0, 10000),
                      'kcp_read_buffer': ('readBufferSize', 0, 1024), 'kcp_write_buffer': ('writeBufferSize', 0, 1024)}
            for field, (target, low, high) in fields.items():
                if field in values:
                    detail[target] = integer(values, field, low, high)
            if 'kcp_congestion' in values:
                detail['congestion'] = flag(values, 'kcp_congestion')
            if scalar(values, 'kcp_seed'):
                detail['seed'] = scalar(values, 'kcp_seed')
        else:
            detail['security'] = choice(values, 'quic_security', {'none', 'aes-128-gcm', 'chacha20-poly1305'}, 'none')
            detail['key'] = scalar(values, 'quic_key', '')
        result[transport + 'Settings'] = detail
    if result['security'] == 'tls':
        cert = required(values, 'tls_cert')
        material = required(values, 'tls_key')
        for path in (cert, material):
            if not path.startswith('/') or any(ord(c) < 32 for c in path):
                raise ConfigError('TLS files require absolute local paths')
            if check_files and (not os.path.isfile(path) or not os.access(path, os.R_OK)):
                raise ConfigError('TLS file is unavailable')
        detail = {'certificates': [{'certificateFile': cert, 'keyFile': material}]}
        if scalar(values, 'tls_servername'):
            detail['serverName'] = scalar(values, 'tls_servername')
        if items(values, 'tls_alpn'):
            detail['alpn'] = items(values, 'tls_alpn')
        result['tlsSettings'] = detail
    return result


USER_FIELDS = {
    'enable', 'remarks', 'protocol', 'port', 'listen', 'bind_local', 'level',
    'password', 'method', 'ss_network', 'uuid', 'alter_id', 'username', 'socks_udp',
    'transport', 'tcp_guise', 'ws_path', 'ws_host', 'h2_path', 'h2_host', 'grpc_service_name',
    'kcp_guise', 'kcp_seed', 'kcp_mtu', 'kcp_tti', 'kcp_uplink', 'kcp_downlink',
    'kcp_congestion', 'kcp_read_buffer', 'kcp_write_buffer', 'quic_guise',
    'quic_security', 'quic_key', 'tls', 'tls_cert', 'tls_key', 'tls_servername', 'tls_alpn'
}
PRIVATE_DESTINATIONS = ['0.0.0.0/8', '10.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16', '172.16.0.0/12',
                        '192.168.0.0/16', '224.0.0.0/4', '240.0.0.0/4', '::/128', '::1/128', 'fc00::/7', 'fe80::/10', 'ff00::/8']


def build_config(sections, check_files=False):
    globals_ = [s['values'] for s in sections if s['type'] == 'global']
    if len(globals_) != 1 or any(s['type'] not in ('global', 'user') for s in sections):
        raise ConfigError('Expected one global section and user sections only')
    main = globals_[0]
    if not flag(main, 'enable'):
        raise Disabled('Service is disabled')
    if set(main) - {'enable', 'accept_lan', 'loglevel'}:
        raise ConfigError('Unsupported global options')
    inbounds, listeners = [], []
    for section in sections:
        values = section['values']
        if section['type'] != 'user' or not flag(values, 'enable'):
            continue
        if set(values) - USER_FIELDS:
            raise ConfigError('Unsupported enabled user options; review the legacy configuration')
        protocol = choice(values, 'protocol', {'shadowsocks', 'vmess', 'vless', 'trojan', 'socks', 'http'})
        listen = scalar(values, 'listen')
        if flag(values, 'bind_local'):
            listen = listen if listen in ('127.0.0.1', '::1') else '127.0.0.1'
        if not listen or '/' in listen or '%' in listen:
            raise ConfigError('Select an explicit listener IP for each enabled user')
        try:
            address = ipaddress.ip_address(listen)
        except ValueError:
            raise ConfigError('Invalid listener IP') from None
        port = integer(values, 'port', 1, 65535)
        for old_address, old_port in listeners:
            if port == old_port and (address == old_address or address.is_unspecified or old_address.is_unspecified):
                raise ConfigError('Overlapping listener ports')
        listeners.append((address, port))
        inbound = {'tag': 'server-' + str(len(inbounds) + 1), 'listen': str(address), 'port': port,
                   'protocol': protocol, 'settings': settings(values, protocol), 'streamSettings': stream(values, check_files)}
        inbounds.append(inbound)
    if not inbounds:
        raise Disabled('No enabled server entries')
    result = {'log': {'loglevel': choice(main, 'loglevel', {'debug', 'info', 'warning', 'error', 'none'}, 'warning')},
              'inbounds': inbounds, 'outbounds': [{'protocol': 'freedom', 'tag': 'direct'}, {'protocol': 'blackhole', 'tag': 'blocked'}]}
    if not flag(main, 'accept_lan'):
        result['routing'] = {'domainStrategy': 'IPIfNonMatch', 'rules': [{'type': 'field', 'ip': PRIVATE_DESTINATIONS, 'outboundTag': 'blocked'}]}
    return result


def write_private(path, config):
    path = Path(path)
    if path.is_symlink():
        raise ConfigError('Refusing a symlink output')
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(config, output, ensure_ascii=False, indent=2)
            output.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='Offline UCI file; omitted on the router')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-files', action='store_true')
    args = parser.parse_args()
    if args.input:
        text = args.input.read_text(encoding='utf-8')
    else:
        result = subprocess.run(['uci', '-q', 'export', 'v2ray_server'], text=True, encoding='utf-8', capture_output=True, timeout=10)
        if result.returncode:
            raise ConfigError('Cannot read v2ray_server UCI')
        text = result.stdout
    write_private(args.output, build_config(parse_uci(text), args.check_files))


if __name__ == '__main__':
    try:
        main()
    except Disabled:
        sys.exit(3)
    except (ConfigError, OSError, UnicodeError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, ConfigError) else 'Unable to generate private server configuration'
        print('neko-v2ray-server: ' + message, file=sys.stderr)
        sys.exit(1)
