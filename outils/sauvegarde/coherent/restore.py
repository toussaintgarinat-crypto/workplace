"""Restore sealed generations into exclusively new, isolated Docker resources."""
import argparse,json,os,re,secrets,shutil,signal,subprocess,time,uuid
from pathlib import Path
from backup import Docker,BackupError,verify_generation,atomic_json,check_root_boundaries,docker_source_paths

LABEL='workplace.s236=true'
SMOKE_SCRIPT=r'''
import urllib.request,urllib.error,urllib.parse,json
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
with opener.open('http://127.0.0.1:5000/health',timeout=15) as response:assert response.status==200
try:
 with opener.open('http://127.0.0.1:5000/dashboard',timeout=15) as response:status=response.status;assert status==200
except urllib.error.HTTPError as error:
 location=urllib.parse.urlsplit(error.headers.get('Location',''))
 assert error.code==303 and not location.scheme and not location.netloc and location.path=='/auth/login'
 status=error.code
print(json.dumps({'health':True,'dashboard_http':status,'dashboard_rendered':status==200,'authentication_required':status==303}))
'''
def validate_target(target,generation,inv,docker=None):
 target=Path(target).absolute()
 if target.exists() or any(p.is_symlink() for p in (target,*target.parents)): raise BackupError('Target must be new without symlink parents')
 sources=[generation]
 sources += [m.get('source',m.get('Source')) for c in inv.get('expected_mounts',[]) for m in c['mounts'] if m.get('type',m.get('Type'))=='volume' and m.get('source',m.get('Source'))]
 sources += [t['source'] for t in [inv.get('repository',{}),*inv.get('trees',[])] if t.get('kind')=='bind']
 sources=docker_source_paths(sources,docker,inv['helper_image']) if docker else [Path(p).resolve(strict=False) for p in sources]
 check_root_boundaries(target,sources,canonical_sources=True)
 return target

class Session:
 def __init__(self,docker,target,helper):
  self.d=docker;self.target=target;self.helper=helper;self.prefix='s236-'+uuid.uuid4().hex;self.resources=[];self.network=None
 def create(self,kind,suffix):
  name=self.prefix+'-'+suffix
  if not re.fullmatch(r's236-[a-f0-9]{32}-[a-z0-9-]+',name): raise BackupError('Invalid generated name')
  # Inspect before create: Docker volume create otherwise silently reuses existing volumes.
  listing=self.d.run([kind,'ls','--format','{{.Name}}']).decode().splitlines() if kind!='container' else self.d.run(['ps','-a','--format','{{.Names}}']).decode().splitlines()
  if name in listing: raise BackupError('Resource already exists')
  if kind=='network': self.d.run(['network','create','--internal','--label',LABEL,name]);self.network=name
  elif kind=='volume': self.d.run(['volume','create','--label',LABEL,name])
  if kind!='container':self.resources.append({'kind':kind,'name':name})
  return name
 def run(self,name,image,args=(),mounts=(),extra=()):
  result=self.d.run(['create','--name',name,'--label',LABEL,'--network',self.network,*extra,*sum((['--mount',m] for m in mounts),[]),image,*args])
  identity=result.decode().strip()
  if not re.fullmatch('[a-f0-9]{64}',identity):raise BackupError('Invalid created container identity')
  self.resources.append({'kind':'container','name':name,'id':identity});self.d.run(['start',identity]);return result
 def helper_run(self,script,mounts=(),network='none'):
  return self.d.run(['run','--rm','--user','0','--label',LABEL,'--network',network,*sum((['--mount',m] for m in mounts),[]),'--entrypoint','python3',self.helper,'-c',script])
 def wait(self,callback):
  end=time.monotonic()+120
  while True:
   try:return callback()
   except Exception:
    if time.monotonic()>end:raise BackupError('Restore readiness timed out') from None
    time.sleep(2)
 def stdin(self,args,path):
  with path.open('rb') as f:
   p=subprocess.run(['docker',*args],stdin=f,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=1800)
  if p.returncode:
   log=self.target/('native-error-'+uuid.uuid4().hex+'.log')
   fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'wb') as stream:stream.write(p.stderr)
   raise BackupError('Native restore failed; private diagnostic retained')
 def cleanup(self):
  failed=[]
  for r in reversed(self.resources):
   try:self.d.run(['rm','-f',r['id']] if r['kind']=='container' else [r['kind'],'rm',r['name']])
   except Exception:failed.append(r['name'])
  return failed

