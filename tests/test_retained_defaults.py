import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from scripts.fwlib import ROOT, profile, requested_config


UCI_MOCK = r'''#!/usr/bin/env python3
import json,os,pathlib,shlex,sys
p=pathlib.Path(os.environ['UCI_STORE']);state=json.loads(p.read_text())
args=[a for a in sys.argv[1:] if a!='-q']
def apply(parts):
    if not parts:return
    with open(os.environ['UCI_LOG'],'a') as out:out.write(' '.join(parts)+'\n')
    if parts[0]=='set':
        name,value=parts[1].split('=',1);state[name]=value
    elif parts[0]=='delete':state.pop(parts[1],None)
if args[0]=='get':
    if args[1] not in state:sys.exit(1)
    print(state[args[1]])
elif args[0]=='batch':
    for line in sys.stdin:apply(shlex.split(line,comments=True))
else:apply(args)
p.write_text(json.dumps(state))
'''


class RetainedDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.work.cleanup)
        cls.tree=Path(cls.work.name)
        fixture=ROOT/'tests/fixtures/retained'
        manifest=json.loads((fixture/'manifest.json').read_text())
        for name,digest in manifest['files'].items():
            if hashlib.sha256((fixture/name).read_bytes()).hexdigest()!=digest:
                raise AssertionError('Pinned fixture mismatch: '+name)
        for feed in ('luci','packages'):shutil.copytree(fixture/feed,cls.tree/feed)
        for feed,patch in [('luci','patches/feeds/luci/x86-ha/030-retained-defaults.patch'),
                           ('packages','patches/feeds/packages/030-openvpn-ha-guard.patch')]:
            subprocess.run(['git','apply','--check',str(ROOT/patch)],cwd=cls.tree/feed,check=True,capture_output=True)
            subprocess.run(['git','apply',str(ROOT/patch)],cwd=cls.tree/feed,check=True,capture_output=True)
        cls.app=cls.tree/'luci/applications/luci-app-openvpn-server'
        cls.ipsec=cls.tree/'luci/applications/luci-app-ipsec-vpnd'

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.bin=self.base/'bin';self.bin.mkdir()
        self.store=self.base/'uci.json';self.log=self.base/'uci.log';self.store.write_text('{}')
        p=self.bin/'uci';p.write_text(UCI_MOCK);p.chmod(0o755)
        self.env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],
                  'UCI_STORE':str(self.store),'UCI_LOG':str(self.log)}

    def run_shell(self,path,**extra):
        return subprocess.run(['sh',str(path)],env={**self.env,**extra},text=True,capture_output=True)

    def prepare_hook(self,app,name):
        build=self.base/name;shutil.copytree(app/'root',build/'root')
        text=(app/'Makefile').read_text()
        body=re.search(r'(?ms)^define Build/Prepare/'+re.escape(name)+r'\n(.*?)^endef',text)[1]
        make=self.base/(name+'.mk')
        make.write_text('PKG_BUILD_DIR := '+str(build)+'\nINSTALL_CONF := install -m0600\n.PHONY: all\nall:\n'+body)
        subprocess.run(['make','-f',str(make),'all'],cwd=app,check=True,capture_output=True)
        return build

    def test_openvpn_prepare_hook_keeps_backend_config_out_of_ui_package(self):
        build=self.prepare_hook(self.app,'luci-app-openvpn-server')
        self.assertFalse((build/'root/etc/config/openvpn').exists())
        self.assertTrue((build/'root/etc/openvpn/genovpn.sh').exists())

    def test_ipsec_prepare_hook_has_no_preset_credentials_or_addresses(self):
        build=self.prepare_hook(self.ipsec,'luci-app-ipsec-vpnd')
        config=build/'root/etc/config/ipsec-vpnd';text=config.read_text()
        self.assertIn("option enabled '0'",text)
        self.assertNotRegex(text,r'option\s+(?:account|secret|password|clientip|clientdns)\b')
        self.assertEqual(config.stat().st_mode & 0o777,0o600)

    def test_optional_themes_register_without_changing_current_visual_default(self):
        for theme,title in [('argon','Argon'),('material','Material')]:
            self.store.write_text(json.dumps({'luci.main.mediaurlbase':'/luci-static/bootstrap'}))
            result=self.run_shell(self.tree/f'luci/themes/luci-theme-{theme}/root/etc/uci-defaults/30_luci-theme-{theme}',PKG_UPGRADE='0')
            self.assertEqual(result.returncode,0,result.stderr)
            state=json.loads(self.store.read_text())
            self.assertEqual(state['luci.main.mediaurlbase'],'/luci-static/bootstrap')
            self.assertEqual(state['luci.themes.'+title],'/luci-static/'+theme)

    def test_vpn_first_boot_does_not_modify_network_firewall_or_existing_server(self):
        original={'network.lan.ipaddr':'192.0.2.1','firewall.custom':'rule','openvpn.myvpn':'openvpn','openvpn.myvpn.enabled':'1'}
        self.store.write_text(json.dumps(original))
        for app,script in [(self.app,'openvpn'),(self.ipsec,'luci-ipsec-vpnd')]:
            result=self.run_shell(app/'root/etc/uci-defaults'/script)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(self.store.read_text()),original)
        self.assertFalse(self.log.exists())

    def test_new_openvpn_server_is_disabled_without_addresses_or_endpoint(self):
        result=self.run_shell(self.app/'root/etc/uci-defaults/openvpn')
        self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads(self.store.read_text())
        self.assertEqual(state['openvpn.myvpn.enabled'],'0')
        for field in ('server','push','ddns','local'):
            self.assertNotIn('openvpn.myvpn.'+field,state)
        self.assertFalse(any(n.startswith(('network.','firewall.')) for n in state))

    def export_script(self):
        root=self.base/'openvpn';pki=root/'pki';pki.mkdir(parents=True)
        for name in ('ca.crt','client1.crt','client1.key'):(pki/name).write_text('fixture-'+name+'\n')
        (self.base/'tmp').mkdir()
        text=(self.app/'root/etc/openvpn/genovpn.sh').read_text()
        text=text.replace('/etc/openvpn',str(root)).replace('/tmp/',str(self.base/'tmp')+'/')
        script=self.base/'export.sh';script.write_text(text)
        self.store.write_text(json.dumps({'openvpn.myvpn.ddns':'vpn.example.test',
            'openvpn.myvpn.port':'1194','openvpn.myvpn.proto':'tcp4-server'}))
        return script,self.base/'tmp/my.ovpn'

    def test_export_maps_tcp_server_to_client_and_protects_profile(self):
        script,output=self.export_script();victim=self.base/'victim';victim.write_text('unchanged')
        output.symlink_to(victim)
        result=self.run_shell(script)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(victim.read_text(),'unchanged')
        self.assertFalse(output.is_symlink())
        self.assertEqual(output.stat().st_mode & 0o777,0o600)
        text=output.read_text()
        self.assertIn('proto tcp4-client\n',text)
        self.assertIn('remote vpn.example.test 1194\n',text)
        self.assertIn('<key>\nfixture-client1.key',text)
        self.assertNotIn('fixture-client1.key',result.stdout+result.stderr)

    def test_invalid_export_cannot_reuse_an_old_profile(self):
        script,output=self.export_script();output.write_text('old profile')
        state=json.loads(self.store.read_text());state['openvpn.myvpn.ddns']='bad\nendpoint';self.store.write_text(json.dumps(state))
        result=self.run_shell(script)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(output.exists())

    def test_openvpn_lua_syntax(self):
        compiler=shutil.which('luac5.1') or shutil.which('luac')
        if not compiler:self.skipTest('Lua parser unavailable; target syntax validation remains pending')
        source=self.app/'luasrc/model/cbi/openvpn-server/openvpn-server.lua'
        subprocess.run([compiler,'-p',str(source)],check=True,capture_output=True)

    def test_syncdial_redial_button_obeys_policy_before_touching_ppp(self):
        runtime=shutil.which('lua5.1') or shutil.which('lua')
        if not runtime:self.skipTest('Lua runtime unavailable')
        source=self.tree/'luci/applications/luci-app-syncdial/luasrc/controller/syncdial.lua'
        script=self.base/'redial-test.lua'
        script.write_text('''
module = function() end
local policy, calls, status, response = 1, 0, nil, nil
package.preload["luci.sys"] = function() return {call = function(command)
    assert(command:find("allow-multidial.sh", 1, true)); return policy
end} end
package.preload["luci.http"] = function() return {
    status = function(code) status = code end,
    prepare_content = function(kind) assert(kind == "application/json") end,
    write_json = function(value) response = value end
} end
os.execute = function(command)
    assert(command == "killall -9 pppd"); calls = calls + 1; return 0
end
assert(loadfile(arg[1]))()
redial()
assert(calls == 0 and status == 409 and response.error)
policy = 0
redial()
assert(calls == 1)
''')
        subprocess.run([runtime,str(script),str(source)],check=True,capture_output=True)

    def test_init_scripts_and_export_parse_as_shell(self):
        for root in (self.tree/'luci',self.tree/'packages'):
            for file in root.rglob('*'):
                if file.is_file() and file.read_bytes().startswith(b'#!/bin/sh'):
                    subprocess.run(['sh','-n',str(file)],check=True,capture_output=True)

    def test_syncdial_is_blocked_before_network_or_hotplug_actions(self):
        helper=self.base/'allow-multidial.sh';helper.write_text('#!/bin/sh\nexit 1\n');helper.chmod(0o755)
        logger=self.bin/'logger';logger.write_text('#!/bin/sh\nexit 0\n');logger.chmod(0o755)
        app=self.tree/'luci/applications/luci-app-syncdial/root'
        for name,status in [('bin/genwancfg',1),('etc/hotplug.d/iface/01-dialcheck',0),
                            ('etc/hotplug.d/iface/01-mvifcreate',0)]:
            text=(app/name).read_text().replace('/usr/libexec/firmware-ha/allow-multidial.sh',str(helper))
            # A canary replaces the upstream body after the actual patched guard.
            guard,body=text.split('\nfi\n',1)
            script=self.base/Path(name).name
            script.write_text(guard+'\nfi\nprintf reached > "'+str(self.base/'reached')+'"\n'+body)
            result=self.run_shell(script)
            self.assertEqual(result.returncode,status,result.stderr)
            self.assertFalse((self.base/'reached').exists())
        self.assertFalse(self.log.exists())

    def test_every_mapped_plugin_is_explicitly_requested_on_x86(self):
        # Public CI does not have private device data: use the public plan rows.
        public=json.loads((ROOT/'migration/current-plugin-plan.json').read_text())
        config=requested_config(profile('x86-ha'))
        for row in public['plugins']:
            if row['action']=='review' or row['unavailable']:continue
            for package in row['packages']:self.assertEqual(config.get('CONFIG_PACKAGE_'+package),'y',package)
        self.assertEqual(config['CONFIG_TARGET_ROOTFS_PARTSIZE'],'2048')
        self.assertEqual(requested_config(profile('x86-basic'))['CONFIG_TARGET_ROOTFS_PARTSIZE'],'512')
