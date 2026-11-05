#!/usr/bin/env python3
"""Fetch the exact actionlint binary, verify SHA256, then lint all workflows."""
import hashlib
from pathlib import Path
import platform
import subprocess
import tarfile
VERSION='1.7.12'
CHECKSUMS={
    ('Darwin','arm64'):'aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f',
    ('Linux','x86_64'):'8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8',
}
def main():
    root=Path(__file__).resolve().parents[1]
    system,machine=platform.system(),platform.machine()
    checksum=CHECKSUMS[(system,machine)]
    os_name={'Darwin':'darwin','Linux':'linux'}[system]
    arch={'arm64':'arm64','x86_64':'amd64'}[machine]
    directory=root/'.work/tools';directory.mkdir(parents=True,exist_ok=True)
    name=f'actionlint_{VERSION}_{os_name}_{arch}.tar.gz'
    archive=directory/name
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=checksum:
        subprocess.run(['curl','--http1.1','--connect-timeout','10','--max-time','120','-fL',
                        f'https://github.com/rhysd/actionlint/releases/download/v{VERSION}/{name}',
                        '-o',str(archive)],check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=checksum:
        raise SystemExit('actionlint checksum mismatch')
    with tarfile.open(archive) as tar:
        member=tar.getmember('actionlint')
        if not member.isfile(): raise SystemExit('invalid actionlint archive')
        executable=directory/'actionlint'
        executable.write_bytes(tar.extractfile(member).read());executable.chmod(0o755)
    subprocess.run([str(executable),'-shellcheck=','-color'],cwd=root,check=True)
if __name__=='__main__':main()