def postgres(s,path,spec,index):
 meta=json.loads((path/'meta.json').read_text());user='s236_bootstrap_'+uuid.uuid4().hex
 env=s.target/('postgres-'+str(index)+'.env');env.write_text('POSTGRES_USER='+user+'\nPOSTGRES_DB='+user+'\nPOSTGRES_PASSWORD='+secrets.token_urlsafe(40)+'\n');env.chmod(0o600)
 volume=s.create('volume','pgdata-'+str(index));name=s.create('container','pg-'+str(index))
 s.run(name,spec.get('restore_image',spec['image']),['postgres'],[f'type=volume,src={volume},dst=/var/lib/postgresql/data'],['--env-file',str(env),'--entrypoint','docker-entrypoint.sh'])
 s.wait(lambda:s.d.run(['exec',name,'pg_isready','-U',user,'-d',user]))
 s.stdin(['exec','-i',name,'psql','-X','-v','ON_ERROR_STOP=1','-U',user,'-d',user],path/'roles.sql')
 for db in meta['databases']:
  s.stdin(['exec','-i',name,'pg_restore','--exit-on-error','--clean','--if-exists','--create','-U',user,'--dbname',user],path/db['file'])
  def query(sql):return s.d.run(['exec',name,'psql','-X','-U',user,'-d',db['name'],'-At','-c',sql]).decode().strip()
  ext=json.loads(query("SELECT coalesce(json_agg(json_build_object('name',extname,'version',extversion) ORDER BY extname),'[]') FROM pg_extension"))
  if ext!=db['extensions']:raise BackupError('Restored PostgreSQL extensions differ')
  tables=json.loads(query("SELECT coalesce(json_agg(json_build_array(schemaname,tablename) ORDER BY schemaname,tablename),'[]') FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"))
  counts={}
  for pair in tables:
   quoted='.'.join('"'+x.replace('"','""')+'"' for x in pair);counts[quoted]=int(query('SELECT count(*) FROM '+quoted))
  if counts!=db['table_counts']:raise BackupError('Restored PostgreSQL rows differ')
 env.unlink();return {'container':name,'volume':volume,'source':spec['container'],'databases':[d['name'] for d in meta['databases']]}

QVERIFY=r'''
import urllib.request,urllib.parse,json,math
meta=json.load(open('/snapshots/meta.json'))
def api(path,body=None):
 req=urllib.request.Request('http://localhost:6333'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)['result']
assert sorted(c['name'] for c in api('/collections')['collections'])==sorted(c['name'] for c in meta['collections'])
a=meta['aliases'].get('aliases',[])
if a:api('/collections/aliases',{'actions':[{'create_alias':x} for x in a]})
assert sorted(api('/aliases')['aliases'],key=lambda a:a['alias_name'])==sorted(meta['aliases']['aliases'],key=lambda a:a['alias_name'])
for c in meta['collections']:
 p='/collections/'+urllib.parse.quote(c['name'],safe=''); info=api(p)
 assert info['points_count']==c['info']['points_count']
 assert info['config']['params']['vectors']==c['info']['config']['params']['vectors']
 points=c['sample']['points']
 if not points:continue
 point=points[0];restored=api(p+'/points',{'ids':[point['id']],'with_vector':True,'with_payload':True})[0]
 assert all(restored[k]==point[k] for k in ('id','vector','payload'))
 vector=point['vector'];vectors=[{'name':k,'vector':v} for k,v in vector.items()] if isinstance(vector,dict) else [vector]
 for v in vectors:
  hits=api(p+'/points/search',{'vector':v,'limit':10})
  assert any(h['id']==point['id'] and math.isfinite(h['score']) for h in hits)
print(json.dumps({'collections':len(meta['collections']),'searches':sum(bool(c['sample']['points']) for c in meta['collections'])}))
'''
def qdrant(s,path,spec):
 meta=json.loads((path/'meta.json').read_text());volume=s.create('volume','qdrant-data');name=s.create('container','qdrant')
 args=[]
 for c in meta['collections']:args+=['--snapshot','/snapshots/'+c['file']+':'+c['name']]
 s.run(name,spec['image'],args,[f'type=volume,src={volume},dst=/qdrant/storage',f'type=bind,src={path},dst=/snapshots,readonly'],['--entrypoint','/qdrant/qdrant'])
 return json.loads(s.wait(lambda:s.helper_run(QVERIFY,[f'type=bind,src={path},dst=/snapshots,readonly'],'container:'+name)))

