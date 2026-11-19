import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from scripts.fwlib import ROOT

spec=importlib.util.spec_from_file_location('keepalived_netns_test',ROOT/'tests/integration/keepalived_netns.py')
integration=importlib.util.module_from_spec(spec);spec.loader.exec_module(integration)

# Contract fixture for the tested VRRP-only build: no LVS selector (-P/-C).
# Running --help exercises argv parsing without starting a daemon or networking.
CLI=r'''#!/usr/bin/env python3
import getopt,json,os,sys
with open(os.environ['CLI_CALLS'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\n')
try:options,arguments=getopt.getopt(sys.argv[1:],'nlp:r:f:',['help'])
except getopt.GetoptError as exc:print(str(exc),file=sys.stderr);sys.exit(2)
if arguments or not options or options[-1][0]!='--help':
    print('fixture only permits help parsing',file=sys.stderr);sys.exit(3)
print('fixture help; VRRP-only argument parsing succeeded')
'''


class KeepalivedCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.bin=self.base/'bin';self.bin.mkdir()
        executable=self.bin/'keepalived';executable.write_text(CLI);executable.chmod(0o755)
        self.calls=self.base/'calls'
        self.env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],'CLI_CALLS':str(self.calls)}

    def test_preflight_parses_runtime_arguments_for_both_private_instances(self):
        expected=[]
        for node in ('primary','backup'):
            state=self.base/node;state.mkdir()
            integration.check_daemon_cli(state,env=self.env)
            runtime=integration.daemon_command(state)
            self.assertEqual(runtime[runtime.index('-p')+1],str(state/'parent.pid'))
            self.assertEqual(runtime[runtime.index('-r')+1],str(state/'vrrp.pid'))
            self.assertEqual(runtime[runtime.index('-f')+1],str(state/'keepalived.conf'))
            expected.append([*runtime[1:],'--help'])
            self.assertEqual(list(state.iterdir()),[])
        self.assertEqual([json.loads(line) for line in self.calls.read_text().splitlines()],expected)

    def test_unsupported_selector_is_rejected_with_diagnostics(self):
        command=[*integration.daemon_command(self.base),'-P']
        with patch.object(integration,'daemon_command',return_value=command):
            with self.assertRaisesRegex(RuntimeError,'exit 2.*option -P not recognized'):
                integration.check_daemon_cli(self.base,env=self.env)

    def test_exact_native_fixtures_render_for_both_roles_and_paths(self):
        for name in ('uci','ubus','jsonfilter','dnsmasq','logger'):
            executable=self.bin/name;executable.write_text(integration.MOCK);executable.chmod(0o755)
        lib=ROOT/'local-packages/firmware-ha/files'
        for dual in (False,True):
            for index in range(2):
                with self.subTest(dual=dual,index=index):
                    state=self.base/('dual' if dual else 'single')/str(index);state.mkdir(parents=True)
                    settings=state/'settings.json';settings.write_text(json.dumps(integration.fixture_settings(index,dual)))
                    env={**self.env,'HA_SETTINGS':str(settings),'HA_LIB':str(lib),'HA_RUN':str(state),'HA_INIT':str(self.bin)}
                    # Rendering itself requires no namespace or root privileges.
                    with patch.object(integration,'net',side_effect=lambda ns,*args,**kw:integration.run(list(map(str,args)),**kw)):
                        config=integration.render_config('fixture',lib,env)
                    self.assertIn('priority '+str(200 if index==0 else 100),config)
                    self.assertIn('192.0.2.1/24 dev lan0',config)
                    self.assertIn('198.51.100.1/24 dev iot0',config)
                    self.assertIn('unicast_src_ip '+('198.19.0.'+str(index+1) if dual else '192.0.2.'+str(index+2)),config)

    def test_failed_renderer_reports_captured_validation_instead_of_only_exit_code(self):
        failure=subprocess.CalledProcessError(1,['sh','render.sh'],output='',stderr='firmware-ha: missing service executable\n')
        with patch.object(integration,'net',side_effect=failure):
            with self.assertRaisesRegex(RuntimeError,'fixture.*exit 1.*\nfirmware-ha: missing service executable'):
                integration.render_config('fixture',self.base,self.env)

    def test_workspace_executes_probe_before_accepting_a_directory(self):
        with integration.fixture_workspace([self.base]) as work:
            self.assertEqual(work.parent,self.base)
            self.assertEqual(work.stat().st_mode & 0o777,0o755)
            self.assertEqual(list(work.iterdir()),[])
            accepted=work
        self.assertFalse(accepted.exists())

    def test_noexec_workspace_falls_back_and_cleans_rejected_directory(self):
        blocked=self.base/'blocked';blocked.mkdir()
        allowed=self.base/'allowed';allowed.mkdir()
        execute=integration.run
        def probe(args,**kwargs):
            if Path(args[0]).is_relative_to(blocked):
                raise PermissionError(13,'Permission denied',args[0])
            return execute(args,**kwargs)
        with patch.object(integration,'run',side_effect=probe):
            with integration.fixture_workspace([blocked,allowed]) as work:
                self.assertEqual(work.parent,allowed)
                self.assertEqual(list(blocked.iterdir()),[])
        self.assertEqual(list(allowed.iterdir()),[])

    def test_workspace_reports_when_no_location_permits_execution(self):
        with patch.object(integration,'run',side_effect=PermissionError(13,'Permission denied')):
            with self.assertRaisesRegex(RuntimeError,'No executable HA fixture workspace.*execution denied'):
                with integration.fixture_workspace([self.base]):
                    self.fail('Non-executable workspace must never be used')
        self.assertEqual(list(self.base.glob('firmware-ha-integration-*')),[])
