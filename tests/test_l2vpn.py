import argparse
import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts.fwlib import ROOT, profile, requested_config

BACKEND = ROOT/'local-packages/neko-l2vpn/files'
HELPER = types.ModuleType('l2vpn_fixture')
exec(compile((BACKEND/'l2vpn.py').read_text(), str(BACKEND/'l2vpn.py'), 'exec'), HELPER.__dict__)


def client_settings():
    return {'enabled': '1', 'role': 'client', 'security': 'tls',
            'uuid': 'f3dc8467-7d0b-4b1c-9b60-ecce99836729', 'target_address': '127.0.0.1',
            'target_port': '51820', 'proxy_port': '51821', 'server': 'vpn.example.net',
            'server_port': '443', 'server_name': 'vpn.example.net', 'egress_device': 'pppoe-wan'}


def uci_text(values):
    return 'package neko-l2vpn\nconfig transport main\n' + ''.join('option '+key+' '+shlex.quote(value)+'\n' for key, value in values.items())


class L2VPNConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_profiles_include_both_ends_and_basic_omits_ha_services(self):
        for name in ('x86-ha', 'r619ac-ha', 'r619ac-basic'):
            config = requested_config(profile(name))
            for package in ('neko-l2vpn', 'luci-app-neko-l2vpn', 'luci-i18n-neko-l2vpn-zh-cn',
                            'kmod-wireguard', 'wireguard-tools', 'kmod-l2tp-eth', 'kmod-l2tp',
                            'kmod-vxlan', 'vxlan', 'luci-proto-vxlan', 'ip-full', 'ip-bridge', 'xray-core'):
                self.assertEqual(config['CONFIG_PACKAGE_'+package], 'y', (name, package))
        basic = requested_config(profile('r619ac-basic'))
        for package in ('firmware-ha', 'keepalived', 'sing-box', 'luci-app-homeproxy',
                        'openvpn-openssl', 'zerotier', 'frpc', 'v2ray-core', 'luci-app-dockerman'):
            self.assertNotIn('CONFIG_PACKAGE_'+package, basic)
        self.assertEqual(basic['CONFIG_TARGET_ipq40xx_generic_DEVICE_p2w_r619ac-128m'], 'y')
        self.assertNotIn('CONFIG_PACKAGE_neko-l2vpn', requested_config(profile('x86-basic')))

    def test_default_disabled_has_no_addresses_identity_or_network_mutations(self):
        values = HELPER.parse_uci((BACKEND/'neko-l2vpn.config').read_text())
        with self.assertRaises(HELPER.Disabled): HELPER.render_xray(values)
        self.assertEqual(values['server'], '')
        self.assertEqual(values['uuid'], '')
        self.assertEqual(values['listen_address'], '')
        self.assertFalse((ROOT/'local-packages/luci-app-neko-l2vpn/root/etc').exists())

    def test_client_preserves_udp_and_requires_explicit_wan_binding(self):
        rendered = HELPER.render_xray(client_settings())
        inbound = rendered['inbounds'][0]
        self.assertEqual(inbound['listen'], '127.0.0.1')
        self.assertEqual(inbound['settings'], {'address': '127.0.0.1', 'port': 51820, 'network': 'udp'})
        self.assertEqual(rendered['outbounds'][0]['protocol'], 'blackhole')
        vless = rendered['outbounds'][1]
        self.assertEqual(vless['streamSettings']['sockopt'], {'interface': 'pppoe-wan'})
        self.assertNotIn('allowInsecure', vless['streamSettings']['tlsSettings'])
        self.assertEqual(rendered['routing']['rules'][0]['network'], 'udp')
        with self.assertRaises(HELPER.ConfigError): HELPER.render_xray({**client_settings(), 'egress_device': ''})
        with patch.object(HELPER, 'ip_json', return_value=[{'flags': ['UP'], 'linkinfo': {'info_kind': 'wireguard'}}]):
            with self.assertRaises(HELPER.ConfigError): HELPER.render_xray(client_settings(), check_runtime=True)

    def test_server_allows_only_the_exact_wireguard_udp_destination(self):
        values = {**client_settings(), 'role': 'server', 'listen_address': '0.0.0.0',
                  'certificate_file': '/etc/neko-l2vpn/cert.crt', 'certificate_key_file': '/etc/neko-l2vpn/tls.key'}
        rendered = HELPER.render_xray(values)
        self.assertEqual(rendered['outbounds'][0]['protocol'], 'blackhole')
        self.assertEqual(rendered['routing']['rules'], [{'type': 'field', 'inboundTag': ['wg-vless'],
                         'network': 'udp', 'ip': ['127.0.0.1/32'], 'port': '51820', 'outboundTag': 'wg-target'}])
        with self.assertRaises(HELPER.ConfigError): HELPER.render_xray(values, check_runtime=True)

    def test_reality_client_and_server_use_pinned_core_fields(self):
        encoded = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
        client = {**client_settings(), 'security': 'reality', 'flow': 'xtls-rprx-vision',
                  'reality_public_key': encoded, 'reality_short_id': '1122aabb'}
        settings = HELPER.render_xray(client)['outbounds'][1]['streamSettings']['realitySettings']
        self.assertEqual(settings['publicKey'], encoded)
        local = self.base/'reality.key'; local.write_text(encoded+'\n'); local.chmod(0o600)
        server = {**client, 'role': 'server', 'listen_address': '::',
                  'reality_private_key_file': str(local), 'reality_target': 'www.example.net:443'}
        settings = HELPER.render_xray(server)['inbounds'][0]['streamSettings']['realitySettings']
        self.assertEqual(settings['target'], 'www.example.net:443')
        self.assertEqual(settings['privateKey'], encoded)

    def test_invalid_identities_endpoints_and_security_fail_explicitly(self):
        invalid = [('enabled', 'yes'), ('uuid', 'bad'), ('target_address', '224.0.0.1'),
                   ('target_port', '0'), ('proxy_port', '65536'), ('security', 'none'),
                   ('role', 'relay'), ('server', 'bad; command'), ('flow', 'unknown'),
                   ('server_name', 'vpn.example.net\ncommand'), ('egress_device', 'eth0;command')]
        for name, value in invalid:
            with self.subTest(name=name), self.assertRaises(HELPER.ConfigError):
                HELPER.render_xray({**client_settings(), name: value})
        with self.assertRaises(HELPER.ConfigError): HELPER.render_xray({**client_settings(), 'unknown': '1'})
        with self.assertRaises(HELPER.ConfigError): HELPER.render_xray({**client_settings(), 'uuid': ['unexpected']})

    def test_uci_quoting_round_trips_without_evaluating_shell_text(self):
        values = {**client_settings(), 'certificate_file': "a' $(touch /tmp/should-not-exist)"}
        self.assertEqual(HELPER.parse_uci(uci_text(values)), values)
        for raw in ('config transport main\noption enabled 1\noption enabled 0\n',
                    'config transport other\n', 'config transport main\nlist enabled 1\n'):
            with self.assertRaises(HELPER.ConfigError): HELPER.parse_uci(raw)

    def test_private_outputs_are_atomic_and_refuse_symlinks(self):
        path = self.base/'config.json'
        HELPER.write_private(path, HELPER.render_xray(client_settings()))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        path.unlink(); target = self.base/'target'; target.write_text('untouched')
        path.symlink_to(target)
        with self.assertRaises(HELPER.ConfigError): HELPER.write_private(path, {})
        self.assertEqual(target.read_text(), 'untouched')


