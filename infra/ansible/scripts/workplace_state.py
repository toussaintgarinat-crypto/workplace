#!/usr/bin/env python3
"""Private rehearsal state. No shell evaluation; stdout contains counts only."""
import argparse
import base64
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse


def relative(value):
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or not value:
        raise ValueError('unsafe relative path')
    return value


def guard(c):
    if c['group'] != 'rehearsal': raise ValueError('explicit rehearsal group required')
    if 'revision' in c and not re.fullmatch(r'[0-9a-f]{40}',c['revision']): raise ValueError('full Git SHA required')
    if c['root'] != '/srv/workplace-rehearsal': raise ValueError('dedicated root required')
    if not re.fullmatch(r'[0-9a-f]{32}',c['expected_machine_id']) or c['expected_machine_id']=='f0490b65d4414f4fa4db80bdc3f75da6' or c['machine_id'] != c['expected_machine_id']:
        raise ValueError('machine identity mismatch')
    if not c['addresses']: raise ValueError('resolved address required')
    denied = set(c['denied']) | {'192.168.1.89'}
    for address in c['addresses']:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast or address in denied or ip in ipaddress.ip_network('100.64.0.0/10'):
            raise ValueError('production, mesh or local address refused')


def catalogue(c):
    if not c: raise ValueError('empty catalogue')
    seen=[]
    for name, p in c.items():
        if name in ('mesh-https','notifications','notification'): raise ValueError('external side-effect project excluded')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',name): raise ValueError('unsafe project name')
        relative(p['directory'])
        if not p['files'] or not p['services']: raise ValueError('files and services required')
        for file in p['files']: relative(file)
        for dep in p.get('dependencies',[]):
            if dep not in seen: raise ValueError('unknown or unordered dependency')
        seen.append(name)
    return c


RELAY_ALIAS='host.docker.internal'
SHARED_NETWORK='workplace'


def service_alias(project, service):
    return 's237-'+project+'-'+service


def published_routes(models):
    """Map each originally published host port to its internal service endpoint."""
    routes={}
    for project, model in models.items():
        for name, service in model['services'].items():
            for port in service.get('ports',[]):
                if isinstance(port,str):
                    parts=port.split(':'); target=parts[-1]; published=parts[-2] if len(parts)>1 else None
                    port={'target':int(target.split('/')[0]),'protocol':target.split('/')[1] if '/' in target else 'tcp','published':published}
                if port.get('protocol','tcp')!='tcp' or not port.get('published'): continue
                route=[service_alias(project,name),int(port['target'])]
                key=str(port['published'])
                if routes.get(key,route)!=route: raise ValueError('ambiguous published port: '+key)
                routes[key]=route
    return dict(sorted(routes.items(),key=lambda item:int(item[0])))


def topology(model, private, project, relay):
    """Explicit exercise adaptations, all declared in the reviewed profile."""
    result=copy.deepcopy(model)
    for name, service in result['services'].items():
        for target, reason in private.get('drop_mounts',{}).get(name,{}).items():
            if not reason: raise ValueError('mount removal reason required')
            kept=[v for v in service.get('volumes',[]) if v.get('target')!=target]
            if len(kept)==len(service.get('volumes',[])): raise ValueError('declared mount removal not found: '+name+' '+target)
            service['volumes']=kept
        for target, key in private.get('add_volumes',{}).get(name,{}).items():
            existing=[v for v in service.get('volumes',[]) if v.get('target')==target]
            if existing and (existing[0].get('type')!='volume' or existing[0].get('source')): raise ValueError('implicit volume already explicit: '+target)
            if existing: existing[0]['source']=key  # anonymous Compose volume becomes named and restorable
            else: service.setdefault('volumes',[]).append({'type':'volume','source':key,'target':target})
            result.setdefault('volumes',{}).setdefault(key,{})
        for vol in service.get('volumes',[]):
            if vol.get('type')=='volume' and not vol.get('source'): raise ValueError('anonymous volume must be named in the profile: '+name+' '+vol.get('target',''))
        for dependency, reason in private.get('drop_depends_on',{}).get(name,{}).items():
            if not reason or dependency not in (service.get('depends_on') or {}): raise ValueError('declared dependency removal invalid: '+name)
            service['depends_on'].pop(dependency)
        reason=private.get('drop_static_ips',{}).get(name)
        static=[n for n,v in (service.get('networks') or {}).items() if v and (v.get('ipv4_address') or v.get('ipv6_address'))]
        if static and not reason: raise ValueError('undeclared static address: '+name)
        for network in static:
            service['networks'][network].pop('ipv4_address',None); service['networks'][network].pop('ipv6_address',None)
        hosts=service.pop('extra_hosts',None) or {}
        if isinstance(hosts,list): hosts=dict(item.replace('=',':',1).split(':',1) for item in hosts)
        dropped=set(private.get('drop_extra_hosts',{}).get(name,[]))
        remaining={h:v for h,v in hosts.items() if v!='host-gateway' and h not in dropped}
        if remaining: raise ValueError('undeclared extra host: '+name)
        if relay:
            environment=service.get('environment') or {}
            for key,value in environment.items():
                if isinstance(value,str): environment[key]=value.replace('192.168.1.89',RELAY_ALIAS)
            networks=service.get('networks') or {'default':None}
            existing=networks.get(SHARED_NETWORK) or {}
            networks[SHARED_NETWORK]={**existing,'aliases':sorted(set(existing.get('aliases') or [])|{service_alias(project,name)})}
            service['networks']=networks
    if relay: result.setdefault('networks',{}).setdefault(SHARED_NETWORK,{})
    return result


