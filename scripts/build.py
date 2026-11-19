#!/usr/bin/env python3
"""Small CLI; implementation lives in separate modules."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.fwlib import ROOT, BuildError, assert_config, config_values, locked_repos, profile, requested_config, run, scan_tree
from scripts.sources import apply_patches, install_files, prepare_source, validate_local_packages
from scripts.configure import configure
from scripts.artifacts import collect
from scripts.build_accel import timed_run

def validate():
    locked_repos()
    validate_local_packages()
    for f in sorted((ROOT/'profiles').glob('*.json')):
        p = profile(f.stem)
        requested_config(p)
        for directory in p['overlays']:
            scan_tree(ROOT/directory)
    for directory in ('patches', 'local-packages', 'themes'):
        scan_tree(ROOT/directory)
    print('Configuration structure, dependency locks and firmware input scan passed')

def main():
    a = argparse.ArgumentParser()
    a.add_argument('step',choices=['validate','matrix','prepare','config-check','download','compile','collect'])
    a.add_argument('--profile',default='x86-basic')
    a.add_argument('--work',type=Path,default=ROOT/'.work')
    a.add_argument('--out',type=Path,default=ROOT/'artifacts')
    a.add_argument('--jobs',type=int,default=2)
    args=a.parse_args()
    if args.step=='validate':
        validate(); return
    if args.step=='matrix':
        names = [f.stem for f in sorted((ROOT/'profiles').glob('*.json'))] if args.profile=='all' else [args.profile]
        for n in names: profile(n)
        print(json.dumps({'profile':names})); return
    p=profile(args.profile)
    work=args.work.resolve()
    src=work/'source'
    if args.jobs < 1 or args.jobs > 64:
        raise BuildError('jobs must be between 1 and 64')
    if args.step=='prepare':
        validate()
        if run(['git','status','--porcelain','--untracked-files=all'], ROOT, True):
            raise BuildError('Commit builder inputs before preparing a reproducible build')
        run(['git','rev-parse','--verify','HEAD'], ROOT, True)
        src=prepare_source(work)
        apply_patches(src,p)
        install_files(src,p)
        configure(src,p,work)
    elif args.step=='config-check':
        assert_config(requested_config(p, work),config_values((src/'.config').read_text()))
    elif args.step=='download':
        timed_run(work,'download',['make','download','-j'+str(args.jobs),'V=s'],src)
    elif args.step=='compile':
        assert_config(requested_config(p, work),config_values((src/'.config').read_text()))
        timed_run(work,'compile',['make','-j'+str(args.jobs),'V=s'],src)
    elif args.step=='collect':
        assert_config(requested_config(p, work),config_values((src/'.config').read_text()))
        collect(src,p,args.out.resolve(),work)

if __name__=='__main__':
    try:
        main()
    except (BuildError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        sys.exit(1)
