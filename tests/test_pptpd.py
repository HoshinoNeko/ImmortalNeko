import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from scripts.fwlib import ROOT


class PptpdBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patched_tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.patched_tmp.cleanup)
        cls.tree=Path(cls.patched_tmp.name)
        shutil.copytree(ROOT/'tests/fixtures/pptpd',cls.tree/'net/pptpd')
        patch=ROOT/'patches/feeds/packages/020-pptpd-retention.patch'
        for action in (['--check'],[]):
            subprocess.run(['git','apply',*action,str(patch)],cwd=cls.tree,check=True,capture_output=True)
        cls.source=(cls.tree/'net/pptpd/files/pptpd.init').read_text()
        subprocess.run(['sh','-n',str(cls.tree/'net/pptpd/files/pptpd.init')],check=True)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.chap=self.base/'chap-secrets'
        self.filter=self.tree/'net/pptpd/files/chap-filter.awk'
        self.env={**os.environ,'TEST_CHAP':str(self.chap),'TEST_FILTER':str(self.filter),
                  'TEST_LINK':str(self.base/'chap-link'),'TEST_CALLS':str(self.base/'calls')}

    def function(self,name):
        match=re.search(r'(?ms)^'+re.escape(name)+r'\(\) \{\n.*?^\}',self.source)
        self.assertIsNotNone(match,name)
        return match.group()

    def shell(self,script,**env):
        return subprocess.run(['sh','-c',script],env={**self.env,**env},text=True,capture_output=True)

    def test_formatting_round_trip_preserves_spaces_quotes_and_backslashes(self):
        script='CHAP_SECRETS="$TEST_CHAP"; login_failed=0\n'+self.function('quote_chap_field')+'\n'+self.function('setup_login')+'\nsetup_login sample 0'
        user='fixture "user" with spaces'
        credential='fixture-only \\ "quoted" # punctuation $ `literal`'
        result=self.shell(script,username=user,password=credential,remoteip='192.0.2.10 !198.51.100.0/24 *')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(shlex.split(self.chap.read_text(),comments=True),
                         [user,'pptp-server',credential,'192.0.2.10','!198.51.100.0/24','*'])
        self.assertNotIn(credential,result.stdout+result.stderr)

    def test_empty_address_default_is_a_literal_wildcard(self):
        script='CHAP_SECRETS="$TEST_CHAP"; login_failed=0\n'+self.function('quote_chap_field')+'\n'+self.function('setup_login')+'\nsetup_login sample 0'
        # The working directory contains files, so accidental glob expansion is observable.
        result=self.shell(script,username='fixture',password='fixture-only',remoteip='')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(shlex.split(self.chap.read_text())[-1],'*')

    def test_control_characters_are_rejected_without_appending_an_entry(self):
        script='CHAP_SECRETS="$TEST_CHAP"; login_failed=0\n'+self.function('quote_chap_field')+'\n'+self.function('setup_login')+'\nsetup_login sample 0'
        for value in ('fixture\nsecond line','fixture\rreturn','fixture\ttab'):
            self.chap.write_text('existing\n')
            result=self.shell(script,username='fixture',password=value,remoteip='*')
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(self.chap.read_text(),'existing\n')

    def test_filter_removes_only_pptp_rows_including_quoted_and_dashed_names(self):
        keep='# comment stays\n"other user" pppoe-server "fixture-only" *\nplain another-server fixture-only *\n'
        old='"old user" pptp-server "fixture-only" *\ndash-name "pptp-server" fixture-only *\n'
        result=subprocess.run(['awk','-f',str(self.filter)],input=keep+old,text=True,capture_output=True,check=True)
        self.assertEqual(result.stdout,keep)

    def start_script(self):
        start=self.function('start_service')
        start=start.replace('/usr/libexec/firmware-ha/service-guard.sh',str(self.base/'absent-guard'))
        start=start.replace('/usr/lib/pptpd/chap-filter.awk','"$TEST_FILTER"')
        stubs='''
CHAP_SECRETS="$TEST_CHAP"; BIN=fixture-server; CONFIG=fixture-config; OPTIONS_PPTP=fixture-options
config_load() { :; }
validate_pptpd_section() { return 0; }
config_foreach() {
    username="$TEST_LOGIN_USER"; password="$TEST_LOGIN_CRED"; remoteip="$TEST_LOGIN_ADDR"
    setup_login sample 0 || true
}
ln() { command ln -sfn "$2" "$TEST_LINK"; }
procd_open_instance() { echo started >> "$TEST_CALLS"; }
procd_set_param() { :; }
procd_close_instance() { :; }
'''
        return stubs+self.function('quote_chap_field')+'\n'+self.function('setup_login')+'\n'+start+'\nstart_service'

    def test_reload_replaces_pptp_accounts_atomically_and_preserves_other_protocols(self):
        other='other pppoe-server fixture-only *\n'
        self.chap.write_text(other+'"old user" pptp-server fixture-only *\n');self.chap.chmod(0o644)
        result=self.shell(self.start_script(),TEST_LOGIN_USER='new user',TEST_LOGIN_CRED='fixture-only',TEST_LOGIN_ADDR='*')
        self.assertEqual(result.returncode,0,result.stderr)
        text=self.chap.read_text()
        self.assertTrue(text.startswith(other));self.assertNotIn('old user',text)
        self.assertEqual(shlex.split(text.splitlines()[1]),['new user','pptp-server','fixture-only','*'])
        self.assertEqual(self.chap.stat().st_mode & 0o777,0o600)
        self.assertEqual((self.base/'chap-link').resolve(),self.chap.resolve())

    def test_invalid_account_does_not_replace_previous_file_or_start_server(self):
        original='old pptp-server fixture-only *\n'
        self.chap.write_text(original)
        result=self.shell(self.start_script(),TEST_LOGIN_USER='new',TEST_LOGIN_CRED='bad\nline',TEST_LOGIN_ADDR='*')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.chap.read_text(),original)
        self.assertFalse((self.base/'calls').exists())
        self.assertEqual(list(self.base.glob('chap-secrets.*')),[])

    def test_ha_guard_rejects_start_before_files_or_processes_change(self):
        guard=self.base/'absent-guard';guard.write_text('#!/bin/sh\nexit 1\n');guard.chmod(0o755)
        original='old pptp-server fixture-only *\n';self.chap.write_text(original)
        result=self.shell(self.start_script(),TEST_LOGIN_USER='new',TEST_LOGIN_CRED='fixture-only',TEST_LOGIN_ADDR='*')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.chap.read_text(),original)
        self.assertFalse((self.base/'calls').exists())

    def test_legacy_dns_servers_are_written_to_ppp_options(self):
        script='''
CONFIG="$TEST_CHAP.config"; OPTIONS_PPTP="$TEST_CHAP.options"
mkdir() { :; }
cp() { : > "$2"; }
enabled=1; localip=192.0.2.1; remoteip=192.0.2.10-20; mppe=require-mppe-128; logwtmp=0
remotedns="192.0.2.53 198.51.100.53"
'''+self.function('setup_config')+'\nsetup_config pptpd 0'
        result=self.shell(script)
        self.assertEqual(result.returncode,0,result.stderr)
        options=(self.base/'chap-secrets.options').read_text()
        self.assertIn('ms-dns 192.0.2.53\n',options)
        self.assertIn('ms-dns 198.51.100.53\n',options)
        self.assertIn('require-mppe-128\n',options)
        self.assertNotIn('-e ',options)

    def test_disabled_or_unconfigured_server_does_not_generate_runtime_config(self):
        for enabled,localip,remoteip in (('0','',''),('1','','192.0.2.10-20'),('1','192.0.2.1','')):
            script='''
CONFIG="$TEST_CHAP.config"; OPTIONS_PPTP="$TEST_CHAP.options"
mkdir() { :; }; cp() { : > "$2"; }
'''+self.function('setup_config')+'\nsetup_config pptpd 0'
            result=self.shell(script,enabled=enabled,localip=localip,remoteip=remoteip)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((self.base/'chap-secrets.config').exists())

    def test_image_defaults_are_disabled_with_no_accounts_or_assigned_addresses(self):
        default=(self.tree/'net/pptpd/files/pptpd.config.neko').read_text()
        self.assertIn("option enabled '0'",default)
        for forbidden in ('localip','remoteip','username','password','config login'):
            self.assertNotIn(forbidden,default)
        self.assertIn('./files/pptpd.config.neko',(self.tree/'net/pptpd/Makefile').read_text())
