#!/usr/bin/env python3
"""Linux-only real Ethernet over WireGuard, direct and inside native VLESS/TLS."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'local-packages/neko-l2vpn/files/l2vpn.py'
HELPER = types.ModuleType('l2vpn_netns')
exec(compile(SOURCE.read_text(), str(SOURCE), 'exec'), HELPER.__dict__)


def run(*args, **kwargs):
    try:
        return subprocess.run(list(map(str, args)), check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    except subprocess.CalledProcessError as exc:
        if str(args[0]) == 'ip' and hasattr(exc, 'add_note'):
            exc.add_note('Namespace diagnostic: '+(exc.stderr or '').strip())
        raise


def net(ns, *args, **kwargs):
    return run('ip', 'netns', 'exec', ns, *args, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--core', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Linux' or os.geteuid() != 0:
        raise SystemExit('Run as root on Linux with WireGuard, l2tp_eth and vxlan modules')
    for tool in ('ip', 'wg', 'ping', 'openssl'):
        if not shutil.which(tool): raise SystemExit('Missing tool: '+tool)
    core = args.core.resolve()
    if not run(core, 'version').stdout.startswith('Xray 26.3.27 '):
        raise SystemExit('Use the pinned Xray 26.3.27 test binary')
    prefix = 'nl'+str(os.getpid())
    routers, hosts = [prefix+'a', prefix+'b'], [prefix+'c', prefix+'d']
    created, processes, root_links = [], [], set()
    with tempfile.TemporaryDirectory(prefix='neko-l2vpn-netns-') as temporary:
        root = Path(temporary); root.chmod(0o700)
        try:
            for ns in routers+hosts:
                run('ip', 'netns', 'add', ns); created.append(ns)
                net(ns, 'ip', 'link', 'set', 'lo', 'up')
            run('ip', 'link', 'add', prefix+'w0', 'type', 'veth', 'peer', 'name', prefix+'w1')
            root_links.update((prefix+'w0', prefix+'w1'))
            for i, ns in enumerate(routers):
                run('ip', 'link', 'set', prefix+'w'+str(i), 'netns', ns)
                root_links.discard(prefix+'w'+str(i))
                net(ns, 'ip', 'link', 'set', prefix+'w'+str(i), 'name', 'wan0')
                net(ns, 'ip', 'address', 'add', f'198.18.0.{i+1}/24', 'dev', 'wan0')
                net(ns, 'ip', 'link', 'set', 'wan0', 'up')
                run('ip', 'link', 'add', prefix+'l'+str(i), 'type', 'veth', 'peer', 'name', prefix+'h'+str(i))
                root_links.update((prefix+'l'+str(i), prefix+'h'+str(i)))
                run('ip', 'link', 'set', prefix+'l'+str(i), 'netns', ns)
                root_links.discard(prefix+'l'+str(i))
                run('ip', 'link', 'set', prefix+'h'+str(i), 'netns', hosts[i])
                root_links.discard(prefix+'h'+str(i))
                net(ns, 'ip', 'link', 'set', prefix+'l'+str(i), 'name', 'lan0')
                net(hosts[i], 'ip', 'link', 'set', prefix+'h'+str(i), 'name', 'eth0')
                net(ns, 'ip', 'link', 'add', 'brvpn', 'type', 'bridge')
                net(ns, 'ip', 'link', 'set', 'lan0', 'mtu', '1360', 'master', 'brvpn', 'up')
                net(ns, 'ip', 'link', 'set', 'brvpn', 'mtu', '1360', 'up')
                net(hosts[i], 'ip', 'link', 'set', 'eth0', 'mtu', '1360', 'up')
                net(hosts[i], 'ip', 'address', 'add', f'198.51.100.{11+i}/24', 'dev', 'eth0')
                net(hosts[i], 'ip', '-6', 'address', 'add', f'2001:db8:1::{11+i}/64', 'dev', 'eth0', 'nodad')
            private = [run('wg', 'genkey').stdout.strip() for _ in routers]
            public = [run('wg', 'pubkey', input=value+'\n').stdout.strip() for value in private]
            for i in range(2):
                file = root/f'wg{i}.key'; file.write_text(private[i]+'\n'); file.chmod(0o600)
            certificate, tlskey = root/'cert.crt', root/'tls.key'
            run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                '-keyout', tlskey, '-out', certificate, '-subj', '/CN=vpn.example.net',
                '-addext', 'subjectAltName=DNS:vpn.example.net')
            tlskey.chmod(0o600)

            def stop_cores():
                for process in processes:
                    if process.poll() is None: process.terminate()
                for process in processes:
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                processes.clear()

            def counters():
                result = {}
                for i, ns in enumerate(routers):
                    row = {}
                    with contextlib.suppress(Exception):
                        transfer = net(ns, 'wg', 'show', 'wg0', 'transfer').stdout.split()
                        row['wg_bytes'] = transfer[-2:]
                    with contextlib.suppress(Exception):
                        links = json.loads(net(ns, 'ip', '-j', '-s', 'link', 'show').stdout)
                        row['links'] = {link['ifname']: {direction: link.get('stats64', link.get('stats', {})).get(direction, {}).get('packets', 0) for direction in ('rx', 'tx')}
                                        for link in links if link['ifname'] in ('wan0', 'wg0', 'lan0', 'nl2-test', 'vxlan0')}
                    with contextlib.suppress(Exception):
                        row['neighbors'] = json.loads(net(hosts[i], 'ip', '-j', 'neigh', 'show', 'dev', 'eth0').stdout)
                    with contextlib.suppress(Exception):
                        snmp = net(ns, 'cat', '/proc/net/snmp').stdout.splitlines()
                        for index, line in enumerate(snmp[:-1]):
                            if line.startswith('Udp:') and 'InErrors' in line:
                                fields = dict(zip(line.split()[1:], snmp[index+1].split()[1:]))
                                row['udp'] = {key: fields.get(key) for key in ('InErrors', 'NoPorts', 'InCsumErrors')}
                    result[str(i)] = row
                return json.dumps(result, separators=(',', ':'))

            def check_ping(ipv6=False, large=False, recovery=False):
                deadline = time.monotonic()+15
                while time.monotonic() < deadline:
                    if any(p.poll() is not None for p in processes):
                        raise RuntimeError('Native Xray exited during namespace test')
                    try:
                        net(hosts[0], 'ping', *(['-6'] if ipv6 else ['-4']), '-n', '-c', '1', '-W', '1',
                            *(['-M', 'do', '-s', '1332'] if large else []),
                            '2001:db8:1::12' if ipv6 else '198.51.100.12')
                        return
                    except subprocess.CalledProcessError: time.sleep(0.1)
                probe = 'IPv6' if ipv6 else ('MTU' if large else 'IPv4')
                raise RuntimeError(transport+'/'+mode+'/'+probe+('/recovery' if recovery else '/initial')+' connectivity failed; '+counters())

            for transport in ('direct', 'vless'):
                if transport == 'vless':
                    common = {'enabled': '1', 'security': 'tls', 'uuid': 'f3dc8467-7d0b-4b1c-9b60-ecce99836729',
                              'target_address': '127.0.0.1', 'target_port': '51820', 'server': '198.18.0.1',
                              'server_port': '14443', 'server_name': 'vpn.example.net', 'egress_device': 'wan0',
                              'listen_address': '198.18.0.1', 'certificate_file': str(certificate),
                              'certificate_key_file': str(tlskey), 'ca_certificate_file': str(certificate)}
                    for i, role in enumerate(('server', 'client')):
                        file = root/(role+'.json'); HELPER.write_private(file, HELPER.render_xray({**common, 'role': role}))
                        with (root/(role+'.log')).open('wb') as log:
                            processes.append(subprocess.Popen(['ip', 'netns', 'exec', routers[i], str(core), 'run', '-config', str(file)], stdout=log, stderr=subprocess.STDOUT))
                for i, ns in enumerate(routers):
                    net(ns, 'ip', 'link', 'add', 'wg0', 'type', 'wireguard')
                    peer = 1-i
                    options = ['wg', 'set', 'wg0', 'listen-port', '51820', 'private-key', root/f'wg{i}.key',
                               'peer', public[peer], 'allowed-ips', f'192.0.2.{peer+1}/32', 'persistent-keepalive', '1']
                    if transport == 'direct': options += ['endpoint', f'198.18.0.{peer+1}:51820']
                    elif i == 1: options += ['endpoint', '127.0.0.1:51821']
                    net(ns, *options)
                    net(ns, 'ip', 'address', 'add', f'192.0.2.{i+1}/32', 'dev', 'wg0')
                    net(ns, 'ip', 'link', 'set', 'wg0', 'mtu', '1420', 'up')
                    net(ns, 'ip', 'route', 'add', f'192.0.2.{peer+1}/32', 'dev', 'wg0')
                deadline = time.monotonic()+15
                while True:
                    try:
                        net(routers[0], 'ping', '-4', '-n', '-c', '1', '-W', '1', '192.0.2.2')
                        break
                    except subprocess.CalledProcessError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError('WireGuard/'+transport+' underlay failed; '+counters())
                        time.sleep(0.1)
                for mode in ('l2tp', 'vxlan'):
                    for i, ns in enumerate(routers):
                        peer = 1-i
                        if mode == 'l2tp':
                            env = {**os.environ, 'L2VPN_LINK_RUN': str(root/f'state{i}')}
                            net(ns, sys.executable, SOURCE, 'l2tp-up', '--name', 'test', '--underlay', 'wg0',
                                '--local', f'192.0.2.{i+1}', '--peer', f'192.0.2.{peer+1}',
                                '--tunnel-id', str(101+i), '--peer-tunnel-id', str(101+peer),
                                '--session-id', str(201+i), '--peer-session-id', str(201+peer),
                                '--local-port', '1701', '--peer-port', '1701', '--mtu', '1360', env=env)
                            name = 'nl2-test'
                        else:
                            name = 'vxlan0'
                            net(ns, 'ip', 'link', 'add', name, 'type', 'vxlan', 'id', '42',
                                'local', f'192.0.2.{i+1}', 'remote', f'192.0.2.{peer+1}', 'dev', 'wg0', 'dstport', '4789')
                        net(ns, 'ip', 'link', 'set', name, 'mtu', '1360', 'master', 'brvpn', 'up')
                    for host in hosts: net(host, 'ip', 'neigh', 'flush', 'dev', 'eth0')
                    check_ping(); check_ping(ipv6=True); check_ping(large=True)
                    print('PASS: '+mode+' over WireGuard/'+transport+' bridges IPv4, IPv6, ARP/NDP and 1360-byte IPv4 packets', flush=True)
                    print('::notice title=L2 VPN scenario::'+transport+'/'+mode+' initial IPv4/IPv6/MTU passed', flush=True)
                    net(routers[0], 'ip', 'link', 'set', 'wg0', 'down')
                    blocked = subprocess.run(['ip', 'netns', 'exec', hosts[0], 'ping', '-4', '-n', '-c', '1', '-W', '1', '198.51.100.12'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if not blocked.returncode: raise RuntimeError('L2 traffic escaped a down WireGuard underlay')
                    net(routers[0], 'ip', 'link', 'set', 'wg0', 'up'); check_ping(recovery=True)
                    for i, ns in enumerate(routers):
                        if mode == 'l2tp':
                            net(ns, sys.executable, SOURCE, 'l2tp-down', '--name', 'test', env={**os.environ, 'L2VPN_LINK_RUN': str(root/f'state{i}')})
                            if net(ns, 'ip', 'l2tp', 'show', 'tunnel').stdout.strip(): raise RuntimeError('Owned L2TP tunnel was not removed')
                        else: net(ns, 'ip', 'link', 'del', 'vxlan0')
                for ns in routers: net(ns, 'ip', 'link', 'del', 'wg0')
                stop_cores()
        finally:
            for process in processes:
                if process.poll() is None: process.terminate()
            for process in processes:
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
            for ns in reversed(created):
                with contextlib.suppress(subprocess.CalledProcessError): run('ip', 'netns', 'del', ns)
            for name in root_links:
                with contextlib.suppress(subprocess.CalledProcessError): run('ip', 'link', 'del', name)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Public Actions annotations provide a bounded diagnostic without dumping keys/configs.
        details = (exc.stderr or '').strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        details = (details or 'Native kernel integration failed')[-3000:]
        details = details.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
        print('::error file=tests/integration/l2vpn_netns.py,title=L2 VPN kernel integration::'+details, flush=True)
        raise
