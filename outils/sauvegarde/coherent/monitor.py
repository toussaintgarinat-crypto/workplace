"""Publish sanitized backup state for node-exporter's textfile collector."""
import argparse
import json
import math
import os
from pathlib import Path
import time
import uuid


def publish(root: Path, output_dir: Path, now=None, rpo_seconds=86400):
    output_dir = Path(output_dir).absolute()
    if any(p.is_symlink() for p in (output_dir, *output_dir.parents)):
        raise ValueError('Unsafe metrics directory')
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    output_dir.chmod(0o755)
    now = time.time() if now is None else now
    try:
        state = json.loads((Path(root) / 'status.json').read_text())
        if not isinstance(state, dict):
            raise ValueError('Invalid status structure')
        def number(key):
            value = float(state.get(key, 0))
            return value if math.isfinite(value) and value >= 0 else 0
        exported = number('last_export_timestamp')
        transferred = number('last_transfer_timestamp')
        failed = number('failed_sources_count')
        success = int(state.get('last_attempt_success') is True)
    except (OSError, ValueError, TypeError):
        state = {}
        exported = transferred = success = 0
        failed = 1
    metrics = {
        'export_success': success,
        'last_export_timestamp_seconds': exported,
        'last_transfer_timestamp_seconds': transferred,
        'failed_sources': failed,
        'transfer_success': int(state.get('last_transfer_success') is True),
        'rpo_ok': int(0 < transferred <= now and now - transferred <= rpo_seconds),
        'status_updated_timestamp_seconds': now,
    }
    text = ''.join('workplace_backup_' + k + ' ' + format(v, '.17g') + '\n' for k, v in metrics.items())
    tmp = output_dir / ('.backup-' + uuid.uuid4().hex + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        tmp.chmod(0o644)
        os.replace(tmp, output_dir / 'workplace-backup.prom')
    finally:
        tmp.unlink(missing_ok=True)
    return metrics


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--rpo-seconds', type=int, default=86400)
    a = p.parse_args()
    publish(a.root, a.output_dir, rpo_seconds=a.rpo_seconds)
