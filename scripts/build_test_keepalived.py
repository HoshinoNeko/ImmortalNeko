#!/usr/bin/env python3
"""Build the feed's exact keepalived version for Linux namespace tests."""
import hashlib
from pathlib import Path
import subprocess
import tarfile

VERSION='2.3.3'
SHA256='2288c5c7609fa452782b7acefa19acce742d0204dc17f54d36da46b10f8b590c'

def main():
    root=Path(__file__).resolve().parents[1]
    work=root/'.work/ha-integration';work.mkdir(parents=True,exist_ok=True)
    archive=work/f'keepalived-{VERSION}.tar.gz'
    subprocess.run(['curl','-fL','--connect-timeout','10','--max-time','120',
                    f'https://www.keepalived.org/software/{archive.name}','-o',str(archive)],check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:
        raise SystemExit('keepalived source checksum mismatch')
    source=work/f'keepalived-{VERSION}'
    if source.exists():raise SystemExit('Use a fresh integration work directory')
    with tarfile.open(archive) as tar:tar.extractall(work,filter='data')
    prefix=root/f'.work/tools/keepalived-{VERSION}'
    subprocess.run(['./configure',f'--prefix={prefix}','--disable-lvs','--disable-bfd',
                    '--disable-nftables','--disable-iptables','--disable-libipset-dynamic'],cwd=source,check=True)
    subprocess.run(['make','-j2'],cwd=source,check=True)
    subprocess.run(['make','install'],cwd=source,check=True)
    print(prefix/'sbin/keepalived')

if __name__=='__main__':main()
