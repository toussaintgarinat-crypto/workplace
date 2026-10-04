"""Host timer entrypoint: prevalidate every destination before exporting."""
import argparse,json,sys,os,signal
from pathlib import Path
import transport
from backup import backup,load_inventory,Docker,BackupError

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True,type=Path);a=p.parse_args()
 previous={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
 def interrupted(signum,frame):
  for sig in previous:signal.signal(sig,signal.SIG_IGN)
  raise BackupError('Backup job interrupted')
 for sig in previous:signal.signal(sig,interrupted)
 try:
  config=json.loads(a.config.read_text());root=Path(config['root']);profiles=[json.loads(Path(p).read_text()) for p in config['profiles']]
  if not profiles:raise BackupError('No destinations configured')
  ids=[p['id'] for p in profiles]
  if len(set(ids))!=len(ids):raise BackupError('Duplicate profile identifiers')
  required=[p['id'] for p in profiles if p.get('required',True)]
  if not required:raise BackupError('At least one required target must be configured')
  usable=[];unavailable=[]
  for profile in profiles:
   try:
    transport.validate_profile(profile,root);transport.credentials(profile['credentials']);profile['required_profiles']=required;usable.append(profile)
   except Exception:
    if profile.get('required',True):raise
    unavailable.append(profile['id'])
  generation=backup(load_inventory(Path(config['inventory'])),root,Docker())
  required_failed=[];optional_failed=[]
  for profile in usable:
   try:transport.transfer(profile,generation,root)
   except Exception:
    (required_failed if profile.get('required',True) else optional_failed).append(profile['id'])
  with transport.lock(root):
   path=root/'status.json';status=json.loads(path.read_text()) if path.exists() else {}
   status['last_transfer_success']=not required_failed
   status['optional_profiles_unavailable']=unavailable;status['optional_profiles_failed']=optional_failed
   transport.atomic_json(path,status)
  print(json.dumps({'profiles':len(profiles),'required_failed':len(required_failed),'optional_unavailable':len(unavailable),'optional_failed':len(optional_failed)}));return int(bool(required_failed))
 except Exception:
  if 'root' in locals():transport.record_failure(root)
  print('Backup job failed; inspect private state');return 1
 finally:
  if 'root' in locals() and 'required' in locals():
   try:
    with transport.lock(root):
     journal=root/'transfers.json';acks=json.loads(journal.read_text()) if journal.exists() else {}
     path=root/'status.json';status=json.loads(path.read_text()) if path.exists() else {}
     status.update(transport.aggregate_acknowledgments(acks,required));transport.atomic_json(path,status)
   except Exception:print('Backup source point status refresh failed')
  for sig,handler in previous.items():signal.signal(sig,handler)
  output=os.environ.get('SAUVEGARDE_METRICS_DIR')
  if output and 'root' in locals():
   try:
    from monitor import publish
    publish(root,Path(output))
   except Exception:print('Backup metrics publication failed')
if __name__=='__main__':raise SystemExit(main())
