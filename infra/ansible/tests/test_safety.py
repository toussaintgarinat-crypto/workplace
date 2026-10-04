import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).parents[1] / 'scripts' / 'workplace_state.py'
spec = importlib.util.spec_from_file_location('state', PATH)
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)

class SafetyTests(unittest.TestCase):
    def config(self):
        return dict(group='rehearsal', addresses=['192.0.2.44'], denied=['192.168.1.89','100.64.0.1'], machine_id='a'*32, expected_machine_id='a'*32, root='/srv/workplace-rehearsal', revision='b'*40)
    def test_valid_guard(self):
        state.guard(self.config())
    def test_guard_refusals(self):
        for field, value in [('group','production'),('addresses',['192.168.1.89']),('addresses',['127.0.0.1']),('addresses',['::1']),('addresses',['100.64.1.2']),('addresses',[]),('machine_id',''),('expected_machine_id','c'*32),('root','/srv/workplace'),('root','/srv/workplace-rehearsal/../production'),('revision','main')]:
            with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                c=self.config(); c[field]=value; state.guard(c)
    def test_catalogue_unknown_dependencies_and_traversal(self):
        for c in [{'a':{'directory':'../x','files':['compose.yml'],'services':['a'],'dependencies':[]}}, {'a':{'directory':'.','files':['compose.yml'],'services':['a'],'dependencies':['unknown']}}]:
            with self.assertRaises(ValueError): state.catalogue(c)
    def test_internal_network_and_data_mapping(self):
        model={'services':{'db':{'image':'postgres:17','volumes':[{'type':'bind','source':'/release/db','target':'/var/lib/postgresql/data'}],'ports':['5432:5432']}},'networks':{'default':{}}}
        with self.assertRaises(ValueError): state.overlay(model,{},'/srv/workplace-rehearsal','db')
        result=state.overlay(model,{'/release/db':'db'},'/srv/workplace-rehearsal','db')
        self.assertTrue(result['networks']['default']['internal'])
        self.assertEqual(result['services']['db']['volumes'][0]['source'],'/srv/workplace-rehearsal/data/db')
        self.assertEqual(result['services']['db']['ports'][0]['host_ip'],'127.0.0.1')
    def test_privileged_and_host_services_refused(self):
        for options in [{'privileged':True},{'network_mode':'host'},{'volumes':[{'type':'bind','source':'/var/run/docker.sock','target':'/sock'}]},{'pid':'host'}]:
            with self.assertRaises(ValueError): state.overlay({'services':{'bad':options}}, {},'/srv/workplace-rehearsal','x')
    def test_manifest_selective_publish(self):
        old={'projects':{'a':{'sha':'a'*40},'b':{'sha':'b'*40}}}
        new=state.publish(old,'a',{'sha':'c'*40},verified=True)
        self.assertEqual(new['projects']['b'],old['projects']['b'])
        self.assertEqual(new['projects']['a']['previous'],{'sha':'a'*40})
        with self.assertRaises(ValueError): state.publish(old,'a',{},verified=False)
    def test_runtime_drift(self):
        self.assertFalse(state.converged({'digest':'x','ids':['id']},'x',[{'Id':'id','State':{'Running':False}}]))
        self.assertFalse(state.converged({'digest':'x','ids':['old']},'x',[{'Id':'new','State':{'Running':True,'Health':{'Status':'healthy'}}}]))
        self.assertTrue(state.converged({'digest':'x','ids':['id']},'x',[{'Id':'id','State':{'Running':True,'Health':{'Status':'healthy'}}}]))

if __name__=='__main__': unittest.main()

