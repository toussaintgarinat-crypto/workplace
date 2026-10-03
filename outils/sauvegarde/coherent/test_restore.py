import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import restore

class NativeDiagnostics(unittest.TestCase):
 def test_native_failure_retains_private_stderr(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'dump';source.write_bytes(b'dump')
   session=restore.Session(unittest.mock.Mock(),root,'helper')
   result=unittest.mock.Mock(returncode=1,stderr=b'private database details')
   with patch.object(restore.subprocess,'run',return_value=result):
    with self.assertRaises(restore.BackupError) as raised:session.stdin(['exec','test'],source)
   self.assertNotIn('private database details',str(raised.exception))
   logs=list(root.glob('native-error-*.log'));self.assertEqual(len(logs),1)
   self.assertEqual(logs[0].read_bytes(),result.stderr)
   self.assertEqual(logs[0].stat().st_mode & 0o777,0o600)

class SmokeAuthentication(unittest.TestCase):
 def run_probe(self,location=None):
  import contextlib,io,json,urllib.request,urllib.error
  response=unittest.mock.MagicMock();response.__enter__.return_value.status=200
  opener=unittest.mock.Mock()
  opener.open.side_effect=[response,response if location is None else urllib.error.HTTPError('http://127.0.0.1:5000/dashboard',303,'See Other',{'Location':location},None)]
  output=io.StringIO()
  with patch.object(urllib.request,'build_opener',return_value=opener),contextlib.redirect_stdout(output):exec(restore.SMOKE_SCRIPT,{})
  self.assertEqual(opener.open.call_count,2)
  return json.loads(output.getvalue())
 def test_protected_dashboard_does_not_follow_sso(self):
  result=self.run_probe('/auth/login?next=%2Fdashboard')
  self.assertTrue(result['health']);self.assertTrue(result['authentication_required'])
  self.assertFalse(result['dashboard_rendered']);self.assertEqual(result['dashboard_http'],303)
 def test_unprotected_dashboard_is_rendered(self):
  self.assertTrue(self.run_probe()['dashboard_rendered'])
 def test_unexpected_external_redirect_fails(self):
  with self.assertRaises(AssertionError):self.run_probe('https://outside.example/auth/login')
class Guards(unittest.TestCase):
 def test_existing_target(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(Exception): restore.validate_target(Path(d),Path('/elsewhere'),{'expected_mounts':[]})
 def test_source_overlap(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(Exception): restore.validate_target(Path(d)/'new',Path('/elsewhere'),{'expected_mounts':[{'mounts':[{'source':d}]}]})
 def test_symlink_parent(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); (p/'link').symlink_to(p,target_is_directory=True)
   with self.assertRaises(Exception): restore.validate_target(p/'link'/'new',Path('/elsewhere'),{'expected_mounts':[]})
 def test_corrupt_before_docker(self):
  with tempfile.TemporaryDirectory() as d:
   docker=unittest.mock.Mock()
   with self.assertRaises(Exception): restore.restore(Path(d)/'missing',Path(d)/'new',docker)
   docker.run.assert_not_called()

class Resources(unittest.TestCase):
 def test_existing_volume_never_created_or_deleted(self):
  with tempfile.TemporaryDirectory() as d:
   fake=unittest.mock.Mock();s=restore.Session(fake,Path(d).resolve(),'helper');name=s.prefix+'-data';fake.run.return_value=(name+'\n').encode()
   with self.assertRaises(Exception):s.create('volume','data')
   self.assertEqual(s.cleanup(),[])
   self.assertEqual(fake.run.call_count,1)
 def test_failed_container_run_never_deleted(self):
  with tempfile.TemporaryDirectory() as d:
   fake=unittest.mock.Mock();s=restore.Session(fake,Path(d).resolve(),'helper');fake.run.side_effect=[b'',restore.BackupError('name collision')]
   name=s.create('container','pg')
   with self.assertRaises(Exception):s.run(name,'image')
   self.assertEqual(s.cleanup(),[])
   self.assertEqual(fake.run.call_count,2)
 def test_real_bind_overlap(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve()
   with self.assertRaises(restore.BackupError):restore.validate_target(root/'new',Path('/elsewhere'),{'trees':[{'kind':'bind','source':str(root)}]})
