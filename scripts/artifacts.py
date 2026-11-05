"""Collect firmware, manifests, inputs and hashes; fail on missing outputs."""
import datetime
import json
import shutil
from scripts.fwlib import ROOT, BuildError, locked_repos, package_names, run, sha

def verify_outputs(target, p):
    for pattern in p['required_artifacts']:
        if not list(target.glob(pattern)):
            raise BuildError('Missing required artifact: '+pattern)
    manifests = list(target.glob('*.manifest'))
    if not manifests:
        raise BuildError('Actual package manifest missing')
    required = {name for name in package_names(p) if not name.startswith('-')}
    for manifest in manifests:
        installed = {line.split()[0] for line in manifest.read_text().splitlines() if line.strip()}
        missing = required-installed
        if missing:
            raise BuildError('Requested packages absent from '+manifest.name+': '+', '.join(sorted(missing)))

def collect(src, p, out, work):
    target = src/'bin/targets'/p['target']/p['subtarget']
    allfiles = [f for f in target.iterdir() if f.is_file()]
    verify_outputs(target, p)
    images = [f for f in allfiles if any(f.name.endswith(s) for s in ('.img.gz', '.bin', '.ubi', '.itb'))]
    if not images or not list(target.glob('*.manifest')):
        raise BuildError('Firmware or actual package manifest missing')
    if out.exists():
        raise BuildError('Refusing to mix artifacts: '+str(out))
    out.mkdir(parents=True)
    for f in allfiles:
        # Never publish repository signing keys or opaque build directories.
        if f.name == 'key-build' or f.suffix in {'.key', '.pem'}:
            raise BuildError('Signing material in target output')
        shutil.copy2(f, out/f.name)
    shutil.copy2(src/'.config', out/'resolved.config')
    shutil.copy2(work/'requested.config', out/'requested.config')
    shutil.copy2(src/'feeds.conf', out/'feeds.conf.lock')
    lock, feeds = locked_repos()
    input_files = {}
    for directory in ['config', 'profiles', 'packages', 'patches', 'files', 'local-packages', 'themes', 'scripts']:
        for f in (ROOT/directory).rglob('*'):
            if f.is_file() and '__pycache__' not in f.parts and f.suffix != '.pyc':
                input_files[str(f.relative_to(ROOT))] = sha(f)
    meta = {'built_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'builder_commit':run(['git','rev-parse','HEAD'],ROOT,True),
            'source':lock, 'profile':p, 'requested_packages':package_names(p),
            'source_commit_actual':run(['git','rev-parse','HEAD'],src,True),
            'feeds_actual':{f['name']:run(['git','rev-parse','HEAD'],src/'feeds'/f['name'],True) for f in feeds},
            'input_sha256':input_files}
    (out/'BUILD_VERSION').write_text(p['name']+'-'+lock['release']+'-'+meta['builder_commit'][:12]+'\n')
    (out/'build-info.json').write_text(json.dumps(meta, indent=2)+'\n')
    run(['git','diff','--exit-code'],ROOT)
    (out/'SHA256SUMS').write_text(''.join(sha(f)+'  '+f.name+'\n' for f in sorted(out.iterdir()) if f.is_file() and f.name != 'SHA256SUMS'))