class AdditionalSafetyTests(unittest.TestCase):
    def test_default_network_is_project_scoped(self):
        result=state.overlay({'services':{'x':{}},'networks':{'default':{},'proxy_net':{}}},{},'/srv/workplace-rehearsal','alpha')
        self.assertEqual(result['networks']['default']['name'],'s237-alpha-default')
        self.assertEqual(result['networks']['proxy_net']['name'],'s237-proxy_net')
    def test_release_mapping_requires_immutable_readonly(self):
        model={'services':{'x':{'volumes':[{'type':'bind','source':'/release/code','target':'/app','read_only':False}]}}}
        with self.assertRaises(ValueError): state.overlay(model,{'/release/code':{'kind':'release','path':'a'*40+'/code'}},'/srv/workplace-rehearsal','x')
    def test_mesh_and_production_identity_refused(self):
        with self.assertRaises(ValueError): state.catalogue({'mesh-https':{'directory':'.','files':['compose.yml'],'services':['x']}})
        with self.assertRaises(ValueError):
            state.guard(dict(group='rehearsal',addresses=['192.0.2.44'],denied=[],machine_id='f0490b65d4414f4fa4db80bdc3f75da6',expected_machine_id='f0490b65d4414f4fa4db80bdc3f75da6',root='/srv/workplace-rehearsal',revision='a'*40))
    def test_service_runtime_drift_refused(self):
        model={'services':{'x':{'image':'sha256:expected','environment':{'KEY':'value'},'volumes':[]}},'networks':{}}
        container={'Config':{'Labels':{'com.docker.compose.service':'x'},'Env':['KEY=value']},'Image':'sha256:wrong','State':{'Running':True},'Mounts':[],'HostConfig':{'RestartPolicy':{'Name':'no'},'Privileged':False,'NetworkMode':'default'}}
        with self.assertRaises(ValueError): state.runtime_matches([container],model)

class TopologyTests(unittest.TestCase):
    def test_host_gateway_and_production_endpoints_refused(self):
        for service in [{'extra_hosts':{'host.docker.internal':'host-gateway'}}, {'environment':{'API_URL':'http://192.168.1.89:5100'}}]:
            with self.assertRaises(ValueError): state.overlay({'services':{'x':service}},{},'/srv/workplace-rehearsal','x')

class ReviewSafetyTests(unittest.TestCase):
    def test_failed_attempt_can_restore_still_active_release(self):
        active={'sha':'a'*40,'previous':{'sha':'z'*40}}
        self.assertEqual(state.rollback_target(active,{'sha':'b'*40},'a'*40),active)
        with self.assertRaises(ValueError):state.rollback_target(active,None,'a'*40)
    def test_existing_artifact_cannot_change(self):
        with self.assertRaises(ValueError):state.artifact_compatible('old','new')
        state.artifact_compatible(None,'new')
    def test_nft_bridge_policy_is_interface_and_subnet_scoped(self):
        info={'Name':'s237-default','Internal':True,'EnableIPv6':False,'Driver':'bridge','Id':'abcdef123456xyz','Labels':{'s237.owner':'rehearsal'},'IPAM':{'Config':[{'Subnet':'172.24.0.0/16'}]},'Options':{}}
        policy=state.bridge_policy([info]); self.assertEqual(policy,[('br-abcdef123456','172.24.0.0/16')])
        expected=state.firewall_expressions(policy)
        self.assertEqual(len(expected),3)
        self.assertEqual(expected[2][0]['match']['right'],'br-abcdef123456')
        self.assertEqual(expected[2][1]['match']['right'],{'prefix':{'addr':'172.24.0.0','len':16}})

