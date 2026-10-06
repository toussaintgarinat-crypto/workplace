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
        # S237b : le S3 d'Oria (SeaweedFS) a sa propre sonde, par sa route de santé.
        self.assertEqual(by_name['Dépendance — Oria S3 (SeaweedFS)']['url'], 'http://host.docker.internal:9106/healthz')

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

    def test_instantane_aligne_sur_les_manifestes_reels(self):
        """S240 (M5) : la sonde de la brique dev suit son nouveau chemin d'accès (réseau Docker
        proxy_net, port publié sur 127.0.0.1 seulement) — l'instantané versionné ne doit pas
        garder l'ancienne URL host.docker.internal:5955."""
        racine = MODULE.parents[2]
        manifeste = json.loads((racine / 'briques' / 'dev' / 'manifest.json').read_text())
        instantane = json.loads(MODULE.with_name('monitors.json').read_text())
        dev = next(m for m in instantane if m['name'] == 'Processus — dev')
        self.assertEqual(dev['url'], manifeste['url_sante'])
        compose = MODULE.with_name('docker-compose.yml').read_text()
        kuma = compose[compose.index('  uptime-kuma:'):compose.index('  node-exporter:')]
        self.assertIn('proxy_net', kuma, 'Kuma doit joindre proxy_net pour sonder workplace_dev')


if __name__ == '__main__':
    unittest.main()
