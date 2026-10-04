#!/usr/bin/env python3
"""Validate exercise-only backup configuration, never perform an export."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path('/srv/workplace-rehearsal')

def private_path(value):
    path=Path(value)
    if not path.is_absolute() or '..' in path.parts or ROOT not in path.parents or path.is_symlink(): raise ValueError('exercise private path required')
    return path

def validate(path):
    config=json.loads(private_path(path).read_text())
    private_path(config['root'])
    inventory=json.loads(private_path(config['inventory']).read_text())
    def walk(value,key=''):
        if isinstance(value,dict):
            for k,v in value.items(): walk(v,k)
        elif isinstance(value,list):
            for v in value: walk(v,key)
        elif isinstance(value,str):
            if key in ('container','owners') and not value.startswith('s237-'): raise ValueError('foreign producer')
            if key=='source' and value.startswith('/'): private_path(value)
    walk(inventory)
    for file in config['profiles']:
        profile=json.loads(private_path(file).read_text())
        if profile.get('kind')!='file': raise ValueError('exercise local backup destination only')
        private_path(profile['mount_path'])
        private_path(profile['credentials'])
    return config

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    try: validate(args.config)
    except Exception: print('Exercise backup configuration refused.',file=sys.stderr);sys.exit(1)
