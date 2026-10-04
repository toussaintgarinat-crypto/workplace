import base64
import importlib.util
import json
from pathlib import Path
import urllib.request
from urllib.parse import urlencode

root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('cfg',root/'kuma-config.py')
cfg=importlib.util.module_from_spec(spec);spec.loader.exec_module(cfg)
env=cfg.read_env(root/'.env')
auth=base64.b64encode((env['GRAFANA_USER']+':'+env['GRAFANA_PASSWORD']).encode()).decode()

def fetch(path, grafana=False, payload=None):
    base='http://192.168.1.89:3001' if grafana else 'http://192.168.1.89:9090'
    headers={'Authorization':'Basic '+auth} if grafana else {}
    data=None
    if payload:
        headers['Content-Type']='application/json';data=json.dumps(payload).encode()
    with urllib.request.urlopen(urllib.request.Request(base+path,headers=headers,data=data),timeout=30) as response:
        return json.load(response)

print('Vérification LIVE de la supervision HP')
targets=fetch('/api/v1/targets')['data']['activeTargets']
print('Scrapes:',[(x['labels']['job'],x['health']) for x in targets])
assert len(targets)==3 and all(t['health']=='up' for t in targets)
for expr in ['node_memory_MemTotal_bytes','node_filesystem_size_bytes{mountpoint="/"}','workplace_tache_age_secondes']:
    data=fetch('/api/v1/query?'+urlencode({'query':expr}))['data']['result']
    assert data,expr
    print('Métrique présente:',expr,'séries',len(data))
print('Grafana health:',fetch('/api/health',True)['database'])
for uid in ['workplace-parc','workplace-hote']:
    dashboard=fetch('/api/dashboards/uid/'+uid,True)['dashboard']
    print('Tableau:',dashboard['title'],'panneaux',len(dashboard['panels']))
    for panel in dashboard['panels']:
        for target in panel.get('targets',[]):
            if not target.get('expr'):continue
            body={'from':'now-15m','to':'now','queries':[{'refId':'A','expr':target['expr'],'instant':True,'format':'table','datasource':{'type':'prometheus','uid':'workplace-prometheus'}}]}
            result=fetch('/api/ds/query',True,body)['results']['A']
            assert not result.get('error'),result.get('error')
            frames=result.get('frames',[])
            rows=sum(len((frame.get('data',{}).get('values') or [[]])[0]) for frame in frames)
            print('  Requête Grafana:',panel['title'],'lignes',rows)
            if uid=='workplace-hote':assert rows>0
print('Vérifications métriques et Grafana OK')
