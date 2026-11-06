import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from scripts.fwlib import ROOT

HELPER = ROOT/'local-packages/neko-bbr/files/apply.sh'

MOCK = r'''#!/usr/bin/env python3
import fcntl,json,os,pathlib,subprocess,sys
name=pathlib.Path(sys.argv[0]).name
if name=='flock':
    with open(sys.argv[2],'a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:sys.exit(1)
        sys.exit(subprocess.run(sys.argv[3:]).returncode)
p=pathlib.Path(os.environ['BBR_STATE']);state=json.loads(p.read_text())
with open(os.environ['BBR_CALLS'],'a') as log:log.write(name+' '+' '.join(sys.argv[1:])+'\n')
if name=='uci':
    print(state['requested'])
elif name=='modprobe':
    if state.get('module_fail'):sys.exit(1)
elif name=='sysctl':
    if sys.argv[1]=='-n':print(state['available'] if 'available' in sys.argv[2] else state['current'])
    else:
        value=sys.argv[2].split('=',1)[1]
        if value=='bbr' and state.get('write_fail'):sys.exit(1)
        state['current']=value;p.write_text(json.dumps(state))
'''


class BbrTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.bin=self.base/'bin';self.bin.mkdir()
        self.run=self.base/'run';self.state=self.base/'state';self.calls=self.base/'calls'
        self.values={'requested':'0','current':'cubic','available':'reno cubic bbr'}
        for name in ('uci','sysctl','modprobe','flock'):
            file=self.bin/name;file.write_text(MOCK);file.chmod(0o755)
        self.env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],
                  'BBR_RUN':str(self.run),'BBR_STATE':str(self.state),'BBR_CALLS':str(self.calls)}

    def invoke(self,action='apply'):
        self.state.write_text(json.dumps(self.values))
        result=subprocess.run([str(HELPER),action],env=self.env,text=True,capture_output=True)
        self.values=json.loads(self.state.read_text())
        return result

    def writes(self):
        return [line for line in self.calls.read_text().splitlines() if line.startswith('sysctl -w')] if self.calls.exists() else []

    def test_disabled_unmanaged_settings_leave_kernel_unchanged(self):
        self.values['current']='reno'
        self.assertEqual(self.invoke().returncode,0)
        self.assertEqual(self.values['current'],'reno');self.assertEqual(self.writes(),[])
        self.assertFalse((self.run/'previous').exists())

    def test_enable_preserves_previous_value_and_private_state(self):
        self.values.update(requested='1',current='reno')
        self.assertEqual(self.invoke().returncode,0)
        self.assertEqual(self.values['current'],'bbr')
        previous=self.run/'previous';self.assertEqual(previous.read_text(),'reno\n')
        self.assertEqual(previous.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.run.stat().st_mode & 0o777,0o700)
        self.assertEqual(self.invoke().returncode,0)
        self.assertEqual(previous.read_text(),'reno\n')

    def test_disable_restores_recorded_algorithm(self):
        self.values.update(requested='1',current='reno');self.assertEqual(self.invoke().returncode,0)
        self.values['requested']='0';self.assertEqual(self.invoke().returncode,0)
        self.assertEqual(self.values['current'],'reno');self.assertFalse((self.run/'previous').exists())

    def test_different_manual_selection_is_preserved(self):
        self.values['requested']='1';self.assertEqual(self.invoke().returncode,0)
        self.values['current']='reno';self.assertEqual(self.invoke('restore').returncode,0)
        self.assertEqual(self.values['current'],'reno')
        self.assertEqual(len(self.writes()),1)

    def test_explicit_reapply_after_manual_override_uses_new_baseline(self):
        self.values['requested']='1';self.assertEqual(self.invoke().returncode,0)
        self.values['current']='reno';self.assertEqual(self.invoke().returncode,0)
        self.assertEqual((self.run/'previous').read_text(),'reno\n')
        self.assertEqual(self.invoke('restore').returncode,0);self.assertEqual(self.values['current'],'reno')

    def test_missing_module_or_registration_never_changes_algorithm(self):
        self.values.update(requested='1',module_fail=True)
        self.assertNotEqual(self.invoke().returncode,0);self.assertEqual(self.writes(),[])
        self.values.update(module_fail=False,available='reno cubic')
        self.assertNotEqual(self.invoke().returncode,0);self.assertEqual(self.writes(),[])
        self.assertFalse((self.run/'previous').exists())

    def test_failed_selection_cleans_unused_baseline(self):
        self.values.update(requested='1',write_fail=True)
        self.assertNotEqual(self.invoke().returncode,0)
        self.assertEqual(self.values['current'],'cubic');self.assertFalse((self.run/'previous').exists())

    def test_unavailable_previous_algorithm_retains_recovery_state(self):
        self.values['requested']='1';self.assertEqual(self.invoke().returncode,0)
        self.values['available']='reno bbr'
        self.assertNotEqual(self.invoke('restore').returncode,0)
        self.assertEqual(self.values['current'],'bbr');self.assertEqual((self.run/'previous').read_text(),'cubic\n')

    def test_invalid_selection_and_state_do_not_reach_kernel_write(self):
        self.values['requested']='1; fixture'
        self.assertNotEqual(self.invoke().returncode,0);self.assertEqual(self.writes(),[])
        (self.run/'previous').write_text('invalid; fixture\n')
        self.assertNotEqual(self.invoke('restore').returncode,0);self.assertEqual(self.writes(),[])

    def test_symlink_state_is_rejected_without_touching_target(self):
        victim=self.base/'victim';victim.write_text('unchanged')
        self.run.mkdir();(self.run/'previous').symlink_to(victim)
        self.values['requested']='1'
        self.assertNotEqual(self.invoke().returncode,0)
        self.assertEqual(victim.read_text(),'unchanged');self.assertEqual(self.writes(),[])

    def test_lock_contention_prevents_parallel_apply(self):
        self.run.mkdir();self.values['requested']='1'
        with (self.run/'lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertNotEqual(self.invoke().returncode,0)
        self.assertEqual(self.writes(),[])


class AccelerationPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        cls.tree=Path(cls.tmp.name);fixture=ROOT/'tests/fixtures/acceleration'
        for name,digest in json.loads((fixture/'manifest.json').read_text()).items():
            if hashlib.sha256((fixture/name).read_bytes()).hexdigest()!=digest:raise AssertionError('Fixture changed: '+name)
        shutil.copytree(fixture/'package',cls.tree/'package')
        shutil.copytree(fixture/'feeds',cls.tree/'feeds')
        for target,patch in [(cls.tree,'patches/x86-ha/010-bbr-preserve-default.patch'),
                             (cls.tree/'feeds/packages','patches/feeds/packages/x86-ha/040-dnsproxy-explicit-config.patch')]:
            for flags in (['--check'],[]):subprocess.run(['git','apply',*flags,str(ROOT/patch)],cwd=target,check=True,capture_output=True)
        cls.dns=cls.tree/'feeds/packages/net/dnsproxy/files'
        cls.init=(cls.dns/'dnsproxy.init').read_text()
        cls.library=(cls.tree/'package/base-files/files/lib/functions.sh').read_text().split('default_prerm()')[0]

    def test_module_and_dnsproxy_installation_do_not_force_global_sysctls(self):
        bbr=(self.tree/'package/kernel/linux/files/sysctl-tcp-bbr.conf').read_text()
        for text in (bbr,(self.dns/'dnsproxy.sysctl').read_text()):
            self.assertFalse(any(line.strip() and not line.lstrip().startswith('#') for line in text.splitlines()))

    def test_dnsproxy_has_no_default_external_resolvers_and_is_disabled(self):
        text=(self.dns/'dnsproxy.config').read_text()
        self.assertIn("option enabled '0'",text)
        servers=text.split("config dnsproxy 'servers'",1)[1].split('config dnsproxy',1)[0]
        self.assertNotIn('list upstream ',servers);self.assertNotIn('list bootstrap ',servers);self.assertNotIn('list fallback ',servers)

    def run_init(self,enabled='1',upstreams=None,extra='',guard_blocks=False):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);log=base/'calls';args=base/'argv'
            recorder=base/'record';recorder.write_text('#!/usr/bin/env python3\nimport json,os,sys\nwith open(os.environ["DNS_ARGS"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n');recorder.chmod(0o755)
            script=base/'init.sh'
            loader=['config dnsproxy global','option enabled '+shlex.quote(enabled),"list listen_addr '127.0.0.1'","list listen_port '5353'",'config dnsproxy cache',"option enabled '1'",'config dnsproxy servers']
            for upstream in upstreams or []:loader.append('list upstream '+shlex.quote(upstream))
            guard=base/'guard'
            if guard_blocks:
                guard.write_text('#!/bin/sh\nprintf "guard %s\\n" "$1" >> "$DNS_CALLS"\nexit 1\n');guard.chmod(0o755)
            source=self.init.replace('/usr/libexec/firmware-ha/service-guard.sh',str(guard))
            script.write_text(self.library+'\n'+source+'\nconfig_load() {\n'+'\n'.join(loader)+'\n}\n'+'''
procd_open_instance() { printf 'open\n' >> "$DNS_CALLS"; }
procd_set_param() { :; }
procd_append_param() { "$DNS_RECORDER" "$@"; }
procd_add_jail() { :; }
procd_add_jail_mount() { :; }
procd_add_jail_mount_rw() { :; }
procd_close_instance() { printf 'close\n' >> "$DNS_CALLS"; }
'''+extra+'\nstart_service\n')
            env={**os.environ,'DNS_ARGS':str(args),'DNS_CALLS':str(log),'DNS_RECORDER':str(recorder)}
            result=subprocess.run(['bash',str(script)],env=env,text=True,capture_output=True)
            return result,log.read_text() if log.exists() else '',[json.loads(line) for line in args.read_text().splitlines()] if args.exists() else []

    def test_disabled_or_missing_upstream_does_not_start(self):
        for enabled,upstreams in [('0',['https://fixture.invalid/dns-query']),('1',[])]:
            result,calls,args=self.run_init(enabled,upstreams)
            self.assertNotEqual(result.returncode,0);self.assertEqual(calls,'');self.assertEqual(args,[])
        result,calls,args=self.run_init(upstreams=['https://fixture.invalid/dns-query'],guard_blocks=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,'guard dnsproxy\n');self.assertEqual(args,[])

    def test_real_config_helpers_preserve_each_argument_and_boolean_flag(self):
        endpoint='https://fixture.invalid/dns-query?label=a b *'
        result,calls,args=self.run_init(upstreams=[endpoint])
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls,'open\nclose\n')
        self.assertIn(['command','--upstream',endpoint],args)
        self.assertIn(['command','--cache'],args)
        self.assertNotIn(['command','--cache',''],args)