class L2TPControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.args = argparse.Namespace(name='home', underlay='wg0', local='192.0.2.1', peer='192.0.2.2',
                                      tunnel_id='101', peer_tunnel_id='102', session_id='201', peer_session_id='202',
                                      local_port='1701', peer_port='1701', mtu='1360')
        self.links = [{'mtu': 1420, 'flags': ['UP'], 'linkinfo': {'info_kind': 'wireguard'}}]
        self.route = [{'dev': 'wg0'}]
        def query(*args):
            if args[0] == '-d': return self.links
            if args[0] == 'address': return [{'addr_info': [{'local': '192.0.2.1'}]}]
            return self.route
        self.query = patch.object(HELPER, 'ip_json', side_effect=query).start()
        self.run = patch.object(HELPER, 'ip_run').start()
        self.addCleanup(patch.stopall)

    def test_creates_only_owned_tunnel_and_session_with_snapshot_cleanup(self):
        HELPER.l2tp_up(self.args, self.base/'run')
        self.assertIn(('l2spec_type', 'none'), [(call.args[-2], call.args[-1]) for call in self.run.call_args_list])
        state = self.base/'run/home.json'
        self.assertEqual(json.loads(state.read_text()), {'tunnel_id': 101, 'session_id': 201})
        self.args.tunnel_id = '999'  # Live settings changing must not change cleanup IDs.
        self.run.reset_mock()
        HELPER.l2tp_down('home', self.base/'run')
        self.assertEqual(self.run.call_args_list[-1].args, ('l2tp', 'del', 'tunnel', 'tunnel_id', 101))
        self.assertFalse(state.exists())
        self.run.reset_mock(); HELPER.l2tp_down('home', self.base/'run'); self.run.assert_not_called()

    def test_wrong_underlay_route_source_or_mtu_never_creates_a_tunnel(self):
        variants = [({'route': [{'dev': 'wan'}]}, {}), ({'links': [{'mtu': 1420, 'flags': ['UP'], 'linkinfo': {'info_kind': 'vlan'}}]}, {}),
                    ({'links': [{'mtu': 1400, 'flags': ['UP'], 'linkinfo': {'info_kind': 'wireguard'}}]}, {'mtu': '1360'}),
                    ({}, {'local': '192.0.2.9'}), ({}, {'name': '../../bad'}), ({}, {'tunnel_id': '1;touch'}),
                    ({}, {'peer': '192.0.2.1'}), ({}, {'mtu': '1279'})]
        for changed, args in variants:
            with self.subTest(changed=changed, args=args):
                original_links, original_route = self.links, self.route
                for name, value in changed.items(): setattr(self, name, value)
                try:
                    with self.assertRaises(HELPER.ConfigError):
                        HELPER.l2tp_up(argparse.Namespace(**{**vars(self.args), **args}), self.base/'run')
                finally:
                    self.links, self.route = original_links, original_route
                self.run.assert_not_called()

    def test_failed_foreign_tunnel_creation_is_never_deleted(self):
        self.run.side_effect = subprocess.CalledProcessError(2, ['ip'])
        with self.assertRaises(subprocess.CalledProcessError): HELPER.l2tp_up(self.args, self.base/'run')
        self.assertEqual(self.run.call_count, 1)
        self.assertFalse((self.base/'run/home.json').exists())

    def test_partial_setup_failure_rolls_back_only_the_created_objects(self):
        self.run.side_effect = [None, subprocess.CalledProcessError(2, ['ip']), None]
        with self.assertRaises(subprocess.CalledProcessError): HELPER.l2tp_up(self.args, self.base/'run')
        self.assertEqual(self.run.call_args_list[-1].args, ('l2tp', 'del', 'tunnel', 'tunnel_id', 101))
        self.assertFalse((self.base/'run/home.json').exists())

    def test_duplicate_state_and_symlink_roots_are_rejected(self):
        HELPER.l2tp_up(self.args, self.base/'run')
        self.run.reset_mock()
        with self.assertRaises(HELPER.ConfigError): HELPER.l2tp_up(self.args, self.base/'run')
        self.run.assert_not_called()
        (self.base/'alias').symlink_to(self.base/'run')
        with self.assertRaises(HELPER.ConfigError): HELPER.l2tp_up(self.args, self.base/'alias')


