#!/usr/bin/env python3
"""Check generated fixture configs with an actual V2Ray 5.53.0 binary (no server run)."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
spec = importlib.util.spec_from_file_location('v2ray_fixtures',ROOT/'tests/test_v2ray_server.py')
fixtures = importlib.util.module_from_spec(spec)
exec(compile((ROOT/'tests/test_v2ray_server.py').read_text(),str(ROOT/'tests/test_v2ray_server.py'),'exec'),fixtures.__dict__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core',type=Path,required=True)
    parser.add_argument('--report',type=Path,default=ROOT/'.work/v2ray-native-validation.json')
    args = parser.parse_args()
    core = args.core.resolve()
    version = subprocess.run([str(core),'version'],capture_output=True,text=True,check=True,timeout=10)
    if not re.search(r'\b5\.53\.0\b',version.stdout):
        raise RuntimeError('Use the version from the pinned firmware feed: V2Ray 5.53.0')
    old_umask = os.umask(0o077)
    results = []
    try:
        with tempfile.TemporaryDirectory(prefix='neko-v2ray-native-') as temporary:
            base = Path(temporary); cert = base/'cert.pem'; material = base/'material.pem'
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                            '-subj','/CN=fixture.invalid','-keyout',str(material),'-out',str(cert)],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            cases = [(protocol,fixtures.configuration(protocol,listen='127.0.0.1'))
                     for protocol in ('shadowsocks','vmess','vless','trojan','socks','http')]
            for transport in ('ws','h2','grpc','kcp','quic'):
                cases.append(('vmess-'+transport,fixtures.configuration('vmess',listen='127.0.0.1',transport=transport,
                    tls='0' if transport=='kcp' else '1',tls_cert=str(cert),tls_key=str(material),
                    h2_host=['fixture.invalid'],grpc_service_name='fixture',ws_path='/fixture')))
            cases.append(('vmess-tcp-http',fixtures.configuration('vmess',listen='127.0.0.1',tcp_guise='http')))
            for name,sections in cases:
                config = fixtures.adapter.build_config(sections,check_files=True)
                output = base/(name+'.json'); fixtures.adapter.write_private(output,config)
                result = subprocess.run([str(core),'test','-format=json','-config',str(output)],
                                        capture_output=True,text=True,timeout=30)
                results.append({'case':name,'exit_code':result.returncode,'passed':result.returncode==0})
                if result.returncode:
                    raise RuntimeError('Core rejected generated fixture: '+name)
            invalid = fixtures.adapter.build_config(fixtures.configuration(listen='127.0.0.1'))
            invalid['inbounds'][0]['protocol'] = 'invalid-fixture-protocol'
            output = base/'invalid.json'; fixtures.adapter.write_private(output,invalid)
            result = subprocess.run([str(core),'test','-format=json','-config',str(output)],
                                    capture_output=True,text=True,timeout=30)
            if result.returncode==0:
                raise RuntimeError('Core unexpectedly accepted an invalid fixture')
            results.append({'case':'invalid-protocol-negative-control','exit_code':result.returncode,'passed':True})
    finally:
        os.umask(old_umask)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps({'result':'passed','version':version.stdout.strip(),
        'core_sha256':hashlib.sha256(core.read_bytes()).hexdigest(),'cases':results,
        'scope':'native configuration parser only; no listener, authentication or data-plane test'},indent=2)+'\n')
    print('Passed',len(results),'native core configuration checks')


if __name__=='__main__':
    main()
