import json
import os
import sqlite3
from pathlib import Path

import pytest

try:
    from artifacts import export_tree, verify_tree, restore_tree
except ImportError:
    export_tree = verify_tree = restore_tree = None


def test_live_wal_roundtrip(tmp_path):
    assert callable(export_tree), 'artifact API missing'
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'empty').mkdir(mode=0o750)
    (source / 'plain.db').write_text('not sqlite')
    (source / 'secret').write_text('private')
    (source / 'secret').chmod(0o640)
    (source / 'link').symlink_to('secret')
    db = sqlite3.connect(source / 'database.weird')
    db.execute('pragma journal_mode=WAL')
    db.execute('create table items(value)')
    db.execute('insert into items values (42)')
    db.commit()
    assert (source / 'database.weird-wal').exists()
    target = tmp_path / 'artifact'
    export_tree(source, target)
    verify_tree(target)
    assert not (target / 'data/database.weird-wal').exists()
    assert target.stat().st_mode & 0o777 == 0o700
    assert (target / 'data/secret').stat().st_mode & 0o777 == 0o600
    restore_tree(target, tmp_path / 'restored')
    with sqlite3.connect(tmp_path / 'restored/database.weird') as restored:
        assert restored.execute('select value from items').fetchall() == [(42,)]
    assert (tmp_path / 'restored/secret').stat().st_mode & 0o777 == 0o640
    assert (tmp_path / 'restored/empty').stat().st_mode & 0o777 == 0o750
    assert (tmp_path / 'restored/link').readlink() == Path('secret')
    db.close()


