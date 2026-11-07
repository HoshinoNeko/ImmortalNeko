import importlib.util
import json
import os
from pathlib import Path
import tempfile
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
