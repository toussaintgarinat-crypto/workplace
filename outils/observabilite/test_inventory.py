import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).with_name('inventory.py')

class InventoryTests(unittest.TestCase):
    def load(self):
        self.assertTrue(MODULE.exists(), 'inventory.py doit exister')
        spec = importlib.util.spec_from_file_location('inventory', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_manifest_health_and_backend_are_independent(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / 'briques' / 'oria'
            p.mkdir(parents=True)
            (p / 'manifest.json').write_text(json.dumps({'nom':'oria','statut':'actif','url_sante':'http://host.docker.internal:6085/sante'}))
            monitors = module.build_inventory(root)
        by_name = {m['name']:m for m in monitors}
        self.assertEqual(by_name['Processus — oria']['url'], 'http://host.docker.internal:6085/sante')
        self.assertEqual(by_name['Dépendance — Oria backend']['url'], 'http://host.docker.internal:8000/health')
        self.assertEqual(by_name['Processus — Cœur']['maxretries'], 2)

    def test_core_url_is_not_monitored_twice(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / 'briques' / 'noyau'
            p.mkdir(parents=True)
            (p/'manifest.json').write_text(json.dumps({'nom':'noyau','statut':'actif','url_sante':'http://host.docker.internal:5100/health'}))
            monitors = module.build_inventory(root)
        self.assertEqual(sum(m['url']=='http://host.docker.internal:5100/health' for m in monitors), 1)

    def test_inactive_manifests_are_excluded_and_loopback_rewritten(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, status in [('active','actif'), ('pending','a_tester'), ('old','deprecie')]:
                p = root / 'briques' / name
                p.mkdir(parents=True)
                (p/'manifest.json').write_text(json.dumps({'nom':name,'statut':status,'url_sante':f'http://localhost:{6001 if name == "pending" else 6000}/sante'}))
            monitors = module.build_inventory(root)
        names = {m['name'] for m in monitors}
        self.assertNotIn('Processus — old', names)
        self.assertIn('Processus — pending', names)
        self.assertEqual(next(m for m in monitors if m['name']=='Processus — active')['url'], 'http://host.docker.internal:6000/sante')

if __name__ == '__main__':
    unittest.main()
