"""Measure real recovery phases; command success is not a recovery acceptance proof.

Commands run as argv, never through a shell. Detailed output stays in private
logs. A report cannot assert service/data correctness merely from exit codes.
The caller must use guarded S237 playbooks for all remote mutations.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time


def validate(phases):
    if not isinstance(phases, list) or not phases:
        raise ValueError('Nonempty phase list required')
    names = set()
    for phase in phases:
        if not isinstance(phase, dict):
            raise ValueError('Invalid phase')
        name = phase.get('name', '')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', name) or name in names:
            raise ValueError('Unique safe phase names required')
        names.add(name)
        argv = phase.get('argv')
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a or '\0' in a for a in argv):
            raise ValueError('Command argv must be a nonempty string list')
        timeout = phase.get('timeout_seconds', 28800)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Positive finite phase timeout required')


def _save(path, report):
    temp = path.with_suffix('.pending')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _stop(process):
    # Stop descendants too, e.g. ansible-playbook's SSH child, on timeout.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def execute(phases, target, *, scope, metadata=None):
    validate(phases)
    if not isinstance(scope, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', scope):
        raise ValueError('Explicit scope label required')
    metadata = metadata or {}
    allowed = {'revision', 'generation', 'target_id', 'cache_condition', 'vm_acquisition_measured'}
    if not isinstance(metadata, dict) or set(metadata) - allowed:
        raise ValueError('Only nonsecret recovery metadata is accepted')
    for key, value in metadata.items():
        if key == 'vm_acquisition_measured':
            if not isinstance(value, bool):
                raise ValueError('VM acquisition measurement must be a boolean')
        elif not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', value):
            raise ValueError('Metadata must contain simple nonsecret labels')
        elif key == 'revision' and not re.fullmatch(r'[0-9a-f]{40}', value):
            raise ValueError('Revision must be an explicit Git SHA')
    # Serialize before running commands or creating the report directory.
    json.dumps(metadata, allow_nan=False)
    target = Path(target).absolute()
    if '..' in target.parts or target.exists() or any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError('New target without symlink parents required')
    if not target.parent.is_dir():
        raise ValueError('Existing parent required')
    target.mkdir(mode=0o700)
    target.chmod(0o700)
    started = time.monotonic()
    report = {
        'schema_version': 1,
        'scope': scope,
        'metadata': metadata,
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'execution_complete': False,
        'recovery_verified': False,
        'rto_target_seconds': 28800,
        'duration_seconds': 0,
        'phases': [],
    }
    _save(target / 'report.json', report)
    try:
        for phase in phases:
            clock = time.monotonic()
            entry = {'name': phase['name'], 'returncode': None, 'duration_seconds': 0}
            process = None
            fd = os.open(target / (phase['name'] + '.log'), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'wb') as log:
                    process = subprocess.Popen(phase['argv'], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
                    try:
                        entry['returncode'] = process.wait(timeout=phase.get('timeout_seconds', 28800))
                        if entry['returncode'] != 0:
                            _stop(process)
                    except subprocess.TimeoutExpired:
                        _stop(process)
                        entry['returncode'] = process.returncode
                        entry['failure'] = 'timeout'
            except OSError:
                entry['failure'] = 'launch'
            except BaseException:
                if process is not None:
                    _stop(process)
                    entry['returncode'] = process.returncode
                entry['failure'] = 'interrupted'
                raise
            finally:
                entry['duration_seconds'] = time.monotonic() - clock
                report['phases'].append(entry)
                report['duration_seconds'] = time.monotonic() - started
                _save(target / 'report.json', report)
            if entry['returncode'] != 0 or entry.get('failure'):
                break
        else:
            report['execution_complete'] = True
    finally:
        report['duration_seconds'] = time.monotonic() - started
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        _save(target / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text())
        report = execute(plan['phases'], args.target, scope=plan['scope'], metadata=plan.get('metadata'))
    except Exception:
        print('Measurement failed; inspect private report/logs if created')
        return 1
    print(json.dumps({k: report[k] for k in ('scope', 'execution_complete', 'recovery_verified', 'duration_seconds')}))
    return 0 if report['execution_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
