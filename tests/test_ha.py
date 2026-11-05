import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
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
    if '-c' in sys.argv:
        settings=json.loads((pathlib.Path(sys.argv[sys.argv.index('-c')+1])/'firmware-ha').read_text())
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
        self.base=Path(self.tmp.name);self.state=self.base/'run';self.state.mkdir();(self.state/'consumer_pid').write_text(str(os.getpid()))
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

    def test_disabled_then_stop_still_releases_services_and_wan(self):
        self.put('state','MASTER');self.settings['enabled']='0'
        p=self.run_script('notify.sh','STOP')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('dnsmasq stop',self.calls());self.assertIn('ifdown wan',self.calls())
        self.assertEqual((self.state/'state').read_text().strip(),'STOP')
    def test_active_snapshot_survives_disabled_and_changed_live_topology(self):
        snapshot=self.state/'config';snapshot.mkdir()
        (snapshot/'firmware-ha').write_text(json.dumps(self.settings))
        self.settings.update({'enabled':'0','wan_interface':'newwan','service':'not-installed'})
        p=self.run_script('notify.sh','STOP')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('ifdown wan',self.calls());self.assertNotIn('newwan',self.calls())
        self.assertIn('openvpn stop',self.calls())
    def test_cleanup_does_not_abandon_wan_after_tunnel_config_changes(self):
        self.settings.update({'managed_interface':'wg0','proto':'static'})
        p=self.run_script('notify.sh','STOP')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('ifdown wg0',self.calls());self.assertIn('ifdown wan',self.calls())
    def test_missing_service_during_cleanup_still_releases_wan(self):
        (self.bin/'dnsmasq').unlink()
        self.assertNotEqual(self.run_script('notify.sh','STOP').returncode,0)
        self.assertIn('ifdown wan',self.calls())
        self.assertTrue((self.state/'inhibit').exists())
    def test_failed_consumer_revokes_health_eligibility(self):
        self.put('consumer_pid','0')
        self.assertNotEqual(self.run_script('check.sh').returncode,0)
    def test_render_uses_ordered_native_fifo_instead_of_concurrent_callbacks(self):
        p=self.run_script('render.sh');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('vrrp_notify_fifo_script',p.stdout)
        self.assertIn('shutdown_script',p.stdout)
        self.assertNotIn('notify_master ',p.stdout)
    def test_fifo_preserves_backup_event_while_master_service_start_is_slow(self):
        self.cfg.write_text(json.dumps(self.settings))
        fifo=self.state/'events.fifo';os.mkfifo(fifo)
        slow=self.bin/'dnsmasq'
        slow.write_text('#!/bin/sh\nif [ "$1" = start ]; then touch "$HA_RUN/start-entered"; while [ ! -e "$HA_RUN/release-start" ]; do sleep 0.05; done; fi\nprintf "dnsmasq %s\\n" "$1" >> "$HA_RUN/calls"\n')
        process=subprocess.Popen(['sh',str(LIB/'events.sh'),str(fifo)],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            with fifo.open('w') as writer:
                writer.write('INSTANCE "ROUTER" MASTER 200\n');writer.flush()
                deadline=time.monotonic()+5
                while not (self.state/'start-entered').exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue((self.state/'start-entered').exists())
                writer.write('INSTANCE "ROUTER" BACKUP 200\n');writer.flush()
                self.put('release-start',1)
            _,error=process.communicate(timeout=8)
            self.assertEqual(process.returncode,0,error)
            lines=self.calls().splitlines()
            self.assertLess(lines.index('dnsmasq start'),lines.index('dnsmasq stop'))
            self.assertIn('ifdown wan',lines)
            self.assertEqual((self.state/'state').read_text().strip(),'STOP')
        finally:
            self.put('release-start',1)
            if process.poll() is None:process.kill();process.communicate()

    def run_init_function(self,function):
        self.cfg.write_text(json.dumps(self.settings))
        env={**self.env,'HA_CONFIG_FILE':str(self.cfg),'HA_KEEPALIVED':str(self.bin/'keepalived')}
        command='procd_open_instance() { :; }; procd_set_param() { :; }; procd_close_instance() { :; }; . "$1"; "$2"'
        return subprocess.run(['sh','-c',command,'ha-init-test',str(LIB/'firmware-ha.init'),function],env=env,text=True,capture_output=True)
    def test_init_stop_uses_old_snapshot_after_ha_is_disabled(self):
        snapshot=self.state/'config';snapshot.mkdir()
        (snapshot/'firmware-ha').write_text(json.dumps(self.settings))
        self.settings.update({'enabled':'0','wan_interface':'newwan','service':'not-installed'})
        result=self.run_init_function('stop_service')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('ifdown wan',self.calls());self.assertNotIn('newwan',self.calls())
    def test_init_start_saves_validated_config_for_later_cleanup(self):
        self.settings.update({'proto':'pppoe','auto':'0'})
        tool=self.bin/'keepalived';tool.write_text(MOCK);tool.chmod(0o755)
        result=self.run_init_function('start_service')
        self.assertEqual(result.returncode,0,result.stderr)
        snapshot=self.state/'config/firmware-ha'
        self.assertEqual(json.loads(snapshot.read_text()),self.settings)
        self.assertEqual(snapshot.stat().st_mode & 0o777,0o600)
        self.assertIn('keepalived stop',self.calls())
        self.assertIn('dnsmasq disable',self.calls())
    def test_invalid_cold_start_does_not_disable_existing_services(self):
        self.settings.update({'proto':'static','auto':'0'})
        result=self.run_init_function('start_service')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.calls(),'')

    def test_multiple_vlan_gateways_share_one_role(self):
        self.settings['extra_vip']='198.51.100.1/24@br-iot 203.0.113.1/24@br-cctv'
        p=self.run_script('render.sh');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('198.51.100.1/24 dev br-iot',p.stdout)
        self.assertIn('203.0.113.1/24 dev br-cctv',p.stdout)
        tracks=p.stdout.split('track_interface {',1)[1].split('}',1)[0]
        self.assertIn('br-iot',tracks);self.assertIn('br-cctv',tracks)
    def test_duplicate_extra_gateway_is_rejected(self):
        self.settings['extra_vip']='192.0.2.1/24@br-iot'
        self.assertNotEqual(self.run_script('render.sh').returncode,0)
        self.settings['extra_vip']='198.51.100.1/24@br-iot 198.51.100.1/24@br-cctv'
        self.assertNotEqual(self.run_script('render.sh').returncode,0)
    def test_extra_gateway_does_not_accept_embedded_configuration(self):
        self.settings['extra_vip']='198.51.100.1/24@br-iot;reboot'
        self.assertNotEqual(self.run_script('render.sh').returncode,0)
    def test_extra_vlan_failure_revokes_node_eligibility(self):
        self.settings['extra_vip']='198.51.100.1/24@br-iot'
        (self.sys/'br-iot').mkdir();(self.sys/'br-iot/carrier').write_text('0')
        self.assertNotEqual(self.run_script('check.sh').returncode,0)
        (self.sys/'br-iot/carrier').write_text('1')
        self.assertEqual(self.run_script('check.sh').returncode,0)
    def test_multiple_gateways_on_same_device_are_tracked_once(self):
        self.settings['extra_vip']='198.51.100.1/24@br-iot 203.0.113.1/24@br-iot'
        p=self.run_script('render.sh');self.assertEqual(p.returncode,0,p.stderr)
        tracks=p.stdout.split('track_interface {',1)[1].split('}',1)[0]
        self.assertEqual(tracks.count('br-iot'),1)
