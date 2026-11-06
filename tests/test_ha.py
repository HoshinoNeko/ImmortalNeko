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
    k=sys.argv[-1]
    if k not in settings:k=k.split('.')[-1]
    if k not in settings: sys.exit(1)
    print(settings[k])
elif name=='ubus':
    monitor='wan_monitor' in sys.argv[2]
    print(json.dumps({'up':not (state/'wan-down').exists(),'pending':(state/'wan-pending').exists(),'l3_device':'eth1' if monitor else 'pppoe-wan'}))
elif name=='jsonfilter':
    v=json.load(sys.stdin).get(sys.argv[-1].split('.')[-1],'')
    print(str(v).lower() if isinstance(v,bool) else v)
elif name=='ping':
    with (state/'calls').open('a') as f: f.write('ping '+' '.join(sys.argv[1:])+'\n')
    sys.exit(1 if (state/'probe-fail').exists() or (state/('down-'+sys.argv[-1])).exists() else 0)
elif name=='ip':
    if 'address' in sys.argv:
        dev=sys.argv[-1]
        address={'lo':settings['election_source'],'eth1':settings.get('wan_monitor_source','192.168.1.2'),
                 'hb0':settings.get('heartbeat_source','198.18.1.2'),'br-lan':settings['vip'].split('/')[0]}.get(dev,'')
        if dev=='br-lan' and (state/'lost-vip').exists():address=''
        if address:print('2: '+dev+' inet '+address+'/32 scope global '+dev)
    elif 'show' in sys.argv:
        print((state/'route-output').read_text() if (state/'route-output').exists() else '',end='')
    else:
        with (state/'calls').open('a') as f:f.write('ip '+' '.join(sys.argv[1:])+'\n')
elif name=='timeout':
    os.execv(sys.argv[4],sys.argv[4:])
