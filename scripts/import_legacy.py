#!/usr/bin/env python3
"""Generate a reviewable preservation proposal; never copy old credentials into firmware."""
import argparse
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.fwlib import ROOT, BuildError, read_json

def installed_names(text):
    names=set()
    for line in text.splitlines():
        if not line.strip(): continue
        m=re.fullmatch(r'([a-zA-Z0-9][a-zA-Z0-9+_.-]*)\s+-\s+\S+(?:\s+-\s+.*)?',line)
        if not m: raise BuildError('Expected opkg list-installed or opkg list format')
        names.add(m[1])
    if not names: raise BuildError('Empty package inventory')
    return sorted(names)

def propose(installed, available, mappings):
    rows=[]
    for name in installed:
        if name in mappings:
            row={'old':name,'action':'replace','packages':mappings[name]['replacement'],'note':mappings[name]['reason']}
        elif name in available:
            row={'old':name,'action':'keep','packages':[name]}
        else:
            row={'old':name,'action':'review','packages':[],'note':'No confirmed equivalent in selected target; do not silently drop.'}
        row['unavailable']=[p for p in row['packages'] if p not in available]
        rows.append(row)
    return rows

def config_schema(directory):
    # Only option names and section TYPES leave the private directory, never values.
    result={}
    for p in sorted(Path(directory).iterdir()):
        if not p.is_file() or p.is_symlink(): continue
        sections=[]; keys=set()
        for line in p.read_text(errors='replace').splitlines():
            m=re.match(r'^\s*config\s+[\'"]?([a-zA-Z0-9_-]+)',line)
            k=re.match(r'^\s*(?:option|list)\s+[\'"]?([a-zA-Z0-9_-]+)',line)
            if m: sections.append(m[1])
            if k: keys.add(k[1])
        result[p.name]={'section_types':sections,'option_names':sorted(keys)}
    return result

def main():
    a=argparse.ArgumentParser()
    a.add_argument('--installed',required=True,type=Path)
    a.add_argument('--available',required=True,type=Path,help='Prepared source/tmp/.packageinfo')
    a.add_argument('--config-dir',type=Path)
    a.add_argument('--output',required=True,type=Path)
    args=a.parse_args()
    if not args.output.resolve().is_relative_to((ROOT/'private').resolve()):
        raise BuildError('Write migration proposals under ignored private/ only')
    available=set(re.findall(r'^Package:\s*(\S+)',args.available.read_text(),re.M))
    if not available: raise BuildError('Empty package metadata; prepare selected target first')
    rows=propose(installed_names(args.installed.read_text()),available,read_json(ROOT/'migration/package-map.json'))
    report={'status':'proposal-needs-review','packages':rows,'config_schema':config_schema(args.config_dir) if args.config_dir else {}}
    args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    proposed=sorted({p for row in rows for p in row['packages']})
    (args.output/'proposed.list').write_text('\n'.join(proposed)+'\n')
    unresolved=[row for row in rows if row['action']=='review' or row['unavailable']]
    print(f'Proposal: {len(rows)} old packages, {len(unresolved)} unresolved; no profile was changed')
    return 2 if unresolved else 0

if __name__=='__main__':
    try: sys.exit(main())
    except (BuildError,OSError,ValueError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);sys.exit(1)
