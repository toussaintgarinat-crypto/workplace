"""Encrypted Duplicati transport of immutable, verified coherent generations."""
import argparse,json,math,os,re,stat,subprocess,sys,time,uuid
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'coherent'))
from backup import BackupError,verify_generation,lock,atomic_json
IMAGE='duplicati/duplicati:2.4.0.0-stable@sha256:eb0c1298a1974048332745b393897ae3cc1c20258e4fc26a796f2b5d75eb6218'

def success_code(code):return code in (0,1)
def credentials(path):
 path=Path(path).absolute();s=path.lstat()
 if any(p.is_symlink() for p in (path,*path.parents)) or not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o600:raise BackupError('Credentials must be owned private regular file')
 if path.parent.stat().st_mode & 0o077:raise BackupError('Credential parent must be private')
 values={}
 for line in path.read_text().splitlines():
  if not line or line.startswith('#'):continue
  if '=' not in line:raise BackupError('Malformed credential environment')
  k,v=line.split('=',1)
  if k not in ('PASSPHRASE','AUTH_USERNAME','AUTH_PASSWORD') or k in values:raise BackupError('Unsupported credential key')
  values[k]=v
 if not values.get('PASSPHRASE','').strip():raise BackupError('AES passphrase required')
 return path

def validate_profile(profile,root=None):
 if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}',profile.get('id','')):raise BackupError('Invalid profile identity')
 if type(profile.get('keep_versions',30)) is not int or profile.get('keep_versions',30)<1:raise BackupError('Invalid retention')
 if profile.get('kind')=='remote':
  url=profile.get('destination','');p=urlsplit(url)
  if any(c.isspace() for c in url) or p.scheme not in ('ssh','s3','webdavs') or not p.hostname or p.username is not None or p.password is not None or p.fragment or p.query:raise BackupError('Remote destination must exclude credentials and query options')
  options=profile.get('options',{})
  allowed={'ssh':{'ssh-fingerprint'},'s3':{'s3-server-name','s3-location-constraint','s3-ext-forcepathstyle','s3-use-ssl'},'webdavs':set()}[p.scheme]
  if not isinstance(options,dict) or set(options)-allowed or any(not isinstance(v,str) or not v or '\n' in v or '\r' in v for v in options.values()):raise BackupError('Unsupported remote backend options')
  if p.scheme=='ssh' and not options.get('ssh-fingerprint'):raise BackupError('SSH host key fingerprint required')
  if 's3-use-ssl' in options and options['s3-use-ssl']!='true':raise BackupError('TLS must remain enabled')
  if 's3-ext-forcepathstyle' in options and options['s3-ext-forcepathstyle'] not in ('true','false'):raise BackupError('Invalid S3 option')
  return url
 if profile.get('kind')!='file':raise BackupError('Unknown target kind')
 path=Path(profile.get('mount_path','')).absolute()
 if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_dir() or not os.path.ismount(path):raise BackupError('Target must be an actual mounted filesystem')
 marker=path/'.workplace-s236-target'
 if marker.is_symlink() or not marker.is_file() or not profile.get('identity') or marker.read_text()!=profile['identity']:raise BackupError('Target mount identity mismatch')
 try:
  p=subprocess.run(['findmnt','--json','--target',str(path),'--output','TARGET,SOURCE,FSTYPE,UUID'],capture_output=True,check=True,timeout=15)
  fs=json.loads(p.stdout)['filesystems'][0]
 except Exception:raise BackupError('Cannot establish mounted filesystem identity') from None
 if Path(fs['target']).resolve()!=path.resolve():raise BackupError('Target is not mount root')
 if root is not None:
  staging=Path(root).absolute()
  while not staging.exists():
   if staging==staging.parent:raise BackupError('Cannot establish staging filesystem')
   staging=staging.parent
  if path.stat().st_dev==staging.stat().st_dev:raise BackupError('Target shares staging filesystem')
 if path.stat().st_dev==Path('/').stat().st_dev and fs['fstype'] not in ('nfs','nfs4','cifs','smb3'):raise BackupError('Target shares root filesystem')
 if profile.get('expected_source') and fs['source']!=profile['expected_source']:raise BackupError('Unexpected mount source')
 if profile.get('expected_uuid') and fs.get('uuid')!=profile['expected_uuid']:raise BackupError('Unexpected mount UUID')
 return 'file:///target/workplace/'+profile['id']

def verified_source_point(manifest):
 try:
  point=float(manifest['started']);ended=float(manifest['ended'])
  if not math.isfinite(point) or not math.isfinite(ended) or not 0<point<=ended<=time.time():raise ValueError()
  return point
 except (KeyError,TypeError,ValueError):raise BackupError('Generation lacks valid source point timestamp') from None


