#!/usr/bin/env python3
"""Real keepalived election/failover in isolated Linux namespaces.
Requires root, iproute2, keepalived and ping. Does NOT access the real LAN/WAN.
Netifd/UCI and application service operations are mocked; no PPPoE emulator.
"""
import json
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

ROOT=Path(__file__).resolve().parents[2]
MOCK=r"""#!/usr/bin/env python3
import json,os,pathlib,sys
n=pathlib.Path(sys.argv[0]).name
s=json.loads(pathlib.Path(os.environ['HA_SETTINGS']).read_text())
if n=='uci':
 k=sys.argv[-1].split('.')[-1]
 if k not in s: sys.exit(1)
 print(s[k])
elif n=='ubus': print('{"up":true,"l3_device":"wan0"}')
elif n=='jsonfilter':
 v=json.load(sys.stdin)[sys.argv[-1].split('.')[-1]]
 print(str(v).lower() if isinstance(v,bool) else v)
else:
 with open(os.environ['HA_RUN']+'/events','a') as f:f.write(n+' '+' '.join(sys.argv[1:])+'\n')
"""

def run(args,**kwargs):
    return subprocess.run(args,check=True,text=True,**kwargs)

def net(ns,*args,**kwargs):
    return run(['ip','netns','exec',ns,*map(str,args)],**kwargs)

def daemon_command(state):
    # -P/--vrrp only exists when both VRRP and LVS are compiled in. The CI
    # binary disables LVS, so let its enabled VRRP subsystem start normally.
    return ['keepalived','-n','-l','-p',str(state/'parent.pid'),
            '-r',str(state/'vrrp.pid'),'-f',str(state/'keepalived.conf')]

def check_daemon_cli(state,env=None):
    # Parse the exact runtime options before creating namespaces. --help exits
    # before reading config or opening pidfiles; place it after all other flags.
    try:
        run([*daemon_command(state),'--help'],env=env,capture_output=True)
    except subprocess.CalledProcessError as exc:
        details=(exc.stderr or exc.stdout or '').strip()
        raise RuntimeError(f'keepalived rejected integration arguments (exit {exc.returncode}): {details}') from exc