elif name=='ssh':
    peer=sys.argv[-2].split('@')[-1]
    reply=state/('reply-'+peer)
    if (state/'lose-vip-on-query').exists():(state/'lost-vip').touch()
    if reply.exists():print(reply.read_text(),end='')
    else:sys.exit(255)
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
        for name in ('uci','ubus','jsonfilter','ping','ifup','ifdown','logger','dnsmasq','openvpn','ip','timeout','ssh'):
            p=self.bin/name;p.write_text(MOCK);p.chmod(0o755)
        self.settings={'enabled':'1','role':'primary','mode':'cold-pppoe','lan_device':'br-lan','election_device':'br-lan',
            'election_source':'192.0.2.2','election_peer':'192.0.2.3','vip':'192.0.2.1/24','wan_interface':'wan','wan_l2_device':'eth1',
            'vrid':'51','preempt_delay':'30','acquire_grace':'90','retry_base':'300','retry_max':'3600',
            'probe_quorum':'1','probe':'198.51.100.1 203.0.113.1','service':'dnsmasq openvpn'}
        self.cfg=self.base/'settings.json'
        self.uptime=self.base/'uptime';self.uptime.write_text('10000.00 0.00')
        self.env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],'HA_LIB':str(LIB),'HA_RUN':str(self.state),
            'HA_INIT':str(self.bin),'HA_SYS':str(self.sys),'HA_SETTINGS':str(self.cfg),'HA_UPTIME':str(self.uptime),
            'HA_SSH':str(self.bin/'ssh'),'HA_KEYS':str(self.base/'keys')}
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
    def test_failed_acquisition_does_not_double_backoff_on_fault(self):
        self.put('fail-ifup','1')
        self.assertEqual(self.run_script('notify.sh','MASTER').returncode,3)
        self.assertEqual(self.run_script('notify.sh','FAULT').returncode,0)
        self.assertEqual((self.state/'failures').read_text().strip(),'1')
        self.assertEqual((self.state/'retry_after').read_text().strip(),'10300')
    def test_warm_mode_does_not_stop_wan(self):
        self.settings.update({'mode':'warm','pppoe_sessions':'multiple'})
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
        self.settings.update({'mode':'warm','pppoe_sessions':'multiple'});self.put('wan-down',1)
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
    def test_bound_election_interface_is_not_repeated_in_a_tracking_block(self):
        result=self.run_script('render.sh');self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('    interface br-lan\n',result.stdout)
        self.assertNotIn('track_interface {',result.stdout)

    def test_explicit_tracking_excludes_only_the_bound_interface(self):
        self.settings['extra_vip']='198.51.100.1/24@br-iot 203.0.113.1/24@br-iot'
        for election,expected in [('br-lan',['br-iot']),('br-iot',['br-lan']),('hb0',['br-lan','br-iot'])]:
            self.settings['election_device']=election
            result=self.run_script('render.sh');self.assertEqual(result.returncode,0,result.stderr)
            tracks=result.stdout.split('track_interface {',1)[1].split('}',1)[0].split()
            self.assertEqual(tracks,expected)
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

    def dual(self):
        self.settings.update({'peer_mode':'dual-path','election_device':'lo','election_source':'198.19.0.1',
            'election_peer':'198.19.0.2','wan_monitor_interface':'wan_monitor','wan_monitor_source':'192.168.1.2',
            'wan_monitor_peer':'192.168.1.3','heartbeat_device':'hb0','heartbeat_source':'198.18.1.2',
            'heartbeat_peer':'198.18.1.3','peer_status_port':'22','handoff_timeout':'5','handoff_delay':'1','unreachable_takeover':'1'})
        (self.sys/'hb0').mkdir();(self.sys/'hb0/carrier').write_text('1')
        keys=self.base/'keys';keys.mkdir()
        for key in ('peer_client','peer_known_hosts'):(keys/key).write_text('test-placeholder')
        self.put('monitor_pid',os.getpid());self.put('path_checked','10000')
        self.put('path_misses','0')

    def test_warm_rejects_single_session_account(self):
        self.settings.update({'mode':'warm','pppoe_sessions':'single'})
        self.assertNotEqual(self.run_script('render.sh').returncode,0)
        self.assertEqual(self.calls(),'')

    def test_multidial_helper_denies_single_or_missing_policy_without_topology(self):
        self.settings={'enabled':'0'}
        self.assertNotEqual(self.run_script('allow-multidial.sh').returncode,0)
        self.settings['pppoe_sessions']='single'
        self.assertNotEqual(self.run_script('allow-multidial.sh').returncode,0)
        self.settings['pppoe_sessions']='multiple'
        self.assertEqual(self.run_script('allow-multidial.sh').returncode,0)
        self.assertEqual(self.calls(),'')

    def test_multidial_helper_uses_active_single_session_snapshot(self):
        snapshot=self.state/'config';snapshot.mkdir()
        (snapshot/'firmware-ha').write_text(json.dumps({'pppoe_sessions':'single'}))
        self.settings['pppoe_sessions']='multiple'
        self.assertNotEqual(self.run_script('allow-multidial.sh').returncode,0)
        self.assertEqual(self.calls(),'')

    def test_preflight_rejects_enabled_syncdial_before_ownership_changes(self):
        self.settings.update({'syncdial.config':'syncdial','syncdial.config.enabled':'1'})
        result=self.run_script('preflight.sh')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('disable SyncDial',result.stderr)
        self.assertEqual(self.calls(),'')
        self.settings['syncdial.config.enabled']='0'
        self.assertEqual(self.run_script('preflight.sh').returncode,0)

    def test_dual_paths_share_one_unbound_vrrp_instance(self):
        self.dual();self.settings['extra_vip']='198.51.100.1/24@br-iot 203.0.113.1/24@br-iot'
        result=self.run_script('render.sh')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.count('vrrp_instance '),1)
        self.assertNotIn('    interface ',result.stdout)
        self.assertIn('down_timer_adverts 10',result.stdout)
        self.assertIn('check_unicast_src',result.stdout)
        tracks=result.stdout.split('track_interface {',1)[1].split('}',1)[0].split()
        self.assertEqual(tracks,['br-lan','br-iot'])

    def test_both_paths_probed_and_one_failure_switches_transport(self):
        self.dual()
        p=self.run_script('paths.sh','once');self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual((self.state/'path_selected').read_text().strip(),'heartbeat')
        self.put('down-198.18.1.3',1)
        p=self.run_script('paths.sh','once');self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual((self.state/'path_selected').read_text().strip(),'wan')
        self.assertEqual((self.state/'path_misses').read_text().strip(),'0')
        self.assertIn('via 192.168.1.3 dev eth1',self.calls())
        self.assertIn('-I hb0',self.calls());self.assertIn('-I eth1',self.calls())
        self.assertNotIn('ifdown',self.calls())
        self.assertEqual(self.run_script('check.sh').returncode,0)

    def test_wan_monitor_failure_leaves_heartbeat_transport(self):
        self.dual();self.put('down-192.168.1.3',1)
        self.assertEqual(self.run_script('paths.sh','once').returncode,0)
        self.assertEqual((self.state/'path_selected').read_text().strip(),'heartbeat')

    def test_both_paths_lost_blackholes_control_and_counts_samples(self):
        self.dual();self.put('probe-fail',1)
        for _ in range(3):self.assertEqual(self.run_script('paths.sh','once').returncode,0)
        self.assertEqual((self.state/'path_misses').read_text().strip(),'3')
        self.assertIn('replace blackhole 198.19.0.2/32 proto 186',self.calls())

    def test_dead_monitor_revokes_eligibility(self):
        self.dual();self.put('monitor_pid','0')
        self.assertNotEqual(self.run_script('check.sh').returncode,0)
        self.put('monitor_pid',os.getpid());self.put('path_checked','9990')
        self.assertNotEqual(self.run_script('check.sh').returncode,0)

    def test_released_peer_allows_single_session_handoff(self):
        self.dual();self.put('reply-192.168.1.3','HA1 RELEASED\n')
        result=self.run_script('notify.sh','MASTER')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('ifup wan',self.calls())
        self.assertNotIn('ifdown wan_monitor',self.calls())

    def test_busy_peer_blocks_dial_even_with_release_on_other_path(self):
        self.dual();self.put('reply-192.168.1.3','HA1 RELEASED\n');self.put('reply-198.18.1.3','HA1 BUSY\n')
        result=self.run_script('notify.sh','MASTER')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('ifup wan',self.calls())
        self.assertTrue((self.state/'retry_after').exists())

    def test_unknown_peer_blocks_dial(self):
        self.dual();self.put('reply-192.168.1.3','HA1 UNKNOWN\n')
        self.assertNotEqual(self.run_script('handoff.sh').returncode,0)
        self.assertNotIn('ifup',self.calls())

    def test_both_unreachable_needs_three_samples_and_explicit_policy(self):
        self.dual();self.put('path_misses','3')
        self.assertEqual(self.run_script('handoff.sh').returncode,0)
        self.settings['unreachable_takeover']='0'
        self.assertNotEqual(self.run_script('handoff.sh').returncode,0)

    def test_stale_master_event_cannot_dial_after_vip_removed(self):
        self.dual();self.put('reply-192.168.1.3','HA1 RELEASED\n');self.put('lose-vip-on-query',1)
        result=self.run_script('notify.sh','MASTER')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('ifup wan',self.calls())
        self.assertNotIn('dnsmasq start',self.calls())

    def test_missing_identity_refuses_dial(self):
        self.dual();(self.base/'keys/peer_client').unlink()
        self.assertNotEqual(self.run_script('notify.sh','MASTER').returncode,0)
        self.assertNotIn('ifup wan',self.calls())

    def test_peer_status_only_accepts_forced_protocol_and_checks_pending(self):
        self.dual();snapshot=self.state/'config';snapshot.mkdir()
        (snapshot/'firmware-ha').write_text(json.dumps(self.settings))
        self.put('state','BACKUP');self.put('wan-down',1);self.put('lost-vip',1)
        self.assertNotEqual(self.run_script('peer-status.sh').returncode,0)
        self.env['SSH_ORIGINAL_COMMAND']='firmware-ha-status-v1'
        self.assertEqual(self.run_script('peer-status.sh').stdout.strip(),'HA1 RELEASED')
        self.put('wan-pending',1)
        self.assertEqual(self.run_script('peer-status.sh').stdout.strip(),'HA1 BUSY')
        (self.state/'wan-pending').unlink();self.put('state','MASTER')
        self.assertEqual(self.run_script('peer-status.sh').stdout.strip(),'HA1 BUSY')

    def test_preflight_validates_monitor_without_service_mutations(self):
        self.dual()
        self.settings.update({'network.wan_monitor.proto':'dhcp','network.wan_monitor.device':'eth1',
            'network.wan_monitor.auto':'1','network.wan_monitor.defaultroute':'0','network.wan_monitor.peerdns':'0'})
        conf=self.base/'sysctl'
        for dev in ('all','eth1','hb0'):
            (conf/dev).mkdir(parents=True);(conf/dev/'rp_filter').write_text('2')
        self.env['HA_SYSCTL']=str(conf)
        p=self.run_script('preflight.sh');self.assertEqual(p.returncode,0,p.stderr)
        self.put('route-output','blackhole 198.19.0.2 proto 186\n')
        self.assertEqual(self.run_script('preflight.sh').returncode,0)
        self.put('route-output','198.19.0.2 via 192.168.1.254 proto static\n')
        self.assertNotEqual(self.run_script('preflight.sh').returncode,0)
        (self.state/'route-output').unlink()
        (conf/'hb0/rp_filter').write_text('1');(conf/'all/rp_filter').write_text('0')
        self.assertNotEqual(self.run_script('preflight.sh').returncode,0)
        (conf/'hb0/rp_filter').write_text('2')
        self.settings['network.wan_monitor.defaultroute']='1'
        self.assertNotEqual(self.run_script('preflight.sh').returncode,0)
        self.assertEqual(self.calls(),'')

    def test_retryable_redial_failure_does_not_permanently_inhibit_fifo(self):
        self.put('fail-ifup',1)
        self.cfg.write_text(json.dumps(self.settings))
        fifo=self.state/'events.fifo';os.mkfifo(fifo)
        process=subprocess.Popen(['sh',str(LIB/'events.sh'),str(fifo)],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            with fifo.open('w') as writer:
                writer.write('INSTANCE "ROUTER" MASTER 200\nINSTANCE "ROUTER" BACKUP 200\n')
            _,error=process.communicate(timeout=12)
            self.assertEqual(process.returncode,0,error)
            self.assertTrue((self.state/'retry_after').exists())
            self.assertFalse((self.state/'inhibit').exists())
            self.assertIn('ifdown wan',self.calls())
        finally:
            if process.poll() is None:process.kill();process.communicate()

    def test_service_guard_preserves_standalone_behavior_when_ha_is_disabled(self):
        self.settings['enabled']='0'
        self.assertEqual(self.run_script('service-guard.sh','dnsmasq').returncode,0)

    def test_service_guard_refuses_standby_or_master_without_vip(self):
        self.put('state','BACKUP')
        self.assertNotEqual(self.run_script('service-guard.sh','dnsmasq').returncode,0)
        self.put('state','MASTER');self.put('phase','active')
        self.assertEqual(self.run_script('service-guard.sh','dnsmasq').returncode,0)
        self.put('lost-vip',1)
        self.assertNotEqual(self.run_script('service-guard.sh','dnsmasq').returncode,0)

    def test_service_guard_requires_live_consumer_and_no_inhibit(self):
        self.put('state','MASTER');self.put('phase','active');self.put('consumer_pid',0)
        self.assertNotEqual(self.run_script('service-guard.sh','dnsmasq').returncode,0)
        self.put('consumer_pid',os.getpid());self.put('inhibit',1)
        self.assertNotEqual(self.run_script('service-guard.sh','dnsmasq').returncode,0)

    def test_service_guard_uses_active_snapshot_after_live_config_edits(self):
        snapshot=self.state/'config';snapshot.mkdir()
        (snapshot/'firmware-ha').write_text(json.dumps(self.settings))
        self.settings.update({'enabled':'0','service':'openvpn'})
        self.put('state','BACKUP')
        self.assertNotEqual(self.run_script('service-guard.sh','dnsmasq').returncode,0)
        # Explicitly unmanaged services keep their upstream behavior.
        self.assertEqual(self.run_script('service-guard.sh','socat').returncode,0)

    def test_proxy_cleanup_cannot_leave_dns_running_on_backup(self):
        self.settings['service']='dnsmasq homeproxy openvpn odhcpd'
        for name in ('homeproxy','odhcpd'):
            p=self.bin/name;p.write_text(MOCK);p.chmod(0o755)
        proxy=self.bin/'homeproxy'
        proxy.write_text('#!/bin/sh\nprintf "homeproxy %s\\n" "$1" >> "$HA_RUN/calls"\nif [ "$1" = stop ]; then "$HA_INIT/dnsmasq" start; fi\n')
        result=self.run_script('notify.sh','BACKUP')
        self.assertEqual(result.returncode,0,result.stderr)
        lines=self.calls().splitlines()
        self.assertLess(lines.index('homeproxy stop'),lines.index('dnsmasq stop'))
        self.assertLess(lines.index('dnsmasq start'),lines.index('dnsmasq stop'))
        self.assertEqual(lines[-2:],['dnsmasq stop','odhcpd stop'])

    def test_service_guard_blocks_acquiring_and_releasing_master(self):
        self.put('state','MASTER')
        for phase in ('acquiring','releasing'):
            self.put('phase',phase)
            self.assertNotEqual(self.run_script('service-guard.sh','dnsmasq').returncode,0)

    def test_failed_acquisition_cleanup_cannot_restart_dns(self):
        self.settings['service']='dnsmasq homeproxy'
        proxy=self.bin/'homeproxy'
        proxy.write_text('#!/bin/sh\nif [ "$1" = stop ]; then "$HA_INIT/dnsmasq" start; fi\n');proxy.chmod(0o755)
        dns=self.bin/'dnsmasq'
        dns.write_text('#!/bin/sh\nif [ "$1" = start ] && ! "$HA_LIB/service-guard.sh" dnsmasq; then echo "dnsmasq denied" >> "$HA_RUN/calls"; exit 0; fi\nprintf "dnsmasq %s\\n" "$1" >> "$HA_RUN/calls"\n')
        self.put('fail-ifup',1)
        result=self.run_script('notify.sh','MASTER')
        self.assertEqual(result.returncode,3,result.stderr)
        self.assertIn('dnsmasq denied',self.calls())
        self.assertNotIn('dnsmasq start',self.calls())
        self.assertEqual((self.state/'phase').read_text().strip(),'releasing')