def etcd(s,path,spec):
 volume=s.create('volume','etcd-data');name=s.create('container','etcd');member='s236member'
 mounts=[f'type=volume,src={volume},dst=/restore',f'type=bind,src={path},dst=/snapshot,readonly']
 base=['run','--rm','--label',LABEL,'--network','none',*sum((['--mount',m] for m in mounts),[]),'--entrypoint','etcdctl',spec['image']]
 s.d.run([*base,'snapshot','status','/snapshot/snapshot.db','--write-out=json'])
 s.d.run([*base,'snapshot','restore','/snapshot/snapshot.db','--data-dir=/restore/data','--name='+member,'--initial-cluster='+member+'=http://localhost:2380','--initial-advertise-peer-urls=http://localhost:2380','--initial-cluster-token='+s.prefix])
 s.run(name,spec['image'],['--name='+member,'--data-dir=/restore/data','--listen-client-urls=http://0.0.0.0:2379','--advertise-client-urls=http://localhost:2379','--listen-peer-urls=http://localhost:2380','--initial-advertise-peer-urls=http://localhost:2380','--initial-cluster='+member+'=http://localhost:2380'],[mounts[0]],['--entrypoint','etcd'])
 s.wait(lambda:s.d.run(['exec',name,'etcdctl','endpoint','health']));return {'healthy':True,'volume':volume}

def smoke(s,generation,inv):
 deployment=json.loads((generation/'deployment.json').read_text());core=next(c for c in deployment if c['name']=='core-core-1');cfg=core['Config'];repo=s.target/'trees'/inv['repository']['id']/'restored'
 env=s.target/'core.env';values=cfg.get('Env',[])
 if any('\n' in x or '\r' in x for x in values):raise BackupError('Unsupported multiline Docker environment')
 env.write_text('\n'.join(values)+'\n');env.chmod(0o600)
 mounts=[]
 expected=next(c for c in inv['expected_mounts'] if c['container']=='core-core-1')
 for m in expected['mounts']:
  dst=m['destination'];src=None
  if dst=='/var/run/docker.sock' or dst in ('/usb','/mnt/sauvegarde-usb') or dst.startswith('/usb/'):continue
  if m['type']=='volume':
   tree=next(t for t in inv['trees'] if t['kind']=='volume' and t['source']==m['name']);src=s.target/'trees'/tree['id']/'restored'
  else:
   source=Path(m['source']);original=Path(inv['repository']['source'])
   if source.is_relative_to(original):src=repo/source.relative_to(original)
   else:
    tree=next((t for t in inv['trees'] if t['kind']=='bind' and Path(t['source'])==source),None)
    if tree:src=s.target/'trees'/tree['id']/'restored'
  if src is None:raise BackupError('Unmapped core data mount')
  mounts.append(f'type=bind,src={src},dst={dst}')
 name=s.create('container','core');extra=['--env-file',str(env)]
 for key,flag in [('User','--user'),('WorkingDir','--workdir')]:
  if cfg.get(key):extra +=[flag,cfg[key]]
 entry=cfg.get('Entrypoint') or [];cmd=cfg.get('Cmd') or []
 if entry:extra+=['--entrypoint',entry[0]];cmd=entry[1:]+cmd
 s.run(name,core['image_id'],cmd,mounts,extra)
 result=json.loads(s.wait(lambda:s.helper_run(SMOKE_SCRIPT,network='container:'+name)));env.unlink();return result