def aggregate_acknowledgments(acks,required,now=None):
 now=time.time() if now is None else now
 def timestamp(profile,key):
  try:
   value=float(acks.get(profile,{}).get(key,0))
   return value if math.isfinite(value) and 0<value<=now else 0
  except (TypeError,ValueError):return 0
 return {
  'last_transfer_timestamp':min((timestamp(p,'timestamp') for p in required),default=0),
  'last_transferred_source_timestamp':min((timestamp(p,'source_point_timestamp') if timestamp(p,'source_point_timestamp')<=timestamp(p,'timestamp') else 0 for p in required),default=0),
 }


class Runner:
 def run(self,args,log):
  fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as stream:
   try:return subprocess.run(['docker',*args],stdout=stream,stderr=subprocess.STDOUT,timeout=86400).returncode
   except (OSError,subprocess.TimeoutExpired):raise BackupError('Duplicati execution unavailable or timed out') from None

def _transfer(profile,generation,root,test_only=False,runner=None):
 root=Path(root).absolute();generation=Path(generation).absolute();runner=runner or Runner()
 # No state mutations before target and source validation.
 destination=validate_profile(profile,root);env=credentials(profile['credentials']);manifest=verify_generation(generation);source_point=verified_source_point(manifest)
 with lock(root):
  if (root/'recovery.json').exists():raise BackupError('Pending producer recovery')
  destination=validate_profile(profile,root)
  state=root/'duplicati'/profile['id'];state.mkdir(parents=True,mode=0o700,exist_ok=True);state.chmod(0o700)
  mounts=['--mount',f'type=bind,src={generation},dst=/source/generation,readonly','--mount',f'type=bind,src={state},dst=/data']
  if profile['kind']=='file':mounts+=['--mount',f"type=bind,src={Path(profile['mount_path']).absolute()},dst=/target"]
  base=['run','--rm','--user',str(os.getuid())+':'+str(os.getgid()),'--label','workplace.s236=true','--env-file',str(env),*mounts,'--entrypoint','/bin/sh',IMAGE,'-c']
  # Positional arguments preserve URI characters; shell receives only fixed code.
  guard=''
  if profile['kind']=='file':
   guard='test "$(cat /target/.workplace-s236-target)" = "$1" || exit 100; shift; '
  script=guard+'exec duplicati-cli "$@"'
  def invoke(command):
   log=state/('operation-'+uuid.uuid4().hex+'.log')
   identity=[profile['identity']] if profile['kind']=='file' else []
   args=[*base,script,'s236',*identity,*command,*['--'+k+'='+v for k,v in profile.get('options',{}).items()],'--encryption-module=aes','--disable-module=console-password-input','--dbpath=/data/backup.sqlite']
   if not success_code(runner.run(args,log)):raise BackupError('Duplicati operation failed; private log retained')
   validate_profile(profile,root)
  if not test_only:
   invoke(['backup',destination,'/source/generation','--abort-if-source-missing=true','--keep-versions='+str(profile.get('keep_versions',30))])
  invoke(['test',destination,'all','--full-remote-verification=true'])
  if test_only:return {'tested':True,'acknowledged':False}
  timestamp=time.time();journal=root/'transfers.json';acks=json.loads(journal.read_text()) if journal.exists() else {}
  acks[profile['id']]={'generation':generation.name,'timestamp':timestamp,'source_point_timestamp':source_point};atomic_json(journal,acks)
  required=profile.get('required_profiles',[profile['id']]);aggregate=aggregate_acknowledgments(acks,required,timestamp)
  status=root/'status.json';value=json.loads(status.read_text()) if status.exists() else {};value.update(aggregate);value['last_transfer_success']=True;atomic_json(status,value)
  metrics=root/'metrics.prom'
  old=metrics.read_text().splitlines() if metrics.exists() else []
  lines=[x for x in old if not x.startswith(('workplace_backup_last_transfer_timestamp_seconds ','workplace_backup_last_transferred_source_timestamp_seconds '))]+['workplace_backup_'+key+'_seconds '+str(value) for key,value in aggregate.items()]
  temp=root/'metrics.prom.tmp';temp.write_text('\n'.join(lines)+'\n');temp.chmod(0o644);os.replace(temp,metrics)
  return {'transferred':True,'acknowledged':True}

def record_failure(root):
 try:
  with lock(Path(root)):
   status=Path(root)/'status.json';value=json.loads(status.read_text()) if status.exists() else {}
   value['last_transfer_success']=False;atomic_json(status,value)
 except Exception:pass


def transfer(profile,generation,root,test_only=False,runner=None):
 try:return _transfer(profile,generation,root,test_only,runner)
 except Exception:
  record_failure(root)
  raise


def main():
 p=argparse.ArgumentParser();p.add_argument('--profile',required=True,type=Path);p.add_argument('--generation',required=True,type=Path);p.add_argument('--root',required=True,type=Path);p.add_argument('--test-only',action='store_true');a=p.parse_args()
 try:
  result=transfer(json.loads(a.profile.read_text()),a.generation,a.root,a.test_only);print(json.dumps(result));return 0
 except Exception:print('Encrypted transfer failed; consult private operation logs');return 1
if __name__=='__main__':raise SystemExit(main())