class L2VPNServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.bin = self.base/'bin'; self.bin.mkdir()
        self.settings = self.base/'settings.json'; self.settings.write_text(json.dumps(client_settings()))
        self.calls = self.base/'calls'
        uci = self.bin/'uci'
        uci.write_text('#!'+sys.executable+'\nimport json,os,shlex,sys\nv=json.load(open(os.environ["SETTINGS"]))\nif sys.argv[-2]=="export":\n print("package neko-l2vpn\\nconfig transport main\\n"+"".join("option "+k+" "+shlex.quote(x)+"\\n" for k,x in v.items()))\nelse: print(v.get(sys.argv[-1].split(".")[-1], ""))\n')
        uci.chmod(0o755)
        core = self.bin/'xray'
        core.write_text('#!/bin/sh\nprintf "core %s\\n" "$*" >> "$CALLS"\nexit "${CORE_STATUS:-0}"\n'); core.chmod(0o755)
        ip = self.bin/'ip'; ip.write_text('#!/bin/sh\nprintf \'[{"flags":["UP"]}]\\n\'\n'); ip.chmod(0o755)
        logger = self.bin/'logger'; logger.write_text('#!/bin/sh\nexit 0\n'); logger.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.bin)+os.pathsep+os.environ['PATH'],
                    'L2VPN_RUN': str(self.base/'run'), 'L2VPN_HELPER': str(BACKEND/'l2vpn.py'),
                    'L2VPN_PYTHON': sys.executable, 'L2VPN_CORE': str(core), 'L2VPN_GUARD': str(self.bin/'guard'),
                    'SETTINGS': str(self.settings), 'CALLS': str(self.calls)}

    def start(self, **extra):
        source = '. "$1"\nprocd_open_instance() { echo open >> "$CALLS"; }\nprocd_set_param() { printf "param %s\\n" "$*" >> "$CALLS"; }\nprocd_close_instance() { echo close >> "$CALLS"; }\nstart_service\n'
        return subprocess.run(['sh', '-c', source, 'test', str(BACKEND/'neko-l2vpn.init')], env={**self.env, **extra}, text=True, capture_output=True)

    def test_enabled_transport_is_core_validated_before_single_procd_registration(self):
        result = self.start(); self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text()
        self.assertLess(calls.index('core run -test'), calls.index('open'))
        self.assertEqual(calls.count('open\n'), 1)
        self.assertIn('param command', calls)
        self.assertEqual((self.base/'run/xray.json').stat().st_mode & 0o777, 0o600)

    def test_disabled_invalid_and_core_rejected_configuration_never_starts(self):
        for values, status in (({**client_settings(), 'enabled': '0'}, '0'),
                               ({**client_settings(), 'uuid': 'bad'}, '0'),
                               (client_settings(), '1')):
            with self.subTest(values=values, status=status):
                self.settings.write_text(json.dumps(values))
                self.calls.unlink(missing_ok=True)
                result = self.start(CORE_STATUS=status)
                self.assertNotIn('open', self.calls.read_text() if self.calls.exists() else '')
                self.assertNotIn(values['uuid'], result.stderr+result.stdout)

    def test_ha_guard_and_output_symlinks_prevent_registration(self):
        guard = self.bin/'guard'; guard.write_text('#!/bin/sh\nexit 1\n'); guard.chmod(0o755)
        self.assertEqual(self.start().returncode, 0)
        self.assertFalse(self.calls.exists())
        guard.unlink()
        (self.base/'run').symlink_to(self.bin)
        self.assertNotEqual(self.start().returncode, 0)
        self.assertFalse(self.calls.exists())


