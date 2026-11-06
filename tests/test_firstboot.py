import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.fwlib import ROOT
from test_retained_defaults import UCI_MOCK


class FirstBootTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.bin=self.base/'bin';self.bin.mkdir()
        self.store=self.base/'state';self.store.write_text('{"firmware-ha.main.initialized":"0"}')
        self.calls=self.base/'calls';self.list=self.base/'retained'
        for name in ('keepalived','openvpn','ddns-go','zerotier','frpc','homeproxy','sing-box','dockerd','ttyd','v2ray','v2ray_server','dnsproxy','wechatpush'):
            f=self.bin/name;f.write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$1" >> "$CALLS"\n');f.chmod(0o755)
        f=self.bin/'uci';f.write_text(UCI_MOCK);f.chmod(0o755)
        self.env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],'UCI_STORE':str(self.store),
                  'UCI_LOG':str(self.base/'uci-log'),'CALLS':str(self.calls),'HA_INIT':str(self.bin),'HA_RETAINED_LIST':str(self.list)}

    def run_script(self):
        return subprocess.run(['sh',str(ROOT/'local-packages/firmware-ha/files/90-firmware-ha.sh')],env=self.env,text=True,capture_output=True)

    def test_fresh_x86_optional_services_are_disabled_without_network_changes(self):
        self.list.write_text((ROOT/'files/x86-ha/etc/firmware-ha/retained-services').read_text())
        result=self.run_script();self.assertEqual(result.returncode,0,result.stderr)
        text=self.calls.read_text();self.assertIn('dockerd disable',text);self.assertIn('ttyd disable',text)
        self.assertIn('v2ray disable',text);self.assertIn('v2ray_server disable',text)
        self.assertIn('dnsproxy disable',text)
        self.assertIn('wechatpush disable',text)
        self.assertNotIn(' start',text);self.assertNotIn(' restart',text)
        state=json.loads(self.store.read_text());self.assertEqual(state,{'firmware-ha.main.initialized':'1'})

    def test_preserved_initialized_config_does_not_disable_services_again(self):
        self.store.write_text('{"firmware-ha.main.initialized":"1"}')
        self.list.write_text('dockerd\nttyd\n')
        self.assertEqual(self.run_script().returncode,0)
        self.assertFalse(self.calls.exists())

    def test_invalid_or_core_service_data_rejected_before_mutations(self):
        for value in ('network','firewall','dnsmasq','rpcd','bad;command'):
            self.list.write_text(value+'\n')
            self.assertNotEqual(self.run_script().returncode,0)
            self.assertFalse(self.calls.exists())
            self.assertEqual(json.loads(self.store.read_text())['firmware-ha.main.initialized'],'0')

    def test_r619ac_without_optional_list_retains_core_only_defaults(self):
        result=self.run_script();self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('dockerd',self.calls.read_text())
        self.assertNotIn('v2ray',self.calls.read_text())