def wait_for(predicate,reason,processes,timeout=35):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError('keepalived exited early: '+str(process.returncode))
        if predicate(): return
        time.sleep(.25)
    raise RuntimeError('Timed out: '+reason)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dual-path',action='store_true')
    dual=parser.parse_args().dual_path
    if sys.platform!='linux' or os.geteuid()!=0:
        raise SystemExit('Run on Linux as root; this test was NOT executed')
    for tool in ('ip','keepalived','ping'):
        if not shutil.which(tool): raise SystemExit('Missing tool: '+tool)
    prefix='fh'+str(os.getpid())
    bridges=[prefix+'l',prefix+'w',prefix+'i']+([prefix+'h'] if dual else [])
    namespaces=[prefix+'p',prefix+'b',prefix+'u']
    created_ns=[];created_br=[];processes=[];monitors=[];logs=[]
    with tempfile.TemporaryDirectory(prefix='firmware-ha-integration-',dir='/run') as tmp:
        base=Path(tmp);base.chmod(0o755)
        check_daemon_cli(base)
        print('PASS: compiled keepalived accepts integration arguments',flush=True)
        lib=base/'lib';shutil.copytree(ROOT/'local-packages/firmware-ha/files',lib)
        bins=base/'bin';bins.mkdir()
        for name in ('uci','ubus','jsonfilter','dnsmasq','logger'):
            f=bins/name;f.write_text(MOCK);f.chmod(0o755)
        try:
            for bridge in bridges:
                run(['ip','link','add',bridge,'type','bridge']);created_br.append(bridge)
                run(['ip','link','set',bridge,'up'])
            for index,ns in enumerate(namespaces):
                run(['ip','netns','add',ns]);created_ns.append(ns)
                run(['ip','-n',ns,'link','set','lo','up'])
                for side,bridge in enumerate(bridges):
                    if index==2 and side!=1: continue
                    host=prefix+str(index)+str(side)
                    peer=host+'n'
                    run(['ip','link','add',host,'type','veth','peer','name',peer])
                    run(['ip','link','set',host,'master',bridge])
                    run(['ip','link','set',host,'up'])
                    run(['ip','link','set',peer,'netns',ns])
                    dev=('lan0','wan0','iot0','hb0')[side]
                    run(['ip','-n',ns,'link','set',peer,'name',dev])
                    addr=f'{("192.0.2","198.18.0","198.51.100","198.18.1")[side]}.{index+2}/24'
                    run(['ip','-n',ns,'addr','add',addr,'dev',dev])
                    run(['ip','-n',ns,'link','set',dev,'up'])
                if dual and index<2:
                    run(['ip','-n',ns,'addr','add',f'192.168.1.{index+2}/24','dev','wan0'])
                    run(['ip','-n',ns,'addr','add',f'198.19.0.{index+1}/32','dev','lo'])
                    for dev in ('wan0','hb0'):
                        net(ns,'sysctl','-qw',f'net.ipv4.conf.{dev}.rp_filter=2')
            for address in ('198.18.0.1/24','198.18.0.254/24'):
                run(['ip','-n',namespaces[2],'addr','add',address,'dev','wan0'])
            for i,role in enumerate(('primary','backup')):
                state=base/role;state.mkdir(mode=0o700)
                settings={'enabled':'1','role':role,'mode':'warm','pppoe_sessions':'multiple','lan_device':'lan0','election_device':'lan0',
                    'election_source':f'192.0.2.{i+2}','election_peer':f'192.0.2.{3-i}','vip':'192.0.2.1/24',
                    'extra_vip':'198.51.100.1/24@iot0','wan_interface':'wan','wan_l2_device':'wan0','vrid':'173','preempt_delay':'1','acquire_grace':'10',
                    'retry_base':'10','retry_max':'20','probe_quorum':'1','probe':'198.18.0.1 198.18.0.254','service':'dnsmasq'}
                if dual:
                    settings.update({'peer_mode':'dual-path','election_device':'lo','election_source':f'198.19.0.{i+1}',
                        'election_peer':f'198.19.0.{2-i}','wan_monitor_interface':'wan_monitor',
                        'wan_monitor_source':f'192.168.1.{i+2}','wan_monitor_peer':f'192.168.1.{3-i}',
                        'heartbeat_device':'hb0','heartbeat_source':f'198.18.1.{i+2}','heartbeat_peer':f'198.18.1.{3-i}',
                        'peer_status_port':'22','handoff_timeout':'5','handoff_delay':'1','unreachable_takeover':'1'})
                setting_file=state/'settings.json';setting_file.write_text(json.dumps(settings))
                env={**os.environ,'HA_SETTINGS':str(setting_file),'HA_LIB':str(lib),'HA_RUN':str(state),
                     'HA_INIT':str(bins),'PATH':str(bins)+os.pathsep+os.environ['PATH']}
                cfg=state/'keepalived.conf'
                cfg.write_text(net(namespaces[i],'sh',lib/'render.sh',env=env,capture_output=True).stdout)
                net(namespaces[i],'keepalived','--config-test','-f',cfg,env=env)
                if dual:
                    net(namespaces[i],'sh',lib/'paths.sh','once',env=env)
                    monitors.append(subprocess.Popen(['ip','netns','exec',namespaces[i],'sh',str(lib/'paths.sh')],env=env))
                log=(state/'keepalived.log').open('w');logs.append(log)
                command=['ip','netns','exec',namespaces[i],*daemon_command(state)]
                processes.append(subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT))
            def has_vip(index,device,address):
                result=run(['ip','-n',namespaces[index],'-j','-4','addr','show','dev',device],capture_output=True)
                return any(a.get('local')==address for item in json.loads(result.stdout) for a in item.get('addr_info',[]))
            gateways=[('lan0','192.0.2.1'),('iot0','198.51.100.1')]
            def only(index):
                return all(has_vip(index,device,address) and not has_vip(1-index,device,address) for device,address in gateways)
            wait_for(lambda:only(0),'initial x86 primary election on both LANs',processes)
            print('PASS: primary elected, exactly one owner for both VLAN gateways',flush=True)
            if dual:
                # Neither individual monitor-link outage should cause an election.
                run(['ip','-n',namespaces[0],'link','set','hb0','down'])
                deadline=time.monotonic()+12
                while time.monotonic()<deadline:
                    if not only(0):raise RuntimeError('heartbeat-only failure changed VIP ownership')
                    time.sleep(.25)
                for role in ('primary','backup'):
                    if (base/role/'path_selected').read_text().strip()!='wan':
                        raise RuntimeError('VRRP transport did not switch to WAN DHCP')
                print('PASS: heartbeat failure retains one primary over WAN DHCP',flush=True)
                run(['ip','-n',namespaces[0],'link','set','hb0','up'])
                # Monitor ICMP only is suppressed on WAN, preserving Internet probes.
                for i in range(2):
                    net(namespaces[i],'ip','route','add','unreachable',f'192.168.1.{3-i}/32')
                deadline=time.monotonic()+12
                while time.monotonic()<deadline:
                    if not only(0):raise RuntimeError('WAN-monitor-only failure changed VIP ownership')
                    time.sleep(.25)
                for role in ('primary','backup'):
                    if (base/role/'path_selected').read_text().strip()!='heartbeat':
                        raise RuntimeError('VRRP transport did not switch to heartbeat')
                print('PASS: WAN monitoring failure retains one primary over heartbeat',flush=True)
                for i in range(2):
                    net(namespaces[i],'ip','route','del','unreachable',f'192.168.1.{3-i}/32')
            run(['ip','-n',namespaces[0],'link','set','wan0','down'])
            wait_for(lambda:only(1),'backup takeover after primary WAN loss',processes)
            print('PASS: backup takes over after primary WAN loss',flush=True)
            run(['ip','-n',namespaces[0],'link','set','wan0','up'])
            wait_for(lambda:only(0),'automatic primary recovery and preemption',processes,timeout=50)
            print('PASS: healthy x86 automatically reclaims primary role',flush=True)
            processes[0].terminate();processes[0].wait(timeout=10)
            if dual:
                # Peer power-loss simulation: primary loses BOTH control paths.
                run(['ip','-n',namespaces[0],'link','set','hb0','down'])
                run(['ip','-n',namespaces[0],'link','set','wan0','down'])
            wait_for(lambda:only(1),'backup takeover after primary daemon stops',[processes[1]])
            print('PASS: backup takes over after primary daemon stops',flush=True)
            for role in ('primary','backup'):
                events=(base/role/'events').read_text()
                if 'dnsmasq start' not in events or 'dnsmasq stop' not in events:
                    raise RuntimeError('Missing service role transitions for '+role)
            print('PASS: both nodes executed application start/stop callbacks',flush=True)
        finally:
            for monitor in monitors:
                if monitor.poll() is None:
                    monitor.terminate()
                    try:monitor.wait(timeout=5)
                    except subprocess.TimeoutExpired:monitor.kill();monitor.wait()
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
            for log in logs:log.close()
            for file in base.glob('*/keepalived.log'):
                print('--- '+str(file)+' ---\n'+file.read_text()[-12000:])
            for ns in reversed(created_ns):subprocess.run(['ip','netns','del',ns],check=False)
            for bridge in reversed(created_br):subprocess.run(['ip','link','del',bridge],check=False)
if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        message = str(exc)[-2000:].replace('%','%25').replace('\r','%0D').replace('\n','%0A')
        print('::error file=tests/integration/keepalived_netns.py,title=Native HA integration::'+message,flush=True)
        raise
