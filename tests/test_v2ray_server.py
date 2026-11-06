import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from scripts.fwlib import ROOT

BACKEND = ROOT/'local-packages/neko-v2ray-server/files'
spec = importlib.util.spec_from_file_location('v2ray_adapter', BACKEND/'render.py')
adapter = importlib.util.module_from_spec(spec)
exec(compile((BACKEND/'render.py').read_text(),str(BACKEND/'render.py'),'exec'),adapter.__dict__)


def configuration(protocol='shadowsocks', **extra):
    values = {'enable': '1', 'protocol': protocol, 'listen': '192.0.2.2', 'port': '8443',
              'password': 'fixture-only', 'method': 'aes-256-gcm', 'ss_network': 'tcp,udp',
              'transport': 'tcp', 'tcp_guise': 'none', 'tls': '0', 'username': 'fixture-user',
              'uuid': ['11111111-2222-4333-8444-555555555555']}
    values.update(extra)
    return [{'type': 'global', 'values': {'enable': '1', 'accept_lan': '1'}},
            {'type': 'user', 'values': values}]


def uci_text(sections):
    lines = ['package v2ray_server']
    for section in sections:
        lines.append('config '+shlex.quote(section['type']))
        for field, value in section['values'].items():
            if isinstance(value, list):
                lines += ['list '+field+' '+shlex.quote(item) for item in value]
            else:
                lines.append('option '+field+' '+shlex.quote(value))
    return '\n'.join(lines)+'\n'


class V2RayConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_uci_quoting_and_json_preserve_values_without_shell_evaluation(self):
        credential = 'fixture "quoted" \\ 中文\n$(touch marker) `literal` # text'
        sections = configuration(password=credential)
        parsed = adapter.parse_uci(uci_text(sections))
        self.assertEqual(parsed, sections)
        config = adapter.build_config(parsed)
        output = self.base/'config.json'; adapter.write_private(output, config)
        self.assertEqual(json.loads(output.read_text())['inbounds'][0]['settings']['password'], credential)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.base/'marker').exists())

    def test_supported_protocols_build_authenticated_settings(self):
        for protocol in ('shadowsocks', 'vmess', 'vless', 'trojan', 'socks', 'http'):
            config = adapter.build_config(configuration(protocol))
            inbound = config['inbounds'][0]
            self.assertEqual(inbound['protocol'], protocol)
            self.assertEqual(inbound['listen'], '192.0.2.2')
            self.assertEqual(inbound['port'], 8443)
            self.assertIsInstance(inbound['settings'], dict)
        self.assertEqual(adapter.build_config(configuration('vless'))['inbounds'][0]['settings']['decryption'], 'none')
        self.assertEqual(adapter.build_config(configuration('socks'))['inbounds'][0]['settings']['auth'], 'password')

    def test_all_transport_objects_and_native_types(self):
        for transport, field in [('tcp', 'tcpSettings'), ('ws', 'wsSettings'), ('h2', 'httpSettings'),
                                 ('kcp', 'kcpSettings'), ('quic', 'quicSettings'), ('grpc', 'grpcSettings')]:
            values = configuration(transport=transport, ws_path='/fixture', h2_host=['example.test'],
                                   kcp_mtu='1200', kcp_congestion='1', quic_security='aes-128-gcm')
            stream = adapter.build_config(values)['inbounds'][0]['streamSettings']
            self.assertEqual(stream['network'], transport); self.assertIn(field, stream)
            if transport == 'kcp':
                self.assertEqual(stream[field]['mtu'], 1200)
                self.assertIs(stream[field]['congestion'], True)

    def test_disabled_service_and_rows_do_not_render_listeners(self):
        sections = configuration(); sections[0]['values']['enable'] = '0'
        with self.assertRaises(adapter.Disabled): adapter.build_config(sections)
        sections = configuration(enable='0', legacy_unknown='retained')
        with self.assertRaises(adapter.Disabled): adapter.build_config(sections)

    def test_unknown_enabled_fields_and_invalid_values_fail_explicitly(self):
        for extra in ({'legacy_unknown': 'retained'}, {'protocol': 'unknown'}, {'transport': 'unknown'},
                      {'port': '0'}, {'port': '65536'}, {'port': '$(fixture-only)'}, {'enable': 'maybe'},
                      {'listen': ''}, {'listen': '192.0.2.2/24'}, {'listen': 'host.example.test'},
                      {'listen': 'fe80::1%eth0'}, {'method': 'unknown'}, {'level': '256'}):
            with self.assertRaises(adapter.ConfigError): adapter.build_config(configuration(**extra))
        with self.assertRaises(adapter.ConfigError):
            adapter.build_config(configuration('vmess', uuid=['invalid']))
        self.assertEqual(adapter.build_config(configuration('http',level='42'))['inbounds'][0]['settings']['userLevel'],42)

    def test_loopback_binding_and_multiple_listeners(self):
        sections = configuration(bind_local='1'); sections[1]['values'].pop('listen')
        self.assertEqual(adapter.build_config(sections)['inbounds'][0]['listen'], '127.0.0.1')
        self.assertEqual(adapter.build_config(configuration(bind_local='1'))['inbounds'][0]['listen'], '127.0.0.1')
        sections = configuration(); sections.append(configuration('vmess', port='9443', listen='2001:db8::2')[1])
        self.assertEqual(len(adapter.build_config(sections)['inbounds']), 2)
        sections[2]['values'].update(port='8443', listen='0.0.0.0')
        with self.assertRaises(adapter.ConfigError): adapter.build_config(sections)

    def test_private_destination_policy_is_controlled_by_legacy_flag(self):
        sections = configuration(); self.assertNotIn('routing', adapter.build_config(sections))
        sections[0]['values']['accept_lan'] = '0'
        rule = adapter.build_config(sections)['routing']['rules'][0]
        self.assertIn('192.168.0.0/16', rule['ip']); self.assertIn('fc00::/7', rule['ip'])
        self.assertEqual(rule['outboundTag'], 'blocked')

    def test_tls_requires_local_files_and_preserves_symlinked_renewal_paths(self):
        cert = self.base/'cert'; cert.write_text('fixture-cert')
        material = self.base/'material'; material.write_text('fixture-credential')
        link = self.base/'current-material'; link.symlink_to(material)
        sections = configuration(tls='1', tls_cert=str(cert), tls_key=str(link), tls_alpn=['h2', 'http/1.1'])
        tls = adapter.build_config(sections, check_files=True)['inbounds'][0]['streamSettings']['tlsSettings']
        self.assertEqual(tls['certificates'][0]['keyFile'], str(link))
        self.assertEqual(tls['alpn'], ['h2', 'http/1.1'])
        material.unlink()
        with self.assertRaises(adapter.ConfigError): adapter.build_config(sections, check_files=True)

    def test_invalid_uci_forms_are_rejected(self):
        for text in ("config global\noption enable 'unterminated", 'option enable 1\n',
                     'config global\noption enable 1\noption enable 0\n',
                     'config global\noption enable 1\nlist enable 0\n',
                     'package another_package\n', 'config global\nexecute anything\n'):
            with self.assertRaises(adapter.ConfigError): adapter.parse_uci(text)

    def test_private_output_is_atomic_and_refuses_symlinks(self):
        victim = self.base/'victim'; victim.write_text('unchanged')
        output = self.base/'config.json'; output.symlink_to(victim)
        with self.assertRaises(adapter.ConfigError): adapter.write_private(output, {})
        self.assertEqual(victim.read_text(), 'unchanged')
        output.unlink(); output.write_text('old'); output.chmod(0o644)
        adapter.write_private(output, adapter.build_config(configuration()))
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ['config.json', 'victim'])


