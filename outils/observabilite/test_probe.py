import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

class ProbeCleanupTests(unittest.TestCase):
    def test_container_removed_even_when_kuma_cleanup_fails(self):
        path = Path(__file__).with_name('probe-live.py')
        spec = importlib.util.spec_from_file_location('probe', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        def broken_rpc(*args, **kwargs):
            raise RuntimeError('Kuma indisponible')
        with patch.object(module.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError):
                module.cleanup_probe(broken_rpc, 'test', 'isolated')
            run.assert_called_once_with(['docker', 'rm', '-f', 'isolated'], capture_output=True)
