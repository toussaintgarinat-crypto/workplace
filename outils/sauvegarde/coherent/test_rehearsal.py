import pytest
from pathlib import Path
import rehearsal

def test_mounts_never_use_production(tmp_path):
 inv={'repository':{'id':'repository','source':'/production/repo'},'trees':[{'id':'data','kind':'volume','source':'appdata'}]}
 assert rehearsal.map_mount({'Type':'bind','Source':'/production/repo/config','Destination':'/app/config'},inv,tmp_path)['source']==str(tmp_path/'trees/repository/restored/config')
 assert rehearsal.map_mount({'Type':'volume','Name':'appdata','Destination':'/data'},inv,tmp_path)['source']==str(tmp_path/'trees/data/restored')
 assert rehearsal.map_mount({'Type':'bind','Source':'/var/run/docker.sock','Destination':'/var/run/docker.sock'},inv,tmp_path) is None
 with pytest.raises(rehearsal.BackupError):rehearsal.map_mount({'Type':'bind','Source':'/home/debian/private','Destination':'/private'},inv,tmp_path)

def test_host_network_is_replaced_not_copied(tmp_path):
 c={'name':'caddy','image_id':'sha256:abc','Config':{'Env':['URL=http://192.168.1.89:5100'],'Cmd':[]},'HostConfig':{'NetworkMode':'host','Privileged':True,'PortBindings':{'80/tcp':[{'HostPort':'80'}]}},'NetworkSettings':{'Networks':{'host':{'Aliases':None}}}}
 p=rehearsal.plan_container(c,{'repository':{'id':'repository','source':'/repo'},'trees':[]},tmp_path,[])
 assert p['networks']=={'rehearsal': ['caddy']}
 assert '192.168.1.89' not in p['environment'][0]
 assert 'HostConfig' not in p

def test_cache_reconstruction_explicit_only(tmp_path):
 inv={'repository':{'id':'repository','source':'/repo'},'trees':[],'classified_mounts':[{'owners':[{'container':'frontend','destination':'/workspace/oria/frontend/node_modules'}]}]}
 m=rehearsal.map_mount({'Type':'volume','Name':'old','Destination':'/workspace/oria/frontend/node_modules'},inv,tmp_path)
 assert m['reconstruct']=='image-or-empty-cache' and m['source'] is None
 with pytest.raises(rehearsal.BackupError):rehearsal.map_mount({'Type':'volume','Name':'old','Destination':'/database'},inv,tmp_path)

def test_isolated_network_removes_host_gateway(tmp_path):
 class Fake:
  def __init__(self):self.calls=[]
  def run(self,args):self.calls.append(args);return b''
 fake=Fake();session=rehearsal.native.Session(fake,tmp_path,'helper');name=rehearsal.create_isolated_network(session,'test')
 create=fake.calls[-1]
 assert '--internal' in create and 'com.docker.network.bridge.gateway_mode_ipv4=isolated' in create
 assert session.resources==[{'kind':'network','name':name}]

def test_all_services_budget_is_bounded():
 names=['core-core-1','oria-db-1','forge-qdrant-1','keycloak','worker']
 assert rehearsal.memory_budget([{'name':n} for n in names]) < 3*1024**3


def test_phase_budget_does_not_sum_stopped_services():
 names=['core-core-1','workplace_audit_fichiers_clamav','workplace_voix','workplace_ecoute']
 budget=rehearsal.memory_budget([{'name':n} for n in names])
 assert budget == rehearsal.memory_limit('core-core-1') + rehearsal.memory_limit('workplace_audit_fichiers_clamav') + 512*1024**2
 assert budget < sum(rehearsal.memory_limit(n) for n in names)

def test_manual_guard_rejects_replacement_without_mutation():
 name='s236-'+'a'*32+'-app-1'
 class Fake:
  def __init__(self):self.calls=[]
  def run(self,args):
   import json
   self.calls.append(args)
   return json.dumps([{'Id':'replacement','Name':'/'+name,'Config':{'Labels':{'workplace.s236':'true'}}}]).encode()
 fake=Fake()
 with pytest.raises(rehearsal.BackupError):rehearsal.validate_owned_resources(fake,[{'kind':'container','name':name,'id':'original'}])
 assert fake.calls==[['inspect',name]]

def test_manual_guard_rejects_extra_production_network():
 import json
 name='s236-'+'b'*32+'-app-1'
 class Fake:
  def run(self,args):return json.dumps([{'Id':'id','Name':'/'+name,'Config':{'Labels':{'workplace.s236':'true'}},'HostConfig':{'NetworkMode':'safe'},'NetworkSettings':{'Networks':{'production':{}}}}]).encode()
 with pytest.raises(rehearsal.BackupError):rehearsal.validate_owned_resources(Fake(),[{'kind':'container','name':name,'id':'id'}])

def test_sqlite_probe_uses_real_token_and_completes_crud(monkeypatch):
 import io,json,urllib.request
 from unittest.mock import patch
 items=[];calls=[]
 class Response(io.StringIO):
  status=200
 def execute(req,timeout):
  calls.append((req.get_method(),req.get_header('Authorization')))
  assert req.get_header('Authorization')=='Bearer signed-keycloak-token'
  method=req.get_method()
  if method=='POST':items.append({'_id':'record',**json.loads(req.data)});value=items[0]
  elif method=='PUT':items[0].update(json.loads(req.data));value=items[0]
  elif method=='DELETE':items.clear();value={}
  else:value=items
  return Response(json.dumps(value))
 class Opener:
  open=staticmethod(execute)
 with patch('builtins.open',return_value=io.StringIO(json.dumps({'core':{'access_token':'signed-keycloak-token'}}))),patch.object(urllib.request,'build_opener',return_value=Opener()):
  exec(rehearsal.SQLITE_CRUD,{})
 assert [method for method,token in calls]==['POST','GET','PUT','GET','DELETE','GET']
 assert items==[]

def test_frontend_watchers_use_polling_without_host_sysctl(tmp_path):
 c={'name':'oria-frontend-1','image_id':'sha256:abc','Config':{'Env':['CHOKIDAR_USEPOLLING=false']}}
 p=rehearsal.plan_container(c,{'repository':{'id':'repository','source':'/repo'},'trees':[]},tmp_path,[])
 assert p['environment'].count('CHOKIDAR_USEPOLLING=true')==1
 assert 'CHOKIDAR_USEPOLLING=false' not in p['environment']

def test_application_readiness_cannot_skip_healthcheck():
 state={'name':'app','running':True,'health':'none','oom_killed':False}
 assert not rehearsal.service_ready(state,{'postgres'})
 state['name']='postgres'
 assert rehearsal.service_ready(state,{'postgres'})
 state.update(name='app',health='healthy')
 assert rehearsal.service_ready(state,{'postgres'})
 state['oom_killed']=True
 assert not rehearsal.service_ready(state,{'postgres'})
