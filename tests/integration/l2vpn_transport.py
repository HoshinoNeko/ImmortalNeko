#!/usr/bin/env python3
"""Real pinned Xray parser and loopback VLESS/TLS UDP forwarding; no router changes."""
import argparse
import contextlib
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import tempfile
import threading
import time
import types

ROOT = Path(__file__).resolve().parents[2]
HELPER = types.ModuleType('l2vpn_native')
SOURCE = ROOT/'local-packages/neko-l2vpn/files/l2vpn.py'
exec(compile(SOURCE.read_text(), str(SOURCE), 'exec'), HELPER.__dict__)


def port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def echo():
    stop = threading.Event()
    received = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0)); sock.settimeout(0.1)
        def serve():
            while not stop.is_set():
                try:
                    data, address = sock.recvfrom(65535)
                    received.append(data)
                    sock.sendto(data, address)
                except socket.timeout:
                    continue
        thread = threading.Thread(target=serve); thread.start()
        try:
            yield sock.getsockname()[1], received
        finally:
            stop.set(); thread.join(2)


def alive(processes):
    if any(process.poll() is not None for process in processes):
        raise RuntimeError('A native Xray test process exited early')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--core', required=True, type=Path)
    args = parser.parse_args()
    core = args.core.resolve()
    version = subprocess.check_output([str(core), 'version'], text=True)
    if not version.startswith('Xray 26.3.27 '):
        raise RuntimeError('Use the locked feed version: Xray 26.3.27')
    processes = []
    with tempfile.TemporaryDirectory(prefix='neko-l2vpn-native-') as directory:
        root = Path(directory); root.chmod(0o700)
        try:
            certificate, key = root/'cert.crt', root/'tls.key'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-keyout', str(key), '-out', str(certificate), '-subj', '/CN=vpn.example.net',
                            '-addext', 'subjectAltName=DNS:vpn.example.net'], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            key.chmod(0o600)
            common = {'enabled': '1', 'role': 'client', 'security': 'tls',
                      'uuid': 'f3dc8467-7d0b-4b1c-9b60-ecce99836729', 'target_address': '127.0.0.1',
                      'target_port': '51820', 'server': '127.0.0.1', 'server_port': str(port(socket.SOCK_STREAM)),
                      'proxy_port': str(port(socket.SOCK_DGRAM)), 'server_name': 'vpn.example.net',
                      'egress_device': 'lo0' if platform.system() == 'Darwin' else 'lo',
                      'listen_address': '127.0.0.1', 'certificate_file': str(certificate),
                      'certificate_key_file': str(key), 'ca_certificate_file': str(certificate)}
            pair = subprocess.check_output([str(core), 'x25519'], text=True)
            private = re.search(r'PrivateKey:\s*(\S+)', pair).group(1)
            public = re.search(r'(?:Password(?: \(PublicKey\))?|PublicKey):\s*(\S+)', pair).group(1)
            private_file = root/'reality.key'; private_file.write_text(private+'\n'); private_file.chmod(0o600)
            for security in ('tls', 'reality'):
                for role in ('client', 'server'):
                    values = {**common, 'role': role, 'security': security,
                              'reality_public_key': public, 'reality_private_key_file': str(private_file),
                              'reality_target': 'www.example.net:443', 'reality_short_id': '01020304',
                              'flow': 'xtls-rprx-vision' if security == 'reality' else ''}
                    file = root/(role+'-'+security+'.json')
                    HELPER.write_private(file, HELPER.render_xray(values))
                    checked = subprocess.run([str(core), 'run', '-test', '-config', str(file)], capture_output=True)
                    if checked.returncode:
                        raise RuntimeError('Native Xray parser rejected '+role+' '+security)
            print('PASS: native Xray 26.3.27 validates client/server TLS and REALITY configurations', flush=True)

            def start(values, name):
                file = root/(name+'.json'); HELPER.write_private(file, HELPER.render_xray(values))
                with (root/(name+'.log')).open('wb') as log:
                    process = subprocess.Popen([str(core), 'run', '-config', str(file)], stdout=log, stderr=subprocess.STDOUT)
                processes.append(process)
                return process

            def wait_udp(number):
                deadline = time.monotonic()+5
                while time.monotonic() < deadline:
                    alive(processes)
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                        try: sock.bind(('127.0.0.1', number))
                        except OSError: return
                    time.sleep(0.05)
                raise RuntimeError('Native UDP listener did not start')

            with echo() as (target, received), echo() as (forbidden, rejected):
                common['target_port'] = str(target)
                start({**common, 'role': 'server'}, 'server')
                start(common, 'client')
                wait_udp(int(common['proxy_port']))
                payload = os.urandom(1280)
                deadline = time.monotonic()+12
                forwarded = False
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(0.7)
                    while time.monotonic() < deadline:
                        alive(processes)
                        sock.sendto(payload, ('127.0.0.1', int(common['proxy_port'])))
                        try:
                            forwarded = sock.recv(65535) == payload
                            if forwarded: break
                        except socket.timeout: pass
                if not forwarded or not received:
                    raise RuntimeError('Native VLESS/TLS UDP round trip failed')
                print('PASS: actual bidirectional UDP payload crosses the generated VLESS/TLS transport', flush=True)
                bad_port = port(socket.SOCK_DGRAM)
                start({**common, 'target_port': str(forbidden), 'proxy_port': str(bad_port)}, 'blocked-client')
                wait_udp(bad_port)
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(1)
                    sock.sendto(payload, ('127.0.0.1', bad_port))
                    try:
                        sock.recv(65535)
                        raise RuntimeError('Server forwarded an unauthorized destination')
                    except socket.timeout: pass
                if rejected:
                    raise RuntimeError('Server reached an unauthorized UDP listener')
                alive(processes)
                print('PASS: native server rejects other UDP destinations', flush=True)
        finally:
            for process in processes:
                if process.poll() is None: process.terminate()
            for process in processes:
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill(); process.wait()


if __name__ == '__main__':
    main()
