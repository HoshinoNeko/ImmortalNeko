#!/usr/bin/env python3
"""Stage the official test binary matching the locked feed's Xray version."""
import hashlib
from pathlib import Path
import platform
import subprocess
import zipfile

VERSION = '26.3.27'
ASSETS = {
    ('Linux', 'x86_64'): ('Xray-linux-64.zip', '23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae'),
    ('Darwin', 'arm64'): ('Xray-macos-arm64-v8a.zip', '2e93a67e8aa1936ecefb307e120830fcbd4c643ab9b1c46a2d0838d5f8409eaf'),
}


def stage(root):
    name, digest = ASSETS[(platform.system(), platform.machine())]
    directory = Path(root)/'.work/tools'/('xray-' + VERSION)
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory/name
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        subprocess.run(['curl', '--connect-timeout', '10', '--max-time', '120', '-fL',
                        f'https://github.com/XTLS/Xray-core/releases/download/v{VERSION}/{name}',
                        '-o', str(archive)], check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise ValueError('Xray test archive checksum mismatch')
    with zipfile.ZipFile(archive) as source:
        binary = directory/'xray'
        binary.write_bytes(source.read('xray'))
        binary.chmod(0o755)
    return binary


if __name__ == '__main__':
    print(stage(Path(__file__).resolve().parents[1]))
