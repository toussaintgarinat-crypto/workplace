import importlib.util
from pathlib import Path
import tempfile
import unittest

class KumaConfigTests(unittest.TestCase):
    def load(self):
        path = Path(__file__).with_name('kuma-config.py')
        self.assertTrue(path.exists(), 'kuma-config.py doit exister')
        spec = importlib.util.spec_from_file_location('kuma_config', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_telegram_requires_explicit_opt_in(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'.env').write_text('TELEGRAM_BOT_TOKEN=secret\n')
            supervision=root/'outils'/'observabilite'
            supervision.mkdir(parents=True)
            (supervision/'.env').write_text('KUMA_USER=admin\nKUMA_PASSWORD="password"\nTELEGRAM_CHAT_ID=123\n')
            cfg=module.build_config(supervision)
            self.assertFalse(cfg['telegramEnabled'])
            self.assertEqual(cfg['password'], 'password')
            self.assertEqual(cfg['telegramToken'], 'secret')

    def test_telegram_missing_destination_rejected_when_enabled(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'.env').write_text('KUMA_USER=admin\nKUMA_PASSWORD=pass\nTELEGRAM_ENABLED=yes\n')
            with self.assertRaises(ValueError):
                module.build_config(root)
