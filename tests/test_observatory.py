import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from scripts.fwlib import ROOT, profile, requested_config

BACKEND = ROOT/'local-packages/neko-observatory/files'
M = types.ModuleType('observatory_fixture')
exec(compile((BACKEND/'collector.py').read_text(), str(BACKEND/'collector.py'), 'exec'), M.__dict__)


class ObservatoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_all_profiles_select_theme_dashboard_and_chinese(self):
        for name in ('x86-basic', 'x86-ha', 'r619ac-basic', 'r619ac-ha'):
            selected = requested_config(profile(name))
            for package in ('luci-theme-vantage', 'luci-app-neko-dashboard', 'neko-observatory',
                            'luci-i18n-vantage-theme-zh-cn', 'luci-i18n-neko-dashboard-zh-cn'):
                self.assertEqual(selected['CONFIG_PACKAGE_'+package], 'y')
            self.assertNotIn('CONFIG_PACKAGE_luci-app-vantage', selected)

    def test_password_requires_private_regular_owned_file(self):
        p = self.base/'credential'; p.write_text(' synthetic credential \n'); p.chmod(0o600)
        self.assertEqual(M.private_password(str(p)), ' synthetic credential ')
        p.chmod(0o644)
        with self.assertRaisesRegex(M.CollectionError, 'permissions'): M.private_password(str(p))
        p.chmod(0o600)
        link = self.base/'link'; link.symlink_to(p)
        with self.assertRaises(M.CollectionError): M.private_password(str(link))
        with self.assertRaises(M.CollectionError): M.private_password('relative')
        with self.assertRaises(M.CollectionError): M.private_password(str(self.base))
        p.write_text('x' * 4097)
        with self.assertRaises(M.CollectionError): M.private_password(str(p))

    def test_password_owner_is_checked(self):
        p = self.base/'credential'; p.write_text('fixture'); p.chmod(0o600)
        with patch.object(M.os, 'geteuid', return_value=p.stat().st_uid + 1):
            with self.assertRaisesRegex(M.CollectionError, 'permissions'): M.private_password(str(p))

    def test_cache_is_atomic_private_and_refuses_symlink(self):
        p = self.base/'cache'; M.atomic_snapshot(p, {'ok': True})
        self.assertEqual(json.loads(p.read_text()), {'ok': True})
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        other = self.base/'link'; other.symlink_to(p)
        with self.assertRaises(M.CollectionError): M.atomic_snapshot(other, {})
        self.assertEqual(list(self.base.glob('.snapshot-*')), [])

    def test_auto_discovery_deduplicates_aliases_excludes_wan_and_tunnels(self):
        interfaces = [
            {'interface': 'guest', 'l3_device': 'br-lan.20', 'proto': 'static', 'up': True},
            {'interface': 'guest_alias', 'l3_device': 'br-lan.20', 'proto': 'static', 'up': True},
            {'interface': 'uplink', 'l3_device': 'eth1.100', 'proto': 'dhcp'},
            {'interface': 'vpn', 'l3_device': 'wg.30', 'proto': 'wireguard'},
            {'interface': 'base', 'l3_device': 'br-lan', 'proto': 'static'}]
        firewall = [{'.type': 'zone', 'name': 'lan', 'network': ['guest', 'guest_alias', 'vpn', 'base']},
                    {'.type': 'zone', 'name': 'outside', 'masq': '1', 'network': ['uplink']}]
        rows = M.discover(interfaces, [], firewall, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['interfaces'], ['guest', 'guest_alias'])
        self.assertEqual(rows[0]['vlan'], 20)
        self.assertEqual(M.discover(interfaces, [], [], []), [])

    def test_explicit_nonstandard_vlan_and_manual_label(self):
        interfaces = [{'interface': 'vlan_a', 'device': 'localnet', 'up': True},
                      {'interface': 'alias', 'device': 'localnet'}]
        network = [{'.type': 'device', 'name': 'localnet', 'type': '8021q', 'vid': '31'}]
        rows = M.discover(interfaces, network, [], [{'interface': 'vlan_a'}, {'interface': 'alias', 'label': 'Lab'}], False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['label'], 'Lab')
        self.assertEqual(rows[0]['vlan'], 31)

    def test_interface_path_and_row_bounds(self):
        interfaces = [{'interface': 'v'+str(i), 'device': 'lan.'+str(i)} for i in range(1, 50)]
        manual = [{'interface': 'v'+str(i)} for i in range(1, 50)]
        self.assertEqual(len(M.discover(interfaces, [], [], manual)), 32)
        self.assertEqual(M.discover([{'interface': 'bad', 'device': '../escape'}], [], [], [{'interface': 'bad'}]), [])

    def test_traffic_direction_and_totals_are_valid_sample_deltas(self):
        c = M.Counters(); devices = [{'device': 'lan.20'}]
        first = c.update(devices, {'lan.20': ('a', 1000, 2000)}, 10, 100)[0]
        self.assertIsNone(first['upload_bps'])
        row = c.update(devices, {'lan.20': ('a', 1500, 3000)}, 15, 105)[0]
        self.assertEqual((row['upload_bps'], row['download_bps']), (800, 1600))
        self.assertEqual((row['upload_bytes'], row['download_bytes']), (500, 1000))

    def test_reset_recreated_device_missing_and_long_gap_never_spike(self):
        for reading, elapsed in [(('a', 1, 2), 5), (('b', 900000, 900000), 5),
                                 (None, 5), (('a', 900000, 900000), 31)]:
            c = M.Counters(); devices = [{'device': 'lan.20'}]
            c.update(devices, {'lan.20': ('a', 100, 200)}, 10, 100)
            row = c.update(devices, {'lan.20': reading}, 10 + elapsed, 100 + elapsed)[0]
            self.assertIsNone(row['upload_bps'])
            self.assertEqual(row['upload_bytes'], 0)
            self.assertEqual(row['history'][-1][1:], [None, None])

    def test_history_is_bounded_and_removed_interfaces_do_not_leak(self):
        c = M.Counters(3)
        for i in range(6): c.update([{'device': 'lan.20'}], {'lan.20': ('a', i, i)}, i+1, i+1)
        self.assertEqual(len(c.rows['lan.20']['history']), 3)
        c.update([], {}, 9, 9)
        self.assertEqual(c.rows, {})

    def test_sanitization_drops_secrets_and_counts_roaming_once(self):
        aps = [{'mac': '02005e000001', 'name': '<img src=x>', 'ip': '192.0.2.2', 'online': 'yes',
                'key_suffix': 'DO_NOT_PUBLISH', 'password': 'DO_NOT_PUBLISH', 'reporttime': 42}]
        stations = [{'mac': '02:00:5e:00:00:02', 'hostname': '<script>alert(1)</script>', 'ip': '0.0.0.0',
                     'ssid': 'Lab', 'vlan': '20', 'apmac': '02005e000001', 'signal': -57, 'tx_rate': 123,
                     'token': 'DO_NOT_PUBLISH'}] * 2
        hotspots = [{'ssid': 'Lab', 'vlan': '20', 'apmac': '02005e000001', 'radio': '5g', 'key': 'DO_NOT_PUBLISH'}]
        data = M.sanitize_ac(aps, stations, hotspots, 100)
        self.assertNotIn('DO_NOT_PUBLISH', json.dumps(data))
        self.assertNotIn('tx_rate', json.dumps(data))
        self.assertEqual(data['unique_clients'], 1)
        self.assertEqual(data['associations'], 2)
        self.assertEqual(data['ssids'][0]['clients'], 1)
        self.assertEqual(data['clients'][0]['ip'], '')
        self.assertEqual(data['aps'][0]['reported_at'], 42)

    def test_failed_collection_retains_last_good_records_and_timestamp(self):
        worker = M.ACWorker({'ac_enabled': '1'})
        worker.data = {'state': 'ok', 'collected_at': 100, 'unique_clients': 8}
        with patch.object(M, 'private_password', side_effect=M.CollectionError('request_failed')):
            worker.collect_once()
        data = worker.snapshot(250)
        self.assertEqual(data['unique_clients'], 8)
        self.assertEqual(data['collected_at'], 100)
        self.assertTrue(data['stale'])
        self.assertEqual(data['state'], 'request_failed')

    def test_credential_changes_reauthenticate_without_echoing_errors(self):
        worker = M.ACWorker({'ac_enabled': '1', 'ac_url': 'http://192.0.2.1'})
        with patch.object(M, 'private_password', return_value='fixture'), patch.object(M.ACClient, 'collect', side_effect=ValueError('sensitive body')):
            worker.collect_once()
        self.assertEqual(worker.data['state'], 'collection_failed')
        self.assertNotIn('sensitive', json.dumps(worker.data))

    def test_rpc_grants_only_cached_status(self):
        acl = json.loads((ROOT/'local-packages/luci-app-neko-dashboard/root/usr/share/rpcd/acl.d/luci-app-neko-dashboard.json').read_text())
        readonly = acl['luci-app-neko-dashboard']
        self.assertEqual(readonly['read'], {'ubus': {'neko.observatory': ['status']}})
        self.assertNotIn('write', readonly)
        rpc = BACKEND/'neko.observatory'
        listed = subprocess.run(['sh', str(rpc), 'list'], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(listed.stdout), {'status': {}})
        self.assertNotEqual(subprocess.run(['sh', str(rpc), 'call', 'exec'], capture_output=True).returncode, 0)

    def test_pinned_theme_patch_registers_without_overriding_selection(self):
        from test_retained_defaults import UCI_MOCK
        fixture = ROOT/'tests/fixtures/vantage'
        manifest = json.loads((fixture/'manifest.json').read_text())
        source = fixture/'30_luci-theme-vantage'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), manifest['sha256'])
        target = self.base/'luci-theme-vantage/root/etc/uci-defaults'
        target.mkdir(parents=True)
        shutil.copyfile(source, target/source.name)
        subprocess.run(['git', 'apply', str(ROOT/'patches/feeds/vantage/010-preserve-selected-theme.patch')], cwd=self.base, check=True)
        binary = self.base/'bin'; binary.mkdir()
        helper = binary/'uci'; helper.write_text(UCI_MOCK); helper.chmod(0o755)
        store = self.base/'uci.json'
        env = {**os.environ, 'PATH': str(binary)+os.pathsep+os.environ['PATH'],
               'UCI_STORE': str(store), 'UCI_LOG': str(self.base/'uci.log')}
        for current in ('/luci-static/bootstrap', '/luci-static/argon', None):
            store.write_text(json.dumps({'luci.main.mediaurlbase': current} if current else {}))
            subprocess.run(['sh', str(target/source.name)], env=env, check=True)
            values = json.loads(store.read_text())
            self.assertEqual(values['luci.themes.Vantage'], '/luci-static/vantage')
            self.assertEqual(values['luci.main.mediaurlbase'], current or '/luci-static/vantage')


class ACProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def reply(self, data, status=200):
                self.send_response(status); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            def do_GET(self):
                cls.requests.append(('GET', self.path, self.headers.get('sysauth')))
                if self.path.endswith('getrandom'): return self.reply({'ret': 1, 'random': 'a'*32})
                if self.headers.get('sysauth') != 'synthetic-session': return self.reply({'ret': -99})
                route = self.path.split('?')[0].removeprefix('/api/')
                count, field = M.ACClient.ROUTES[route]
                return self.reply({'ret': 1, count: 0, field: []})
            def do_POST(self):
                cls.requests.append(('POST', self.path, None))
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path != '/api/sysauth' or data != {'password': hashlib.md5(('a'*32+'fixture').encode()).hexdigest()}:
                    return self.reply({'ret': 0})
                return self.reply({'ret': 1, 'token': 'synthetic-session'})
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.addClassCleanup(cls.server.server_close); cls.addClassCleanup(cls.server.shutdown)

    def client(self):
        return M.ACClient('http://127.0.0.1:'+str(self.server.server_port), 'fixture')

    def test_real_http_authentication_read_only_routes_and_session_reuse(self):
        self.requests.clear(); client = self.client(); first = client.collect(100); client.collect(200)
        self.assertEqual(first['unique_clients'], 0)
        self.assertEqual([r for r in self.requests if r[0] == 'POST'], [('POST', '/api/sysauth', None)])
        self.assertTrue(all(r[2] == 'synthetic-session' for r in self.requests if r[0] == 'GET' and '?' in r[1]))

    def test_endpoint_and_method_allowlists(self):
        for url in ('http://user:pass@192.0.2.1', 'ftp://192.0.2.1', 'http://192.0.2.1/api', 'http://192.0.2.1?a=1'):
            with self.assertRaises(M.CollectionError): M.ACClient(url, 'fixture')
        client = self.client()
        for route, body in [('system/reboot', None), ('ac/apsearch', {}), ('sysauth', None)]:
            with self.assertRaises(M.CollectionError): client.request(route, body)

    def test_redirects_do_not_forward_authentication(self):
        handler = M.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, '', {}, 'http://192.0.2.3/'))
        self.assertEqual(self.client().opener.proxies if hasattr(self.client().opener, 'proxies') else {}, {})

    def test_all_pages_are_fetched(self):
        client = self.client()
        with patch.object(client, 'request', side_effect=[{'apnum': 101, 'aplist': [{'id': i} for i in range(100)]},
                                                         {'apnum': 101, 'aplist': [{'id': 100}]}]) as request:
            self.assertEqual(len(client.pages('ac/apsearch')), 101)
            self.assertIn('pagenum=2', request.call_args.args[0])

    def test_partial_invalid_and_repeated_pages_are_rejected(self):
        client = self.client()
        for data in ({'apnum': 10, 'aplist': []}, {'apnum': '10'}, {'apnum': 3000}, {'apnum': 1, 'aplist': ['bad']}):
            with patch.object(client, 'request', return_value=data):
                with self.assertRaises(M.CollectionError): client.pages('ac/apsearch')
        with patch.object(client, 'request', return_value={'apnum': 2, 'aplist': [{'id': 1}]}):
            with self.assertRaisesRegex(M.CollectionError, 'repeated'): client.pages('ac/apsearch')

    def test_expired_session_retries_once_without_publishing_partial_data(self):
        client = self.client(); client.session_value = 'expired'
        client.collect()
        self.assertEqual(client.session_value, 'synthetic-session')
        with patch.object(client, 'pages', side_effect=M.CollectionError('auth_expired')):
            with self.assertRaisesRegex(M.CollectionError, 'auth_expired'): client.collect()


if __name__ == '__main__': unittest.main()