def restore(generation,target,docker=None,keep=False,smoke_core=True):
 generation=Path(generation).absolute();manifest=verify_generation(generation);inv=manifest['inventory'];docker=docker or Docker();target=validate_target(target,generation,inv,docker)
 target.mkdir(mode=0o700,parents=True);target.chmod(0o700);s=Session(docker,target,inv['helper_image']);started=time.time();report={'success':False,'full_stack_restored':False,'scope':'Native data and isolated core startup; external connectors and full application flows excluded','trees':[],'postgres':[],'source_verified':True}
 try:
  s.create('network','network')
  for source in manifest['sources']:
   report['active_source']={'kind':source['kind'],'id':source.get('id',source['source'].get('container'))}
   path=generation/source['path'];kind=source['kind']
   if kind=='tree':
    parent=target/'trees'/source['id'];parent.mkdir(mode=0o700,parents=True)
    script="import sys,json;sys.path.insert(0,'/scripts');import artifacts\nm=artifacts.restore_tree('/artifact','/output/restored')\nfor e in m['entries']:\n if e['type']=='file':\n  p=artifacts.Path('/output/restored')/e['path'];assert artifacts._hash(p)=={k:e[k] for k in ('sha256','size')}\n  if 'sqlite' in e:assert artifacts._sqlite(p)==e['sqlite']\nprint(json.dumps({'entries':len(m['entries'])}))"
    result=json.loads(s.helper_run(script,[f'type=bind,src={path},dst=/artifact,readonly',f'type=bind,src={parent},dst=/output',f'type=bind,src={Path(__file__).resolve().parent},dst=/scripts,readonly']))
    report['trees'].append({'id':source['id'],**result})
   elif kind=='postgres':report['postgres'].append(postgres(s,path,source['source'],len(report['postgres'])))
   elif kind=='qdrant':report['qdrant']=qdrant(s,path,source['source'])
   elif kind=='etcd':report['etcd']=etcd(s,path,source['source'])
  if smoke_core:report['core']=smoke(s,generation,inv)
  report['success']=True;report['active_source']=None
 finally:
  report.update(duration=time.time()-started,resources=s.resources,kept=bool(keep and report['success']))
  report['cleanup_failed']=[] if report['kept'] else s.cleanup()
  if not report['kept'] and (target/'trees').exists():
   try:
    s.helper_run("import os,shutil\nfor folder,dirs,files in os.walk('/output',followlinks=False):\n os.chmod(folder,0o700)\nshutil.rmtree('/output/trees')",[f'type=bind,src={target},dst=/output'])
   except Exception:report['cleanup_failed'].append('restored-trees')
  for p in target.glob('*.env'):p.unlink()
  atomic_json(target/'report.json',report)
 return report

def main():
 def interrupted(signum,frame):raise BackupError('Restore interrupted')
 signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
 p=argparse.ArgumentParser();p.add_argument('--generation',required=True,type=Path);p.add_argument('--target',required=True,type=Path);p.add_argument('--keep',action='store_true');p.add_argument('--skip-smoke-core',action='store_true');a=p.parse_args()
 try:
  r=restore(a.generation,a.target,keep=a.keep,smoke_core=not a.skip_smoke_core);print(json.dumps({'success':r['success'],'trees':len(r['trees']),'postgres':len(r['postgres']),'full_stack_restored':False}));return int(bool(r['cleanup_failed']))
 except Exception:print('Restore failed; private report written when target was created');return 1
if __name__=='__main__':raise SystemExit(main())
