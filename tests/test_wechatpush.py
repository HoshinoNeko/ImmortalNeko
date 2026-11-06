import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from scripts.fwlib import ROOT, profile, requested_config


class WechatPushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.tree=Path(cls.tmp.name);fixture=ROOT/'tests/fixtures/wechatpush'
        for name,digest in json.loads((fixture/'manifest.json').read_text()).items():
            if hashlib.sha256((fixture/name).read_bytes()).hexdigest()!=digest:raise AssertionError('Fixture changed: '+name)
        shutil.copytree(fixture/'applications',cls.tree/'applications')
        patch=ROOT/'patches/feeds/luci/x86-ha/040-wechatpush-retention.patch'
        for flags in (['--check'],[]):subprocess.run(['git','apply',*flags,str(patch)],cwd=cls.tree,check=True,capture_output=True)
        cls.app=cls.tree/'applications/luci-app-wechatpush'
        cls.init=(cls.app/'root/etc/init.d/wechatpush').read_text()
        cls.backend=(cls.app/'root/usr/share/wechatpush/wechatpush').read_text()
        cls.helpers=cls.backend.split('# 初始化设置信息',1)[0]
        for text in (cls.init,cls.backend):subprocess.run(['bash','-n'],input=text,text=True,check=True,capture_output=True)

    def run_init(self,flag='0',blocked=False):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);log=base/'calls';guard=base/'guard'
            if blocked:
                guard.write_text('#!/bin/sh\nprintf "guard %s\\n" "$1" >> "$CALLS"\nexit 1\n');guard.chmod(0o755)
            source=self.init.replace('/usr/libexec/firmware-ha/service-guard.sh',str(guard))
            source+='''
uci() { [ "$FLAG" = missing ] && return 1; printf '%s\\n' "$FLAG"; }
procd_open_instance() { printf 'open\\n' >> "$CALLS"; }
procd_set_param() { printf '%s\\n' "$*" >> "$CALLS"; }
procd_close_instance() { printf 'close\\n' >> "$CALLS"; }
start_service
'''
            result=subprocess.run(['sh'],input=source,text=True,capture_output=True,
                env={**os.environ,'FLAG':flag,'CALLS':str(log)})
            return result,log.read_text() if log.exists() else ''

    def test_disabled_missing_and_invalid_flags_never_register_a_process(self):
        for flag in ('0','missing','2','invalid'):
            result,calls=self.run_init(flag)
            self.assertEqual(calls,'')
            self.assertEqual(result.returncode,0 if flag in ('0','missing') else 1)

    def test_explicit_enable_registers_only_the_official_backend(self):
        result,calls=self.run_init('1')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,'open\ncommand /usr/share/wechatpush/wechatpush\nclose\n')

    def test_managed_standby_guard_blocks_process_registration(self):
        result,calls=self.run_init('1',blocked=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls,'guard wechatpush\n')

    def test_uci_values_are_data_including_quotes_and_command_text(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);value=base/'value';result_file=base/'result';marker=base/'must-not-exist'
            payload="fixture'; touch "+str(marker)+"; : '\n$(touch "+str(marker)+") $HOME * \\ tail"
            value.write_text(payload+'\n')
            script=self.helpers+'''
uci() { cat "$VALUE"; }
get_config device_name
printf '%s' "$device_name" > "$RESULT"
'''
            result=subprocess.run(['bash'],input=script,text=True,capture_output=True,
                env={**os.environ,'VALUE':str(value),'RESULT':str(result_file)})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result_file.read_text(),payload);self.assertFalse(marker.exists())

    def test_invalid_variable_names_are_rejected_before_reading_uci(self):
        result=subprocess.run(['bash'],input=self.helpers+"\nuci() { echo called; }\nget_config 'bad[name]'\n",text=True,capture_output=True)
        self.assertNotEqual(result.returncode,0);self.assertEqual(result.stdout,'')

    def test_json_result_values_preserve_quotes_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);out=base/'out';out.mkdir();marker=base/'must-not-exist'
            payload="fixture'; touch "+str(marker)+"; : '\n$literal"
            (out/'_api').write_text(payload+'\n');saved=base/'saved'
            script=self.helpers+'\ndir='+shlex.quote(str(base))+'\noutput_dir='+shlex.quote(str(out))+"\nwait_and_cat\nprintf '%s' \"$_api\" > "+shlex.quote(str(saved))+'\n'
            result=subprocess.run(['bash'],input=script,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(saved.read_text(),payload);self.assertFalse(marker.exists())

    def test_default_and_profile_boundaries_leave_traffic_extension_disabled(self):
        subprocess.run(['msgfmt','--check','-o',os.devnull,str(self.app/'po/zh_Hans/wechatpush.po')],check=True,capture_output=True)
        self.assertIn("option enable '0'",(self.app/'root/etc/config/wechatpush').read_text())
        makefile=(self.app/'Makefile').read_text()
        self.assertIn('depends on BROKEN',makefile)
        for name in ('x86-basic','r619ac-ha'):
            self.assertNotIn('CONFIG_PACKAGE_luci-app-wechatpush',requested_config(profile(name)))
        config=requested_config(profile('x86-ha'))
        self.assertEqual(config['CONFIG_PACKAGE_luci-app-wechatpush'],'y')
        self.assertNotEqual(config.get('CONFIG_PACKAGE_WECHATPUSH_Enable_Traffic_Monitoring'),'y')
