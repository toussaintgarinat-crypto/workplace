import json
import tempfile
import unittest
from pathlib import Path
import backup

class SafetyTests(unittest.TestCase):
    def test_lock_excludes_second_writer(self):
        with tempfile.TemporaryDirectory() as d:
            with backup.lock(Path(d).resolve()):
                with self.assertRaises(backup.BackupError):
                    with backup.lock(Path(d).resolve()): pass
    def test_drift_rejected(self):
        inv={'expected_mounts':[{'container':'app','running':True,'mounts':[]}]}
        with self.assertRaises(backup.BackupError):
            backup.check_containers(inv,[{'Name':'/app','Id':'1','State':{'Running':True},'Config':{},'Mounts':[{'Type':'volume','Name':'new','Source':'/x','Destination':'/x'}]}])
    def test_recovery_id_guard(self):
        class Fake:
            def inspect(self): return [{'Name':'/app','Id':'replacement','State':{'Running':False}}]
            def run(self,*a,**kw): self.fail=True
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); backup.atomic_json(root/'recovery.json',[{'name':'app','id':'old'}])
            with self.assertRaises(backup.BackupError): backup.recover(root,Fake())
            self.assertTrue((root/'recovery.json').exists())
    def test_corrupt_generation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve(); (p/'a').write_text('original'); backup.seal(p,[] ,{},0)
            (p/'a').write_text('broken')
            with self.assertRaises(backup.BackupError): backup.verify_generation(p)

class FlowTests(unittest.TestCase):
    def test_export_failure_restarts_without_complete(self):
        from unittest.mock import patch
        class Fake:
            def __init__(self): self.running=True; self.calls=[]
            def inspect(self): return [{'Name':'/app','Id':'original','State':{'Running':self.running},'Config':{},'Mounts':[]}]
            def run(self,args,**kw):
                self.calls.append(args)
                if args[0]=='stop': self.running=False
                if args[0]=='start': self.running=True
                return b''
        inv={'repository':{'id':'repository'},'trees':[],'keep_running':[],'postgres':[]}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); fake=Fake()
            with patch.object(backup,'preflight',return_value=({'app':fake.inspect()[0]},{})), patch.object(backup,'export_tree',side_effect=backup.BackupError('export failed')):
                with self.assertRaises(backup.BackupError): backup.backup(inv,root,fake)
            self.assertTrue(fake.running)
            self.assertEqual(list((root/'complete').iterdir()),[])
            self.assertEqual(len(list((root/'failed').iterdir())),1)
            self.assertFalse((root/'recovery.json').exists())
            self.assertFalse(json.loads((root/'status.json').read_text())['last_attempt_success'])

class SourceBoundaryTests(unittest.TestCase):
    def test_root_inside_bind_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()
            with self.assertRaises(backup.BackupError): backup.check_root_boundaries(p/'repo'/'backups',[p/'repo'])
    def test_root_contains_source_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()
            with self.assertRaises(backup.BackupError): backup.check_root_boundaries(p,[p/'source'])
    def test_symlink_parent_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve(); (p/'real').mkdir(); (p/'alias').symlink_to(p/'real',target_is_directory=True)
            with self.assertRaises(backup.BackupError): backup.check_root_boundaries(p/'alias'/'backups',[])
    def test_empty_sources_cannot_verify(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve(); (p/'a').write_text('data'); backup.seal(p,[],{},0)
            with self.assertRaises(backup.BackupError): backup.verify_generation(p)
    def test_missing_native_descriptor_rejected(self):
        import artifacts
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); source=root/'source'; source.mkdir(); (source/'a').write_text('data')
            generation=root/'generation'; generation.mkdir(); (generation/'trees').mkdir(); (generation/'trees/repository').mkdir()
            artifacts.export_tree(source,generation/'trees/repository/artifact')
            inventory={'repository':{'id':'repository','kind':'bind','source':str(source)},'trees':[],'postgres':[{'container':'pg','image':'pg16','restore_image':'pg16'}]}
            tree={'kind':'tree','id':'repository','path':'trees/repository/artifact','source':inventory['repository']}
            backup.seal(generation,[tree],inventory,0)
            with self.assertRaises(backup.BackupError): backup.verify_generation(generation)

class ProtectedDockerSources(unittest.TestCase):
    def test_protected_source_canonicalized_by_root_helper(self):
        from unittest.mock import patch
        class Fake:
            def __init__(self): self.calls=[]
            def run(self,args,**kw): self.calls.append(args);return b'["/var/lib/docker/volumes/v/_data"]\n'
        fake=Fake()
        with tempfile.TemporaryDirectory() as d:
            with patch.object(Path,'is_symlink',side_effect=PermissionError):
                self.assertEqual(backup.docker_source_path('/var/lib/docker/volumes/v/_data',fake,'core-core'),'/var/lib/docker/volumes/v/_data')
        self.assertIn('--network',fake.calls[0])
    def test_helper_rejects_noncanonical_response(self):
        class Fake:
            def run(self,args,**kw):return b'["relative/path"]'
        with self.assertRaises(backup.BackupError):backup.docker_source_path('/protected',Fake(),'core-core')

class CompleteGenerationVerification(unittest.TestCase):
    def test_valid_original_seal_verifies_without_reseal(self):
        import artifacts
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();source=root/'source';source.mkdir();(source/'data').write_text('sealed contents')
            generation=root/'generation';artifact=generation/'trees/repository/artifact';artifact.parent.mkdir(parents=True)
            artifacts.export_tree(source,artifact)
            inventory={'repository':{'id':'repository','kind':'bind','source':str(source)},'trees':[]}
            backup.seal(generation,backup.expected_sources(inventory),inventory,0)
            manifest=(generation/'manifest.json').read_bytes()
            result=backup.verify_generation(generation)
            self.assertEqual(result['inventory'],inventory)
            self.assertEqual((generation/'manifest.json').read_bytes(),manifest)