class ReviewIntegrationTests(unittest.TestCase):
    def fixture(self):
        model={'services':{'x':{'image':'sha256:expected','environment':{'KEY':'value'},'volumes':[],'networks':{'default':{}},'ports':[]}},'networks':{'default':{'name':'s237-test-default'}}}
        container={'Config':{'Labels':{'com.docker.compose.service':'x'},'Env':['KEY=value']},'Image':'sha256:expected','State':{'Running':True},'Mounts':[],'HostConfig':{'RestartPolicy':{'Name':'no'},'Privileged':False,'NetworkMode':'s237-test-default'},'NetworkSettings':{'Networks':{'s237-test-default':{}}}}
        return model,container
    def test_runtime_real_configuration_and_drift(self):
        import copy
        model,container=self.fixture();self.assertTrue(state.runtime_matches([container],model))
        cases=[('NetworkSettings',{'Networks':{'s237-test-default':{},'bridge':{}}}),('Mounts',[{'Destination':'/added','Type':'bind','Source':'/etc','RW':True}])]
        for field,value in cases:
            changed=copy.deepcopy(container);changed[field]=value
            with self.assertRaises(ValueError):state.runtime_matches([changed],model)
        for field,value in [('CapAdd',['SYS_ADMIN']),('PidMode','host'),('Devices',[{}]),('PortBindings',{'80/tcp':[{'HostIp':'0.0.0.0','HostPort':'80'}]})]:
            changed=copy.deepcopy(container);changed['HostConfig'][field]=value
            with self.assertRaises(ValueError):state.runtime_matches([changed],model)
    def test_artifacts_all_validated_before_any_write(self):
        import tempfile,base64
        with tempfile.TemporaryDirectory() as directory:
            release=pathlib.Path(directory)/'releases'/('a'*40);release.mkdir(parents=True);(release/'existing').write_text('old')
            artifacts=[{'destination':'new','content':base64.b64encode(b'new').decode()},{'destination':'existing','content':base64.b64encode(b'changed').decode()}]
            with self.assertRaises(ValueError):state.install_artifacts(directory,'a'*40,artifacts)
            self.assertFalse((release/'new').exists());self.assertEqual((release/'existing').read_text(),'old')
    def test_firewall_extra_rule_refused(self):
        import copy
        policy=[('br-abcdef123456','172.24.0.0/16')]
        rules=[{'chain':{'hook':'output','policy':'drop','prio':-10}}]+[{'rule':{'expr':expr}} for expr in state.firewall_expressions(policy)]
        state.firewall_matches(rules,policy)
        rules.append({'rule':{'expr':[{'accept':None}]}})
        with self.assertRaises(ValueError):state.firewall_matches(rules,policy)

class AttemptRecoveryTests(unittest.TestCase):
    def test_failed_activation_preserves_active_and_rollback_recovers_it(self):
        import copy,tempfile,json
        from unittest.mock import patch
        fixture=ReviewIntegrationTests(); model_a,container=fixture.fixture(); model_b=copy.deepcopy(model_a);model_b['services']['x']['image']='sha256:new'
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);(root/'state').mkdir();(root/'runtime').mkdir()
            path_a=root/'runtime/a.json';path_b=root/'runtime/b.json';state.write_private(path_a,model_a);state.write_private(path_b,model_b)
            digest=lambda path:state.hashlib.sha256(path.read_bytes()).hexdigest()
            container['Id']='old'; active={'sha':'a'*40,'config':str(path_a),'digest':digest(path_a),'ids':['old'],'images':{'x':'sha256:expected'}}
            state.write_private(root/'state/active.json',{'projects':{'x':active,'untouched':{'sha':'c'*40}}})
            state.write_private(root/'state/x-prepared.json',{'sha':'b'*40,'config':str(path_b),'digest':digest(path_b),'images':{'x':'sha256:new'}})
            c={'root':directory,'catalogue':{'x':{'directory':'.','files':['compose.yml'],'services':['x']}},'private_projects':{'x':{'probes':[]}},'revision':'b'*40,'migration_compatible':True,'denied':[],'probe_image':'unused'}
            failed=[False]
            def command(argv):
                if 'up' in argv:
                    image=json.loads(pathlib.Path(argv[argv.index('-f')+1]).read_text())['services']['x']['image'];container['Image']=image;container['Id']='new' if image=='sha256:new' else 'restored'
                    if image=='sha256:new' and not failed[0]:failed[0]=True;raise RuntimeError('activation failed')
                return ''
            with patch.object(state,'run',side_effect=command),patch.object(state,'inspect_project',side_effect=lambda name:[copy.deepcopy(container)]),patch.object(state,'isolation_check'),patch.object(state,'container_isolation'),patch.object(state,'verify'):
                with self.assertRaises(RuntimeError):state.deploy(c)
                self.assertEqual(json.loads((root/'state/active.json').read_text())['projects']['x'],active)
                self.assertTrue((root/'state/x-attempt.json').exists())
                c['revision']='a'*40;self.assertEqual(state.deploy(c,rollback=True),1)
                self.assertFalse((root/'state/x-attempt.json').exists())
                result=json.loads((root/'state/active.json').read_text());self.assertEqual(result['projects']['x']['sha'],'a'*40);self.assertEqual(result['projects']['untouched'],{'sha':'c'*40})