class V2RayServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.bin = self.base/'bin'; self.bin.mkdir()
        self.config = self.base/'uci'; self.config.write_text(uci_text(configuration()))
        uci = self.bin/'uci'
        uci.write_text('''#!/usr/bin/env python3
import os,pathlib,sys
if sys.argv[2]=='get':print(os.environ.get('GENERIC_ENABLED','0'))
elif sys.argv[2]=='export':print(pathlib.Path(os.environ['TEST_UCI']).read_text())
else:sys.exit(1)
'''); uci.chmod(0o755)
        core = self.bin/'v2ray'
        core.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$CORE_CALLS"
if [ "${CORE_FAIL:-0}" = 1 ]; then echo 'fixture credential diagnostic'; exit 1; fi
exit 0
'''); core.chmod(0o755)
        logger = self.bin/'logger'; logger.write_text('#!/bin/sh\nexit 0\n'); logger.chmod(0o755)
        self.run = self.base/'run'; self.calls = self.base/'calls'
        self.env = {**os.environ, 'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],
                    'V2RAY_SERVER_RUN':str(self.run), 'V2RAY_SERVER_CORE':str(core),
                    'V2RAY_SERVER_RENDER':str(BACKEND/'render.py'), 'V2RAY_SERVER_PYTHON':sys.executable,
                    'TEST_UCI':str(self.config), 'CORE_CALLS':str(self.calls)}
        self.script = self.base/'init.sh'
        self.script.write_text((BACKEND/'v2ray_server.init').read_text()+'''
procd_open_instance() { printf 'open %s\\n' "$*" >> "$CORE_CALLS"; }
procd_set_param() { printf 'param %s\\n' "$*" >> "$CORE_CALLS"; }
procd_close_instance() { printf 'close\\n' >> "$CORE_CALLS"; }
"$1"
''')

    def invoke(self, action='start_service', **env):
        return subprocess.run(['sh',str(self.script),action],env={**self.env,**env},text=True,capture_output=True)

    def test_start_validates_private_json_and_delegates_only_one_procd_instance(self):
        result = self.invoke(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.run/'config.json').stat().st_mode & 0o777, 0o600)
        calls = self.calls.read_text()
        self.assertIn('test -format=json -config', calls); self.assertIn('run -format=json -config', calls)
        self.assertEqual(calls.count('open server'), 1)
        self.assertNotIn('fixture-only', calls+result.stdout+result.stderr)
        self.assertEqual(self.invoke('stop_service').returncode, 0)
        self.assertFalse((self.run/'config.json').exists())

    def test_core_validation_failure_does_not_launch_or_publish_diagnostics(self):
        result = self.invoke(CORE_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('open server', self.calls.read_text())
        self.assertEqual(list(self.run.iterdir()), [])
        self.assertNotIn('fixture credential diagnostic',result.stdout+result.stderr)

    def test_disabled_or_invalid_configuration_never_launches(self):
        sections = configuration(enable='0'); self.config.write_text(uci_text(sections))
        self.assertEqual(self.invoke().returncode, 0); self.assertFalse(self.calls.exists())
        self.config.write_text(uci_text(configuration(port='invalid-fixture')))
        result = self.invoke(); self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists()); self.assertEqual(list(self.run.iterdir()), [])
        self.assertNotIn('invalid-fixture',result.stderr)

    def test_generic_core_conflict_and_output_symlinks_fail_before_core_execution(self):
        self.assertNotEqual(self.invoke(GENERIC_ENABLED='1').returncode, 0)
        self.assertFalse(self.calls.exists()); self.assertFalse(self.run.exists())
        victim = self.base/'victim'; victim.write_text('unchanged')
        self.run.mkdir(); (self.run/'config.json').symlink_to(victim)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(victim.read_text(), 'unchanged'); self.assertFalse(self.calls.exists())
