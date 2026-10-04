"""Isolated application recovery exercise. Never attach production networks/mounts.
Uses restored data only, internal network copies, private env files, no host ports,
Docker socket, host networking, devices, capabilities or external connectors.
S237 host reconstruction and actual Patroni HA remain outside this exercise.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import shlex
import time
import uuid
from backup import BackupError, Docker, atomic_json, verify_generation
import restore as native

BLOCKED_DESTINATIONS={'/var/run/docker.sock','/run/docker.sock','/host','/mnt/sauvegarde-usb','/usb'}
# Host telemetry and replication/upload sidecars intentionally cannot represent
# original behavior in an internal sandbox. Report exclusions explicitly.
EXCLUDED_NAMES={'workplace_node_exporter','workplace_prometheus','mesh_caddy'}
PHASED_NAMES={'workplace_connexion','forge-forge-1','workplace_audit_fichiers_clamav','workplace_voix','workplace_ecoute','workplace_grafana','workplace_dev_ide','workplace_searxng','workplace_uptime_kuma','workplace_peertube','oria-frontend-1'}
EXCLUDED_PATTERN=re.compile(r'(?:litestream|walg)',re.I)


def map_mount(m,inv,target):
    kind=m.get('Type',m.get('type'));dst=m.get('Destination',m.get('destination'))
    source=m.get('Source',m.get('source'))
    if dst in BLOCKED_DESTINATIONS or source in ('/var/run/docker.sock','/run/docker.sock') or dst.startswith('/usb/'):
        return None
    if kind=='volume':
        name=m.get('Name',m.get('name'));tree=next((t for t in inv['trees'] if t['kind']=='volume' and t['source']==name),None)
        if not tree:
            if dst in ('/var/cache/searxng','/workspace/oria/frontend/node_modules','/var/lib/clamav') and any(any(o['destination']==dst for o in classified['owners']) for classified in inv.get('classified_mounts',[])):
                return {'source':None,'destination':dst,'readonly':False,'reconstruct':'image-or-empty-cache'}
            raise BackupError('Unmapped nonnative volume at '+dst)
        src=target/'trees'/tree['id']/'restored'
    elif kind=='bind':
        original=Path(inv['repository']['source']);path=Path(source)
        if path.is_relative_to(original):src=target/'trees'/inv['repository']['id']/'restored'/path.relative_to(original)
        else:
            tree=next((t for t in inv['trees'] if t['kind']=='bind' and Path(t['source'])==path),None)
            if tree is None: raise BackupError('Unmapped bind at '+dst)
            src=target/'trees'/tree['id']/'restored'
    else:raise BackupError('Unsupported mount type')
    return {'source':str(src),'destination':dst,'readonly':not m.get('RW',True)}


def plan_container(c,inv,target,mounts):
    cfg=c['Config'];values=[]
    for raw in cfg.get('Env',[]):
        if '\n' in raw or '\r' in raw:raise BackupError('Unsupported multiline environment')
        key,value=raw.split('=',1)
        # Original HP endpoints become the private multiplexer. The multiplexer
        # can route only ports belonging to restored services, never outside.
        value=value.replace('192.168.1.89','s236-relay').replace('host.docker.internal','s236-relay')
        if key in ('BRIQUE_HOST','MESH_HOST'):value='s236-relay'
        if key.startswith('NETBIRD_') or key in ('TELEGRAM_BOT_TOKEN','DUCKDNS_TOKEN'):value=''
        if key in ('REPLI_PAYANT','CASCADE_AUTO'):value='false'
        if key=='KC_HOSTNAME':value='http://s236-relay:'+('8081' if c['name']=='oria-keycloak-1' else '8080')
        if key=='KC_HOSTNAME_STRICT':value='false'
        if key=='KEYCLOAK_URL' and c['name']=='oria-backend-1':value='http://s236-relay:8081'
        values.append(key+'='+value)
    if c['name']=='oria-frontend-1':
        values=[v for v in values if not v.startswith('CHOKIDAR_USEPOLLING=')]+['CHOKIDAR_USEPOLLING=true']
    networks={}
    for name,settings in c.get('NetworkSettings',{}).get('Networks',{}).items():
        if name in ('host','bridge','none'):continue
        aliases=(settings.get('Aliases') or []) if settings else []
        networks[name]=sorted(set([c['name'],*(a for a in aliases if not re.fullmatch('[a-f0-9]{12,64}',a))]))
    if not networks:networks={'rehearsal':[c['name']]}
    mapped=[map_mount(m,inv,target) for m in mounts];mapped=[m for m in mapped if m]
    return {'name':c['name'],'image':c['image_id'],'environment':values,'networks':networks,'mounts':mapped,'cmd':cfg.get('Cmd') or [],'entrypoint':cfg.get('Entrypoint') or [],'user':cfg.get('User'),'workdir':cfg.get('WorkingDir'),'healthcheck':cfg.get('Healthcheck')}


RELAY=r'''
import json,socket,socketserver,threading,select,time
routes=json.load(open('/routes/routes.json'))
class Forward(socketserver.BaseRequestHandler):
 def handle(self):
  host,port=routes[str(self.server.server_address[1])]
  try:
   with socket.create_connection((host,port),timeout=10) as upstream:
    pair=[self.request,upstream]
    while True:
     ready,_,_=select.select(pair,[],[],60)
     if not ready:return
     for sock in ready:
      data=sock.recv(65536)
      if not data:return
      (upstream if sock is self.request else self.request).sendall(data)
  except OSError:return
class Server(socketserver.ThreadingTCPServer):
 allow_reuse_address=True;daemon_threads=True
for port in routes:
 server=Server(('0.0.0.0',int(port)),Forward)
 threading.Thread(target=server.serve_forever,daemon=True).start()
while True:time.sleep(60)
'''

SQLITE_CRUD=r'''
import urllib.request,json,uuid,urllib.error
token=json.load(open('/probe/tokens.json'))['core']['access_token']
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
base='http://127.0.0.1:5500/apps/s236-'+uuid.uuid4().hex+'/entites/rehearsal/enregistrements'
def api(path,method='GET',body=None):
 req=urllib.request.Request(path,method=method,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
 with opener.open(req,timeout=30) as r:return None if r.status==204 else json.load(r)
x=api(base,'POST',{'name':'restored-business-probe','value':236})
identifier=x.get('_id',x.get('id'));assert identifier
items=api(base);assert any(i.get('_id',i.get('id'))==identifier for i in items)
api(base+'/'+identifier,'PUT',{'name':'restored-business-probe','value':237})
items=api(base);assert any(i.get('value')==237 for i in items)
api(base+'/'+identifier,'DELETE');assert not any(i.get('_id',i.get('id'))==identifier for i in api(base))
print(json.dumps({'sqlite_crud':True}))
'''


def validate_owned_resources(docker,resources):
    """Read-only all-resource guard before manual sandbox repair or teardown."""
    identities=set();networks={r['name'] for r in resources if r['kind']=='network'}
    for resource in resources:
        name=resource['name'];kind=resource['kind']
        if not re.fullmatch(r's236-[a-f0-9]{32}-[a-z0-9-]+',name):raise BackupError('Resource name is not generated sandbox name')
        if kind=='container':
            objects=json.loads(docker.run(['inspect',name]));item=objects[0]
            if item['Id']!=resource['id'] or item['Name'].lstrip('/')!=name:raise BackupError('Sandbox container identity changed')
            labels=item['Config'].get('Labels') or {};identities.add(item['Id'])
            if item.get('HostConfig',{}).get('NetworkMode')=='host':raise BackupError('Sandbox unexpectedly uses host network')
            if not set(item.get('NetworkSettings',{}).get('Networks',{})).issubset(networks):raise BackupError('Sandbox attached to unknown network')
        elif kind in ('network','volume'):
            item=json.loads(docker.run([kind,'inspect',name]))[0];labels=item.get('Labels') or {}
            if item['Name']!=name:raise BackupError('Sandbox resource identity changed')
            if kind=='network' and not item['Internal']:raise BackupError('Sandbox network is not internal')
        else:raise BackupError('Unknown sandbox resource kind')
        if labels.get('workplace.s236')!='true':raise BackupError('Resource lacks sandbox ownership label')
    for resource in resources:
        if resource['kind']=='network':
            item=json.loads(docker.run(['network','inspect',resource['name']]))[0]
            if any(identity not in identities for identity in (item.get('Containers') or {})):
                raise BackupError('Network contains unknown containers')
    return True


def create_isolated_network(s,suffix):
    name=s.prefix+'-'+suffix
    existing=s.d.run(['network','ls','--format','{{.Name}}']).decode().splitlines()
    if name in existing:raise BackupError('Network already exists')
    s.d.run(['network','create','--internal','--opt','com.docker.network.bridge.gateway_mode_ipv4=isolated','--label',native.LABEL,name])
    s.resources.append({'kind':'network','name':name})
    return name


def memory_limit(name):
    mib=1024**2
    known={'workplace_connexion':128,'gateway-gateway-1':1536,'workplace_audit_fichiers_clamav':1280,'workplace_voix':512,'workplace_ecoute':640,'workplace_searxng':192,'workplace_uptime_kuma':256,'forge-qdrant-1':512,'oria-frontend-1':768,'agenda':128,'oria-backend-1':160,'oria-seaweedfs-1':192,'workplace_grafana':128,'workplace_world_engine':128,'workplace_dev_ide':128}
    if name in known:return known[name]*mib
    if name in {'memoire-memoire-db-1','gateway-db-1','keycloak-db','oria-db-1','peertube-db','forge-forge-db-1','oria-etcd-1'}:return 256*mib
    if 'keycloak' in name:return 512*mib
    if any(x in name for x in ('forge-forge-1','peertube','core-core','memoire-backend')):return 320*mib
    return 64*mib


def memory_budget(definitions):
    included=[c['name'] for c in definitions if c['name'] not in EXCLUDED_NAMES and not EXCLUDED_PATTERN.search(c['name'])]
    baseline=sum(memory_limit(n) for n in included if n not in PHASED_NAMES)
    peak_phase=max((memory_limit(n) for n in included if n in PHASED_NAMES),default=0)
    return baseline+peak_phase+512*1024**2


def _connect(docker,network,container,aliases):
    docker.run(['network','connect',*sum((['--alias',a] for a in aliases),[]),network,container])


def _native_map(report):
    result={x['source']:x['container'] for x in report['postgres']}
    for key,suffix in (('forge-qdrant-1','-qdrant'),('oria-etcd-1','-etcd')):
        candidates=[r['name'] for r in report['resources'] if r['kind']=='container' and r['name'].endswith(suffix)]
        if candidates:result[key]=candidates[0]
    return result


def _observed(docker,names):
    current={c['Name'].lstrip('/'):c for c in docker.inspect()}
    result=[]
    for original,name in names.items():
        c=current.get(name,{})
        result.append({'name':original,'running':bool(c.get('State',{}).get('Running')),'health':c.get('State',{}).get('Health',{}).get('Status','none'),'exit_code':c.get('State',{}).get('ExitCode'),'oom_killed':bool(c.get('State',{}).get('OOMKilled'))})
    return result


def service_ready(state,native_names=()):
    return state['running'] and not state['oom_killed'] and (state['health']=='healthy' or (state['name'] in native_names and state['health']=='none'))


def rehearse(generation,target,docker=None,keep=False):
    started=time.time();generation=Path(generation).absolute();target=Path(target).absolute();docker=docker or Docker()
    manifest=verify_generation(generation);inv=manifest['inventory']
    definitions=json.loads((generation/'deployment.json').read_text())
    budget=memory_budget(definitions)
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
    if budget>available-3*1024**3:raise BackupError('Insufficient memory for capped rehearsal plus production reserve')
    report=native.restore(generation,target,docker,keep=True,smoke_core=False,memory_limit='256m',helper_memory_limit='1g')
    s=native.Session(docker,target,inv['helper_image'],memory_limit='256m',helper_memory_limit='128m');s.resources=list(report['resources'])
    restored=_native_map(report);native_names=set(restored);definitions=json.loads((generation/'deployment.json').read_text());expected={x['container']:x for x in inv['expected_mounts']}
    result={'success':False,'full_stack_restored':False,'generation_verified':True,'expected_active':len(definitions),'excluded':[],'startup':[],'probes':{},'host_rebuild_proven':False,'patroni_ha_proven':False,'native_restore_duration':report['duration'],'stage':'planning','reconstructed_dependencies':[],'memory_budget_bytes':budget,'phases':[],'application_recovery_validated':False,'full_stack_simultaneous':False}
    plan=[];networks={};routes={};private=target/'rehearsal-private';private.mkdir(mode=0o700,exist_ok=True)
    try:
        for c in definitions:
            name=c['name']
            if name in restored:continue
            if name in EXCLUDED_NAMES or EXCLUDED_PATTERN.search(name):result['excluded'].append({'name':name,'reason':'Host telemetry or external replication excluded'});continue
            mounts=expected[name]['mounts'];p=plan_container(c,inv,target,mounts);plan.append(p)
        # Native replacements inherit each source's exact network aliases.
        native_plans=[]
        for c in definitions:
            if c['name'] in restored:
                p=plan_container(c,inv,target,[]);native_plans.append(p)
        for p in plan+native_plans:
            for network in p['networks']:
                if network not in networks:networks[network]=create_isolated_network(s,'net-'+str(len(networks)))
        for p in native_plans:
            for network,aliases in p['networks'].items():_connect(docker,networks[network],restored[p['name']],aliases)
        original_networks=[r['name'] for r in report['resources'] if r['kind']=='network']
        for container in restored.values():
            for old_network in original_networks:docker.run(['network','disconnect',old_network,container])
        for index,p in enumerate(plan):restored[p['name']]=s.prefix+'-app-'+str(index)
        # Relay owns every internal network but has no external interface.
        for c in definitions:
            for internal,bindings in (c.get('HostConfig',{}).get('PortBindings') or {}).items():
                if not internal.endswith('/tcp'):continue
                for binding in bindings or []:
                    hostport=binding.get('HostPort')
                    if hostport and c['name'] not in EXCLUDED_NAMES:
                        route=[restored[c['name']],int(internal.split('/')[0])]
                        if hostport in routes and routes[hostport]!=route:raise BackupError('Ambiguous published port in relay')
                        routes[hostport]=route
        # Caddy originally host-network; no mapping to host is preserved.
        atomic_json(private/'routes.json',routes)
        s.network=next(iter(networks.values()));relay=s.create('container','relay')
        s.run(relay,inv['helper_image'],['-c',RELAY],[f'type=bind,src={private},dst=/routes,readonly'],['--memory','64m','--memory-swap','64m','--network-alias','s236-relay','--network-alias','host.docker.internal','--entrypoint','python3'])
        for network in list(networks.values())[1:]:_connect(docker,network,relay,['s236-relay','host.docker.internal'])
        # Create all first; DNS topology exists before starting applications.
        result['stage']='create'
        for index,p in enumerate(plan):
            name=s.create('container','app-'+str(index));env=private/(str(index)+'.env');env.write_text('\n'.join(p['environment'])+'\n');env.chmod(0o600)
            primary=next(iter(p['networks']));args=['create','--name',name,'--label',native.LABEL,'--restart','no','--network',networks[primary],'--env-file',str(env),'--memory',str(memory_limit(p['name'])),'--memory-swap',str(memory_limit(p['name'])),'--mount',f'type=bind,src={private},dst=/s236-probes,readonly']
            for alias in p['networks'][primary]:args+=['--network-alias',alias]
            for midx,m in enumerate(p['mounts']):
                if m.get('reconstruct'):
                    volume=s.create('volume','scratch-'+str(index)+'-'+str(midx));args+=['--mount','type=volume,src='+volume+',dst='+m['destination']]
                    result['reconstructed_dependencies'].append({'name':p['name'],'destination':m['destination'],'method':'Pinned image volume population; empty for caches'})
                    continue
                if not Path(m['source']).exists():raise BackupError('Restored mount missing for '+p['name'])
                args+=['--mount','type=bind,src='+m['source']+',dst='+m['destination']+(',readonly' if m['readonly'] else '')]
            for field,flag in (('user','--user'),('workdir','--workdir')):
                if p[field]:args +=[flag,p[field]]
            health=p['healthcheck'] or {};test=health.get('Test') or []
            if test and test[0]!='NONE':
                command_health=test[1] if test[0]=='CMD-SHELL' else shlex.join(test[1:])
                args+=['--health-cmd',command_health,'--health-interval','5s','--health-timeout','5s','--health-retries','30','--health-start-period','30s']
            command=p['cmd']
            if p['entrypoint']:args+=['--entrypoint',p['entrypoint'][0]];command=p['entrypoint'][1:]+command
            identity=docker.run([*args,p['image'],*command]).decode().strip()
            if not re.fullmatch('[a-f0-9]{64}',identity):raise BackupError('Invalid sandbox identity')
            s.resources.append({'kind':'container','name':name,'id':identity});restored[p['name']]=name
            for network,aliases in list(p['networks'].items())[1:]:_connect(docker,networks[network],name,aliases)
        result['stage']='start'
        # Infra dependency services start first; application processes can retry.
        order=sorted(plan,key=lambda p:(0 if any(x in p['name'] for x in ('redis','keycloak','pgbouncer','seaweedfs','dendrite')) else 2 if p['name']=='core-core-1' else 1,p['name']))
        for p in order:
            if p['name'] not in PHASED_NAMES:docker.run(['start',restored[p['name']]])
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            result['startup']=_observed(docker,{n:c for n,c in restored.items() if n not in PHASED_NAMES})
            if any(x['oom_killed'] for x in result['startup']):raise BackupError('Sandbox memory cap exceeded')
            if all(service_ready(x,native_names) for x in result['startup']):break
            time.sleep(3)
        business_probes(s,generation,definitions,restored,private,result)
        for p in order:
            if p['name'] in PHASED_NAMES:
                docker.run(['start',restored[p['name']]])
                phase_started=time.time()
                try:
                    until=time.monotonic()+180
                    while True:
                        observation=_observed(docker,{p['name']:restored[p['name']]})[0]
                        if observation['oom_killed']:raise BackupError('Phased sandbox memory cap exceeded')
                        if service_ready(observation):break
                        if time.monotonic()>until:raise BackupError('Phased readiness failed')
                        time.sleep(3)
                    phase={'name':p['name'],'healthy':True,'observation':observation,'duration':time.time()-phase_started}
                    result['phases'].append(phase)
                finally:docker.run(['stop','-t','20',restored[p['name']]],timeout=60)
                phase['stopped_after_validation']=True
        result['startup']=_observed(docker,{n:c for n,c in restored.items() if n not in PHASED_NAMES})
        if any(x['oom_killed'] for x in result['startup']):raise BackupError('Baseline service exhausted memory during probes')
        result['stage']='started'
        result['running_count']=sum(x['running'] for x in result['startup'])
        result['all_included_running']=all(x['running'] for x in result['startup'])
        result['health_checks_passed']=all(service_ready(x,native_names) for x in result['startup'])
        result['success']=result['all_included_running'] and result['health_checks_passed'] and bool(result['probes']['sqlite_crud'])
        # Auth/memory/Oria/Gateway probes must populate true before full-stack claim.
        result['application_recovery_validated']=result['success'] and all(result['probes'].get(k,{}).get('success') for k in ('core_authenticated','memory_query','oria_auth','forge_search','gateway_local')) and all(p['healthy'] for p in result['phases'])
        result['success']=result['application_recovery_validated']
        result['full_stack_restored']=False;result['full_stack_simultaneous']=False
    finally:
        result['duration']=time.time()-started;result['resources']=s.resources;result['container_map']=restored;result['network_map']=networks
        result['kept']=bool(keep)
        s.resources.sort(key=lambda r:{'network':0,'volume':1,'container':2}[r['kind']])
        result['cleanup_failed']=[] if keep else s.cleanup()
        atomic_json(target/'rehearsal-report.json',result)
        if not keep:
            for p in private.glob('*.env'):p.unlink()
            for p in (private/'tokens.json',private/'probe-config.json'):
                if p.exists():p.unlink()
            try:
                s.helper_run("import os,shutil\nfor folder,dirs,files in os.walk('/output/trees',followlinks=False):\n os.chmod(folder,0o700)\n for name in dirs:\n  path=os.path.join(folder,name)\n  if not os.path.islink(path):os.chmod(path,0o700)\nshutil.rmtree('/output/trees')",[f'type=bind,src={target},dst=/output'])
            except Exception:result['cleanup_failed'].append('restored-trees')
            report['kept']=False;report['cleanup_failed']=result['cleanup_failed'];atomic_json(target/'report.json',report)
            atomic_json(target/'rehearsal-report.json',result)
    return result


def main():
    def interrupted(signum,frame):raise BackupError('Rehearsal interrupted')
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    p=argparse.ArgumentParser();p.add_argument('--generation',type=Path,required=True);p.add_argument('--target',type=Path,required=True);p.add_argument('--keep',action='store_true');a=p.parse_args()
    try:
        r=rehearse(a.generation,a.target,keep=a.keep)
        print(json.dumps({k:r[k] for k in ('success','application_recovery_validated','full_stack_restored','full_stack_simultaneous','expected_active','duration')}));return int(not r['success'] or bool(r['cleanup_failed']))
    except Exception:print('Rehearsal failed; private report retained');return 1

# Real password-grant sessions from the restored Keycloak realms. These scripts
# run only in isolated namespaces and never emit credentials or tokens.
AUTH_BOOTSTRAP=r'''
import urllib.request,urllib.parse,json,secrets,uuid,os
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
cfg=json.load(open('/probe/probe-config.json'))
def api(base,path,method='GET',body=None,token=None,form=False):
 data=None if body is None else urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
 headers={'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json'}
 if token:headers['Authorization']='Bearer '+token
 req=urllib.request.Request(base+path,method=method,data=data,headers=headers)
 with opener.open(req,timeout=30) as r:return json.load(r) if r.status not in (201,204) else None
result={}
for kind in ('core','oria'):
 item=cfg[kind];base=item['url'];realm=item['realm'];client=item['client'];admin=item['admin']
 token=api(base,'/realms/master/protocol/openid-connect/token','POST',{'client_id':'admin-cli','grant_type':'password','username':admin['username'],'password':admin['password']},form=True)['access_token']
 clients=api(base,'/admin/realms/'+realm+'/clients?clientId='+urllib.parse.quote(client),'GET',token=token)
 assert len(clients)==1
 c=clients[0];c['directAccessGrantsEnabled']=True;c['publicClient']=True;c['standardFlowEnabled']=True
 api(base,'/admin/realms/'+realm+'/clients/'+c['id'],'PUT',c,token)
 mapper={'name':'s236-audience','protocol':'openid-connect','protocolMapper':'oidc-audience-mapper','config':{'included.client.audience':item.get('audience',client),'id.token.claim':'true','access.token.claim':'true'}}
 mappers=api(base,'/admin/realms/'+realm+'/clients/'+c['id']+'/protocol-mappers/models',token=token)
 if not any(m['name']=='s236-audience' for m in mappers):api(base,'/admin/realms/'+realm+'/clients/'+c['id']+'/protocol-mappers/models','POST',mapper,token)
 username='s236-'+uuid.uuid4().hex;password=secrets.token_urlsafe(30)
 user={'username':username,'enabled':True,'emailVerified':True,'firstName':'Rehearsal','lastName':'Isolated','email':username+'@example.invalid','credentials':[{'type':'password','temporary':False,'value':password}]}
 api(base,'/admin/realms/'+realm+'/users','POST',user,token)
 tokens=api(base,'/realms/'+realm+'/protocol/openid-connect/token','POST',{'client_id':client,'grant_type':'password','username':username,'password':password,'scope':'openid'},form=True)
 result[kind]=tokens
with open('/probe/tokens.json','w') as f:json.dump(result,f)
os.chmod('/probe/tokens.json',0o600);owner=os.stat('/probe');os.chown('/probe/tokens.json',owner.st_uid,owner.st_gid)
print(json.dumps({'keycloak_real_tokens':True}))
'''

CORE_AUTH=r'''
import json,urllib.request,urllib.error,sys
sys.path.insert(0,'/app')
import auth,session_registre
from jose import jwt
tokens=json.load(open('/s236-probes/tokens.json'))['core'];claims=jwt.get_unverified_claims(tokens['access_token']);sub=claims['sub']
generation,_=session_registre.nouvelle_session(sub,'s236-rehearsal')
cookie=auth.chiffrer_cookie({'sub':sub,'nom':'Rehearsal','refresh_token':tokens['refresh_token'],'generation':generation,'registre_id':session_registre.identifiant_registre()})
req=urllib.request.Request('http://127.0.0.1:5000/dashboard',headers={'Cookie':auth.COOKIE_SESSION+'='+cookie})
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(req,timeout=60) as r:
 assert r.status==200;assert len(r.read())>500
try:
 urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open('http://127.0.0.1:5000/dashboard',timeout=30)
 raise AssertionError('Unauthenticated dashboard unexpectedly accepted')
except urllib.error.HTTPError as e:assert e.code==303
print(json.dumps({'success':True,'real_keycloak_refresh':True,'encrypted_session':True,'dashboard_authenticated_http':200,'unauthenticated_http':303}))
'''

ORIA_AUTH=r'''
import urllib.request,urllib.error,json
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
access=json.load(open('/probe/tokens.json'))['oria']['access_token']
url='http://s236-relay:8000/api/auth/me'
with opener.open(urllib.request.Request(url,headers={'Authorization':'Bearer '+access}),timeout=30) as r:
 assert r.status==200;assert json.load(r)
try:
 opener.open(url,timeout=30);raise AssertionError('Oria accepted missing token')
except urllib.error.HTTPError as e:assert e.code in (401,403)
print(json.dumps({'success':True,'authenticated_http':200}))
'''

MEMORY_QUERY=r'''
import urllib.request,json,urllib.parse
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
cfg=json.load(open('/probe/probe-config.json'))['memory']
req=urllib.request.Request('http://s236-relay:5600/souvenirs?limite=2',headers={'Authorization':'Bearer '+cfg['key'],'X-User-Id':'perso'})
with opener.open(req,timeout=60) as r:
 result=json.load(r);assert r.status==200 and 'souvenirs' in result
print(json.dumps({'success':True,'query_http':200,'results_count':result.get('total',len(result.get('souvenirs',[]))),'scope':'Authenticated restored Memory database listing; no embedding inference'}))
'''


LOCAL_OPENAI_FIXTURE=r'''
from http.server import BaseHTTPRequestHandler,HTTPServer
import json,time
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
  data={'id':'s236-local-protocol','object':'chat.completion','created':int(time.time()),'model':body.get('model','s236-local'),'choices':[{'index':0,'message':{'role':'assistant','content':'s236-local-protocol-ok'},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
  encoded=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
HTTPServer(('0.0.0.0',8088),Handler).serve_forever()
'''

GATEWAY_LOCAL=r'''
import urllib.request,json,uuid
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
key=json.load(open('/probe/probe-config.json'))['gateway']['key'];base='http://s236-relay:4001'
def api(path,body=None):
 req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 with opener.open(req,timeout=60) as r:return json.load(r)
models=api('/v1/models');assert 'data' in models
name='s236-local-protocol-'+uuid.uuid4().hex
entry=api('/model/new',{'model_name':name,'litellm_params':{'model':'openai/s236-local','api_base':'http://s236-local-fixture:8088/v1','api_key':'isolated-fixture'}})
try:
 result=api('/v1/chat/completions',{'model':name,'messages':[{'role':'user','content':'local protocol probe'}],'max_tokens':8})
 assert result['choices'][0]['message']['content']=='s236-local-protocol-ok'
finally:
 identifier=entry.get('model_info',{}).get('id')
 if identifier:api('/model/delete',{'id':identifier})
print(json.dumps({'success':True,'scope':'Local OpenAI fixture through real LiteLLM HTTP/auth/database/routing; no model inference','paid_calls':0,'restored_model_count':len(models['data'])}))
'''


def business_probes(s,generation,definitions,restored,private,result):
    envs={c['name']:dict(raw.split('=',1) for raw in c['Config'].get('Env',[])) for c in definitions}
    core=envs['core-core-1'];oria=envs['oria-backend-1']
    def kc_config(values,keycloak,url):
        admin=envs[keycloak]
        return {'url':url,'realm':values['KEYCLOAK_REALM'],'client':values['KEYCLOAK_CLIENT_ID'],'audience':values.get('KEYCLOAK_AUDIENCE') or values['KEYCLOAK_CLIENT_ID'],'admin':{'username':admin.get('KC_BOOTSTRAP_ADMIN_USERNAME',admin.get('KEYCLOAK_ADMIN')),'password':admin.get('KC_BOOTSTRAP_ADMIN_PASSWORD',admin.get('KEYCLOAK_ADMIN_PASSWORD'))}}
    config={'core':kc_config(core,'keycloak','http://s236-relay:8080'),'oria':kc_config(oria,'oria-keycloak-1','http://s236-relay:8081'),'memory':{'key':core.get('MEMOIRE_KEY','')},'gateway':{'key':envs['gateway-gateway-1']['LITELLM_MASTER_KEY']}}
    atomic_json(private/'probe-config.json',config)
    mounts=[f'type=bind,src={private},dst=/probe']
    network='container:'+restored['core-core-1']
    result['stage']='keycloak_tokens'
    result['probes']['keycloak_tokens']=json.loads(s.wait(lambda:s.helper_run(AUTH_BOOTSTRAP,mounts,network)))
    (private/'tokens.json').chmod(0o600)
    result['stage']='sqlite_crud'
    result['probes']['sqlite_crud']=json.loads(s.helper_run(SQLITE_CRUD,[f'type=bind,src={private},dst=/probe,readonly'],'container:'+restored['workplace_donnees']))
    result['stage']='core_authenticated'
    result['probes']['core_authenticated']=json.loads(s.wait(lambda:s.d.run(['exec',restored['core-core-1'],'python3','-c',CORE_AUTH])))
    result['stage']='oria_auth'
    result['probes']['oria_auth']=json.loads(s.wait(lambda:s.helper_run(ORIA_AUTH,mounts,network)))
    result['stage']='memory_query'
    result['probes']['memory_query']=json.loads(s.wait(lambda:s.helper_run(MEMORY_QUERY,mounts,network)))
    gateway_network=s.d.run(['inspect','--format','{{json .NetworkSettings.Networks}}',restored['gateway-gateway-1']])
    s.network=next(iter(json.loads(gateway_network)))
    fixture=s.create('container','local-fixture')
    s.run(fixture,s.helper,['-c',LOCAL_OPENAI_FIXTURE],extra=['--network-alias','s236-local-fixture','--entrypoint','python3','--memory','64m','--memory-swap','64m'])
    result['stage']='gateway_local'
    result['probes']['gateway_local']=json.loads(s.wait(lambda:s.helper_run(GATEWAY_LOCAL,mounts,network)))
    qpath=generation/'qdrant'
    result['stage']='forge_search'
    result['probes']['forge_search']={'success':True,**json.loads(s.wait(lambda:s.helper_run(native.QVERIFY,[f'type=bind,src={qpath},dst=/snapshots,readonly'],'container:'+restored['forge-qdrant-1'])))}

if __name__=='__main__':raise SystemExit(main())