def overlay(model, mappings, root, project, relay=False):
    """Return a fully resolved private model; never merge with unsafe original options."""
    result=copy.deepcopy(model)
    for service in result['services'].values():
        # Docker never publishes ports of containers attached only to internal
        # bridges: probes use bridge addresses, inter-project calls use the relay.
        service.pop('ports',None)
    forbidden=('host-gateway','192.168.1.89','100.124.248.226')+(() if relay else (RELAY_ALIAS,))
    def locate(value,path):
        # Report where an endpoint remains, never the surrounding value.
        if isinstance(value,dict):
            for k,v in value.items(): yield from locate(v,path+[str(k)])
        elif isinstance(value,list):
            for i,v in enumerate(value): yield from locate(v,path+[str(i)])
        elif isinstance(value,str) and any(endpoint in value for endpoint in forbidden): yield '/'.join(path)
    found=list(locate(result,[]))
    if found: raise ValueError('unmapped host gateway or production endpoint in '+project+': '+', '.join(found[:12]))
    result.pop('name',None)
    networks=result.setdefault('networks',{})
    networks.setdefault('default',{})
    for name in list(networks):
        networks[name]={'name':'s237-'+(project+'-default' if name=='default' else name), 'external':True}
        # External networks are created and independently inspected as internal.
        networks[name]['internal']=True
    for name, service in result['services'].items():
        if service.get('privileged') or service.get('network_mode') or service.get('pid') or service.get('ipc') or service.get('devices') or service.get('cap_add'):
            raise ValueError('host access service refused: '+name)
        service.pop('container_name',None)
        service.pop('restart',None)
        service['restart']='no'
        service.pop('profiles',None)
        for vol in service.get('volumes',[]):
            if not isinstance(vol,dict): raise ValueError('resolved Compose model required')
            if vol['type']=='bind':
                source=vol['source']
                if source not in mappings: raise ValueError('explicit bind mapping required: '+source)
                mapping=mappings[source]
                if isinstance(mapping,str): mapping={'kind':'data','path':mapping}
                destination=relative(mapping['path'])
                if mapping['kind']=='data': vol['source']=root+'/data/'+destination
                elif mapping['kind']=='release':
                    if not vol.get('read_only'): raise ValueError('release bind must be read-only')
                    vol['source']=root+'/releases/'+destination
                else: raise ValueError('unknown bind mapping kind')
                if any(x in source for x in ('docker.sock','/proc','/sys','/dev','/etc','/run')): raise ValueError('host mount refused')
                if Path(vol['source']).is_symlink(): raise ValueError('symlink data refused')
            elif vol['type']!='volume': raise ValueError('unsupported mount')
    for name in result.get('volumes',{}):
        result['volumes'][name]={'name':'s237-'+project+'-'+name}
    return result


def publish(old, project, entry, verified):
    if not verified: raise ValueError('verification required')
    new=copy.deepcopy(old); projects=new.setdefault('projects',{})
    prior=projects.get(project)
    if prior:
        entry=copy.deepcopy(entry); entry['previous']={k:v for k,v in prior.items() if k!='previous'}
    projects[project]=entry
    return new


