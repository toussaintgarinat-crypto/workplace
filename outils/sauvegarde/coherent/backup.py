"""Host backup orchestrator. Generation: manifest.json, deployment.json (private),
trees/<id>/artifact/{manifest.json,data/}, postgres/<container>/, qdrant/, etcd/.
All regular files except top manifest are SHA256 sealed; tree symlinks are
validated by artifacts. Complete generations are published only after recovery.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import time
import uuid
import artifacts
import engines


class BackupError(RuntimeError): pass

class DockerError(BackupError):
    def __init__(self,operation,returncode,stderr=b''):
        self.operation=operation;self.returncode=returncode
        matches=re.findall(rb'^(AssertionError|MemoryError|PermissionError|FileNotFoundError|ValueError|sqlite3\.OperationalError)(?::|\s*$)',stderr,re.MULTILINE)
        self.diagnostic_type=matches[-1].decode() if matches else None
        super().__init__('Docker operation '+operation+' failed (code '+str(returncode)+')')


class Docker:
    def run(self,args,output=None,timeout=1800):
        try:
            if output is not None:
                fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream:
                    result=subprocess.run(['docker',*args],stdout=stream,stderr=subprocess.PIPE,timeout=timeout)
            else:
                result=subprocess.run(['docker',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
            if result.returncode: raise DockerError(args[0],result.returncode,result.stderr)
            return result.stdout or b''
        except (OSError,subprocess.TimeoutExpired) as e:
            raise BackupError('Docker operation '+args[0]+' unavailable or timed out') from None
    def inspect(self):
        ids=self.run(['ps','-aq']).decode().split()
        return json.loads(self.run(['inspect',*ids])) if ids else []


def atomic_json(path,value):
    path=Path(path); tmp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(value,f,sort_keys=True); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


@contextmanager
def lock(root):
    root=Path(root).absolute()
    if any(p.is_symlink() for p in (root,*root.parents)): raise BackupError('Unsafe root')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    root.chmod(0o700)
    fd=os.open(root/'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise BackupError('Backup already locked') from None
        yield
    finally: os.close(fd)


def load_inventory(path):
    with open(path) as f: inv=json.load(f)
    if inv.get('version')!=1: raise BackupError('Unsupported inventory')
    ids=[x['id'] for x in [inv['repository'],*inv['trees']]]
    if len(set(ids))!=len(ids) or any(not x or '/' in x or x in ('.','..') for x in ids): raise BackupError('Invalid source identifiers')
    return inv


def ignored(c):
    return (c.get('Config',{}).get('Labels') or {}).get('workplace.s236')=='true' or c['Name'].lstrip('/').startswith('s236-')


def mount_key(m):
    return (m.get('Type',m.get('type')),m.get('Name',m.get('name')),m.get('Source',m.get('source')),m.get('Destination',m.get('destination')))


def check_containers(inv,containers):
    actual={c['Name'].lstrip('/'):c for c in containers if not ignored(c)}
    expected={c['container']:c for c in inv['expected_mounts']}
    for name,c in actual.items():
        if name not in expected: raise BackupError('Unclassified container: '+name)
        if {mount_key(m) for m in c['Mounts']} != {mount_key(m) for m in expected[name]['mounts']}: raise BackupError('Mount drift: '+name)
        if c.get('Config',{}).get('Image') not in (None,expected[name].get('image')): raise BackupError('Image drift: '+name)
    required={o['container'] for t in inv.get('trees',[]) for o in t['owners']}
    required.update(x['container'] for x in inv.get('postgres',[]))
    required.update(inv[k]['container'] for k in ('qdrant','etcd') if inv.get(k))
    for name,e in expected.items():
        if name not in actual:
            if e['running'] or name in required: raise BackupError('Missing producer: '+name)
        elif bool(actual[name]['State']['Running'])!=e['running']: raise BackupError('Running state drift: '+name)
    return actual


def check_root_boundaries(root, sources, canonical_sources=False):
    def plain(path):
        path=Path(path).absolute()
        if any(p.is_symlink() for p in (path,*path.parents)):
            raise BackupError('Symlink backup/source parent')
        return path.resolve(strict=False)
    root=plain(root)
    for source in sources:
        source=Path(source) if canonical_sources else plain(source)
        if not source.is_absolute(): raise BackupError('Noncanonical source path')
        if root.is_relative_to(source) or source.is_relative_to(root):
            raise BackupError('Backup root overlaps a source')


def docker_source_paths(sources,docker,helper):
    """Canonicalize protected Docker paths in one root helper, host mounted read-only."""
    script="import os,sys,json; result=[]\nfor source in json.loads(sys.argv[1]):\n q=os.path.realpath('/host'+source,strict=True); assert q.startswith('/host/'); result.append(q[5:])\nprint(json.dumps(result))"
    try:
        result=json.loads(docker.run(['run','--rm','--user','0','--label','workplace.s236=true','--network','none','--mount','type=bind,src=/,dst=/host,readonly','--entrypoint','python3',helper,'-c',script,json.dumps([str(p) for p in sources])]))
        if not isinstance(result,list) or len(result)!=len(sources) or any(not isinstance(p,str) or not p.startswith('/') or '..' in Path(p).parts for p in result): raise ValueError()
        return result
    except Exception: raise BackupError('Cannot canonicalize Docker sources') from None


def docker_source_path(source,docker,helper):
    return docker_source_paths([source],docker,helper)[0]


def expected_sources(inv):
    result=[{'kind':'tree','id':t['id'],'path':'trees/'+t['id']+'/artifact','source':t} for t in [inv['repository'],*inv['trees']]]
    result.extend({'kind':'postgres','path':'postgres/'+t['container'],'source':t} for t in inv.get('postgres',[]))
    result.extend({'kind':kind,'path':kind,'source':inv[kind]} for kind in ('qdrant','etcd') if inv.get(kind))
    return result


def preflight(inv,root,docker):
    current=check_containers(inv,docker.inspect())
    source_paths=[t['source'] for t in [inv['repository'],*inv['trees']] if t['kind']=='bind']
    volume_names={t['source'] for t in inv['trees'] if t['kind']=='volume'}
    for c in current.values():
        source_paths.extend(m['Source'] for m in c['Mounts'] if m.get('Type')=='volume' and m.get('Name') in volume_names)
    for name in volume_names:
        volume=json.loads(docker.run(['volume','inspect',name]))
        source_paths.append(volume[0]['Mountpoint'])
    source_paths=docker_source_paths(source_paths,docker,inv['helper_image'])
    check_root_boundaries(root,source_paths,canonical_sources=True)
    docker.run(['image','inspect',inv['helper_image']])
    estimate=8*1024**3
    for t in [inv['repository'],*inv['trees']]:
        if t['kind']=='volume': docker.run(['volume','inspect',t['source']])
        elif not Path(t['source']).exists(): raise BackupError('Missing bind source: '+t['id'])
        code="import os;print(sum(os.lstat(os.path.join(p,n)).st_size for p,d,f in os.walk('/source') for n in f))"
        mount=f"type={t['kind']},src={t['source']},dst=/source,readonly"
        estimate+=int(docker.run(['run','--rm','--label','workplace.s236=true','--network','none','--mount',mount,'--entrypoint','python3',inv['helper_image'],'-c',code]))
    repo=Path(inv['repository']['source'])
    for rel in ('.env','briques/gateway/.env'):
        if not (repo/rel).is_file(): raise BackupError('Required repository configuration missing')
    for e in inv['expected_mounts']:
        for m in e['mounts']:
            if m['type']=='bind' and not Path(m['source']).exists(): raise BackupError('Missing expected bind source')
    if shutil.disk_usage(root).free<estimate: raise BackupError('Insufficient backup disk space')
    return current,{'containers':len(current),'estimated_bytes':estimate}


def recover(root,docker):
    journal=Path(root)/'recovery.json'
    if not journal.exists(): return []
    records=json.loads(journal.read_text()); current={c['Name'].lstrip('/'):c for c in docker.inspect()}
    failures=[]
    for r in reversed(records):
        try:
            if current.get(r['name'],{}).get('Id')!=r['id']: raise BackupError('Recovery container identity changed: '+r['name'])
            docker.run(['start',r['id']])
            check=next((c for c in docker.inspect() if c['Id']==r['id']),{})
            if not check.get('State',{}).get('Running'): raise BackupError('Recovery start not running: '+r['name'])
        except BackupError: failures.append(r['name'])
    if failures: raise BackupError('Recovery incomplete: '+', '.join(failures))
    restored=docker.inspect()
    journal.unlink()
    names={r['name'] for r in records}
    return [{'name':c['Name'].lstrip('/'),'running':bool(c['State']['Running']),'health':c['State'].get('Health',{}).get('Status','none')} for c in restored if c['Name'].lstrip('/') in names]


def export_tree(docker,inv,source,target):
    target.mkdir(parents=True,mode=0o700)
    script="import sys,os,json;sys.path.insert(0,'/scripts');import artifacts\n"
    script+="excluded=json.loads(sys.argv[1]); paths=[]\nfor folder,dirs,files in os.walk('/source',followlinks=False):\n for n in dirs+files:\n  if n in excluded: paths.append(os.path.relpath(os.path.join(folder,n),'/source'))\n dirs[:]=[n for n in dirs if n not in excluded]\n"
    script+="try:\n artifacts.export_tree('/source','/output/artifact',paths,frozen=True)\nfinally:\n"
    script+=''.join(' '+line+'\n' for line in engines.chown_script(os.getuid(),os.getgid()).splitlines() if line)
    docker.run(['run','--rm','--network','none','--label','workplace.s236=true','--mount',f"type={source['kind']},src={source['source']},dst=/source,readonly",'--mount',f'type=bind,src={target},dst=/output','--mount',f'type=bind,src={Path(__file__).resolve().parent},dst=/scripts,readonly','--entrypoint','python3',inv['helper_image'],'-c',script,json.dumps(source.get('exclude',[]))])
    artifacts.verify_tree(target/'artifact')


def file_hashes(root):
    hashes={}
    for p in sorted(root.rglob('*')):
        if p==root/'manifest.json':
            if p.is_symlink() or not p.is_file():raise BackupError('Unsafe generation manifest')
            continue
        if p.is_symlink():
            if not p.resolve().is_relative_to(root.resolve()): raise BackupError('Escaping generation symlink')
        elif p.is_file():
            with p.open('rb') as f:
                h=hashlib.file_digest(f,'sha256').hexdigest()
            hashes[p.relative_to(root).as_posix()]=h
        elif not p.is_dir(): raise BackupError('Special generation path')
    return hashes


def seal(root,sources,inventory,started):
    atomic_json(root/'manifest.json',{'schema':1,'sources':sources,'inventory':inventory,'started':started,'ended':time.time(),'paths': sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p!=root/'manifest.json'), 'hashes':file_hashes(root)})


def verify_generation(path):
    root=Path(path).absolute()
    if any(p.is_symlink() for p in (root,*root.parents)): raise BackupError('Symlink generation root')
    try:
        m=json.loads((root/'manifest.json').read_text())
        if m['schema']!=1 or sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p!=root/'manifest.json')!=m['paths'] or file_hashes(root)!=m['hashes']: raise BackupError('Generation checksum mismatch')
        expected=expected_sources(m['inventory'])
        if not m['hashes'] or not m['sources'] or sorted(m['sources'],key=lambda x:x['path'])!=sorted(expected,key=lambda x:x['path']):
            raise BackupError('Generation source coverage mismatch')
        for s in m['sources']:
            rel=PurePosixPath(s['path'])
            if rel.is_absolute() or '..' in rel.parts: raise BackupError('Unsafe generation source')
            if s['kind']=='tree': artifacts.verify_tree(root/rel)
        return m
    except (ValueError,KeyError,OSError): raise BackupError('Invalid generation') from None


def status(root,success,started,failed=0):
    p=root/'status.json'; old=json.loads(p.read_text()) if p.exists() else {}
    value={'last_attempt_success':success,'last_export_timestamp':time.time() if success else old.get('last_export_timestamp',0),'last_transfer_timestamp':old.get('last_transfer_timestamp',0),'failed_sources_count':failed,'duration':time.time()-started}
    atomic_json(p,value)
    gauges={'export_success':int(success),'last_export_timestamp_seconds':value['last_export_timestamp'],'last_transfer_timestamp_seconds':value['last_transfer_timestamp'],'failed_sources':failed}
    tmp=root/'metrics.prom.tmp'; tmp.write_text(''.join('workplace_backup_'+k+' '+str(v)+'\n' for k,v in gauges.items())); tmp.chmod(0o644); os.replace(tmp,root/'metrics.prom')


def backup(inv,root,docker):
    root=Path(root)
    with lock(root):
        if (root/'recovery.json').exists(): raise BackupError('Pending recovery; run recover first')
        started=time.time(); partial=None; sources=[]
        try:
            current,_=preflight(inv,root,docker)
            for d in ('staging','complete','failed'): (root/d).mkdir(exist_ok=True,mode=0o700)
            partial=root/'staging'/('.partial-'+uuid.uuid4().hex); partial.mkdir(mode=0o700)
            atomic_json(partial/'deployment.json',[{'name':name,'id':c['Id'],'image_id':c.get('Image'),'Config':c.get('Config',{}),'HostConfig':c.get('HostConfig',{}),'NetworkSettings':c.get('NetworkSettings',{})} for name,c in current.items() if c['State']['Running']])
            producers=[(name,c) for name,c in current.items() if c['State']['Running'] and name not in inv.get('keep_running',[])+inv.get('never_stop',[])]
            producers.sort(key=lambda x:(0 if 'kuma' in x[0] else 1 if 'caddy' in x[0] else 2,x[0]))
            journal=[]
            try:
                for name,c in producers:
                    journal.append({'name':name,'id':c['Id']}); atomic_json(root/'recovery.json',journal)
                    docker.run(['stop','-t','30',c['Id']],timeout=90)
                for t in [inv['repository'],*inv['trees']]:
                    rel='trees/'+t['id']+'/artifact'; export_tree(docker,inv,t,partial/Path(rel).parent)
                    sources.append({'kind':'tree','id':t['id'],'path':rel,'source':t})
                (partial/'postgres').mkdir(mode=0o700)
                for spec in inv.get('postgres',[]):
                    engines.postgres(docker,spec,partial/'postgres'/spec['container']); sources.append({'kind':'postgres','path':'postgres/'+spec['container'],'source':spec})
                for kind in ('qdrant','etcd'):
                    if inv.get(kind):
                        if kind=='qdrant': engines.qdrant(docker,inv[kind],partial/kind,inv['helper_image'])
                        else: engines.etcd(docker,inv[kind],partial/kind,inv['helper_image'])
                        sources.append({'kind':kind,'path':kind,'source':inv[kind]})
                seal(partial,sources,inv,started); verify_generation(partial)
            finally: health=recover(root,docker)
            atomic_json(partial/'recovery-health.json',{'containers':health,'running_count':sum(x['running'] for x in health),'healthy_count':sum(x['health']=='healthy' for x in health)})
            seal(partial,sources,inv,started); verify_generation(partial)
            complete=root/'complete'/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8]); os.rename(partial,complete)
            status(root,True,started); return complete
        except BaseException:
            if partial is not None and partial.exists(): os.rename(partial,root/'failed'/partial.name)
            status(root,False,started,1); raise


def main():
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['preflight','inventory','backup','verify','recover','status']); p.add_argument('--inventory',type=Path,default=Path(__file__).with_name('inventory-hp.json')); p.add_argument('--root',type=Path,default=Path('/home/debian/.local/share/workplace-backups')); p.add_argument('--generation',type=Path); a=p.parse_args()
    def interrupted(signum,frame): raise BackupError('Backup interrupted')
    signal.signal(signal.SIGTERM,interrupted); signal.signal(signal.SIGINT,interrupted)
    try:
        inv=load_inventory(a.inventory); docker=Docker()
        if a.command=='backup': result={'generation':str(backup(inv,a.root,docker))}
        elif a.command=='verify': result={'verified':bool(verify_generation(a.generation))}
        elif a.command=='inventory': result=[{'name':c['Name'],'image':c.get('Config',{}).get('Image'),'mounts':c['Mounts']} for c in docker.inspect() if not ignored(c)]
        elif a.command=='status':
            result=json.loads((a.root/'status.json').read_text()); result['rpo_ok']=bool(result['last_transfer_timestamp'] and time.time()-result['last_transfer_timestamp']<=inv['rpo_seconds'])
        else:
            with lock(a.root):
                result=preflight(inv,a.root,docker)[1] if a.command=='preflight' else recover(a.root,docker)
        print(json.dumps(result))
    except BackupError as e: print(str(e)); return 1
    except Exception: print('Backup operation failed'); return 1
    return 0


if __name__=='__main__': raise SystemExit(main())
