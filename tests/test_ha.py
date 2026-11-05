import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.fwlib import ROOT

LIB=ROOT/'local-packages/firmware-ha/files'
# Mocks exercise the actual installed shell scripts, not a duplicate state model.
MOCK=r"""#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
settings=json.loads(pathlib.Path(os.environ['HA_SETTINGS']).read_text())
state=pathlib.Path(os.environ['HA_RUN'])
if name=='uci':
    k=sys.argv[-1].split('.')[-1]
    if k not in settings: sys.exit(1)
    print(settings[k])
elif name=='ubus':
    print(json.dumps({'up':not (state/'wan-down').exists(),'l3_device':'pppoe-wan'}))
elif name=='jsonfilter':
    v=json.load(sys.stdin).get(sys.argv[-1].split('.')[-1],'')
    print(str(v).lower() if isinstance(v,bool) else v)
elif name=='ping':
    with (state/'calls').open('a') as f: f.write('ping '+' '.join(sys.argv[1:])+'\n')
    sys.exit(1 if (state/'probe-fail').exists() else 0)
elif name=='logger':
    pass
else:
    with (state/'calls').open('a') as f: f.write(name+' '+' '.join(sys.argv[1:])+'\n')
    if (state/('fail-'+name)).exists(): sys.exit(1)
"""

class HaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.state=self.base/'run';self.state.mkdir()
        self.bin=self.base/'bin';self.bin.mkdir();self.sys=self.base/'sys';self.sys.mkdir()
        for dev in ('br-lan','eth1'):
            (self.sys/dev).mkdir();(self.sys/dev/'carrier').write_text('1')
        for name in ('uci','ubus','jsonfilter','ping','ifup','ifdown','logger','dnsmasq','openvpn'):
            p=self.bin/name;p.write_text(MOCK);p.chmod(0o755)
        self.settings={'enabled':'1','role':'primary','mode':'cold-pppoe','lan_device':'br-lan','election_device':'br-lan',
            'election_source':'192.0.2.2','election_peer':'192.0.2.3','vip':'192.0.2.1/24','wan_interface':'wan','wan_l2_device':'eth1',
            'vrid':'51','preempt_delay':'30','acquire_grace':'90','retry_base':'300','retry_max':'3600',
            'probe_quorum':'1','probe':'198.51.100.1 203.0.113.1','service':'dnsmasq openvpn'}
        self.cfg=self.base/'settings.json'
        self.uptime=self.base/'uptime';self.uptime.write_text('10000.00 0.00')
        self.env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],'HA_LIB':str(LIB),'HA_RUN':str(self.state),
            'HA_INIT':str(self.bin),'HA_SYS':str(self.sys),'HA_SETTINGS':str(self.cfg),'HA_UPTIME':str(self.uptime)}
    def run_script(self,name,*args):
        self.cfg.write_text(json.dumps(self.settings))
        return subprocess.run(['sh',str(LIB/name),*args],env=self.env,text=True,capture_output=True)
    def put(self,name,value): (self.state/name).write_text(str(value))
    def calls(self): return (self.state/'calls').read_text() if (self.state/'calls').exists() else ''
    def test_no_topology_no_activation(self):
        self.settings['enabled']='0'
        self.assertNotEqual(self.run_script('render.sh').returncode,0)
        self.assertEqual(self.calls(),'')
    def test_primary_uses_delayed_preemption_and_fault_tracking(self):
        p=self.run_script('render.sh');self.assertEqual(p.returncode,0,p.stderr)
        for text in ('state BACKUP','priority 200','preempt_delay 30','weight 0','init_fail'):
            self.assertIn(text,p.stdout)
        self.assertNotIn('nopreempt',p.stdout)
        self.settings['role']='backup'
        self.assertIn('priority 100',self.run_script('render.sh').stdout)
    def test_injected_interface_rejected(self):
        self.settings['lan_device']='eth0; reboot'
        self.assertNotEqual(self.run_script('render.sh').returncode,0)
    def test_duplicate_source_and_peer_rejected(self):
        self.settings['election_peer']=self.settings['election_source']
        self.assertNotEqual(self.run_script('render.sh').returncode,0)
    def test_backup_never_dials(self):
        self.assertEqual(self.run_script('notify.sh','BACKUP').returncode,0)
        self.assertIn('ifdown wan',self.calls())
        self.assertNotIn('ifup',self.calls())
        self.assertIn('dnsmasq stop',self.calls())
    def test_master_dials_and_starts_services(self):
        p=self.run_script('notify.sh','MASTER');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('ifup wan',self.calls());self.assertIn('dnsmasq start',self.calls())
        self.assertEqual((self.state/'state').read_text().strip(),'MASTER')
    def test_failed_ifup_enters_backoff_and_releases(self):
        self.put('fail-ifup','1')
        self.assertNotEqual(self.run_script('notify.sh','MASTER').returncode,0)
        self.assertTrue((self.state/'retry_after').exists())
        self.assertIn('ifdown wan',self.calls())
        self.assertNotIn('dnsmasq start',self.calls())
    def test_warm_mode_does_not_stop_wan(self):
        self.settings['mode']='warm'
        self.assertEqual(self.run_script('notify.sh','BACKUP').returncode,0)
        self.assertNotIn('ifdown',self.calls())
    def test_wan_failure_after_grace_faults(self):
        self.put('state','MASTER');self.put('acquire_until',0);self.put('probe-fail',1)
        self.assertNotEqual(self.run_script('check.sh').returncode,0)
        self.assertEqual(self.run_script('notify.sh','FAULT').returncode,0)
        self.assertTrue((self.state/'retry_after').exists())
        self.assertIn('ifdown wan',self.calls())
    def test_acquisition_grace_does_not_reject_cold_redial(self):
        self.put('state','MASTER');self.put('acquire_until',999999999);self.put('probe-fail',1)
        self.assertEqual(self.run_script('check.sh').returncode,0)
    def test_quarantine_prevents_premature_preemption(self):
        self.put('retry_after',999999999)
        self.assertNotEqual(self.run_script('check.sh').returncode,0)
    def test_cold_standby_allows_recovery_trial(self):
        self.put('state','BACKUP');self.put('retry_after',0);self.put('wan-down',1)
        self.assertEqual(self.run_script('check.sh').returncode,0)
    def test_warm_standby_requires_own_wan(self):
        self.settings['mode']='warm';self.put('wan-down',1)
        self.assertNotEqual(self.run_script('check.sh').returncode,0)
    def test_physical_failure_rejects_eligibility(self):
        (self.sys/'eth1/carrier').write_text('0')
        self.assertNotEqual(self.run_script('check.sh').returncode,0)
    def test_probes_are_bound_to_own_wan(self):
        self.put('state','MASTER')
        self.assertEqual(self.run_script('check.sh').returncode,0)
        self.assertIn('-I pppoe-wan',self.calls())
    def test_service_failure_inhibits_and_releases(self):
        self.put('fail-openvpn',1)
        self.assertNotEqual(self.run_script('notify.sh','MASTER').returncode,0)
        self.assertTrue((self.state/'inhibit').exists())
        self.assertIn('dnsmasq stop',self.calls());self.assertIn('ifdown wan',self.calls())
    def test_overlap_fails_explicitly(self):
        (self.state/'transition.lock').mkdir()
        self.assertNotEqual(self.run_script('notify.sh','MASTER').returncode,0)
    def test_backoff_is_capped(self):
        self.put('state','MASTER');self.put('failures',30)
        self.assertEqual(self.run_script('notify.sh','FAULT').returncode,0)
        self.assertEqual(int((self.state/'retry_after').read_text()),13600)

    def test_wireguard_interfaces_follow_role(self):
        self.settings['managed_interface']='wg0'
        self.settings['proto']='wireguard'
        self.assertEqual(self.run_script('notify.sh','MASTER').returncode,0)
        self.assertIn('ifup wg0',self.calls())
        self.assertEqual(self.run_script('notify.sh','BACKUP').returncode,0)
        self.assertIn('ifdown wg0',self.calls())
    def test_non_wireguard_interface_rejected(self):
        self.settings['managed_interface']='lan'
        self.settings['proto']='static'
        self.assertNotEqual(self.run_script('render.sh').returncode,0)