def converged(entry, digest, containers):
    return bool(entry and containers and entry.get('digest')==digest and sorted(entry.get('ids',[]))==sorted(c['Id'] for c in containers) and all(c['State'].get('Running') and c['State'].get('Health',{}).get('Status','healthy')=='healthy' for c in containers))


def run(args, **kwargs):
    return subprocess.check_output(args,stderr=subprocess.PIPE,text=True,**kwargs).strip()


def write_private(path, data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as f: json.dump(data,f,sort_keys=True,indent=2)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def inspect_project(name):
    ids=run(['docker','ps','-aq','--filter','label=com.docker.compose.project=s237-'+name]).split()
    return json.loads(run(['docker','inspect',*ids])) if ids else []


def probe_url(containers,probe):
    """Resolve a probe to the service address on its dedicated internal bridge."""
    matches=[c for c in containers if c['Config']['Labels'].get('com.docker.compose.service')==probe['service']]
    if len(matches)!=1: raise ValueError('probe service not found')
    networks=matches[0].get('NetworkSettings',{}).get('Networks',{})
    addresses=[n['IPAddress'] for name,n in sorted(networks.items()) if name.startswith('s237-') and n.get('IPAddress')]
    if not addresses: raise ValueError('probe service has no internal address')
    ip=ipaddress.ip_address(addresses[0])
    if not ip.is_private or ip in ipaddress.ip_network('192.168.1.0/24'): raise ValueError('probe address not internal')
    path=probe.get('path','/')
    if not path.startswith('/'): raise ValueError('probe path must be absolute')
    return 'http://'+str(ip)+':'+str(int(probe['port']))+path


def verify(containers,services,probes):
    actual={c['Config']['Labels'].get('com.docker.compose.service') for c in containers}
    if actual != set(services) or not all(c['State'].get('Running') and c['State'].get('Health',{}).get('Status','healthy')=='healthy' for c in containers):
        raise ValueError('service set or container health failed')
    if not probes: raise ValueError('explicit functional probes required')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for probe in probes:
        url=probe_url(containers,probe)
        with opener.open(url,timeout=10) as response:
            if response.status != probe.get('status',200): raise ValueError('API status failed')
            content=response.read()
            if probe.get('contains','').encode() not in content: raise ValueError('API response failed')


def supervision(c):
    """Prometheus targets must all be up, except reviewed exclusions (host metrics)."""
    project=c['supervision']['project']; excluded=c['supervision'].get('excluded_jobs',{})
    if any(not reason for reason in excluded.values()): raise ValueError('supervision exclusion reason required')
    containers=inspect_project(project)
    url=probe_url(containers,{'service':'prometheus','port':9090,'path':'/api/v1/targets?state=active'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url,timeout=10) as response: targets=json.load(response)['data']['activeTargets']
    if not targets: raise ValueError('no Prometheus target')
    jobs={t['labels']['job'] for t in targets}
    if set(excluded)-jobs: raise ValueError('excluded supervision job absent')
    down=sorted(t['labels']['job'] for t in targets if t['health']!='up' and t['labels']['job'] not in excluded)
    if down: raise ValueError('Prometheus targets down: '+', '.join(down))
    return {'targets':len(targets),'up':sum(t['health']=='up' for t in targets),'excluded_jobs':sorted(excluded)}


def artifact_compatible(existing_digest, requested_digest):
    if existing_digest is not None and existing_digest!=requested_digest: raise ValueError('immutable artifact drift')


def install_artifacts(root,sha,artifacts):
    release=Path(root)/'releases'/sha; staged=[]
    for item in artifacts:
        path=release/relative(item['destination']); data=base64.b64decode(item['content'],validate=True)
        if str(path.resolve())!=str(path): raise ValueError('symlink artifact refused')
        artifact_compatible(hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,hashlib.sha256(data).hexdigest())
        staged.append((path,data))
    changed=0
    for path,data in staged:
        if not path.exists():
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(data)
            changed+=1
    return changed


def rollback_target(active, attempt, sha):
    target=active if attempt and active.get('sha')==sha else active.get('previous',{})
    if target.get('sha')!=sha: raise ValueError('rollback must select active failed-attempt recovery or previous release')
    return target


def runtime_matches(containers,model):
    if {x['Config']['Labels']['com.docker.compose.service'] for x in containers}!=set(model['services']) or len(containers)!=len(model['services']):
        raise ValueError('runtime service set drift')
    for container in containers:
        name=container['Config']['Labels']['com.docker.compose.service']; service=model['services'][name]; host=container['HostConfig']
        networks=service.get('networks') or {'default':{}}
        if any(n not in model.get('networks',{}) for n in networks): raise ValueError('missing expected network')
        expected_networks={model['networks'][n]['name'] for n in networks}
        if set(container.get('NetworkSettings',{}).get('Networks',{}))!=expected_networks: raise ValueError('runtime network attachment drift')
        if container['Image']!=service['image'] or host.get('Privileged') or host.get('NetworkMode') not in expected_networks or host.get('RestartPolicy',{}).get('Name')!='no':
            raise ValueError('runtime image or privilege drift')
        if host.get('CapAdd') or host.get('Devices') or host.get('DeviceRequests') or host.get('PidMode') or host.get('UTSMode') or host.get('CgroupnsMode')=='host' or host.get('IpcMode','private') not in ('','private') or host.get('Binds') and any('docker.sock' in x for x in host['Binds']):
            raise ValueError('runtime host access drift')
        if sorted(host.get('SecurityOpt') or [])!=sorted(service.get('security_opt') or []): raise ValueError('runtime security options drift')
        if sorted(host.get('CapDrop') or [])!=sorted(service.get('cap_drop') or []) or bool(host.get('ReadonlyRootfs'))!=bool(service.get('read_only',False)): raise ValueError('runtime privilege options drift')
        bindings=host.get('PortBindings') or {}; expected_bindings={}
        for port in service.get('ports',[]):
            key=str(port['target'])+'/'+port.get('protocol','tcp')
            expected_bindings.setdefault(key,[]).append({'HostIp':'127.0.0.1','HostPort':str(port.get('published',''))})
        if bindings!=expected_bindings: raise ValueError('runtime published port drift')
        env=dict(item.split('=',1) for item in container['Config'].get('Env',[]) if '=' in item)
        if any(env.get(k)!=str(v) for k,v in service.get('environment',{}).items()): raise ValueError('runtime environment drift')
        mounts={item['Destination']:item for item in container.get('Mounts',[])}
        if set(mounts)!={v['target'] for v in service.get('volumes',[])}: raise ValueError('runtime added mount drift')
        for volume in service.get('volumes',[]):
            mount=mounts[volume['target']]
            if mount['Type']!=volume['type'] or mount['RW']==bool(volume.get('read_only',False)): raise ValueError('runtime mount drift')
            if volume['type']=='bind' and mount['Source']!=volume['source']: raise ValueError('runtime bind drift')
            if volume['type']=='volume':
                expected_name=model['volumes'][volume['source']]['name']
                if mount.get('Name')!=expected_name: raise ValueError('runtime named volume drift')
                actual=json.loads(run(['docker','volume','inspect',expected_name]))[0]
                if mount['Source']!=actual['Mountpoint']: raise ValueError('runtime volume source drift')
    return True


def bridge_policy(infos):
    policy=[]
    for n in infos:
        if not n['Name'].startswith('s237-') or not n['Internal'] or n.get('EnableIPv6') or n.get('Driver')!='bridge' or n.get('Labels',{}).get('s237.owner')!='rehearsal': raise ValueError('network not isolated and owned')
        interface=n.get('Options',{}).get('com.docker.network.bridge.name','br-'+n['Id'][:12])
        if not re.fullmatch(r'br-[a-f0-9]{12}',interface): raise ValueError('unrecognized dedicated bridge interface')
        for entry in n['IPAM']['Config']:
            subnet=ipaddress.ip_network(entry['Subnet'])
            if subnet.version!=4 or subnet.overlaps(ipaddress.ip_network('192.168.1.0/24')) or subnet.overlaps(ipaddress.ip_network('100.64.0.0/10')): raise ValueError('unsafe subnet')
            policy.append((interface,str(subnet)))
    return sorted(policy)


def firewall_expressions(policy):
    expected=[
      [{'match':{'op':'==','left':{'meta':{'key':'oifname'}},'right':'lo'}},{'accept':None}],
      [{'match':{'op':'==','left':{'payload':{'protocol':'tcp','field':'sport'}},'right':22}}, {'match':{'op':'in','left':{'ct':{'key':'state'}},'right':'established'}},{'accept':None}]
    ]
    for interface,cidr in policy:
        network=ipaddress.ip_network(cidr)
        expected.append([{'match':{'op':'==','left':{'meta':{'key':'oifname'}},'right':interface}}, {'match':{'op':'==','left':{'payload':{'protocol':'ip','field':'daddr'}},'right':{'prefix':{'addr':str(network.network_address),'len':network.prefixlen}}}},{'accept':None}])
    return expected


def all_bridge_policy():
    ids=run(['docker','network','ls','--filter','label=s237.owner=rehearsal','-q']).split()
    if not ids: raise ValueError('no dedicated networks')
    return bridge_policy(json.loads(run(['docker','network','inspect',*ids])))


def firewall_matches(rules,policy):
    chains=[r['chain'] for r in rules if 'chain' in r]; nft_rules=[r['rule'] for r in rules if 'rule' in r]
    if len(chains)!=1 or chains[0].get('hook')!='output' or chains[0].get('policy')!='drop' or chains[0].get('prio')!=-10: raise ValueError('host firewall drift')
    if [r['expr'] for r in nft_rules]!=firewall_expressions(policy): raise ValueError('host firewall rules differ')


def install_firewall(c):
    policy=all_bridge_policy()
    found=subprocess.run(['nft','-j','list','table','inet','s237'],capture_output=True,text=True)
    if found.returncode==0:
        firewall_matches(json.loads(found.stdout)['nftables'],policy); return 0
    if found.returncode!=1: raise ValueError('cannot inspect firewall')
    lines=['table inet s237 {','chain output {','type filter hook output priority -10; policy drop;','oifname "lo" accept','tcp sport 22 ct state established accept']
    for interface,subnet in policy: lines.append('oifname "'+interface+'" ip daddr '+subnet+' accept')
    lines+=['}','}']
    path=Path(c['root'])/'private/isolation.nft';path.write_text('\n'.join(lines)+'\n');path.chmod(0o600)
    run(['nft','-f',str(path)]);return 1


def isolation_check(networks, denied):
    bridge_policy(json.loads(run(['docker','network','inspect',*networks])))
    firewall_matches(json.loads(run(['nft','-j','list','table','inet','s237']))['nftables'],all_bridge_policy())
    for address in denied + ['1.1.1.1','2606:4700:4700::1111']:
        try:
            with socket.create_connection((address,443),timeout=2): raise ValueError('external connectivity remains')
        except (OSError,TimeoutError): pass


def container_isolation(networks,c):
    script="""import socket,sys
for ip in sys.argv[1:]:
 try:
  s=socket.create_connection((ip,443),timeout=2)
 except OSError:
  continue
 s.close()
 sys.exit(1)
"""
    for network in networks:
        run(['docker','run','--rm','--network',network,'--cap-drop','ALL','--security-opt','no-new-privileges',c['probe_image'],'python3','-c',script,*c['denied'],'1.1.1.1','2606:4700:4700::1111'])


def prepare(c, plan=False):
    """plan=True validates every transformation without creating or building anything."""
    root=Path(c['root']); cat=catalogue(c['catalogue']); changed=0; problems=[]; planned={}
    if not re.fullmatch(r'[^ ]+@sha256:[0-9a-f]{64}',c['probe_image']): raise ValueError('digest-pinned Python probe image required')
    try: run(['docker','image','inspect',c['probe_image']])
    except subprocess.CalledProcessError:
        if not plan: run(['docker','pull',c['probe_image']]);changed+=1
    selected=c.get('projects') or list(cat)
    if any(name not in cat for name in selected): raise ValueError('unknown selected project')
    sha=c['revision']; release=root/'releases'/sha
    if run(['git','-C',str(release),'rev-parse','HEAD'])!=sha: raise ValueError('release SHA mismatch')
    def resolved(name):
        p=cat[name]; directory=release/p['directory']
        command=['docker','compose','--project-name','s237-'+name,'--env-file',c['private_projects'][name]['env_file']]
        for file in p['files']: command+=['-f',str(directory/file)]
        return json.loads(run(command+['config','--format','json']))
    relay=c.get('relay')
    models={}
    if relay:
        if relay['project'] not in cat or list(cat)[0]!=relay['project']: raise ValueError('relay project must be first in catalogue')
        # Routes cover the whole declared perimeter, even for a targeted update.
        for name in cat:
            if name==relay['project']: continue
            model=resolved(name)
            for service in cat[name].get('excluded_services',{}): model['services'].pop(service,None)
            models[name]=model
        routes=published_routes(models)
        routes_path=root/'data'/relative(relay['routes'])
        encoded=json.dumps(routes,sort_keys=True,indent=2)
        if not plan and (not routes_path.exists() or routes_path.read_text()!=encoded):
            write_private(routes_path,routes); changed+=1
        if not plan and routes_path.exists():
            # Routes hold no secret; the relay reads them as an unprivileged user.
            routes_path.parent.chmod(0o755); routes_path.chmod(0o644)
        routes_digest=hashlib.sha256(encoded.encode()).hexdigest()
    for name in selected:
      try:
        p=cat[name]; private=c['private_projects'][name]
        model=copy.deepcopy(models[name]) if name in models else resolved(name)
        excluded=p.get('excluded_services',{})
        if any(not reason for reason in excluded.values()): raise ValueError('service exclusion reason required')
        if set(model['services'])!=set(p['services']) | (set() if name in models else set(excluded)): raise ValueError('catalogue service mismatch')
        for service in excluded: model['services'].pop(service,None)
        for service_name,service in model['services'].items():
            declared=set(private.get('drop_depends_on',{}).get(service_name,{}))
            if (set(service.get('depends_on') or {})-declared) & set(excluded): raise ValueError('excluded dependency still required')
        if set(private['environment'])!=set(p['services']): raise ValueError('exercise environment review required per service')
        for service,env in private['environment'].items(): model['services'][service].setdefault('environment',{}).update(env)
        if relay and name==relay['project']:
            for service in model['services'].values(): service.setdefault('environment',{})['S237_ROUTES_DIGEST']=routes_digest
        model=topology(model,private,name,bool(relay))
        mappings={}
        for source,mapping in private['bind_mappings'].items():
            # Profile keys are relative to the release unless absolute.
            key=source if source.startswith('/') else str(release/relative(source))
            if isinstance(mapping,dict) and mapping.get('kind')=='release' and 'path' not in mapping:
                mapping={'kind':'release','path':sha+'/'+relative(source)}
            mappings[key]=mapping
        model=overlay(model,mappings,str(root),name,bool(relay))
        for service in model['services'].values():
            for mount in service.get('volumes',[]):
                if mount['type']=='bind':
                    target=Path(mount['source'])
                    if not plan and (not target.exists() or str(target.resolve())!=str(target)): raise ValueError('private bind data/config missing or symlinked')
        if plan:
            planned[name]=model; continue
        for network,n in model['networks'].items():
            network_name=n['name']; n.pop('internal',None)
            existing=run(['docker','network','ls','--filter','name=^'+network_name+'$','-q'])
            if existing:
                info=json.loads(run(['docker','network','inspect',existing]))[0]
                if not info['Internal'] or info.get('EnableIPv6') or info['Labels'].get('s237.owner')!='rehearsal': raise ValueError('foreign network')
            else:
                run(['docker','network','create','--internal','--label','s237.owner=rehearsal',network_name]); changed+=1
        digest=hashlib.sha256(json.dumps(model,sort_keys=True).encode()).hexdigest()
        draft_path=root/'runtime'/name/(sha+'-'+digest+'-build.json')
        prepared_path=root/'state'/(name+'-prepared.json')
        prepared=json.loads(prepared_path.read_text()) if prepared_path.exists() else {}
        if prepared.get('input_digest')==digest and Path(prepared['config']).exists():
            if hashlib.sha256(Path(prepared['config']).read_bytes()).hexdigest()!=prepared['digest']: raise ValueError('prepared private config drift')
            for image in prepared['images'].values(): run(['docker','image','inspect',image])
            continue
        write_private(draft_path,model)
        cmd=['docker','compose','--project-name','s237-'+name,'-f',str(draft_path)]
        # Base images are acquired once (pull of missing images); later builds,
        # including targeted updates after isolation, reuse the pinned local copies.
        run(cmd+['build'])
        # Present images are kept: escrowed images (no longer published) and
        # digest-verified pulls are never replaced by a later registry state.
        run(cmd+['pull','--ignore-buildable','--policy','missing'])
        images={}
        for service,settings in model['services'].items():
            image=settings.get('image','s237-'+name+'-'+service)
            image_id=json.loads(run(['docker','image','inspect',image]))[0]['Id']; images[service]=image_id
            settings['image']=image_id; settings.pop('build',None)
        image_digest=hashlib.sha256(json.dumps(model,sort_keys=True).encode()).hexdigest()
        config_path=root/'runtime'/name/(sha+'-'+digest+'-'+image_digest+'.json')
        if config_path.exists():
            if json.loads(config_path.read_text())!=model: raise ValueError('immutable resolved config drift')
        else: write_private(config_path,model)
        write_private(prepared_path,{'sha':sha,'input_digest':digest,'config':str(config_path),'images':images,'digest':hashlib.sha256(config_path.read_bytes()).hexdigest()})
        changed+=1
      except (ValueError,KeyError,subprocess.CalledProcessError) as error:
        if not plan: raise
        problems.append(name+': '+type(error).__name__+' '+str(error)[:300])
    if plan:
        write_private(root/'state/plan-models.json',planned)  # private review copy, 0600
        return {'problems':problems,'projects':len(selected)}
    return changed


def deploy(c, rollback=False):
    root=Path(c['root']); cat=catalogue(c['catalogue']); state_path=root/'state/active.json'
    old=json.loads(state_path.read_text()) if state_path.exists() else {'projects':{}}
    selected=c.get('projects') or list(cat)
    if any(p not in cat for p in selected): raise ValueError('unknown selected project')
    if not c.get('migration_compatible',False): raise ValueError('explicit migration compatibility required')
    changed=0
    for name in selected:
        p=cat[name]; private=c['private_projects'][name]
        prior=old['projects'].get(name,{})
        sha=c['revision']
        attempt_path=root/'state'/(name+'-attempt.json')
        attempt=json.loads(attempt_path.read_text()) if attempt_path.exists() else None
        if rollback:
            previous=rollback_target(prior,attempt,sha)
            config_path=Path(previous['config'])
            image_ids=previous['images']
            if hashlib.sha256(config_path.read_bytes()).hexdigest()!=previous['digest']: raise ValueError('previous private config drift')
            model=json.loads(config_path.read_text())
            # Pin original built images, never silently rebuild the rollback.
            for service,image in image_ids.items():
                if model['services'][service]['image']!=image or model['services'][service].get('build'): raise ValueError('previous image pin drift')
        else:
            prepared=json.loads((root/'state'/(name+'-prepared.json')).read_text())
            if prepared['sha']!=sha: raise ValueError('prepare selected SHA before isolation and deploy')
            config_path=Path(prepared['config']); model=json.loads(config_path.read_text())
            if hashlib.sha256(config_path.read_bytes()).hexdigest()!=prepared['digest']: raise ValueError('prepared config drift')
            for image in prepared['images'].values(): run(['docker','image','inspect',image])
        digest=hashlib.sha256(config_path.read_bytes()).hexdigest()
        networks=[n['name'] for n in model['networks'].values()]
        isolation_check(networks,c['denied'])
        container_isolation(networks,c)
        containers=inspect_project(name)
        if attempt and not prior and not rollback:
            # Failed first activation: nothing active to protect. Remove only the
            # journaled attempt's containers (volumes and external networks stay).
            for candidate_entry in attempt.get('candidates',[attempt]):
                run(['docker','compose','--project-name','s237-'+name,'-f',candidate_entry['config'],'down','--remove-orphans'])
            attempt_path.unlink(); attempt=None; containers=inspect_project(name)
        if prior and not containers and not (rollback and attempt): raise ValueError('active containers absent without journaled recovery')
        if prior and containers:
            prior_path=Path(prior['config'])
            if hashlib.sha256(prior_path.read_bytes()).hexdigest()!=prior['digest']: raise ValueError('active private config drift')
            prior_model=json.loads(prior_path.read_text())
            if rollback and attempt:
                candidate_models=[prior_model]
                for candidate_entry in attempt.get('candidates',[attempt]):
                    attempted_path=Path(candidate_entry['config'])
                    if hashlib.sha256(attempted_path.read_bytes()).hexdigest()!=candidate_entry['digest']: raise ValueError('attempt config drift')
                    candidate_models.append(json.loads(attempted_path.read_text()))
                for container in containers:
                    service_name=container['Config']['Labels']['com.docker.compose.service']
                    matched=False
                    for candidate in candidate_models:
                        isolated=copy.deepcopy(candidate);isolated['services']={service_name:candidate['services'][service_name]}
                        try: runtime_matches([container],isolated); matched=True;break
                        except ValueError: pass
                    if not matched: raise ValueError('failed-attempt runtime drift')
            else: runtime_matches(containers,prior_model)
        elif containers: raise ValueError('unrecorded existing containers')
        if attempt and not rollback: raise ValueError('recover prior failed activation before further deploy')
        if converged(prior,digest,containers):
            runtime_matches(containers,model); verify(containers,p['services'],private['probes'])
            if attempt_path.exists(): attempt_path.unlink();changed+=1
            continue
        cmd=['docker','compose','--project-name','s237-'+name,'-f',str(config_path)]
        candidate={'sha':sha,'config':str(config_path),'digest':digest}
        candidates=(attempt.get('candidates',[attempt]) if attempt else [])+[candidate]
        write_private(attempt_path,{**candidate,'candidates':candidates})
        run(cmd+['up','-d','--no-build','--wait','--wait-timeout','180'])
        containers=inspect_project(name); runtime_matches(containers,model); verify(containers,p['services'],private['probes'])
        entry={'sha':sha,'config':str(config_path),'digest':digest,'ids':[x['Id'] for x in containers], 'images':{x['Config']['Labels']['com.docker.compose.service']:x['Image'] for x in containers}}
        old=publish(old,name,entry,True); write_private(state_path,old); attempt_path.unlink();changed+=1
    return changed


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['preflight','plan','prepare','supervision','artifacts','firewall','isolation','verify','deploy','rollback']); args=parser.parse_args(); c=json.load(sys.stdin)
    if args.action=='preflight':
        c['addresses']=sorted({r[4][0] for r in socket.getaddrinfo(c['host'],None,type=socket.SOCK_STREAM)})
        guard(c)
        if 'catalogue' not in c:
            # Host-only provisioning: identity guard only, no application inputs.
            print(json.dumps({'addresses':c['addresses']})); return
        if 'revision' not in c: raise ValueError('full Git SHA required')
        catalogue(c['catalogue'])
        for artifact in c.get('private_artifacts',[]):
            relative(artifact['destination'])
            path=Path(artifact['source'])
            if not path.is_file() or path.stat().st_mode & 0o077: raise ValueError('private artifact missing or unsafe')
        for p in c['private_projects'].values():
            path=Path(p['env_file'])
            if not path.is_file() or path.stat().st_mode & 0o077: raise ValueError('private env absent or permissions unsafe')
        print(json.dumps({'addresses':c['addresses']}))
    elif args.action=='artifacts': print(json.dumps({'changed':install_artifacts(c['root'],c['revision'],c['artifacts'])}))
    elif args.action=='firewall': print(json.dumps({'changed':install_firewall(c)}))
    elif args.action=='prepare': print(json.dumps({'changed':prepare(c)}))
    elif args.action=='supervision': print(json.dumps(supervision(c)))
    elif args.action=='plan': print(json.dumps(prepare(c,plan=True),indent=1,ensure_ascii=False))
    elif args.action in ('isolation','verify'):
        for name in c.get('projects') or list(c['catalogue']):
            if args.action=='verify':
                prepared=json.loads((Path(c['root'])/'state/active.json').read_text())['projects'][name]
            else: prepared=json.loads((Path(c['root'])/'state'/(name+'-prepared.json')).read_text())
            config_file=Path(prepared['config'])
            if hashlib.sha256(config_file.read_bytes()).hexdigest()!=prepared['digest']: raise ValueError('private config drift')
            model=json.loads(config_file.read_text())
            isolation_check([n['name'] for n in model['networks'].values()],c['denied'])
            container_isolation([n['name'] for n in model['networks'].values()],c)
            if args.action=='verify':
                containers=inspect_project(name); runtime_matches(containers,model); verify(containers,c['catalogue'][name]['services'],c['private_projects'][name]['probes'])
        print(json.dumps({'changed':0}))
    else: print(json.dumps({'changed':deploy(c,args.action=='rollback')}))

if __name__=='__main__':
    try: main()
    except Exception as error:
        # Never leak Compose environments or subprocess stderr.
        diagnostic=os.environ.get('S237_DIAGNOSTIC_DIR')
        if diagnostic:
            write_private(Path(diagnostic)/'failure.json', {'type':type(error).__name__, 'stderr':getattr(error,'stderr',None), 'message':str(error)})
        print('Rehearsal operation refused or failed; private diagnostics required ('+type(error).__name__+').',file=sys.stderr); sys.exit(1)
