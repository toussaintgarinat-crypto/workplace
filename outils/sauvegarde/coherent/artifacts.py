"""Private directory artifacts. export_tree(source, target, exclude=None),
verify_tree(target), restore_tree(target, new_destination) return the manifest.
Exclusions are exact relative paths (directories exclude their descendants).
CLI: export SOURCE TARGET [--exclude PATH], verify TARGET, restore TARGET NEW_DEST.
SQLite snapshots are engine-consistent; producers must be paused by the caller.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import time
import tempfile


MAGIC = b'SQLite format 3\x00'


def _relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Invalid relative path')
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('Unsafe path: ' + value)
    return p


def _stamp(p):
    s = p.lstat()
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _hash(p):
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('Not an ordinary file')
        h = hashlib.sha256()
        size = 0
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
            size += len(block)
    return {'sha256': h.hexdigest(), 'size': size}


def _sqlite(p):
    with closing(sqlite3.connect(p.as_uri() + '?mode=ro', uri=True, timeout=30)) as db:
        if db.execute('pragma integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity failure')
        tables = {}
        for (name,) in db.execute("select name from sqlite_master where type='table' order by name"):
            quoted = '"' + name.replace('"', '""') + '"'
            tables[name] = db.execute('select count(*) from ' + quoted).fetchone()[0]
        schema = db.execute('select type,name,tbl_name,sql from sqlite_master order by type,name').fetchall()
        return {'tables': tables, 'schema_sha256': hashlib.sha256(json.dumps(schema).encode()).hexdigest()}


def _entries(root, include=lambda p: True):
    result = []
    def walk(folder):
        for p in sorted(folder.iterdir()):
            if not include(p):
                continue
            s = p.lstat()
            kind = 'directory' if stat.S_ISDIR(s.st_mode) else 'file' if stat.S_ISREG(s.st_mode) else 'symlink' if stat.S_ISLNK(s.st_mode) else 'special'
            result.append((p, kind, s))
            if kind == 'directory':
                walk(p)
    walk(root)
    return result


def _link(root, p, value):
    if Path(value).is_absolute():
        raise ValueError('Absolute symlink')
    resolved = (p.parent / value).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError('Escaping symlink')


def _parents_plain(p):
    for parent in (p, *p.parents):
        if parent.is_symlink():
            raise ValueError('Symlink parent')


def _backup_sqlite(source, destination, progress, frozen):
    def backup_from(path):
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=30)) as db:
            with closing(sqlite3.connect(destination)) as dest:
                db.backup(dest, pages=256, progress=progress)
                dest.execute('pragma journal_mode=DELETE')
    try:
        backup_from(source)
    except sqlite3.OperationalError as error:
        code=getattr(error,'sqlite_errorcode',0) & 255
        wal=Path(str(source)+'-wal')
        if not frozen or code not in (sqlite3.SQLITE_CANTOPEN,sqlite3.SQLITE_READONLY):
            raise
        with os.fdopen(os.open(source,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
            header=stream.read(20)
        if not wal.exists() and header[18:20]!=b'\x02\x02':
            raise
        # Producers must already be stopped. A writable mirror allows SQLite to
        # rebuild SHM and replay all committed WAL pages through its Backup API.
        inputs=[source]+([wal] if wal.exists() else [])
        stamps={p:_stamp(p) for p in inputs}
        if any(not stat.S_ISREG(p.lstat().st_mode) for p in inputs):
            raise ValueError('Unsafe frozen SQLite source')
        with tempfile.TemporaryDirectory(prefix='.sqlite-',dir=destination.parent) as temporary:
            mirror=Path(temporary)/source.name
            for p in inputs:
                with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW),'rb') as src:
                    out=Path(temporary)/p.name
                    with os.fdopen(os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as dst:
                        shutil.copyfileobj(src,dst)
            if any(_stamp(p)!=stamps[p] for p in inputs):
                raise ValueError('Frozen SQLite source changed while copying')
            backup_from(mirror)
            if any(_stamp(p)!=stamps[p] for p in inputs):
                raise ValueError('Frozen SQLite source changed while backing up')


def export_tree(source: Path, target: Path, exclude: list[str] | None = None, *, frozen=False) -> dict:
    source, target = Path(source).absolute(), Path(target).absolute()
    _parents_plain(source)
    _parents_plain(target)
    source = source.resolve(strict=True)
    target = target.resolve(strict=False)
    if not source.is_dir():
        raise ValueError('Source must be a directory')
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('Source/output overlap')
    excluded = [_relative(x) for x in (exclude or [])]
    def included(p):
        rel = PurePosixPath(p.relative_to(source).as_posix())
        return not any(rel == e or e in rel.parents for e in excluded)
    items = [(p, k, s) for p, k, s in _entries(source, included) if included(p)]
    initial = {p: _stamp(p) for p, _, _ in items}
    databases = set()
    for p, kind, _ in items:
        if kind == 'file':
            with os.fdopen(os.open(p, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as f:
                if f.read(16) == MAGIC:
                    databases.add(p)
    companions = {Path(str(p) + suffix) for p in databases for suffix in ('-wal', '-shm', '-journal')}
    target.mkdir(mode=0o700)
    target.chmod(0o700)
    try:
        data = target / 'data'
        data.mkdir(mode=0o700)
        root = source.stat()
        manifest = {'version': 1, 'root': {'mode': stat.S_IMODE(root.st_mode), 'uid': root.st_uid, 'gid': root.st_gid}, 'entries': []}
        for p, kind, s in items:
            if p in companions:
                continue
            rel = p.relative_to(source).as_posix()
            out = data / rel
            entry = {'path': rel, 'type': kind, 'mode': stat.S_IMODE(s.st_mode), 'uid': s.st_uid, 'gid': s.st_gid}
            if kind == 'directory':
                out.mkdir(mode=0o700)
            elif kind == 'symlink':
                value = os.readlink(p)
                _link(source, p, value)
                out.symlink_to(value)
                entry['target'] = value
            elif kind == 'file':
                fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
                if p in databases:
                    deadline = time.monotonic() + 60
                    def progress(status, remaining, total):
                        if time.monotonic() > deadline:
                            raise TimeoutError('SQLite backup timeout')
                    _backup_sqlite(p, out, progress, frozen)
                    entry['sqlite'] = _sqlite(out)
                else:
                    with os.fdopen(os.open(p, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as src, out.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
                    if _stamp(p) != initial[p]:
                        raise ValueError('Source changed: ' + rel)
                entry.update(_hash(out))
            else:
                raise ValueError('Special source file: ' + rel)
            manifest['entries'].append(entry)
        # SQLite/WAL may change during the backup; ordinary files/directories must not.
        for p, kind, _ in items:
            if p not in databases and p not in companions and _stamp(p) != initial[p]:
                raise ValueError('Source changed: ' + str(p.relative_to(source)))
        if {p for p, _, _ in _entries(source, included) if included(p)} != set(initial):
            raise ValueError('Source file set changed')
        fd = os.open(target / 'manifest.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(manifest, f, sort_keys=True)
        verify_tree(target)
        return manifest
    except BaseException:
        shutil.rmtree(target)
        raise


def verify_tree(target: Path) -> dict:
    target = Path(target).absolute()
    _parents_plain(target)
    for p in (target / 'manifest.json', target / 'data'):
        if p.is_symlink():
            raise ValueError('Symlink artifact structure')
    with (target / 'manifest.json').open() as f:
        manifest = json.load(f)
    if manifest.get('version') != 1:
        raise ValueError('Unsupported manifest')
    for field in ('mode', 'uid', 'gid'):
        value = manifest['root'][field]
        if type(value) is not int or value < 0 or (field == 'mode' and value > 0o7777):
            raise ValueError('Invalid root metadata')
    expected = {}
    for e in manifest['entries']:
        rel = str(_relative(e['path']))
        if rel in expected or e['type'] not in ('file', 'directory', 'symlink'):
            raise ValueError('Duplicate or invalid entry')
        for field in ('mode', 'uid', 'gid'):
            if type(e[field]) is not int or e[field] < 0 or (field == 'mode' and e[field] > 0o7777):
                raise ValueError('Invalid metadata')
        expected[rel] = e
    actual = {p.relative_to(target / 'data').as_posix(): (p, k) for p, k, _ in _entries(target / 'data')}
    if set(actual) != set(expected):
        raise ValueError('Artifact inventory mismatch')
    for rel, e in expected.items():
        p, kind = actual[rel]
        if kind != e['type']:
            raise ValueError('Artifact type mismatch')
        for parent in PurePosixPath(rel).parents:
            if str(parent) != '.' and expected.get(str(parent), {}).get('type') != 'directory':
                raise ValueError('Invalid parent')
        if kind == 'symlink':
            if os.readlink(p) != e['target']:
                raise ValueError('Symlink mismatch')
            _link(target / 'data', p, e['target'])
        elif kind == 'file':
            fingerprint = _hash(p)
            if any(e.get(k) != v for k, v in fingerprint.items()):
                raise ValueError('Artifact hash mismatch: ' + rel)
            with p.open('rb') as f:
                is_db = f.read(16) == MAGIC
            if is_db != ('sqlite' in e) or (is_db and _sqlite(p) != e['sqlite']):
                raise ValueError('SQLite fingerprint mismatch')
    return manifest


def restore_tree(target: Path, destination: Path) -> dict:
    destination = Path(destination).absolute()
    _parents_plain(destination)
    if destination.exists():
        raise FileExistsError(destination)
    manifest = verify_tree(target)
    destination.mkdir(mode=0o700)
    try:
        entries = sorted(manifest['entries'], key=lambda e: (len(PurePosixPath(e['path']).parts), e['path']))
        for e in entries:
            out = destination / e['path']
            if e['type'] == 'directory':
                out.mkdir(mode=0o700)
            elif e['type'] == 'file':
                with os.fdopen(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as dst:
                    with os.fdopen(os.open(Path(target) / 'data' / e['path'], os.O_RDONLY | os.O_NOFOLLOW), 'rb') as src:
                        shutil.copyfileobj(src, dst)
                if _hash(out) != {k: e[k] for k in ('sha256', 'size')}:
                    raise ValueError('Artifact changed during restore')
            else:
                out.symlink_to(e['target'])
        for e in reversed(entries):
            out = destination / e['path']
            if os.geteuid() == 0:
                os.chown(out, e['uid'], e['gid'], follow_symlinks=False)
            if e['type'] != 'symlink':
                out.chmod(e['mode'])
        root = manifest['root']
        if os.geteuid() == 0:
            os.chown(destination, root['uid'], root['gid'])
        destination.chmod(root['mode'])
        return manifest
    except BaseException:
        # Restore directory access before removing restrictive original modes.
        destination.chmod(0o700)
        for folder, dirs, files in os.walk(destination):
            for name in dirs:
                p = Path(folder) / name
                if not p.is_symlink():
                    p.chmod(0o700)
        shutil.rmtree(destination)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    export.add_argument('source', type=Path)
    export.add_argument('target', type=Path)
    export.add_argument('--exclude', action='append', default=[])
    verify = sub.add_parser('verify')
    verify.add_argument('target', type=Path)
    restore = sub.add_parser('restore')
    restore.add_argument('target', type=Path)
    restore.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.command == 'export':
        result = export_tree(args.source, args.target, args.exclude)
    elif args.command == 'verify':
        result = verify_tree(args.target)
    else:
        result = restore_tree(args.target, args.destination)
    print(json.dumps({'status': 'ok', 'entries': len(result['entries'])}))


if __name__ == '__main__':
    main()
