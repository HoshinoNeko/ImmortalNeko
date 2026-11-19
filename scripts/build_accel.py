#!/usr/bin/env python3
"""Content-addressed compiler caches, resource limits and build measurements."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fwlib import ROOT, BuildError, locked_repos, profile, requested_config, run, sha

GIB = 1024 ** 3


def available_memory():
    available = 4 * GIB
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                available = int(line.split()[1]) * 1024
        limit = Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if limit != 'max':
            used = int(Path('/sys/fs/cgroup/memory.current').read_text())
            available = min(available, max(0, int(limit) - used))
    except (OSError, ValueError):
        pass
    return available


def select_jobs(requested='auto', cpus=None, memory=None):
    if cpus is None:
        cpus = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1
    if requested != 'auto':
        try:
            count = int(requested)
        except ValueError:
            raise BuildError('Compile jobs must be auto or an integer from 1 to 16') from None
        if not 1 <= count <= 16:
            raise BuildError('Compile jobs must be auto or an integer from 1 to 16')
        return count
    memory = available_memory() if memory is None else memory
    # Leave 2 GiB for the runner and reserve about 2 GiB per concurrent job.
    return max(1, min(cpus, 8, max(1, (memory - 2 * GIB) // (2 * GIB))))


def cache_plan(p, host_os, host_arch):
    for value in (host_os, host_arch, p['target'], p['subtarget']):
        if not value or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in value):
            raise BuildError('Invalid cache platform component')
    source, feeds = locked_repos()
    revision = hashlib.sha256(json.dumps([source, feeds], sort_keys=True).encode()).hexdigest()[:24]
    scope = host_os + '-' + host_arch
    target = p['target'] + '-' + p['subtarget']
    # Go does not notice changes to external C libraries automatically. Keep
    # cgo results within the same configuration and native dependency inputs.
    native_inputs = {}
    for directory in ('local-packages', 'themes', 'patches'):
        for entry in (ROOT/directory).rglob('*'):
            if entry.is_file() and (entry.name in ('Makefile', 'CMakeLists.txt', 'Config.in') or
                                    entry.suffix in ('.mk', '.cmake', '.c', '.h', '.hpp', '.cc', '.cpp', '.cxx', '.S', '.s', '.rs', '.patch')):
                native_inputs[str(entry.relative_to(ROOT))] = sha(entry)
    go_revision = hashlib.sha256(json.dumps([requested_config(p), native_inputs], sort_keys=True).encode()).hexdigest()[:24]
    return {
        'downloads_prefix': f'fw-downloads-v2-{scope}-{revision}-',
        'downloads_fallback': f'fw-downloads-v2-{scope}-',
        'compiler_prefix': f'fw-ccache-v2-{scope}-{target}-{revision}-',
        'go_prefix': f'fw-go-v1-{scope}-{target}-{revision}-{go_revision}-',
    }


def bind_go_cache(src, work):
    """The pinned Go feed uses tmp/go-build; keep that cache outside source."""
    src, work = Path(src), Path(work).resolve()
    destination = work/'go-build'
    if destination.is_symlink():
        raise BuildError('Go cache root must not be a symlink')
    destination.mkdir(parents=True, exist_ok=True)
    link = src/'tmp/go-build'
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() and link.resolve() == destination:
        return
    if link.exists() or link.is_symlink():
        raise BuildError('Refusing to replace an existing Go cache path: '+str(link))
    link.symlink_to(destination, target_is_directory=True)


def timed_run(work, phase, args, cwd):
    started = time.monotonic()
    status = 1
    try:
        result = run(args, cwd)
        status = 0
        return result
    except subprocess.CalledProcessError as exc:
        status = exc.returncode
        raise
    finally:
        try:
            logs = Path(work)/'logs'
            logs.mkdir(parents=True, exist_ok=True)
            (logs/(phase+'-timing.json')).write_text(json.dumps({
                'phase': phase, 'seconds': round(time.monotonic()-started, 3), 'exit_code': status,
            }, indent=2)+'\n')
        except OSError:
            print('Could not record build timing', file=sys.stderr)


def prune_go_cache(folder, limit=GIB):
    """Go refreshes entry mtimes on reuse. Trim oldest regular files only."""
    folder = Path(folder)
    if folder.is_symlink():
        raise BuildError('Go cache root must not be a symlink')
    files = []
    for directory, names, entries in os.walk(folder, followlinks=False):
        names[:] = [name for name in names if not (Path(directory)/name).is_symlink()]
        for name in entries:
            entry = Path(directory)/name
            if entry.is_symlink() or not entry.is_file():
                continue
            metadata = entry.stat()
            files.append((metadata.st_mtime_ns, str(entry), metadata.st_size))
    total = sum(item[2] for item in files)
    for _, name, size in sorted(files):
        if total <= limit:
            break
        Path(name).unlink()
        total -= size
    return total


def report(work):
    work = Path(work).resolve()
    logs = work/'logs'
    logs.mkdir(parents=True, exist_ok=True)
    plan_path = logs/'acceleration-plan.json'
    data = json.loads(plan_path.read_text()) if plan_path.exists() else {}
    data['phases'] = [json.loads(p.read_text()) for p in sorted(logs.glob('*-timing.json'))]
    data['restored'] = {name: bool(os.environ.get(variable)) for name, variable in (
        ('downloads', 'DOWNLOADS_MATCHED'), ('compiler', 'COMPILER_MATCHED'), ('go', 'GO_MATCHED'))}
    binary = work/'source/staging_dir/host/bin/ccache'
    if binary.is_file():
        for flag, filename in (('--cleanup', 'ccache-cleanup.txt'), ('--show-log-stats', 'ccache-stats.txt')):
            result = subprocess.run([str(binary), flag], text=True, capture_output=True, check=False)
            (logs/filename).write_text(result.stdout + result.stderr)
    data['go_cache_bytes'] = prune_go_cache(work/'go-build')
    (logs/'build-metrics.json').write_text(json.dumps(data, indent=2)+'\n')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        lines = ['## Firmware build measurements', '',
                 '| Item | Result |', '| --- | --- |',
                 '| Compile jobs | '+str(data.get('jobs', 'unknown'))+' |']
        lines.extend('| '+name+' cache restored | '+str(value)+' |' for name, value in data['restored'].items())
        lines.extend('| '+item['phase']+' | '+str(round(item['seconds']/60, 1))+' min; exit '+str(item['exit_code'])+' |' for item in data['phases'])
        stats = logs/'ccache-stats.txt'
        if stats.exists():
            lines.extend(['', '```text', stats.read_text().replace('```', '')[:6000], '```'])
        with open(summary, 'a') as stream:
            stream.write('\n'.join(lines)+'\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('step', choices=('plan', 'report'))
    parser.add_argument('--profile', default='x86-basic')
    parser.add_argument('--work', type=Path, default=Path('.work'))
    parser.add_argument('--jobs', default='auto')
    args = parser.parse_args()
    if args.step == 'report':
        report(args.work)
        return
    data = cache_plan(profile(args.profile), os.environ.get('RUNNER_OS', platform.system()),
                      os.environ.get('RUNNER_ARCH', platform.machine()))
    data['jobs'] = select_jobs(args.jobs)
    data['available_memory_bytes'] = available_memory()
    logs = args.work/'logs'
    logs.mkdir(parents=True, exist_ok=True)
    (logs/'acceleration-plan.json').write_text(json.dumps(data, indent=2)+'\n')
    output = ''.join(name+'='+str(value)+'\n' for name, value in data.items())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write(output)
    print(output, end='')


if __name__ == '__main__':
    try:
        main()
    except (BuildError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
