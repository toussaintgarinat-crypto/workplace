"""Inventaire Kuma depuis les contrats des briques ; aucune lecture de secrets."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def monitor(name, url, description):
    parsed = urlsplit(url)
    if parsed.hostname in {'localhost', '127.0.0.1'}:
        parsed = parsed._replace(netloc='host.docker.internal' + (f':{parsed.port}' if parsed.port else ''))
    return {'name': name, 'url': urlunsplit(parsed), 'description': description,
            'type': 'http', 'method': 'GET', 'interval': 60, 'retryInterval': 60,
            'maxretries': 2, 'timeout': 15, 'resendInterval': 0,
            'accepted_statuscodes': ['200-299'], 'notificationIDList': {},
            'ignoreTls': False, 'upsideDown': False}


def build_inventory(root):
    monitors = [monitor('Processus — Cœur', 'http://host.docker.internal:5100/health',
                        'Processus du Cœur. Ne prouve pas les dépendances ni une opération métier.')]
    for path in sorted((root / 'briques').glob('*/manifest.json')):
        data = json.loads(path.read_text())
        if data.get('statut') not in {'actif', 'a_tester'} or not data.get('url_sante'):
            continue
        monitors.append(monitor(f'Processus — {data["nom"]}', data['url_sante'],
                                f'Contrat {path.relative_to(root)} ; santé déclarée, pas preuve métier.'))
    monitors.extend([
        monitor('Dépendance — Forge backend', 'http://host.docker.internal:8600/api/health', 'Backend Forge, distinct de son adaptateur.'),
        monitor('Dépendance — Keycloak', 'http://host.docker.internal:8080/realms/master/.well-known/openid-configuration', 'Disponibilité du fournisseur identité.'),
        monitor('Dépendance — Oria backend', 'http://host.docker.internal:8000/health',
                'Backend réel Oria, indépendant de son adaptateur Workplace.'),
        monitor('Dépendance — Oria S3 (SeaweedFS)', 'http://host.docker.internal:9106/healthz',
                'Stockage objet S3 d\'Oria. Santé du processus, pas une écriture d\'objet.'),
        monitor('Supervision — Prometheus', 'http://prometheus:9090/-/ready', 'Disponibilité du stockage et moteur Prometheus.'),
        monitor('Supervision — Grafana', 'http://grafana:3000/api/health', 'Disponibilité Grafana et base interne.'),
    ])
    unique = {}
    for item in monitors:
        unique.setdefault(item['url'], item)
    return list(unique.values())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(build_inventory(args.root), ensure_ascii=False, indent=2))