class PreparedCacheTests(unittest.TestCase):
    def test_cached_prepare_works_offline_without_any_pull(self):
        import tempfile,json,subprocess
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            sha='a'*40;release=pathlib.Path(directory)/'releases'/sha;release.mkdir(parents=True)
            calls=[];cached_probe=[False];offline=[False]
            probe='python@sha256:'+('b'*64)
            def command(argv):
                calls.append(argv)
                if 'pull' in argv:
                    if offline[0]:raise RuntimeError('network disabled')
                    if argv[:2]==['docker','pull']:cached_probe[0]=True
                    return ''
                if argv[:3]==['docker','image','inspect']:
                    if argv[3]==probe and not cached_probe[0]:raise subprocess.CalledProcessError(1,argv)
                    return json.dumps([{'Id':'sha256:expected'}])
                if argv[0]=='git':return sha
                if argv[:3]==['docker','network','ls']:return 'netid'
                if argv[:3]==['docker','network','inspect']:return json.dumps([{'Internal':True,'EnableIPv6':False,'Labels':{'s237.owner':'rehearsal'}}])
                if 'config' in argv:return json.dumps({'services':{'x':{'image':'sha256:expected','volumes':[]}},'networks':{'default':{}}})
                return ''
            config={'root':directory,'revision':sha,'probe_image':probe,'catalogue':{'x':{'directory':'.','files':['compose.yml'],'services':['x']}},'private_projects':{'x':{'env_file':'/private/env','bind_mappings':{},'environment':{'x':{}}}}}
            with patch.object(state,'run',side_effect=command):
                state.prepare(config);calls.clear();offline[0]=True
                self.assertEqual(state.prepare(config),0)
                self.assertFalse(any('pull' in call for call in calls))

class MissingActiveContainersTests(unittest.TestCase):
    def test_absent_active_containers_refused_before_compose(self):
        import tempfile,json
        from unittest.mock import patch
        model,_=ReviewIntegrationTests().fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);(root/'state').mkdir();config_path=root/'model.json';state.write_private(config_path,model)
            entry={'sha':'a'*40,'config':str(config_path),'digest':state.hashlib.sha256(config_path.read_bytes()).hexdigest(),'ids':['old'],'images':{'x':'sha256:expected'}}
            state.write_private(root/'state/active.json',{'projects':{'x':entry}});state.write_private(root/'state/x-prepared.json',entry)
            c={'root':directory,'revision':'a'*40,'catalogue':{'x':{'directory':'.','files':['compose.yml'],'services':['x']}},'private_projects':{'x':{'probes':[]}},'migration_compatible':True,'denied':[]}
            calls=[]
            with patch.object(state,'run',side_effect=lambda args:calls.append(args) or ''),patch.object(state,'inspect_project',return_value=[]),patch.object(state,'isolation_check'),patch.object(state,'container_isolation'),patch.object(state,'verify'),patch.object(state,'runtime_matches'):
                with self.assertRaises(ValueError):state.deploy(c)
                self.assertFalse(any('up' in args for args in calls))
