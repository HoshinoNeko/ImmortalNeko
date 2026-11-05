#!/usr/bin/env python3
"""Read-only device inventory. Raw configuration is kept in private/ only."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fwlib import ROOT, BuildError, sha

# Commands are constants, never assembled from configuration or device output.
ARTIFACTS = [
    ('board.json', 'ubus call system board'),
    ('release.txt', 'cat /etc/openwrt_release'),
    ('package-manager.txt', 'if command -v opkg >/dev/null 2>&1; then echo opkg; elif command -v apk >/dev/null 2>&1; then echo apk; else exit 1; fi'),
    ('packages-installed.txt', 'if command -v opkg >/dev/null 2>&1; then opkg list-installed; elif command -v apk >/dev/null 2>&1; then apk info -v; else exit 1; fi'),
    ('memory.txt', 'cat /proc/meminfo'),
    ('flash.txt', 'if test -r /proc/mtd; then cat /proc/mtd; else echo not-present; fi'),
    ('links.txt', 'ip -d link show'),
    ('addresses.txt', 'ip address show'),
    ('routes.txt', 'ip route show table all'),
    ('network-runtime.json', 'ubus call network.interface dump'),
    ('etc-config-private.tar.gz', 'tar -C / -czf - etc/config'),
]


def ssh_arguments(host, port, identity=None):
    if not re.fullmatch(r'[-A-Za-z0-9_@.:\[\]]+', host) or host.startswith('-'):
        raise BuildError('Invalid SSH host')
    if not 1 <= port <= 65535:
        raise BuildError('SSH port must be between 1 and 65535')
    args = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=10', '-p', str(port)]
    if identity is not None:
        identity = Path(identity).expanduser().resolve()
        if not identity.is_file():
            raise BuildError('SSH identity file does not exist')
        args += ['-i', str(identity)]
    return args + ['--', host]


def private_destination(workspace, output):
    original_workspace = Path(workspace).absolute()
    workspace = original_workspace.resolve()
    private = workspace/'private'
    if private.is_symlink():
        raise BuildError('private/ must not be a symlink')
    dest = Path(output)
    if not dest.is_absolute():
        dest = workspace/dest
    elif dest.is_relative_to(original_workspace):
        # macOS /var and /tmp are OS aliases; only reject symlinks below the workspace.
        dest = workspace/dest.relative_to(original_workspace)
    if not dest.resolve().is_relative_to(private.resolve()) or dest.resolve() == private.resolve():
        raise BuildError('Use a new destination underneath ignored private/')
    for path in [dest, *dest.parents]:
        if path == workspace:
            break
        if path.is_symlink():
            raise BuildError('Symlinks are forbidden in snapshot paths')
    if dest.exists():
        raise BuildError('Snapshot destination already exists; choose a new directory')
    private.mkdir(mode=0o700, exist_ok=True)
    private.chmod(0o700)
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    dest.mkdir(mode=0o700)
    return dest


def save_metadata(dest, meta):
    path = dest/'snapshot.json'
    with path.open('w') as stream:
        os.chmod(path, 0o600)
        json.dump(meta, stream, indent=2)
        stream.write('\n')


def validate_archive(path):
    try:
        with tarfile.open(path, 'r:gz') as archive:
            members = archive.getmembers()
            if not members:
                raise BuildError('Configuration archive is empty')
            for member in members:
                name = Path(member.name)
                if name.is_absolute() or '..' in name.parts or name.parts[:2] != ('etc', 'config'):
                    raise BuildError('Unexpected path in configuration archive')
                # This command never extracts the archive. Keep future extraction safe too.
                if not member.isfile() and not member.isdir():
                    raise BuildError('Configuration archive contains links or special files; review privately')
    except (tarfile.TarError, EOFError) as exc:
        raise BuildError('Invalid configuration archive') from exc


def collect(host, port, output, identity=None, workspace=ROOT, runner=subprocess.run):
    command = ssh_arguments(host, port, identity)
    dest = private_destination(workspace, output)
    meta = {'status': 'collecting', 'host': host, 'port': port,
            'collected_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'artifacts': [], 'scope': 'read-only snapshot; no firmware or network changes'}
    save_metadata(dest, meta)
    errors = dest/'ssh-errors.log'
    try:
        with errors.open('wb') as stderr:
            errors.chmod(0o600)
            for name, remote in ARTIFACTS:
                path = dest/name
                with path.open('wb') as stdout:
                    path.chmod(0o600)
                    result = runner(command+[remote], stdout=stdout, stderr=stderr, timeout=90, check=False)
                if result.returncode != 0 or path.stat().st_size == 0:
                    raise BuildError('SSH collection failed for '+name+'; inspect private ssh-errors.log')
                if name == 'board.json' or name == 'network-runtime.json':
                    try:
                        json.loads(path.read_text())
                    except (ValueError, UnicodeError) as exc:
                        raise BuildError('Invalid device JSON in '+name) from exc
                if name == 'package-manager.txt' and path.read_text().strip() not in {'opkg', 'apk'}:
                    raise BuildError('Unsupported package manager response')
                if name.endswith('.tar.gz'):
                    validate_archive(path)
                meta['artifacts'].append({'name': name, 'sha256': sha(path), 'bytes': path.stat().st_size})
                save_metadata(dest, meta)
        meta['status'] = 'complete'
        save_metadata(dest, meta)
        files = sorted(p for p in dest.iterdir() if p.is_file())
        sums = dest/'SHA256SUMS'
        sums.write_text(''.join(sha(p)+'  '+p.name+'\n' for p in files))
        sums.chmod(0o600)
        print('Saved read-only device snapshot: '+str(dest))
        print('Raw settings stay private. No configuration values were printed.')
        return dest
    except (BuildError, OSError, subprocess.SubprocessError) as exc:
        meta['status'] = 'failed'
        meta['error'] = str(exc)
        save_metadata(dest, meta)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='user@host; no password in this argument')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--identity', type=Path, help='Existing local SSH identity; never copied into snapshot')
    parser.add_argument('--output', required=True, type=Path, help='New directory under private/')
    args = parser.parse_args()
    collect(args.host, args.port, args.output, args.identity)


if __name__ == '__main__':
    try:
        main()
    except (BuildError, OSError, subprocess.SubprocessError) as exc:
        print('ERROR: '+str(exc), file=sys.stderr)
        sys.exit(1)
