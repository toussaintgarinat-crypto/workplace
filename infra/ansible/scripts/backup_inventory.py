#!/usr/bin/env python3
"""Generate the exercise S236 backup inventory from the running S237 containers.

The inventory follows the S236 format (version 1) so the real coherent tooling
can discover, stop and export the exercise producers. Engines and volume trees
are classified from the restore journal; every other mount is classified with a
reason. It never runs an export: validation uses the S236 read-only preflight.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/srv/workplace-rehearsal')
DATA = ROOT / 'data'
REPOSITORY = DATA / 'repo'
REPRODUCIBLE = {'/var/cache/searxng': 'Cache SearxNG reproductible.',
                '/workspace/oria/frontend/node_modules': "Dépendances reconstruites depuis l'image.",
                '/var/lib/clamav': 'Signatures ClamAV retéléchargeables.',
                '/prometheus': "Historique Prometheus exclu de la reprise applicative (comme S236).",
                '/var/lib/postgresql/wal_archive': 'Archive WAL locale régénérée ; reprise par dump logique.'}


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True).stdout.strip()


def build():
    journal = json.loads((ROOT / 'state/restore.json').read_text())
    ids = docker('ps', '-aq', '--filter', 'label=s237.owner', '--filter', 'label=com.docker.compose.project').split()
    ids += docker('ps', '-aq', '--filter', 'label=com.docker.compose.project').split()
    containers = [c for c in json.loads(docker('inspect', *sorted(set(ids))))
                  if c['Config']['Labels'].get('com.docker.compose.project', '').startswith('s237-')]
    restored_trees = {v['volume'] for k, v in journal.items() if k.startswith('tree:')}
    pg_volumes = {v['volume'] for k, v in journal.items() if k.startswith('postgres:')}
    qdrant_volume = next(v['volume'] for k, v in journal.items() if k.startswith('qdrant:'))
    inv = {'version': 1, 'rpo_seconds': 86400, 'rto_seconds': 28800, 'expected_mounts': [], 'trees': [],
           'classified_mounts': [], 'postgres': [], 'qdrant': None, 'etcd': None,
           'repository': {'id': 'repository', 'kind': 'bind', 'source': str(REPOSITORY), 'owners': [],
                          'exclude': ['.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache']},
           'note': "Inventaire de l'exercice S237 généré depuis les conteneurs réels ; aucune valeur secrète."}
    trees = {}
    classified = {}
    for c in containers:
        name = c['Name'].lstrip('/')
        labels = c['Config']['Labels']
        mounts = []
        for m in c['Mounts']:
            entry = {'type': m['Type'], 'source': m['Source'], 'destination': m['Destination'], 'name': m.get('Name')}
            mounts.append(entry)
            owner = {'container': name, 'destination': m['Destination']}
            if m['Type'] == 'volume' and m['Name'] in pg_volumes:
                inv['postgres'].append({'container': name, 'image': c['Config']['Image'], 'restore_image': c['Config']['Image']})
            elif m['Type'] == 'volume' and m['Name'] == qdrant_volume:
                inv['qdrant'] = {'container': name, 'image': c['Config']['Image']}
            elif m['Type'] == 'volume' and m['Name'] in restored_trees:
                trees.setdefault(m['Name'], {'id': m['Name'], 'kind': 'volume', 'source': m['Name'], 'owners': [], 'exclude': []})['owners'].append(owner)
            elif labels.get('com.docker.compose.service') == 'etcd' and m['Type'] == 'volume':
                inv['etcd'] = {'container': name, 'image': c['Config']['Image']}
            else:
                source = m['Source']
                if m['Type'] == 'bind' and Path(source).is_relative_to(REPOSITORY):
                    reason = 'Couvert par repository (données restaurées du dépôt).'
                elif m['Type'] == 'bind' and Path(source).is_relative_to(ROOT / 'releases'):
                    reason = 'Code immuable de la release, reconstruit depuis Git.'
                elif m['Type'] == 'bind' and Path(source).is_relative_to(DATA / 'workspace'):
                    reason = "Copie de travail de l'atelier, reconstruite depuis repository."
                elif m['Type'] == 'bind' and Path(source).is_relative_to(DATA / 'relais'):
                    reason = 'Routes du relais régénérées par prepare.'
                elif m['Destination'] in REPRODUCIBLE:
                    reason = REPRODUCIBLE[m['Destination']]
                else:
                    raise SystemExit('unclassified mount ' + name + ' ' + m['Destination'])
                classified.setdefault(source, {'source': source, 'owners': [], 'reason': reason})['owners'].append(owner)
        inv['expected_mounts'].append({'container': name, 'running': bool(c['State']['Running']), 'image': c['Config']['Image'], 'mounts': mounts})
    inv['trees'] = sorted(trees.values(), key=lambda t: t['id'])
    inv['classified_mounts'] = sorted(classified.values(), key=lambda t: t['source'])
    core = next(c for c in containers if c['Config']['Labels'].get('com.docker.compose.project') == 's237-core')
    inv['helper_image'] = core['Image']
    if len(inv['postgres']) != len(pg_volumes) or not inv['qdrant'] or not inv['etcd']:
        raise SystemExit('engine classification incomplete')
    return inv


def write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
    os.replace(tmp, path)


if __name__ == '__main__':
    inventory = build()
    target = ROOT / 'private/backup/inventory-exercise.json'
    previous = target.read_text() if target.exists() else None
    write(target, inventory)
    print(json.dumps({'changed': int(previous != target.read_text()), 'containers': len(inventory['expected_mounts']),
                      'trees': len(inventory['trees']), 'postgres': len(inventory['postgres'])}))
    sys.exit(0)
