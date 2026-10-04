#!/usr/bin/env python3
"""Authenticated business probes on the deployed S237 exercise (after deploy).

Adapted from the S236 rehearsal probes: real Keycloak password-grant sessions
on the restored realms, authenticated Core dashboard, Données CRUD, Oria
identity, Memory listing, Gateway protocol through a local fake provider and a
Qdrant vector search. Probes run in helper containers attached only to internal
exercise networks. Credentials and tokens stay in a private 0600 directory that
is removed afterwards; stdout and the report contain booleans and counts only.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path('/srv/workplace-rehearsal')
NETWORK = 's237-workplace'
RELAY = 'http://host.docker.internal'

AUTH_BOOTSTRAP = r'''
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
 mapper={'name':'s237-audience','protocol':'openid-connect','protocolMapper':'oidc-audience-mapper','config':{'included.client.audience':item.get('audience',client),'id.token.claim':'true','access.token.claim':'true'}}
 mappers=api(base,'/admin/realms/'+realm+'/clients/'+c['id']+'/protocol-mappers/models',token=token)
 if not any(m['name']=='s237-audience' for m in mappers):api(base,'/admin/realms/'+realm+'/clients/'+c['id']+'/protocol-mappers/models','POST',mapper,token)
 username='s237-'+uuid.uuid4().hex;password=secrets.token_urlsafe(30)
 user={'username':username,'enabled':True,'emailVerified':True,'firstName':'Rehearsal','lastName':'Isolated','email':username+'@example.invalid','credentials':[{'type':'password','temporary':False,'value':password}]}
 api(base,'/admin/realms/'+realm+'/users','POST',user,token)
 result[kind]=api(base,'/realms/'+realm+'/protocol/openid-connect/token','POST',{'client_id':client,'grant_type':'password','username':username,'password':password,'scope':'openid'},form=True)
with open('/probe/tokens.json','w') as f:json.dump(result,f)
os.chmod('/probe/tokens.json',0o600)
print(json.dumps({'success':True,'keycloak_real_tokens':True}))
'''

SQLITE_CRUD = r'''
import urllib.request,json,uuid
token=json.load(open('/probe/tokens.json'))['core']['access_token']
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
base='http://127.0.0.1:5500/apps/s237-'+uuid.uuid4().hex+'/entites/rehearsal/enregistrements'
def api(path,method='GET',body=None):
 req=urllib.request.Request(path,method=method,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
 with opener.open(req,timeout=30) as r:return None if r.status==204 else json.load(r)
x=api(base,'POST',{'name':'restored-business-probe','value':237})
identifier=x.get('_id',x.get('id'));assert identifier
assert any(i.get('_id',i.get('id'))==identifier for i in api(base))
api(base+'/'+identifier,'PUT',{'name':'restored-business-probe','value':238})
assert any(i.get('value')==238 for i in api(base))
api(base+'/'+identifier,'DELETE');assert not any(i.get('_id',i.get('id'))==identifier for i in api(base))
print(json.dumps({'success':True,'sqlite_crud':True}))
'''

# Runs inside the Core container (its own session code); tokens arrive on stdin.
CORE_AUTH = r'''
import json,urllib.request,urllib.error,sys
sys.path.insert(0,'/app')
import auth,session_registre
from jose import jwt
tokens=json.load(sys.stdin)['core'];sub=jwt.get_unverified_claims(tokens['access_token'])['sub']
generation,_=session_registre.nouvelle_session(sub,'s237-rehearsal')
cookie=auth.chiffrer_cookie({'sub':sub,'nom':'Rehearsal','refresh_token':tokens['refresh_token'],'generation':generation,'registre_id':session_registre.identifiant_registre()})
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
with opener.open(urllib.request.Request('http://127.0.0.1:5000/dashboard',headers={'Cookie':auth.COOKIE_SESSION+'='+cookie}),timeout=60) as r:
 assert r.status==200;assert len(r.read())>500
try:
 opener.open('http://127.0.0.1:5000/dashboard',timeout=30);raise AssertionError('unauthenticated dashboard accepted')
except urllib.error.HTTPError as e:assert e.code==303
print(json.dumps({'success':True,'dashboard_authenticated_http':200,'unauthenticated_http':303}))
'''

ORIA_AUTH = r'''
import urllib.request,urllib.error,json
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
access=json.load(open('/probe/tokens.json'))['oria']['access_token']
url='http://host.docker.internal:8000/api/auth/me'
with opener.open(urllib.request.Request(url,headers={'Authorization':'Bearer '+access}),timeout=30) as r:
 assert r.status==200;assert json.load(r)
try:
 opener.open(url,timeout=30);raise AssertionError('Oria accepted missing token')
except urllib.error.HTTPError as e:assert e.code in (401,403)
print(json.dumps({'success':True,'authenticated_http':200}))
'''

MEMORY_QUERY = r'''
import urllib.request,json
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
key=json.load(open('/probe/probe-config.json'))['memory']['key']
req=urllib.request.Request('http://host.docker.internal:5600/souvenirs?limite=2',headers={'Authorization':'Bearer '+key,'X-User-Id':'perso'})
with opener.open(req,timeout=60) as r:
 result=json.load(r);assert r.status==200 and 'souvenirs' in result
print(json.dumps({'success':True,'results_count':result.get('total',len(result.get('souvenirs',[])))}))
'''

LOCAL_OPENAI_FIXTURE = r'''
from http.server import BaseHTTPRequestHandler,HTTPServer
import json,time
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
  data={'id':'s237-local-protocol','object':'chat.completion','created':int(time.time()),'model':body.get('model','s237-local'),'choices':[{'index':0,'message':{'role':'assistant','content':'s237-local-protocol-ok'},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
  encoded=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
HTTPServer(('0.0.0.0',8088),Handler).serve_forever()
'''

GATEWAY_LOCAL = r'''
import urllib.request,json,uuid
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
key=json.load(open('/probe/probe-config.json'))['gateway']['key'];base='http://host.docker.internal:4001'
def api(path,body=None):
 req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 with opener.open(req,timeout=60) as r:return json.load(r)
models=api('/v1/models');assert 'data' in models
name='s237-local-protocol-'+uuid.uuid4().hex
entry=api('/model/new',{'model_name':name,'litellm_params':{'model':'openai/s237-local','api_base':'http://s237-local-fixture:8088/v1','api_key':'isolated-fixture'}})
try:
 result=api('/v1/chat/completions',{'model':name,'messages':[{'role':'user','content':'local protocol probe'}],'max_tokens':8})
 assert result['choices'][0]['message']['content']=='s237-local-protocol-ok'
finally:
 identifier=entry.get('model_info',{}).get('id')
 if identifier:api('/model/delete',{'id':identifier})
print(json.dumps({'success':True,'paid_calls':0,'restored_model_count':len(models['data'])}))
'''

QDRANT_SEARCH = r'''
import urllib.request,urllib.parse,json,math
meta=json.load(open('/snapshots/meta.json'))
def api(path,body=None):
 req=urllib.request.Request('http://127.0.0.1:6333'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)['result']
searches=0
for c in meta['collections']:
 p='/collections/'+urllib.parse.quote(c['name'],safe='')
 assert api(p)['points_count']==c['info']['points_count']
 for point in c['sample']['points'][:1]:
  vector=point['vector'];vectors=[{'name':k,'vector':v} for k,v in vector.items()] if isinstance(vector,dict) else [vector]
  for v in vectors:
   hits=api(p+'/points/search',{'vector':v,'limit':10});assert any(h['id']==point['id'] and math.isfinite(h['score']) for h in hits);searches+=1
print(json.dumps({'success':True,'collections':len(meta['collections']),'searches':searches}))
'''


# S3 round trip (SigV4, stdlib only) inside the SeaweedFS network namespace:
# bucket and object are created, read back, then removed.
S3_ROUNDTRIP = r'''
import datetime,hashlib,hmac,json,urllib.request,urllib.error,uuid
cfg=json.load(open('/probe/probe-config.json'))['s3']
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def call(method,path,body=b''):
 now=datetime.datetime.now(datetime.timezone.utc);stamp=now.strftime('%Y%m%dT%H%M%SZ');day=stamp[:8]
 digest=hashlib.sha256(body).hexdigest();host='127.0.0.1:8333'
 canonical='\n'.join([method,path,'','host:'+host,'x-amz-content-sha256:'+digest,'x-amz-date:'+stamp,'','host;x-amz-content-sha256;x-amz-date',digest])
 scope=day+'/us-east-1/s3/aws4_request'
 key=('AWS4'+cfg['secret']).encode()
 for part in (day,'us-east-1','s3','aws4_request'):key=hmac.new(key,part.encode(),hashlib.sha256).digest()
 signature=hmac.new(key,('AWS4-HMAC-SHA256\n'+stamp+'\n'+scope+'\n'+hashlib.sha256(canonical.encode()).hexdigest()).encode(),hashlib.sha256).hexdigest()
 auth='AWS4-HMAC-SHA256 Credential='+cfg['key']+'/'+scope+', SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature='+signature
 req=urllib.request.Request('http://'+host+path,data=body if method=='PUT' else None,method=method,headers={'x-amz-date':stamp,'x-amz-content-sha256':digest,'Authorization':auth})
 with opener.open(req,timeout=30) as r:return r.status,r.read()
bucket='s237-probe-'+uuid.uuid4().hex[:12];payload=('restored-s3-probe '+uuid.uuid4().hex).encode()
try:
 opener.open('http://127.0.0.1:8333/',timeout=10);raise AssertionError('anonymous S3 listing accepted')
except urllib.error.HTTPError as e:assert e.code==403
call('PUT','/'+bucket)
try:
 call('PUT','/'+bucket+'/probe.txt',payload)
 status,body=call('GET','/'+bucket+'/probe.txt');assert status==200 and body==payload
 call('DELETE','/'+bucket+'/probe.txt')
finally:
 call('DELETE','/'+bucket)
print(json.dumps({'success':True,'s3_roundtrip':True,'anonymous_http':403}))
'''

def docker(*args, stdin=None, timeout=180):
    result = subprocess.run(['docker', *args], input=stdin, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError('docker ' + args[0] + ' failed')
    return result.stdout.strip()


def container(project, service):
    ids = docker('ps', '-q', '--filter', 'label=com.docker.compose.project=s237-' + project, '--filter', 'label=com.docker.compose.service=' + service).split()
    if len(ids) != 1:
        raise RuntimeError('expected one running container for ' + project + '/' + service)
    return ids[0]


def environment(identifier):
    env = json.loads(docker('inspect', identifier))[0]['Config']['Env']
    return dict(item.split('=', 1) for item in env if '=' in item)


def helper(image, script, network, mounts, retries=60):
    args = ['run', '--rm', '--network', network, '--user', '65534:65534', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--label', 's237.owner=rehearsal']
    for mount in mounts:
        args += ['--mount', mount]
    deadline = time.monotonic() + retries * 2
    while True:
        try:
            return json.loads(docker(*args, image, 'python3', '-c', script).splitlines()[-1])
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def probes(config):
    image = config['probe_image']
    private = ROOT / 'private' / ('probes-' + uuid.uuid4().hex)
    private.mkdir(mode=0o700)
    os.chown(private, 65534, 65534)  # helper runs unprivileged as nobody
    report = {'success': False, 'probes': {}}
    fixture = None
    try:
        core_env = environment(container('core', 'core'))
        oria_env = environment(container('oria', 'backend'))
        def kc(values, project, service, port):
            admin = environment(container(project, service))
            return {'url': RELAY + ':' + str(port), 'realm': values['KEYCLOAK_REALM'], 'client': values['KEYCLOAK_CLIENT_ID'],
                    'audience': values.get('KEYCLOAK_AUDIENCE') or values['KEYCLOAK_CLIENT_ID'],
                    'admin': {'username': admin.get('KC_BOOTSTRAP_ADMIN_USERNAME', admin.get('KEYCLOAK_ADMIN')),
                              'password': admin.get('KC_BOOTSTRAP_ADMIN_PASSWORD', admin.get('KEYCLOAK_ADMIN_PASSWORD'))}}
        s3_env = environment(container('oria', 'seaweedfs'))
        probe_config = {'core': kc(core_env, 'keycloak', 'keycloak', 8080), 'oria': kc(oria_env, 'oria', 'keycloak', 8081),
                        'memory': {'key': core_env.get('MEMOIRE_KEY', '')},
                        'gateway': {'key': environment(container('gateway', 'gateway'))['LITELLM_MASTER_KEY']},
                        's3': {'key': s3_env['AWS_ACCESS_KEY_ID'], 'secret': s3_env['AWS_SECRET_ACCESS_KEY']}}
        path = private / 'probe-config.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(probe_config, stream)
        os.chown(path, 65534, 65534)
        rw = ['type=bind,src=' + str(private) + ',dst=/probe']
        ro = ['type=bind,src=' + str(private) + ',dst=/probe,readonly']
        report['probes']['keycloak_tokens'] = helper(image, AUTH_BOOTSTRAP, NETWORK, rw)
        tokens = (private / 'tokens.json').read_text()
        report['probes']['core_authenticated'] = json.loads(docker('exec', '-i', container('core', 'core'), 'python3', '-c', CORE_AUTH, stdin=tokens).splitlines()[-1])
        report['probes']['sqlite_crud'] = helper(image, SQLITE_CRUD, 'container:' + container('donnees', 'donnees'), ro)
        report['probes']['oria_auth'] = helper(image, ORIA_AUTH, NETWORK, ro)
        report['probes']['memory_query'] = helper(image, MEMORY_QUERY, NETWORK, ro)
        fixture = 's237-local-fixture-' + uuid.uuid4().hex[:8]
        docker('run', '-d', '--name', fixture, '--label', 's237.owner=rehearsal', '--network', NETWORK, '--network-alias', 's237-local-fixture',
               '--cap-drop', 'ALL', '--user', '65534:65534', image, 'python3', '-c', LOCAL_OPENAI_FIXTURE)
        report['probes']['gateway_local'] = helper(image, GATEWAY_LOCAL, NETWORK, ro)
        snapshots = ROOT / 'backups/recovered/qdrant'
        report['probes']['forge_search'] = helper(image, QDRANT_SEARCH, 'container:' + container('forge', 'qdrant'), ['type=bind,src=' + str(snapshots) + ',dst=/snapshots,readonly'])
        report['probes']['oria_s3'] = helper(image, S3_ROUNDTRIP, 'container:' + container('oria', 'seaweedfs'), ro)
        report['success'] = all(p.get('success') for p in report['probes'].values()) and len(report['probes']) == 8
    except Exception as error:
        report['failure'] = type(error).__name__ + ': ' + str(error)[:200]
        report['stage'] = list(report['probes'])[-1] if report['probes'] else 'setup'
    finally:
        if fixture:
            subprocess.run(['docker', 'rm', '-f', fixture], capture_output=True)
        shutil.rmtree(private, ignore_errors=True)
    path = ROOT / 'state/business.json'
    fd = os.open(path.with_suffix('.tmp'), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
    os.replace(path.with_suffix('.tmp'), path)
    return report


if __name__ == '__main__':
    config = json.load(sys.stdin)
    result = probes(config)
    print(json.dumps({'success': result['success'], 'probes': {k: bool(v.get('success')) for k, v in result['probes'].items()}, 'failure': result.get('failure')}))
    sys.exit(0 if result['success'] else 1)