@pytest.mark.parametrize('kind', ['corruption', 'extra', 'traversal', 'parent_link', 'fingerprint'])
def test_tampered_artifact_rejected(tmp_path, kind):
    assert callable(export_tree), 'artifact API missing'
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'x').write_text('hello')
    with sqlite3.connect(source / 'db') as db:
        db.execute('create table items(x)')
    target = tmp_path / 'artifact'
    export_tree(source, target)
    manifest = json.loads((target / 'manifest.json').read_text())
    if kind == 'corruption':
        (target / 'data/x').write_text('changed')
    elif kind == 'extra':
        (target / 'data/extra').write_text('extra')
    elif kind == 'parent_link':
        (target / 'data/x').unlink()
        (target / 'data/x').symlink_to(source / 'x')
    elif kind == 'fingerprint':
        next(e for e in manifest['entries'] if e['path'] == 'db')['sqlite']['tables']['items'] = 9
    else:
        manifest['entries'][0]['path'] = '../escape'
    (target / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises((ValueError, OSError)):
        restore_tree(target, tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


@pytest.mark.parametrize('link', ['/etc/passwd', '../outside', 'missing'])
def test_unsafe_source_symlinks_rejected(tmp_path, link):
    assert callable(export_tree), 'artifact API missing'
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'link').symlink_to(link)
    with pytest.raises((ValueError, OSError)):
        export_tree(source, tmp_path / 'artifact')


def test_overlap_special_and_existing_destination(tmp_path):
    assert callable(export_tree), 'artifact API missing'
    source = tmp_path / 'source'
    source.mkdir()
    with pytest.raises(ValueError):
        export_tree(source, source / 'artifact')
    os.mkfifo(source / 'fifo')
    with pytest.raises(ValueError):
        export_tree(source, tmp_path / 'artifact')
    export_tree(source, tmp_path / 'artifact', exclude=['fifo'])
    with pytest.raises(FileExistsError):
        restore_tree(tmp_path / 'artifact', source)


def test_invalid_root_metadata_rejected_before_restore(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    target = tmp_path / 'artifact'
    export_tree(source, target)
    manifest = json.loads((target / 'manifest.json').read_text())
    manifest['root']['mode'] = -1
    (target / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify_tree(target)


def test_parent_symlink_destination_rejected(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    export_tree(source, tmp_path / 'artifact')
    (tmp_path / 'alias').symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError):
        restore_tree(tmp_path / 'artifact', tmp_path / 'alias/new')
    assert not (source / 'new').exists()


def test_mutating_ordinary_file_fails_and_cleans_up(tmp_path, monkeypatch):
    import artifacts
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'x').write_bytes(b'original')
    original = artifacts.shutil.copyfileobj
    def mutate(src, dst):
        original(src, dst)
        (source / 'x').write_bytes(b'changed')
    monkeypatch.setattr(artifacts.shutil, 'copyfileobj', mutate)
    with pytest.raises(ValueError, match='Source changed'):
        export_tree(source, tmp_path / 'artifact')
    assert not (tmp_path / 'artifact').exists()


def test_normalized_overlap_rejected_before_creating_target(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (tmp_path / 'other').mkdir()
    with pytest.raises(ValueError, match='overlap'):
        export_tree(source, tmp_path / 'other/../source/output')
    assert not (source / 'output').exists()


def test_excluded_subtree_not_visited(tmp_path, monkeypatch):
    source=tmp_path/'source'; source.mkdir(); blocked=source/'excluded'; blocked.mkdir()
    (blocked/'secret').write_text('private'); (source/'keep').write_text('yes')
    original=Path.iterdir
    def guarded(path):
        if path == blocked: raise PermissionError('must not visit excluded directory')
        return original(path)
    monkeypatch.setattr(Path,'iterdir',guarded)
    export_tree(source,tmp_path/'artifact',['excluded'])
    assert (tmp_path/'artifact/data/keep').exists()

@pytest.mark.parametrize('frozen', [False, True])
def test_frozen_readonly_wal_without_shm_preserves_committed_rows(tmp_path, monkeypatch, frozen):
    import shutil, artifacts
    live=tmp_path/'live';live.mkdir();source=tmp_path/'frozen';source.mkdir()
    db=sqlite3.connect(live/'test.db');db.execute('pragma journal_mode=WAL');db.execute('create table records(value)');db.execute('insert into records values (99)');db.commit()
    for name in ('test.db','test.db-wal'):shutil.copyfile(live/name,source/name)
    assert not (source/'test.db-shm').exists()
    original={p.name:p.read_bytes() for p in source.iterdir()};connect=sqlite3.connect
    def readonly_access(database,*args,**kwargs):
        if str(database).startswith((source/'test.db').as_uri()):
            e=sqlite3.OperationalError('unable to open database file');e.sqlite_errorcode=sqlite3.SQLITE_CANTOPEN;raise e
        return connect(database,*args,**kwargs)
    monkeypatch.setattr(artifacts.sqlite3,'connect',readonly_access)
    try:
        if not frozen:
            with pytest.raises(sqlite3.OperationalError):export_tree(source,tmp_path/'artifact',frozen=False)
            assert not (tmp_path/'artifact').exists()
        else:
            export_tree(source,tmp_path/'artifact',frozen=True)
            with connect(tmp_path/'artifact/data/test.db') as result:assert result.execute('select value from records').fetchall()==[(99,)]
            verify_tree(tmp_path/'artifact')
        assert {p.name:p.read_bytes() for p in source.iterdir()}==original
    finally:db.close()

def test_frozen_wal_mode_checkpointed_without_wal_or_shm(tmp_path, monkeypatch):
    import shutil, artifacts
    live=tmp_path/'live';live.mkdir();source=tmp_path/'frozen';source.mkdir()
    db=sqlite3.connect(live/'geo.db');db.execute('pragma journal_mode=WAL');db.execute('create table records(value)');db.execute('insert into records values (107)');db.commit();db.execute('pragma wal_checkpoint(TRUNCATE)')
    shutil.copyfile(live/'geo.db',source/'geo.db')
    assert (source/'geo.db').read_bytes()[18:20]==b'\x02\x02'
    original=(source/'geo.db').read_bytes();connect=sqlite3.connect
    def readonly_access(database,*args,**kwargs):
        if str(database).startswith((source/'geo.db').as_uri()):
            e=sqlite3.OperationalError('unable to open database file');e.sqlite_errorcode=sqlite3.SQLITE_CANTOPEN;raise e
        return connect(database,*args,**kwargs)
    monkeypatch.setattr(artifacts.sqlite3,'connect',readonly_access)
    try:
        export_tree(source,tmp_path/'artifact',frozen=True)
        with connect(tmp_path/'artifact/data/geo.db') as result:assert result.execute('select value from records').fetchall()==[(107,)]
        assert list(p.name for p in source.iterdir())==['geo.db'];assert (source/'geo.db').read_bytes()==original
    finally:db.close()
