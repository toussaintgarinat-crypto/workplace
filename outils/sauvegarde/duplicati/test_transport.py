import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import transport
class Guards(unittest.TestCase):
 def test_unmounted_marker_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   (Path(d)/'.workplace-s236-target').write_text('test')
   with patch('os.path.ismount',return_value=False):
    with self.assertRaises(Exception): transport.validate_profile({'id':'a','kind':'file','mount_path':d,'identity':'test'})
 def test_uri_credentials_rejected(self):
  for uri in ('ssh://user:pass@host/path','s3://bucket/path?auth-password=secret','http://host/path',''):
   with self.assertRaises(Exception): transport.validate_profile({'id':'a','kind':'remote','destination':uri})
 def test_private_passphrase_required(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'env'; p.write_text('AUTH_USERNAME=x\n'); p.chmod(0o600); Path(d).chmod(0o700)
   with self.assertRaises(Exception): transport.credentials(p)
 def test_warning_is_failure(self):
  self.assertFalse(transport.success_code(2));self.assertTrue(transport.success_code(1))

class TransferFailures(unittest.TestCase):
 def test_warning_does_not_ack(self):
  class Fake:
   def run(self,args,log):return 2
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();env=root/'env';env.write_text('PASSPHRASE=example-test-secret\n');env.chmod(0o600)
   profile={'id':'remote','kind':'remote','destination':'webdavs://example.test/path','credentials':str(env)}
   with patch.object(transport,'verify_generation',return_value={'started':100,'ended':101}),self.assertRaises(Exception):transport.transfer(profile,root/'generation',root,runner=Fake())
   self.assertFalse((root/'transfers.json').exists())
 def test_encryption_remote_verification_and_status(self):
  class Fake:
   def __init__(self):self.calls=[]
   def run(self,args,log):self.calls.append(args);return 0
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();env=root/'env';env.write_text('PASSPHRASE=example-test-secret\n');env.chmod(0o600)
   profile={'id':'remote','kind':'remote','destination':'ssh://example.test/path','options':{'ssh-fingerprint':'ssh-ed25519 256 example-test-fingerprint'},'credentials':str(env)};fake=Fake()
   transport.atomic_json(root/'status.json',{'last_export_timestamp':123})
   with patch.object(transport,'verify_generation',return_value={'started':100,'ended':101}):transport.transfer(profile,root/'generation',root,runner=fake)
   self.assertEqual(len(fake.calls),2)
   self.assertIn('--encryption-module=aes',fake.calls[0]);self.assertIn('--full-remote-verification=true',fake.calls[1])
   self.assertNotIn('example-test-secret',' '.join(fake.calls[0]))
   self.assertEqual(__import__('json').loads((root/'status.json').read_text())['last_export_timestamp'],123)

class RemoteOptions(unittest.TestCase):
 def test_ssh_requires_pinned_host_key(self):
  with self.assertRaises(Exception):transport.validate_profile({'id':'x','kind':'remote','destination':'ssh://host/path'})
 def test_tls_disable_rejected(self):
  with self.assertRaises(Exception):transport.validate_profile({'id':'x','kind':'remote','destination':'s3://bucket/path','options':{'s3-use-ssl':'false'}})
 def test_failed_validation_records_failure(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();transport.atomic_json(root/'status.json',{'last_transfer_timestamp':321,'last_export_timestamp':123})
   with self.assertRaises(Exception):transport.transfer({'id':'x','kind':'remote','destination':''},root/'generation',root)
   status=__import__('json').loads((root/'status.json').read_text());self.assertFalse(status['last_transfer_success']);self.assertEqual(status['last_transfer_timestamp'],321)

class StagingDiskGuard(unittest.TestCase):
 def test_target_on_same_nonroot_staging_device_rejected(self):
  import types,json
  with tempfile.TemporaryDirectory() as d:
   base=Path(d).resolve();target=base/'target';target.mkdir();staging=base/'staging';staging.mkdir();(target/'.workplace-s236-target').write_text('identity')
   real_stat=Path.stat
   def stat_device(path,*args,**kwargs):
    result=real_stat(path,*args,**kwargs)
    if path in (target,staging,Path('/')):
     return types.SimpleNamespace(st_dev=11 if path==Path('/') else 22,st_mode=result.st_mode)
    return result
   result=types.SimpleNamespace(stdout=json.dumps({'filesystems':[{'target':str(target),'source':'/dev/test','fstype':'ext4'}]}).encode())
   profile={'id':'disk','kind':'file','mount_path':str(target),'identity':'identity'}
   with patch('os.path.ismount',return_value=True),patch.object(Path,'stat',stat_device),patch.object(transport.subprocess,'run',return_value=result):
    with self.assertRaisesRegex(transport.BackupError,'staging'):transport.validate_profile(profile,staging)

class SourcePointRPO(unittest.TestCase):
 def test_ack_records_verified_source_point_and_oldest_required(self):
  import json
  class Fake:
   def run(self,args,log):return 0
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();env=root/'env';env.write_text('PASSPHRASE=example-test-secret\n');env.chmod(0o600)
   profile={'id':'nas','kind':'remote','destination':'webdavs://example.test/path','credentials':str(env),'required_profiles':['usb','nas']}
   transport.atomic_json(root/'transfers.json',{'usb':{'generation':'old','timestamp':990,'source_point_timestamp':700}})
   with patch.object(transport,'verify_generation',return_value={'started':900,'ended':950}),patch.object(transport.time,'time',return_value=1000):transport.transfer(profile,root/'generation',root,runner=Fake())
   status=json.loads((root/'status.json').read_text());acks=json.loads((root/'transfers.json').read_text())
   self.assertEqual(status['last_transfer_timestamp'],990)
   self.assertEqual(status['last_transferred_source_timestamp'],700)
   self.assertEqual(acks['nas']['source_point_timestamp'],900)
 def test_legacy_required_ack_cannot_imply_verified_freshness(self):
  import json
  class Fake:
   def run(self,args,log):return 0
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();env=root/'env';env.write_text('PASSPHRASE=example-test-secret\n');env.chmod(0o600)
   profile={'id':'nas','kind':'remote','destination':'webdavs://example.test/path','credentials':str(env),'required_profiles':['usb','nas']}
   transport.atomic_json(root/'transfers.json',{'usb':{'generation':'old','timestamp':990}})
   with patch.object(transport,'verify_generation',return_value={'started':900,'ended':950}),patch.object(transport.time,'time',return_value=1000):transport.transfer(profile,root/'generation',root,runner=Fake())
   self.assertEqual(json.loads((root/'status.json').read_text())['last_transferred_source_timestamp'],0)
