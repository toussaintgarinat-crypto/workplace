"""Native exports: postgres/<container>/{roles.sql,db-N.dump,meta.json},
qdrant/{collection-N.snapshot,meta.json}, etcd/{snapshot.db,meta.json}."""
import json
import os
from pathlib import Path
import uuid


def private_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True)); path.chmod(0o600)


def postgres(docker, spec, target):
    target.mkdir(mode=0o700)
    c = spec['container']
    info = next(x for x in docker.inspect() if x['Name'].lstrip('/') == c)
    environment=dict(x.split('=',1) for x in info.get('Config',{}).get('Env',[]) if '=' in x)
    user = spec.get('backup_user') or environment.get('PATRONI_SUPERUSER_USERNAME') or environment.get('POSTGRES_USER') or 'postgres'
    def query(sql, db='postgres'):
        return docker.run(['exec',c,'psql','-X','-U',user,'-d',db,'-At','-c',sql]).decode().strip()
    if query('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')!='t':
        raise RuntimeError('PostgreSQL backup requires configured superuser')
    dbs=json.loads(query("SELECT coalesce(json_agg(datname ORDER BY datname),'[]') FROM pg_database WHERE NOT datistemplate"))
    docker.run(['exec',c,'pg_dumpall','-U',user,'--roles-only'], output=target/'roles.sql')
    metadata={**spec,'user':user,'version':query('SHOW server_version'),'databases':[]}
    for n, db in enumerate(dbs):
        filename=f'db-{n}.dump'
        docker.run(['exec',c,'pg_dump','-U',user,'-d',db,'-Fc'],output=target/filename)
        extensions=json.loads(query("SELECT coalesce(json_agg(json_build_object('name',extname,'version',extversion) ORDER BY extname),'[]') FROM pg_extension",db))
        tables=json.loads(query("SELECT coalesce(json_agg(json_build_object('schema',schemaname,'name',tablename) ORDER BY schemaname,tablename),'[]') FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')",db))
        counts={}
        for t in tables:
            quoted='.'.join('"'+t[k].replace('"','""')+'"' for k in ('schema','name'))
            counts[quoted]=int(query('SELECT count(*) FROM '+quoted,db))
        metadata['databases'].append({'name':db,'file':filename,'extensions':extensions,'table_counts':counts})
    private_json(target/'meta.json',metadata)


QDRANT_SCRIPT = r'''
import urllib.request,json,urllib.parse,os
base='http://127.0.0.1:6333'
def request(path,method='GET',body=None):
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(base+path,data=data,method=method,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=300) as r: return r.read()
def api(path,method='GET',body=None): return json.loads(request(path,method,body))['result']
meta={'collections':[],'aliases':api('/aliases')}
for n,c in enumerate(api('/collections')['collections']):
    name=c['name']; path='/collections/'+urllib.parse.quote(name,safe='')
    info=api(path); sample=api(path+'/points/scroll','POST',{'limit':1,'with_vector':True,'with_payload':True})
    snap=api(path+'/snapshots?wait=true','POST')['name']
    sp=path+'/snapshots/'+urllib.parse.quote(snap,safe='')
    try:
        filename='collection-'+str(n)+'.snapshot'
        with urllib.request.urlopen(base+sp,timeout=600) as r,open('/output/'+filename,'wb') as f:
            import shutil;shutil.copyfileobj(r,f)
        meta['collections'].append({'name':name,'file':filename,'info':info,'sample':sample})
    finally: request(sp,'DELETE')
with open('/output/meta.json','w') as f: json.dump(meta,f)
'''


def chown_script(uid,gid):
    return f"\nfor folder,dirs,files in os.walk('/output',followlinks=False):\n for name in dirs+files: os.lchown(os.path.join(folder,name),{uid},{gid})\nos.lchown('/output',{uid},{gid})\n"


def qdrant(docker,spec,target,helper):
    target.mkdir(mode=0o700)
    script='import os\ntry:\n'+''.join(' '+line+'\n' for line in QDRANT_SCRIPT.splitlines())+'finally:\n'+''.join(' '+line+'\n' for line in chown_script(os.getuid(),os.getgid()).splitlines() if line)
    docker.run(['run','--rm','--label','workplace.s236=true','--network','container:'+spec['container'],'--mount',f'type=bind,src={target},dst=/output','--entrypoint','python3',helper,'-c',script])
    for p in target.iterdir(): p.chmod(0o600)


def etcd(docker,spec,target,helper='core-core'):
    target.mkdir(mode=0o700); c=spec['container']; basename='s236-'+uuid.uuid4().hex+'.db'
    source=next(x for x in docker.inspect() if x['Name'].lstrip('/')==c)
    directory=spec.get('snapshot_directory','/var/etcd')
    mount=next((m for m in source['Mounts'] if m['Destination']==directory and m['Type'] in ('bind','volume')),None)
    if mount is None:raise RuntimeError('etcd snapshot requires recorded data mount')
    remote=directory+'/'+basename
    cleanup_mount=f"type={mount['Type']},src={mount['Name'] if mount['Type']=='volume' else mount['Source']},dst=/cleanup"
    try:
        docker.run(['exec',c,'etcdctl','snapshot','save',remote])
        docker.run(['cp',c+':'+remote,str(target/'snapshot.db')])
        metadata={**spec}
        try: metadata['status']=docker.run(['exec',c,'etcdctl','snapshot','status',remote,'--write-out=json']).decode()
        except Exception: metadata['status_available']=False
        private_json(target/'meta.json',metadata)
        (target/'snapshot.db').chmod(0o600)
    finally:
        docker.run(['run','--rm','--user','0','--label','workplace.s236=true','--network','none','--mount',cleanup_mount,'--entrypoint','python3',helper,'-c',"import pathlib,sys;pathlib.Path('/cleanup',sys.argv[1]).unlink(missing_ok=True)",basename])
