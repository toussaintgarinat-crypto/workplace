#!/usr/bin/env python3
"""Recover one encrypted S236 generation on the exercise VM.

Uses a staged copy of the encrypted destination, a brand-new Duplicati database
and new output paths; never exports, never touches production media. Prints
counts only: Duplicati logs stay private under state/diagnostics.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def archive_digest(remote):
    """Identity of the staged encrypted destination (names and sizes)."""
    entries = sorted((p.name, p.stat().st_size) for p in remote.iterdir() if p.is_file())
    if not entries:
        raise ValueError('empty encrypted destination')
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def write_json(path, value):
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
    os.replace(tmp, path)


def run_logged(argv, diagnostics, label):
    log = diagnostics / (label + '-' + uuid.uuid4().hex + '.log')
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        raise ValueError(label + ' failed; private log retained')


def verify(root, generation, diagnostics):
    run_logged([sys.executable, str(root / 'bin/coherent/backup.py'), 'verify', '--generation', str(generation)], diagnostics, 'verify')
    manifest = json.loads((generation / 'manifest.json').read_text())
    return manifest


def recover(root, profile, version, image):
    root = Path(root)
    remote = root / 'backups/remote' / profile
    generation = root / 'backups/recovered'
    repository = root / 'backups/repository'
    state = root / 'state/recovery.json'
    diagnostics = private_dir(root / 'state/diagnostics')
    digest = archive_digest(remote)
    if state.exists():
        recorded = json.loads(state.read_text())
        if recorded.get('archive') != digest or recorded.get('version') != version or recorded.get('profile') != profile:
            raise ValueError('a different generation is already recovered; use a new exercise VM')
        manifest = verify(root, generation, diagnostics)
        if manifest['started'] != recorded['started'] or not repository.is_dir():
            raise ValueError('recovered generation drift')
        return {'changed': 0, 'sources': len(manifest['sources'])}
    if generation.exists() or repository.exists():
        raise ValueError('unrecorded recovery output exists')
    database = private_dir(root / 'state/recovery-db') / ('restore-' + uuid.uuid4().hex + '.sqlite')
    private_dir(generation)
    run_logged(['docker', 'run', '--rm', '--network', 'none', '--env-file', str(root / 'private/recovery.env'),
                '--mount', 'type=bind,src=' + str(root / 'backups/remote') + ',dst=/remote,readonly',
                '--mount', 'type=bind,src=' + str(database.parent) + ',dst=/data',
                '--mount', 'type=bind,src=' + str(generation) + ',dst=/restore',
                '--entrypoint', 'duplicati-cli', image, 'restore', 'file:///remote/' + profile, '*',
                '--version=' + version, '--restore-path=/restore', '--dbpath=/data/' + database.name,
                '--encryption-module=aes', '--disable-module=console-password-input'], diagnostics, 'duplicati-restore')
    manifest = verify(root, generation, diagnostics)
    source = [s for s in manifest['sources'] if s['kind'] == 'tree' and s.get('id') == 'repository']
    if len(source) != 1:
        raise ValueError('repository tree missing from generation')
    sys.path.insert(0, str(root / 'bin/coherent'))
    import artifacts
    restored = artifacts.restore_tree(str(generation / source[0]['path']), str(repository))
    write_json(state, {'profile': profile, 'version': version, 'archive': digest, 'started': manifest['started'],
                       'sources': len(manifest['sources']), 'repository_entries': len(restored['entries'])})
    return {'changed': 1, 'sources': len(manifest['sources'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    if args.root != '/srv/workplace-rehearsal':
        raise SystemExit('dedicated root required')
    try:
        print(json.dumps(recover(args.root, args.profile, args.version, args.image)))
    except Exception as error:
        print('Recovery refused or failed (' + type(error).__name__ + '): ' + str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
