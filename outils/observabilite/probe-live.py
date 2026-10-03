"""Test de panne isolé sur le HP ; Telegram désactivé sauf option explicite."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import time


def cleanup_probe(rpc, name, container):
    try:
        print(rpc('delete', name=name), flush=True)
    finally:
        # Le conteneur est supprimé même si Kuma est devenu indisponible.
        subprocess.run(['docker', 'rm', '-f', container], capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--telegram', action='store_true', help='Messages vers le canal configuré et autorisé')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('cfg', root/'kuma-config.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = module.build_config(root)
    if args.telegram and not base['telegramEnabled']:
        parser.error('Telegram doit être configuré et autorisé dans .env avant le test')
    base['telegramEnabled'] = args.telegram
    name = 'TEST S235 — cible isolée'
    container = 'workplace_s235_probe'

    def rpc(action, **kwargs):
        config = {**base, 'action': action, **kwargs}
        out = subprocess.run(['docker', 'exec', '-i', 'workplace_uptime_kuma', 'node', '/app/s235-bootstrap.cjs'],
                             input=json.dumps(config), text=True, capture_output=True, check=True)
        return out.stdout

    def wait_status(expected, limit=180):
        end = time.monotonic()+limit
        while time.monotonic() < end:
            result = json.loads(rpc('beats', name=name))['data']
            latest = result[-1] if result else {}
            if latest.get('status') == expected:
                print('État prouvé:', expected, latest.get('time'), flush=True)
                return result
            time.sleep(5)
        raise AssertionError(f'État {expected} absent')

    created = False
    try:
        subprocess.run(['docker', 'run', '-d', '--name', container, '--network', 'observabilite_default',
                        '--entrypoint', 'python', 'core-core:latest', '-m', 'http.server', '8088', '--bind', '0.0.0.0'],
                       check=True, capture_output=True)
        created = True
        monitor = {'name': name, 'url': 'http://'+container+':8088/', 'type': 'http', 'method': 'GET',
                   'interval': 20, 'retryInterval': 20, 'maxretries': 2, 'timeout': 5, 'resendInterval': 0,
                   'accepted_statuscodes': ['200-299'], 'notificationIDList': {},
                   'description': 'Cible isolée ; cadence accélérée 20 s, deux retries comme les sondes réelles.'}
        print(rpc('provision', monitor=monitor), flush=True)
        wait_status(1)
        subprocess.run(['docker', 'stop', container], check=True, capture_output=True)
        print('Cible isolée arrêtée', flush=True)
        wait_status(0)
        subprocess.run(['docker', 'start', container], check=True, capture_output=True)
        print('Cible isolée relancée', flush=True)
        beats = wait_status(1)
        statuses = [x['status'] for x in beats]
        assert 2 in statuses, 'Confirmation par retries absente'
        assert statuses[0] == 1 and 0 in statuses and statuses[-1] == 1, statuses
        print('Séquence UP → PENDING → DOWN → UP prouvée:', statuses, flush=True)
    finally:
        if created:
            cleanup_probe(rpc, name, container)


if __name__ == '__main__':
    main()