class L2TPNetifdTests(unittest.TestCase):
    def test_adapter_tracks_wireguard_dependency_and_uses_the_same_cleanup_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root/'helper.sh'; helper.write_text('#!/bin/sh\nprintf "helper %s\\n" "$*" >> "$CALLS"\n')
            calls = root/'calls'
            env = {**os.environ, 'INCLUDE_ONLY': '1', 'L2VPN_PYTHON': '/bin/sh',
                   'L2VPN_HELPER': str(helper), 'CALLS': str(calls)}
            shell = '''
. "$1"
json_get_vars() { tunlink=wghome; ipaddr=192.0.2.1; peeraddr=192.0.2.2; tunnel_id=101; peer_tunnel_id=102; session_id=201; peer_session_id=202; local_port=1701; peer_port=1701; mtu=1360; }
uci() { echo "${UNDERLAY_PROTO:-wireguard}"; }
network_get_device() { link=wg0; }
proto_add_host_dependency() { printf 'dependency %s\\n' "$*" >> "$CALLS"; }
proto_notify_error() { printf 'error %s\\n' "$*" >> "$CALLS"; }
proto_init_update() { printf 'update %s\\n' "$*" >> "$CALLS"; }
proto_send_update() { :; }
proto_neko_l2tp_setup home || exit 1
proto_neko_l2tp_teardown home
'''
            args = ['sh', '-c', shell, 'test', str(BACKEND/'neko_l2tp.sh')]
            result = subprocess.run(args, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = calls.read_text()
            self.assertIn('dependency home 192.0.2.2 wghome', text)
            self.assertIn('l2tp-up --name home --underlay wg0', text)
            self.assertIn('update nl2-home 1', text)
            self.assertIn('l2tp-down --name home', text)
            calls.unlink()
            result = subprocess.run(args, env={**env, 'UNDERLAY_PROTO': 'dhcp'}, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('helper ', calls.read_text())


if __name__ == '__main__':
    unittest.main()
