"""Shared validation and process primitives. No external Python dependencies."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
class BuildError(RuntimeError):
    pass

def read_json(path):
    return json.loads(Path(path).read_text())

def run(args, cwd=None, capture=False):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    p = subprocess.run(list(map(str, args)), cwd=cwd, check=True, text=True,
                       stdout=subprocess.PIPE if capture else None)
    return p.stdout.strip() if capture else None

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def safe_path(base, name):
    p = Path(base) / name
    if p.is_symlink() or not p.resolve().is_relative_to(Path(base).resolve()):
        raise BuildError('Unsafe path: ' + str(p))
    return p

def locked_repos():
    source = read_json(ROOT/'config/source.lock.json')
    extras = read_json(ROOT/'config/feeds.extra.lock.json')
    repos = [source] + source['feeds'] + extras
    names = []
    for r in repos:
        u = urlparse(r['url'])
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise BuildError('Git URLs must be HTTPS without credentials/query')
        if not re.fullmatch(r'[0-9a-f]{40}', r['commit']):
            raise BuildError('Every source/feed requires a full commit SHA')
        if r is not source:
            if not re.fullmatch(r'[a-z][a-z0-9_-]*', r['name']):
                raise BuildError('Invalid feed name')
            names.append(r['name'])
    if len(set(names)) != len(names):
        raise BuildError('Duplicate feed names')
    if not re.fullmatch(r'openwrt-\d{2}\.\d{2}', source['branch']):
        raise BuildError('Use an official stable branch')
    return source, source['feeds'] + extras

def profile(name):
    if not re.fullmatch(r'[a-z0-9-]+', name):
        raise BuildError('Invalid profile name')
    p = read_json(safe_path(ROOT/'profiles', name+'.json'))
    if p['name'] != name:
        raise BuildError('Profile name mismatch')
    allowed = {'fragments': ('config/',), 'packages': ('packages/',), 'overlays': ('files/', 'themes/luci-overrides/')}
    for group in ('fragments', 'packages', 'overlays'):
        for f in p[group]:
            if not f.startswith(allowed[group]):
                raise BuildError('Input outside approved firmware directory: '+f)
            path = safe_path(ROOT, f)
            if not any(path.resolve().is_relative_to((ROOT/parent).resolve()) for parent in allowed[group]):
                raise BuildError('Input resolves outside approved firmware directory: '+f)
            if not path.exists():
                raise BuildError('Missing profile input: '+f)
    return p

def package_names(p):
    result = []
    for f in p['packages']:
        for line in (ROOT/f).read_text().splitlines():
            v = line.split('#', 1)[0].strip()
            if not v:
                continue
            if not re.fullmatch(r'-?[a-zA-Z0-9][a-zA-Z0-9+_.-]*', v):
                raise BuildError('Invalid package: '+v)
            if v in result or ('-'+v) in result or v.removeprefix('-') in result:
                raise BuildError('Duplicate/conflicting package: '+v)
            result.append(v)
    return result

def config_values(text):
    vals = {}
    for line in text.splitlines():
        m = re.fullmatch(r'(CONFIG_[A-Za-z0-9_+.-]+)=(.*)', line)
        n = re.fullmatch(r'# (CONFIG_[A-Za-z0-9_+.-]+) is not set', line)
        if m:
            vals[m[1]] = m[2]
        elif n:
            vals[n[1]] = 'n'
        elif line.strip() and not line.lstrip().startswith('#'):
            raise BuildError('Invalid config line: '+line)
    return vals

def requested_config(p, work=None):
    result = {}
    for f in ['config/common.config'] + p['fragments'] + ['config/kernel.config']:
        result.update(config_values((ROOT/f).read_text()))
    for pkg in package_names(p):
        result['CONFIG_PACKAGE_'+pkg.removeprefix('-')] = 'n' if pkg.startswith('-') else 'y'
    if work is not None:
        result['CONFIG_CCACHE_DIR'] = json.dumps(str(Path(work)/'ccache'))
    return result

def assert_config(wanted, actual):
    missing = [k+'='+v+' (resolved '+actual.get(k, 'n')+')'
               for k,v in wanted.items() if actual.get(k, 'n') != v]
    if missing:
        raise BuildError('Unavailable packages/options after defconfig:\n'+'\n'.join(missing))

SECRET = re.compile(r"""(?im)(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:option\s+)?(?:password|passwd|token|secret|private_key|preshared_key|auth_pass|api_key|key)\s*(?:=|\s)\s*["']?[^\s"'#]+)""")

def scan_tree(base):
    base = Path(base)
    if not base.exists():
        return
    forbidden = {'shadow', 'passwd', 'authorized_keys', 'id_rsa', 'id_ed25519', '.env'}
    for f in base.rglob('*'):
        safe_path(base, f.relative_to(base))
        if f.is_symlink():
            raise BuildError('Symlinks are forbidden in firmware inputs: '+str(f))
        if not f.is_file() or f.name == '.gitkeep':
            continue
        if f.name in forbidden or f.suffix in {'.key', '.pem', '.p12', '.pfx', '.ovpn'}:
            raise BuildError('Credential file forbidden in firmware inputs: '+str(f))
        try:
            text = f.read_text()
        except UnicodeError:
            raise BuildError('Binary overlay requires explicit review: '+str(f))
        if SECRET.search(text):
            raise BuildError('Possible credential in firmware input: '+str(f))
