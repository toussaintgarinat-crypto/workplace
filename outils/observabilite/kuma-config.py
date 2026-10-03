"""Émet la configuration privée sur stdout, à canaliser uniquement vers Kuma."""
import argparse
import json
from pathlib import Path
import shlex
import sys


def read_env(path):
    if not path.exists():
        return {}
    result = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.removeprefix('export ').split('=', 1)
        # Ne réalise aucune expansion shell ni substitution de commande.
        parts = shlex.split(value, comments=True)
        result[key.strip()] = ' '.join(parts)
    return result


def build_config(directory):
    local = read_env(directory / '.env')
    root = read_env(directory.parents[1] / '.env')
    cfg = {
        'username': local.get('KUMA_USER', 'admin'),
        'password': local.get('KUMA_PASSWORD', ''),
        'telegramEnabled': local.get('TELEGRAM_ENABLED', 'no') == 'yes',
        'telegramToken': local.get('TELEGRAM_BOT_TOKEN') or root.get('TELEGRAM_BOT_TOKEN', ''),
        'telegramChatID': local.get('TELEGRAM_CHAT_ID', ''),
        'telegramTopicID': local.get('TELEGRAM_TOPIC_ID', ''),
    }
    if not cfg['password']:
        raise ValueError('KUMA_PASSWORD requis')
    if cfg['telegramEnabled'] and (not cfg['telegramToken'] or not cfg['telegramChatID']):
        raise ValueError('Token et destination Telegram requis avant activation')
    return cfg


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--action', choices=['list', 'beats', 'delete', 'provision'], default='provision')
    parser.add_argument('--name')
    parser.add_argument('--monitor-file', type=Path)
    args = parser.parse_args()
    if sys.stdout.isatty():
        parser.error('Sortie privée : utiliser un pipe vers docker exec, pas le terminal')
    try:
        config = build_config(Path(__file__).resolve().parent)
        config.update(setup=args.setup, action=args.action, name=args.name)
        if args.monitor_file:
            config['monitor'] = json.loads(args.monitor_file.read_text())
        print(json.dumps(config))
    except ValueError as error:
        parser.exit(1, str(error) + '\n')
