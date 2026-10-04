import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

BASE = pathlib.Path(__file__).parents[1] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


restore = load('restore_data')
recover = load('recover_generation')


class FilesPhaseTests(unittest.TestCase):
    def setup_root(self, directory):
        root = pathlib.Path(directory)
        (root / 'state').mkdir()
        (root / 'state/recovery.json').write_text('{}')
        repo = root / 'backups/repository'
        (repo / 'briques/voix/data').mkdir(parents=True)
        (repo / 'briques/voix/data/a.txt').write_text('a')
        (repo / '.env').write_text('X=1')
        config = {'root': str(root), 'private_projects': {'voix': {'bind_mappings': {
            'briques/voix/data': 'repo/briques/voix/data', '.env': 'repo/.env', 'briques/voix/empty': 'repo/briques/voix/empty',
            'infra/ansible/relay/routes': 'relais/routes', 'briques': {'kind': 'release'}}}}}
        return root, config

    def test_copies_recorded_once_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root, config = self.setup_root(directory)
            with patch.object(restore.os, 'lchown'):
                result = restore.files(config)
                self.assertEqual(result, {'changed': 3, 'empty_directories': 1})
                self.assertEqual((root / 'data/repo/briques/voix/data/a.txt').read_text(), 'a')
                self.assertTrue((root / 'data/repo/briques/voix/empty').is_dir())
                self.assertFalse((root / 'data/relais').exists())
                self.assertEqual(restore.files(config)['changed'], 0)
                (root / 'data/repo/.env').unlink()
                with self.assertRaises(ValueError):
                    restore.files(config)

    def test_unrecorded_existing_target_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root, config = self.setup_root(directory)
            (root / 'data/repo/briques/voix/data').mkdir(parents=True)
            with patch.object(restore.os, 'lchown'), self.assertRaises(ValueError):
                restore.files(config)

    def test_requires_recorded_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root, config = self.setup_root(directory)
            (root / 'state/recovery.json').unlink()
            with self.assertRaises(ValueError):
                restore.files(config)


class LocateTests(unittest.TestCase):
    def exercise(self):
        ex = restore.Exercise.__new__(restore.Exercise)
        ex.config = {'catalogue': {'oria': {'directory': 'oria-stack/oria', 'excluded_services': {}},
                                   'oria-adaptateur': {'directory': 'briques/oria'},
                                   'agenda': {'directory': 'briques/agenda', 'excluded_services': {'litestream': 'r'}}}}
        ex.models = {'oria': {'services': {'db': {}}}, 'oria-adaptateur': {'services': {'oria': {}}}, 'agenda': {'services': {'agenda': {}}}}
        ex.excluded_directories = {'/home/debian/workplace/outils/mesh-https'}
        def labelled(directory, service):
            return {'Config': {'Labels': {'com.docker.compose.project.working_dir': '/home/debian/workplace/' + directory, 'com.docker.compose.service': service}}}
        ex.deployment = {'oria-db-1': labelled('oria-stack/oria', 'db'), 'workplace_oria': labelled('briques/oria', 'oria'),
                         'litestream': labelled('briques/agenda', 'litestream'), 'mesh_caddy': labelled('outils/mesh-https', 'caddy'),
                         'unknown': labelled('briques/autre', 'x')}
        return ex

    def test_same_compose_project_split_by_working_directory(self):
        ex = self.exercise()
        self.assertEqual(ex.locate('oria-db-1'), ('oria', 'db'))
        self.assertEqual(ex.locate('workplace_oria'), ('oria-adaptateur', 'oria'))

    def test_excluded_services_and_projects_are_skipped_others_refused(self):
        ex = self.exercise()
        self.assertIsNone(ex.locate('litestream'))
        self.assertIsNone(ex.locate('mesh_caddy'))
        with self.assertRaises(ValueError):
            ex.locate('unknown')
        with self.assertRaises(ValueError):
            ex.locate('absent')


class RecoveryTests(unittest.TestCase):
    def test_archive_identity_and_refusal_of_unrecorded_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            remote = root / 'backups/remote/p'
            remote.mkdir(parents=True)
            with self.assertRaises(ValueError):
                recover.archive_digest(remote)
            (remote / 'a.aes').write_bytes(b'x')
            first = recover.archive_digest(remote)
            (remote / 'b.aes').write_bytes(b'y')
            self.assertNotEqual(first, recover.archive_digest(remote))
            (root / 'backups/recovered').mkdir()
            with self.assertRaises(ValueError):
                recover.recover(str(root), 'p', '0', 'image')

    def test_recorded_different_generation_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            remote = root / 'backups/remote/p'
            remote.mkdir(parents=True)
            (remote / 'a.aes').write_bytes(b'x')
            (root / 'state').mkdir()
            (root / 'state/recovery.json').write_text(json.dumps({'archive': 'other', 'version': '0', 'profile': 'p'}))
            with self.assertRaises(ValueError):
                recover.recover(str(root), 'p', '0', 'image')


if __name__ == '__main__':
    unittest.main()
