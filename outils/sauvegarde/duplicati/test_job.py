import json,sys
from pathlib import Path
import job,transport

def setup_job(tmp_path,monkeypatch):
 root=tmp_path/'state';root.mkdir();paths=[]
 for name,required in [('nas',True),('usb',False)]:
  path=tmp_path/(name+'.json');path.write_text(json.dumps({'id':name,'required':required,'credentials':'unused'}));paths.append(str(path))
 config=tmp_path/'job.json';config.write_text(json.dumps({'root':str(root),'inventory':'unused','profiles':paths}))
 monkeypatch.setattr(sys,'argv',['job.py','--config',str(config)]);monkeypatch.delenv('SAUVEGARDE_METRICS_DIR',raising=False)
 monkeypatch.setattr(job,'load_inventory',lambda p:{});monkeypatch.setattr(transport,'credentials',lambda p:None)
 return root

def test_missing_optional_usb_does_not_block_required_nas(tmp_path,monkeypatch):
 root=setup_job(tmp_path,monkeypatch);exports=[];transfers=[]
 def validate(profile,root):
  if profile['id']=='usb':raise transport.BackupError('Disconnected')
 monkeypatch.setattr(transport,'validate_profile',validate)
 monkeypatch.setattr(job,'backup',lambda *args:exports.append(True) or root/'generation')
 monkeypatch.setattr(transport,'transfer',lambda p,*args:transfers.append(p['id']))
 assert job.main()==0
 assert exports==[True];assert transfers==['nas']
 assert json.loads((root/'status.json').read_text())['last_transfer_success'] is True

def test_required_target_failure_blocks_export(tmp_path,monkeypatch):
 root=setup_job(tmp_path,monkeypatch);exports=[]
 monkeypatch.setattr(transport,'validate_profile',lambda *args:(_ for _ in ()).throw(transport.BackupError('Unavailable')))
 monkeypatch.setattr(job,'backup',lambda *args:exports.append(True))
 assert job.main()==1;assert exports==[]
 assert json.loads((root/'status.json').read_text())['last_transfer_success'] is False

def test_optional_transfer_failure_does_not_override_required_success(tmp_path,monkeypatch):
 root=setup_job(tmp_path,monkeypatch)
 monkeypatch.setattr(transport,'validate_profile',lambda *args:None)
 monkeypatch.setattr(job,'backup',lambda *args:root/'generation')
 def transfer(profile,*args):
  if profile['id']=='usb':
   transport.record_failure(root);raise transport.BackupError('Transfer failed')
 monkeypatch.setattr(transport,'transfer',transfer)
 assert job.main()==0
 assert json.loads((root/'status.json').read_text())['last_transfer_success'] is True

def test_job_keeps_verified_source_point_after_export_replaces_status(tmp_path,monkeypatch):
 root=setup_job(tmp_path,monkeypatch)
 transport.atomic_json(root/'transfers.json',{'nas':{'generation':'prior','timestamp':900,'source_point_timestamp':800}})
 monkeypatch.setattr(transport,'validate_profile',lambda *args:None)
 def exporting(*args):
  transport.atomic_json(root/'status.json',{'last_attempt_success':True,'last_export_timestamp':990,'last_transfer_timestamp':900})
  return root/'generation'
 monkeypatch.setattr(job,'backup',exporting)
 monkeypatch.setattr(transport,'transfer',lambda *args:None)
 assert job.main()==0
 assert json.loads((root/'status.json').read_text())['last_transferred_source_timestamp']==800


def test_timer_sigterm_unwinds_backup_and_restores_signal_handler(tmp_path,monkeypatch):
 import signal
 root=setup_job(tmp_path,monkeypatch);cleaned=[];observed=[];previous=signal.getsignal(signal.SIGTERM)
 monkeypatch.setattr(transport,'validate_profile',lambda *args:None)
 def exporting(*args):
  try:
   handler=signal.getsignal(signal.SIGTERM);observed.append(callable(handler));handler(signal.SIGTERM,None)
  finally:cleaned.append(True)
 monkeypatch.setattr(job,'backup',exporting)
 assert job.main()==1
 assert cleaned==[True]
 assert observed==[True]
 assert signal.getsignal(signal.SIGTERM)==previous
