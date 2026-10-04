#!/usr/bin/env python3
"""Restore a verified S236 generation into the S237 exercise projects.

Phase `files` (before prepare): data binds mapped to `repo/<path>` or
`workspace` are copied from the recovered repository tree.
Phase `engines` (after prepare, before deploy): volume trees, PostgreSQL dumps
and Qdrant snapshots are restored into the exact named volumes of the prepared
models, using the exercise's own images, without any network.

Each production container of the generation is attached to its exercise project
through its Compose labels (working directory + service); mounts are matched by
destination. Targets must be new or recorded: nothing is ever overwritten.
stdout carries counts only; native errors stay in private diagnostics.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path('/srv/workplace-rehearsal')
WORKSPACE = '/home/debian/workplace'
PGDATA = '/var/lib/postgresql/data'
LABEL = 's237.owner=rehearsal'


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def write_json(path, value):
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
    os.replace(tmp, path)


class Journal:
    """Durable record of completed restorations: a recorded item is never redone."""

    def __init__(self, root):
        self.path = root / 'state/restore.json'
        self.done = json.loads(self.path.read_text()) if self.path.exists() else {}

    def record(self, key, value):
        self.done[key] = value
        write_json(self.path, self.done)


def run(argv, diagnostics=None, label='native', stdin=None, timeout=3600):
    result = subprocess.run(argv, stdin=stdin, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        if diagnostics:
            log = diagnostics / (label + '-' + uuid.uuid4().hex + '.log')
            fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(result.stderr[-200000:])
        raise ValueError(label + ' failed; private diagnostic retained')
    return result.stdout.decode().strip()


def copy_tree(source, target):
    """Copy a recovered file or directory, preserving modes and owners."""
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
    for path in [target, *(target.rglob('*') if target.is_dir() else [])]:
        stat = (source / path.relative_to(target)).lstat() if source.is_dir() else source.lstat()
        os.lchown(path, stat.st_uid, stat.st_gid)


def files(config):
    root = Path(config['root'])
    repository = root / 'backups/repository'
    if not (root / 'state/recovery.json').exists() or not repository.is_dir():
        raise ValueError('verified recovered generation required')
    journal = Journal(root)
    changed = 0
    created_empty = []
    for project, private in config['private_projects'].items():
        for source, mapping in private['bind_mappings'].items():
            if not isinstance(mapping, str):
                continue
            if mapping == 'workspace':
                relative, origin = '', repository
            elif mapping.startswith('repo/'):
                relative = mapping[len('repo/'):]
                origin = repository / relative
            else:
                continue  # produced by the tooling itself (relay routes)
            target = root / 'data' / mapping
            key = 'files:' + mapping
            if key in journal.done:
                if not target.exists():
                    raise ValueError('recorded restored data missing: ' + mapping)
                continue
            if target.exists():
                raise ValueError('unrecorded data target exists: ' + mapping)
            if origin.exists() or origin.is_symlink():
                copy_tree(origin, target)
                journal.record(key, {'source': 'repository/' + relative, 'kind': 'dir' if origin.is_dir() else 'file'})
            else:
                # Empty directories are not archived by S236; production had them empty.
                target.mkdir(mode=0o755, parents=True)
                created_empty.append(mapping)
                journal.record(key, {'source': None, 'kind': 'empty-dir'})
            changed += 1
    return {'changed': changed, 'empty_directories': len(created_empty)}


class Exercise:
    def __init__(self, config):
        self.root = Path(config['root'])
        self.config = config
        self.generation = self.root / 'backups/recovered'
        self.manifest = json.loads((self.generation / 'manifest.json').read_text())
        self.deployment = {c['name']: c for c in json.loads((self.generation / 'deployment.json').read_text())}
        self.inventory = self.manifest['inventory']
        self.diagnostics = private_dir(self.root / 'state/diagnostics')
        observed = json.loads((self.root / 'releases' / config['revision'] / 'infra/ansible/catalogue.observed.json').read_text())
        # Whole projects excluded by the reviewed profile (for example mesh-https).
        self.excluded_directories = {WORKSPACE + '/' + observed[name]['directory'] for name in config.get('exclusions', {})}
        self.models = {}
        for project in config['catalogue']:
            prepared = json.loads((self.root / 'state' / (project + '-prepared.json')).read_text())
            self.models[project] = json.loads(Path(prepared['config']).read_text())

    def locate(self, container):
        """Production container -> (exercise project, service) via Compose labels."""
        source = self.deployment.get(container)
        if source is None:
            raise ValueError('container absent from generation deployment: ' + container)
        labels = source['Config']['Labels']
        directory = labels['com.docker.compose.project.working_dir']
        service = labels['com.docker.compose.service']
        for project, entry in self.config['catalogue'].items():
            if WORKSPACE + '/' + entry['directory'] == directory and service in self.models[project]['services']:
                return project, service
        same = [p for p, e in self.config['catalogue'].items() if WORKSPACE + '/' + e['directory'] == directory]
        if any(service in self.config['catalogue'][p].get('excluded_services', {}) for p in same):
            return None
        if directory in self.excluded_directories:
            return None
        raise ValueError('no exercise service for ' + container)

    def volume_for(self, project, service, destination):
        model = self.models[project]
        for volume in model['services'][service].get('volumes', []):
            if volume['target'] == destination:
                if volume['type'] != 'volume':
                    raise ValueError('expected named volume at ' + destination)
                return model['volumes'][volume['source']]['name']
        raise ValueError('destination not mounted in exercise model: ' + project + '/' + service + ' ' + destination)

    def image_for(self, project, service):
        return self.models[project]['services'][service]['image']

    def fresh_volume(self, name, journal_key, journal):
        if journal_key in journal.done:
            return None
        existing = run(['docker', 'volume', 'ls', '-q', '--filter', 'name=^' + name + '$'])
        if existing:
            mountpoint = Path(json.loads(run(['docker', 'volume', 'inspect', name]))[0]['Mountpoint'])
            if any(mountpoint.iterdir()):
                raise ValueError('unrecorded non-empty volume: ' + name)
        else:
            run(['docker', 'volume', 'create', '--label', LABEL, name])
        return Path(json.loads(run(['docker', 'volume', 'inspect', name]))[0]['Mountpoint'])


def trees(ex, journal):
    sys.path.insert(0, str(ex.root / 'bin/coherent'))
    import artifacts
    staging = private_dir(ex.root / 'state/restore-staging')
    restored = skipped = 0
    for source in ex.manifest['sources']:
        if source['kind'] != 'tree' or source['source']['kind'] != 'volume':
            continue
        owners = source['source']['owners']
        targets = set()
        for owner in owners:
            located = ex.locate(owner['container'])
            if located:
                targets.add(ex.volume_for(*located, owner['destination']))
        if not targets:
            skipped += 1
            continue
        if len(targets) != 1:
            raise ValueError('volume tree maps to several exercise volumes: ' + source['id'])
        name = targets.pop()
        key = 'tree:' + source['id']
        mountpoint = ex.fresh_volume(name, key, journal)
        if mountpoint is None:
            continue
        work = staging / source['id']
        if work.exists():
            shutil.rmtree(work)
        result = artifacts.restore_tree(str(ex.generation / source['path']), str(work))
        for entry in work.iterdir():
            target = mountpoint / entry.name
            if entry.is_dir() and not entry.is_symlink():
                shutil.copytree(entry, target, symlinks=True)
            else:
                shutil.copy2(entry, target, follow_symlinks=False)
        # copytree/copy2 keep modes; owners are restored from the recovered tree.
        for path in [mountpoint, *mountpoint.rglob('*')]:
            origin = work / path.relative_to(mountpoint)
            if origin.exists() or origin.is_symlink():
                stat = origin.lstat()
                os.lchown(path, stat.st_uid, stat.st_gid)
        shutil.rmtree(work)
        journal.record(key, {'volume': name, 'entries': len(result['entries'])})
        restored += 1
    return restored, skipped


def wait(check, seconds=180):
    end = time.monotonic() + seconds
    while True:
        try:
            return check()
        except Exception:
            if time.monotonic() > end:
                raise
            time.sleep(2)


def postgres(ex, journal):
    restored = 0
    for source in ex.manifest['sources']:
        if source['kind'] != 'postgres':
            continue
        key = 'postgres:' + source['source']['container']
        project, service = ex.locate(source['source']['container'])
        name = ex.volume_for(project, service, PGDATA)
        if ex.fresh_volume(name, key, journal) is None:
            continue
        path = ex.generation / source['path']
        meta = json.loads((path / 'meta.json').read_text())
        user = 's237_bootstrap_' + uuid.uuid4().hex[:12]
        env = ex.root / 'private' / ('restore-' + uuid.uuid4().hex + '.env')
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write('POSTGRES_USER=' + user + '\nPOSTGRES_DB=' + user + '\nPOSTGRES_PASSWORD=' + secrets.token_urlsafe(32) + '\n')
        container = 's237-restore-pg-' + uuid.uuid4().hex[:12]
        try:
            # The exercise image itself initialises the cluster (Patroni image included:
            # its PostgreSQL entrypoint creates a standalone data directory Patroni adopts).
            run(['docker', 'run', '-d', '--name', container, '--label', LABEL, '--network', 'none', '--env-file', str(env),
                 '--mount', 'type=volume,src=' + name + ',dst=' + PGDATA, '--entrypoint', 'docker-entrypoint.sh',
                 ex.image_for(project, service), 'postgres'], ex.diagnostics, 'pg-start')
            wait(lambda: run(['docker', 'exec', container, 'pg_isready', '-h', '127.0.0.1', '-U', user, '-d', user]))
            wait(lambda: run(['docker', 'exec', container, 'psql', '-X', '-h', '127.0.0.1', '-U', user, '-d', user, '-c', 'select 1']), 60)
            with (path / 'roles.sql').open('rb') as roles:
                run(['docker', 'exec', '-i', container, 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-h', '127.0.0.1', '-U', user, '-d', user], ex.diagnostics, 'pg-roles', stdin=roles)
            for database in meta['databases']:
                with (path / database['file']).open('rb') as dump:
                    run(['docker', 'exec', '-i', container, 'pg_restore', '--exit-on-error', '--clean', '--if-exists', '--create', '-h', '127.0.0.1', '-U', user, '--dbname', user], ex.diagnostics, 'pg-restore', stdin=dump)
                def query(sql):
                    return run(['docker', 'exec', container, 'psql', '-X', '-h', '127.0.0.1', '-U', user, '-d', database['name'], '-At', '-c', sql])
                extensions = json.loads(query("SELECT coalesce(json_agg(json_build_object('name',extname,'version',extversion) ORDER BY extname),'[]') FROM pg_extension"))
                if extensions != database['extensions']:
                    raise ValueError('restored PostgreSQL extensions differ')
                tables = json.loads(query("SELECT coalesce(json_agg(json_build_array(schemaname,tablename) ORDER BY schemaname,tablename),'[]') FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"))
                counts = {}
                for pair in tables:
                    quoted = '.'.join('"' + x.replace('"', '""') + '"' for x in pair)
                    counts[quoted] = int(query('SELECT count(*) FROM ' + quoted))
                if counts != database['table_counts']:
                    raise ValueError('restored PostgreSQL rows differ')
            run(['docker', 'stop', '-t', '60', container], ex.diagnostics, 'pg-stop')
        finally:
            subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
            env.unlink(missing_ok=True)
        journal.record(key, {'volume': name, 'databases': len(meta['databases']), 'bootstrap_role': user})
        restored += 1
    return restored


QVERIFY = r'''
import urllib.request,urllib.parse,json,math
meta=json.load(open('/snapshots/meta.json'))
def api(path,body=None):
 req=urllib.request.Request('http://127.0.0.1:6333'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)['result']
assert sorted(c['name'] for c in api('/collections')['collections'])==sorted(c['name'] for c in meta['collections'])
a=meta['aliases'].get('aliases',[])
if a:api('/collections/aliases',{'actions':[{'create_alias':x} for x in a]})
assert sorted(api('/aliases')['aliases'],key=lambda a:a['alias_name'])==sorted(meta['aliases']['aliases'],key=lambda a:a['alias_name'])
for c in meta['collections']:
 p='/collections/'+urllib.parse.quote(c['name'],safe='');info=api(p)
 assert info['points_count']==c['info']['points_count']
 points=c['sample']['points']
 if not points:continue
 point=points[0];restored=api(p+'/points',{'ids':[point['id']],'with_vector':True,'with_payload':True})[0]
 assert all(restored[k]==point[k] for k in ('id','vector','payload'))
 vector=point['vector'];vectors=[{'name':k,'vector':v} for k,v in vector.items()] if isinstance(vector,dict) else [vector]
 for v in vectors:
  hits=api(p+'/points/search',{'vector':v,'limit':10})
  assert any(h['id']==point['id'] and math.isfinite(h['score']) for h in hits)
print(json.dumps({'collections':len(meta['collections'])}))
'''


def qdrant(ex, journal):
    source = next(s for s in ex.manifest['sources'] if s['kind'] == 'qdrant')
    key = 'qdrant:' + source['source']['container']
    project, service = ex.locate(source['source']['container'])
    name = ex.volume_for(project, service, '/qdrant/storage')
    if ex.fresh_volume(name, key, journal) is None:
        return 0
    path = ex.generation / source['path']
    meta = json.loads((path / 'meta.json').read_text())
    container = 's237-restore-qdrant-' + uuid.uuid4().hex[:12]
    args = []
    for collection in meta['collections']:
        args += ['--snapshot', '/snapshots/' + collection['file'] + ':' + collection['name']]
    try:
        run(['docker', 'run', '-d', '--name', container, '--label', LABEL, '--network', 'none',
             '--mount', 'type=volume,src=' + name + ',dst=/qdrant/storage',
             '--mount', 'type=bind,src=' + str(path) + ',dst=/snapshots,readonly',
             '--entrypoint', '/qdrant/qdrant', ex.image_for(project, service), *args], ex.diagnostics, 'qdrant-start')
        probe = ex.config['probe_image']
        result = wait(lambda: run(['docker', 'run', '--rm', '--network', 'container:' + container, '--mount', 'type=bind,src=' + str(path) + ',dst=/snapshots,readonly', probe, 'python3', '-c', QVERIFY]))
        run(['docker', 'stop', '-t', '30', container], ex.diagnostics, 'qdrant-stop')
    finally:
        subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
    journal.record(key, {'volume': name, **json.loads(result)})
    return 1


def neutralize(ex, journal):
    """Reviewed exercise neutralisations on restored SQLite copies (never production)."""
    import sqlite3
    done = 0
    for item in ex.config.get('neutralize', []):
        if not item.get('reason'):
            raise ValueError('neutralisation reason required')
        key = 'neutralize:' + item['name']
        name = ex.volume_for(item['project'], item['service'], item['destination'])
        mountpoint = Path(json.loads(run(['docker', 'volume', 'inspect', name]))[0]['Mountpoint'])
        database = mountpoint / item['sqlite']
        if not database.is_file() or database.is_symlink():
            raise ValueError('neutralisation database missing: ' + item['name'])
        connection = sqlite3.connect(database)
        try:
            if key not in journal.done:
                with connection:
                    connection.execute(item['statement'])
            remaining = connection.execute(item['verify']).fetchone()[0]
        finally:
            connection.close()
        if remaining != item['expect']:
            raise ValueError('neutralisation not effective: ' + item['name'])
        if key not in journal.done:
            journal.record(key, {'volume': name, 'verified': remaining})
            done += 1
    return done


def engines(config):
    ex = Exercise(config)
    journal = Journal(ex.root)
    trees_restored, trees_skipped = trees(ex, journal)
    neutralized = neutralize(ex, journal)
    pg = postgres(ex, journal)
    qd = qdrant(ex, journal)
    return {'changed': trees_restored + neutralized + pg + qd, 'trees': trees_restored, 'trees_outside_perimeter': trees_skipped,
            'neutralized': neutralized, 'postgres': pg, 'qdrant': qd}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['files', 'engines'])
    args = parser.parse_args()
    config = json.load(sys.stdin)
    if config.get('root') != str(ROOT):
        raise SystemExit('dedicated root required')
    try:
        print(json.dumps(files(config) if args.phase == 'files' else engines(config)))
    except Exception as error:
        print('Restore refused or failed (' + type(error).__name__ + '): ' + str(error)[:400], file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
