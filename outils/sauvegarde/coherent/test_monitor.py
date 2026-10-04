import importlib.util
import json
from pathlib import Path
import pytest

MODULE = Path(__file__).with_name('monitor.py')


def load():
    assert MODULE.exists(), 'backup monitoring is missing'
    spec = importlib.util.spec_from_file_location('s236_monitor', MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_export_and_transfer_are_separate_and_no_private_fields(tmp_path):
    m = load()
    root = tmp_path / 'private'; root.mkdir()
    (root / 'status.json').write_text(json.dumps({'last_attempt_success':True,'last_export_timestamp':900,'last_transfer_timestamp':0,'failed_sources_count':0,'secret':'must-never-appear'}))
    out = tmp_path / 'public'
    m.publish(root, out, now=1000)
    content = (out / 'workplace-backup.prom').read_text()
    assert 'workplace_backup_export_success 1' in content
    assert 'workplace_backup_rpo_ok 0' in content
    assert 'workplace_backup_last_transfer_timestamp_seconds 0' in content
    assert 'secret' not in content
    assert 'must-never-appear' not in content


def test_missing_status_and_expired_transfer_fail_rpo(tmp_path):
    m=load(); root=tmp_path/'private'; root.mkdir(); out=tmp_path/'public'
    m.publish(root,out,now=200000)
    assert 'workplace_backup_export_success 0' in (out/'workplace-backup.prom').read_text()
    (root/'status.json').write_text(json.dumps({'last_attempt_success':False,'last_export_timestamp':100,'last_transfer_timestamp':100,'failed_sources_count':1}))
    m.publish(root,out,now=200000)
    text=(out/'workplace-backup.prom').read_text()
    assert 'workplace_backup_failed_sources 1' in text
    assert 'workplace_backup_rpo_ok 0' in text


def test_recent_transfer_passes_and_symlink_output_is_refused(tmp_path):
    m=load(); root=tmp_path/'private'; root.mkdir(); out=tmp_path/'public'
    (root/'status.json').write_text(json.dumps({'last_attempt_success':True,'last_export_timestamp':990,'last_transfer_timestamp':995,'last_transferred_source_timestamp':990,'failed_sources_count':0}))
    m.publish(root,out,now=1000)
    assert 'workplace_backup_rpo_ok 1' in (out/'workplace-backup.prom').read_text()
    alias=tmp_path/'alias'; alias.symlink_to(out,target_is_directory=True)
    with pytest.raises(ValueError): m.publish(root,alias,now=1000)


def test_malformed_state_does_not_break_collection(tmp_path):
    m=load(); root=tmp_path/'private'; root.mkdir(); out=tmp_path/'public'
    (root/'status.json').write_text('[1,2]')
    m.publish(root,out,now=1000)
    text=(out/'workplace-backup.prom').read_text()
    assert 'workplace_backup_failed_sources 1' in text
    assert 'workplace_backup_transfer_success 0' in text


def test_public_collector_directory_survives_private_service_umask(tmp_path):
    import os, stat
    m=load(); root=tmp_path/'private'; root.mkdir(); out=tmp_path/'public'
    old=os.umask(0o077)
    try:m.publish(root,out,now=1000)
    finally:os.umask(old)
    assert stat.S_IMODE(out.stat().st_mode)==0o755
    assert stat.S_IMODE((out/'workplace-backup.prom').stat().st_mode)==0o644

def test_recent_ack_cannot_refresh_old_source_point(tmp_path):
    m=load();root=tmp_path/'private';root.mkdir()
    (root/'status.json').write_text(json.dumps({'last_attempt_success':True,'last_export_timestamp':199990,'last_transfer_timestamp':199995,'last_transferred_source_timestamp':100,'last_transfer_success':True}))
    values=m.publish(root,tmp_path/'public',now=200000)
    assert values['last_transfer_timestamp_seconds']==199995
    assert values['last_transferred_source_timestamp_seconds']==100
    assert values['rpo_ok']==0


def test_verified_fresh_source_point_passes(tmp_path):
    m=load();root=tmp_path/'private';root.mkdir()
    (root/'status.json').write_text(json.dumps({'last_transfer_timestamp':995,'last_transferred_source_timestamp':990,'last_transfer_success':True}))
    assert m.publish(root,tmp_path/'public',now=1000)['rpo_ok']==1


def test_legacy_ack_is_preserved_but_unproven_source_fails_closed(tmp_path):
    m=load();root=tmp_path/'private';root.mkdir()
    (root/'status.json').write_text(json.dumps({'last_export_timestamp':990,'last_transfer_timestamp':995}))
    values=m.publish(root,tmp_path/'public',now=1000)
    assert values['last_transfer_timestamp_seconds']==995
    assert values['last_transferred_source_timestamp_seconds']==0
    assert values['rpo_ok']==0
