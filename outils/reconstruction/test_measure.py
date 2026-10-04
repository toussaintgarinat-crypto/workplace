import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import measure


class Measurements(unittest.TestCase):
    def test_success_records_durations_without_claiming_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d).resolve() / 'run'
            report = measure.execute([
                {'name': 'provision', 'argv': [sys.executable, '-c', "print('private-output')"]},
                {'name': 'verify', 'argv': [sys.executable, '-c', 'pass']},
            ], target, scope='local-test', metadata={'revision': 'a' * 40})
            self.assertTrue(report['execution_complete'])
            self.assertFalse(report['recovery_verified'])
            self.assertGreaterEqual(report['duration_seconds'], sum(x['duration_seconds'] for x in report['phases']))
            self.assertEqual([x['returncode'] for x in report['phases']], [0, 0])
            self.assertNotIn('private-output', json.dumps(report))
            self.assertNotIn('argv', json.dumps(report))
            for p in target.iterdir():
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)

    def test_failure_stops_following_phases_and_records_failure(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d).resolve() / 'should-not-exist'
            report = measure.execute([
                {'name': 'restore', 'argv': [sys.executable, '-c', 'raise SystemExit(4)']},
                {'name': 'verify', 'argv': [sys.executable, '-c', f'open({str(marker)!r}, "w").close()']},
            ], Path(d).resolve() / 'run', scope='local-test')
            self.assertFalse(report['execution_complete'])
            self.assertEqual(report['phases'][0]['returncode'], 4)
            self.assertEqual(len(report['phases']), 1)
            self.assertFalse(marker.exists())

    def test_timeout_is_a_failure_with_persisted_report(self):
        with tempfile.TemporaryDirectory() as d:
            report = measure.execute([
                {'name': 'boot', 'argv': [sys.executable, '-c', 'import time; time.sleep(10)'], 'timeout_seconds': 0.05},
            ], Path(d).resolve() / 'run', scope='local-test')
            self.assertEqual(report['phases'][0]['failure'], 'timeout')
            self.assertFalse(report['execution_complete'])

    def test_missing_executable_is_reported_without_command_details(self):
        with tempfile.TemporaryDirectory() as d:
            report = measure.execute([{'name': 'boot', 'argv': ['/missing-s237-command']}], Path(d).resolve() / 'run', scope='local-test')
            self.assertEqual(report['phases'][0]['failure'], 'launch')
            self.assertNotIn('/missing-s237-command', json.dumps(report))

    def test_failure_and_timeout_kill_descendants(self):
        for mode in ('failure', 'timeout'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root = Path(d).resolve()
                marker = root / 'surviving-child'
                child = f'import time; print("ready", flush=True); time.sleep(0.4); open({str(marker)!r}, "w").close()'
                parent = ('import subprocess, sys, time; '
                          f'p = subprocess.Popen([sys.executable, "-c", {child!r}], stdout=subprocess.PIPE); '
                          'p.stdout.readline(); '
                          + ('raise SystemExit(4)' if mode == 'failure' else 'time.sleep(10)'))
                report = measure.execute([{'name': 'phase', 'argv': [sys.executable, '-c', parent],
                                           'timeout_seconds': 3 if mode == 'failure' else 0.15}], root / 'run', scope='local-test')
                self.assertFalse(report['execution_complete'])
                time.sleep(0.5)
                self.assertFalse(marker.exists(), 'A child survived a failed/timed-out phase')

    def test_invalid_plan_has_no_filesystem_effect(self):
        with tempfile.TemporaryDirectory() as d:
            for phases in ([], [{'name': '../escape', 'argv': ['true']}], [{'name': 'x', 'argv': 'true'}], [{'name': 'x', 'argv': []}], [{'name': 'x', 'argv': ['true'], 'timeout_seconds': -1}], [{'name': 'x', 'argv': ['true']}] * 2):
                target = Path(d).resolve() / 'run'
                with self.assertRaises(ValueError):
                    measure.execute(phases, target, scope='local-test')
                self.assertFalse(target.exists())

    def test_existing_target_and_symlink_parent_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / 'link').symlink_to(root, target_is_directory=True)
            for target in (root, root / 'link' / 'run'):
                with self.assertRaises(ValueError):
                    measure.execute([{'name': 'x', 'argv': ['true']}], target, scope='local-test')

    def test_metadata_has_unambiguous_types_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            for metadata in ({'vm_acquisition_measured': 'false'}, {'revision': {'secret': 'value'}}, {'revision': 'main'}, {'target_id': []}):
                target = Path(d).resolve() / 'run'
                with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                    measure.execute([{'name': 'x', 'argv': ['true']}], target, scope='local-test', metadata=metadata)
                self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
