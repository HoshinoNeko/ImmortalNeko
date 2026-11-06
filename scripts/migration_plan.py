#!/usr/bin/env python3
"""Regenerate the public, package-name-only retention plan from a private inventory."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fwlib import ROOT, BuildError, package_names, profile, read_json, safe_path
from scripts.import_legacy import installed_names, propose


def make_plan(inventory, metadata, mappings, selections, local, source_commit):
    names = installed_names(inventory)
    available = set(re.findall(r'^Package:\s*(\S+)', metadata, re.M))
    if not available:
        raise BuildError('Empty package metadata')
    plugins = [n for n in names if n.startswith(('luci-app-', 'luci-proto-', 'luci-theme-'))]
    rows = propose(plugins, available | set(local), mappings)
    for row in rows:
        if row['old'] in local:
            row.update(action='port', note='Local LuCI implementation; backend ownership and compatibility boundaries are documented in source-evidence.json; target compilation and runtime acceptance remain pending.')
            row['definition'] = local[row['old']]
        row['selected_in'] = sorted(name for name, packages in selections.items()
                                    if row['packages'] and set(row['packages']) <= packages)
        row['verification'] = 'package definitions and explicit profile selections only; defconfig, compilation and runtime acceptance pending'
    unresolved = sum(r['action'] == 'review' or bool(r['unavailable']) for r in rows)
    return {
        'status': 'incomplete-retention-plan',
        'baseline': 'current x86 read-only SSH snapshot; supersedes historical backups',
        'installed_package_count': len(names),
        'inventory_sha256': hashlib.sha256(inventory.encode()).hexdigest(),
        'metadata_sha256': hashlib.sha256(metadata.encode()).hexdigest(),
        'plugin_count': len(rows),
        'unresolved_plugin_count': unresolved,
        'profile_request_coverage': {
            name: {
                'explicit_plugin_mapping_count': sum(name in row['selected_in'] for row in rows),
                'defined_but_not_explicitly_requested': sum(
                    row['action'] != 'review' and not row['unavailable'] and name not in row['selected_in']
                    for row in rows),
                'scope': 'direct package requests only; dependencies and actual image require manifest verification'
            } for name in sorted(selections)
        },
        # A package definition/selection never proves preservation of runtime behavior.
        'all_plugins_preserved': False,
        'source_commit': source_commit,
        'plugins': rows,
        'standalone_services': [
            {'old': n, 'packages': [n], 'selected_in': sorted(p for p, packages in selections.items() if n in packages),
             'verification': 'selected only; target compilation and runtime pending'}
            for n in ('tailscale',) if n in names
        ]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'migration/current-plugin-plan.json')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.parent != (ROOT/'migration').resolve():
        raise BuildError('Public plan output must be directly inside migration/')
    safe_path(ROOT/'migration', output.name)
    raw = args.metadata.read_bytes()
    metadata = (gzip.decompress(raw) if raw.startswith(b'\x1f\x8b') else raw).decode()
    local = {}
    for makefile in sorted((ROOT/'local-packages').glob('*/Makefile')):
        name = makefile.parent.name
        if re.search(r'^PKG_NAME\s*:?=\s*'+re.escape(name)+r'\s*$', makefile.read_text(), re.M):
            local[name] = str(makefile.relative_to(ROOT))
    selections = {p.stem: {n for n in package_names(profile(p.stem)) if not n.startswith('-')}
                  for p in sorted((ROOT/'profiles').glob('*.json'))}
    plan = make_plan(args.installed.read_text(), metadata, read_json(ROOT/'migration/package-map.json'),
                     selections, local, read_json(ROOT/'config/source.lock.json')['commit'])
    output.write_text(json.dumps(plan, indent=2, ensure_ascii=False)+'\n')
    print(f"Plan: {plan['plugin_count']} plugins, {plan['unresolved_plugin_count']} unresolved; runtime preservation not verified")


if __name__ == '__main__':
    try:
        main()
    except (BuildError, OSError, ValueError) as exc:
        print('ERROR: '+str(exc), file=sys.stderr)
        sys.exit(1)
