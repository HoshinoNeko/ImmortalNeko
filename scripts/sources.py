"""Pinned source checkout and feed installation."""
import shutil
from pathlib import Path
from scripts.fwlib import ROOT, BuildError, locked_repos, run, safe_path

def prepare_source(work):
    lock, feeds = locked_repos()
    src = work/'source'
    if src.exists():
        raise BuildError('Source already exists; use a fresh --work directory')
    work.mkdir(parents=True, exist_ok=True)
    run(['git', 'init', src])
    run(['git', 'remote', 'add', 'origin', lock['url']], src)
    run(['git', 'fetch', '--depth=1', 'origin', lock['commit']], src)
    run(['git', 'checkout', '--detach', 'FETCH_HEAD'], src)
    (work/'downloads').mkdir(exist_ok=True)
    (src/'dl').symlink_to(work/'downloads', target_is_directory=True)
    if run(['git', 'rev-parse', 'HEAD'], src, True) != lock['commit']:
        raise BuildError('Source commit mismatch')
    (src/'feeds.conf').write_text(''.join('src-git {name} {url}^{commit}\n'.format(**f) for f in feeds))
    run(['./scripts/feeds', 'update', '-a'], src)
    for f in feeds:
        path = safe_path(src/'feeds', f['name'])
        if run(['git', 'rev-parse', 'HEAD'], path, True) != f['commit']:
            raise BuildError('Feed commit mismatch: '+f['name'])
    run(['./scripts/feeds', 'install', '-a'], src)
    return src

def apply_patches(src, p):
    for directory in [ROOT/'patches/common', ROOT/'patches'/p['name']]:
        series = directory/'series'
        if not series.exists():
            continue
        for name in series.read_text().splitlines():
            name = name.split('#', 1)[0].strip()
            if not name:
                continue
            patch = safe_path(directory, name)
            run(['git', 'apply', '--check', patch], src)
            run(['git', 'apply', patch], src)

def install_files(src, p):
    from scripts.fwlib import scan_tree
    for directory in p['overlays']:
        overlay = ROOT/directory
        scan_tree(overlay)
        shutil.copytree(overlay, src/'files', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('.gitkeep'))
    for parent in ['local-packages', 'themes/packages']:
        for directory in sorted((ROOT/parent).iterdir()):
            if directory.is_dir() and (directory/'Makefile').exists():
                dest = src/'package/custom'/directory.name
                if dest.exists():
                    raise BuildError('Duplicate local package: '+directory.name)
                shutil.copytree(directory, dest)
