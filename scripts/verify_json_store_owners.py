"""Actual owner modules, native leases and full auth blueprint; OS-temp only.

PermissionError is injected into both current read_bytes and legacy read_text.
The fixture does not alter Windows ACLs or import app/default runtime paths.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--repo-root', default=str(Path(__file__).resolve().parents[1]))
parser.add_argument('--expect-guarded', action='store_true', default=True)
args, unittest_args = parser.parse_known_args()
ROOT = Path(args.repo_root).resolve()
sys.path.insert(0, str(ROOT))
temporary = tempfile.TemporaryDirectory(prefix='json-store-owners-')
RUNTIME = Path(temporary.name).resolve()
ORIGINAL_CWD = Path.cwd()
assert RUNTIME.is_relative_to(Path(tempfile.gettempdir()).resolve())


def target(value):
    return Path(os.path.abspath(os.fsdecode(value))) if isinstance(value, (str, bytes, os.PathLike)) else None


def audit(event, values):
    if event == 'import' and values[0] in {'app', 'core.paths'}:
        raise AssertionError('app/default path import prohibited')
    if event in {'socket.connect', 'socket.bind'}:
        raise AssertionError('network prohibited')
    if event == 'open':
        path = target(values[0])
        if path is None:
            return
        mode, flags = values[1], values[2] or 0
        writing = (isinstance(mode, str) and any(flag in mode for flag in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        if (writing or path.suffix in {'.json', '.sqlite', '.db', '.lock', '.tmp'}) and not path.is_relative_to(RUNTIME):
            raise AssertionError('non-temp runtime I/O: ' + str(path))
    elif event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime'}:
        path = target(values[0])
        if path is not None and not path.is_relative_to(RUNTIME):
            raise AssertionError('non-temp mutation: ' + str(path))
    elif event == 'os.rename':
        for value in values[:2]:
            path = target(value)
            if path is not None and not path.is_relative_to(RUNTIME):
                raise AssertionError('non-temp rename: ' + str(path))


sys.addaudithook(audit)
os.environ.update(DATA_MIRROR_DIR=str(RUNTIME / 'mirror'), DATA_MIRROR_SYNC='1', DATA_MIRROR_SNAPSHOTS='0')
from core import storage, stores, person_identity, person_identity_store, material_state
from core import update_assignment_store, watch_store, school_calendar_store, json_store
from flask import Flask


def fingerprint(path):
    raw = path.read_bytes()
    info = path.stat()
    return raw, info.st_mtime_ns, info.st_size, hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


@contextmanager
def denied_read(path):
    original_bytes, original_text = Path.read_bytes, Path.read_text
    blocked = Path(path).resolve()
    def read_bytes(value):
        if value.resolve() == blocked:
            raise PermissionError('synthetic primary read denial')
        return original_bytes(value)
    def read_text(value, *values, **keywords):
        if value.resolve() == blocked:
            raise PermissionError('synthetic primary read denial')
        return original_text(value, *values, **keywords)
    with patch.object(Path, 'read_bytes', read_bytes), patch.object(Path, 'read_text', read_text):
        yield


class OwnerContracts(unittest.TestCase):
    def test_all_account_writer_owners_exclude_password_maps_from_mirroring(self):
        from core.student_app_auth_store import create_account, change_credentials
        from core.student_account_repository import StudentAccountRepository
        accounts = self.root / 'public-accounts.json'
        roster = self.root / 'public-students.json'
        write_json(roster, [{'id': 's1', 'name': 'Synthetic', 'school': 'QA', 'grade': '1'}])
        with patch.object(storage, '_submit_committed_mirror', side_effect=AssertionError('account values cannot enter mirror jobs')):
            create_account(accounts, 'Synthetic', ['s1'])
            change_credentials(accounts, 'Synthetic', 'SyntheticRenamed', 'synthetic-hash')
            repository = StudentAccountRepository(accounts, roster)
            repository.admin_reset('SyntheticRenamed', 'temporary-qa-only')
            repository.admin_set_disabled('SyntheticRenamed', True)
        self.assertTrue(repository.get('SyntheticRenamed')['disabled'])
        self.assertFalse((RUNTIME / 'mirror/public-accounts.json').exists())

    def setUp(self):
        self.root = RUNTIME / self._testMethodName
        self.root.mkdir()

    def identity(self):
        persons, students, journal = self.root / 'persons.json', self.root / 'students.json', self.root / 'pending.json'
        directory = person_identity.new_directory(now='2026-10-13T00:00:00Z')
        directory['unknown'] = {'keep': ['한글', 7]}
        write_json(persons, directory)
        write_json(students, [])
        return persons, students, journal, directory

    def material(self):
        paths = tuple(self.root / name for name in ['materials.json', 'assigns.json', 'pageFolders.json'])
        values = ({'known': {'unknown': 'keep'}}, {'date': {'s1': ['material']}}, {'s1': {'folder': 'keep'}})
        for path, value in zip(paths, values):
            write_json(path, value)
        return paths, values

    def warm_identity(self, persons, students):
        person_identity_store.load_identity_state_strict(persons, students)
        stores.get_store('persons', persons).read()
        stores.get_store('students', students).read()

    def warm_material(self, paths):
        material_state.load_material_state(*paths)
        for path in paths:
            stores.get_store('legacy', path).read()

    def test_relative_registry_and_store_paths_stay_bound_after_cwd_change(self):
        first, second = self.root / 'first', self.root / 'second'
        first.mkdir()
        second.mkdir()
        for folder, value in [(first, 'A'), (second, 'B')]:
            write_json(folder / 'state.json', {'store': value})
        try:
            os.chdir(first)
            relative = stores.get_store('legacy', Path('state.json'))
            direct = json_store.JsonStore('state.json', dict, mirror=False)
            self.assertEqual(relative.read()[0], {'store': 'A'})
            self.assertEqual(direct.read()[0], {'store': 'A'})
            os.chdir(second)
            alias = stores.get_store('legacy', first / 'state.json')
            self.assertIs(alias, relative)
            self.assertEqual(alias.read()[0], {'store': 'A'})
            self.assertEqual(direct.read()[0], {'store': 'A'})
        finally:
            os.chdir(ORIGINAL_CWD)

    def test_warm_identity_read_and_mutation_deny_before_all_writes(self):
        persons, students, journal, _directory = self.identity()
        for blocked in (persons, students):
            self.warm_identity(persons, students)
            with denied_read(blocked), self.assertRaises(person_identity_store.PersonIdentityRecoveryRequiredError):
                person_identity_store.load_identity_state_strict(persons, students)
            # Re-prime the cache separately: the mutation must also start warm.
            self.warm_identity(persons, students)
            before = tuple(fingerprint(path) for path in (persons, students))
            mutator = unittest.mock.Mock(side_effect=AssertionError('mutator before authoritative read'))
            with denied_read(blocked), patch.object(person_identity_store, 'save_atomic', wraps=person_identity_store.save_atomic) as writer:
                with self.assertRaises(person_identity_store.PersonIdentityRecoveryRequiredError):
                    person_identity_store.mutate_identity_state(persons, students, journal, mutator)
                writer.assert_not_called()
                mutator.assert_not_called()
            self.assertEqual(tuple(fingerprint(path) for path in (persons, students)), before)
            self.assertFalse(journal.exists())

    def test_warm_identity_partial_store_fault_does_not_initialize_empty_state(self):
        persons, students, journal, _directory = self.identity()
        self.warm_identity(persons, students)
        persons.unlink()
        with self.assertRaises(person_identity_store.PersonIdentityUnavailableError):
            person_identity_store.load_identity_state_strict(persons, students)
        self.assertFalse(persons.exists())
        self.assertFalse(journal.exists())
        write_json(persons, _directory)
        self.warm_identity(persons, students)
        students.unlink()
        with self.assertRaises(person_identity_store.PersonIdentityRecoveryRequiredError):
            person_identity_store.load_identity_state_strict(persons, students)
        self.assertFalse(students.exists())
        self.assertFalse(journal.exists())

    def test_identity_fault_rollback_and_recovery_refresh_cached_alias_reads(self):
        persons, students, journal, directory = self.identity()
        alias = stores.get_store('legacy', persons)
        self.assertEqual(alias.read()[0], directory)
        def mutation(current, rows):
            draft = dict(current)
            draft['transactionChange'] = True
            return draft, rows, None
        for boundary in ('after_persons', 'after_students', 'before_commit'):
            def failure(stage):
                if stage == boundary:
                    raise RuntimeError('synthetic transaction failure')
            with self.assertRaisesRegex(RuntimeError, 'synthetic transaction failure'):
                person_identity_store.mutate_identity_state(persons, students, journal, mutation, failure_injector=failure)
            self.assertEqual(person_identity_store.load_identity_state_strict(persons, students), (directory, []))
            self.assertEqual(alias.read()[0], directory)
            self.assertFalse(journal.exists())
        rollback_started = [False]
        original = person_identity_store.save_atomic
        def failure(stage):
            if stage == 'after_persons':
                rollback_started[0] = True
                raise RuntimeError('synthetic first commit failure')
        def failed_restore(path, value, **options):
            if Path(path) == students and rollback_started[0]:
                raise PermissionError('synthetic rollback write denial')
            return original(path, value, **options)
        with patch.object(person_identity_store, 'save_atomic', failed_restore):
            with self.assertRaises(person_identity_store.PersonIdentityRecoveryRequiredError):
                person_identity_store.mutate_identity_state(persons, students, journal, mutation, failure_injector=failure)
        self.assertTrue(journal.exists())
        self.assertEqual(json.loads(journal.read_bytes())['state'], 'RECOVERY_REQUIRED')
        self.assertTrue(person_identity_store.recover_identity_state_if_needed(persons, students, journal))
        self.assertEqual(person_identity_store.load_identity_state_strict(persons, students), (directory, []))
        self.assertEqual(alias.read()[0], directory)
        self.assertFalse(journal.exists())

    def test_warm_material_read_and_replace_deny_before_journals_or_writes(self):
        paths, _values = self.material()
        for blocked in paths:
            self.warm_material(paths)
            with denied_read(blocked), self.assertRaises(material_state.MaterialStateRecoveryRequiredError):
                material_state.load_material_state(*paths)
            self.warm_material(paths)
            before = tuple(fingerprint(path) for path in paths)
            with denied_read(blocked), patch.object(material_state, 'save_atomic', wraps=material_state.save_atomic) as writer:
                with self.assertRaises(material_state.MaterialStateRecoveryRequiredError):
                    material_state.replace_material_state_component(*paths, 'materials', {'new': {}})
                writer.assert_not_called()
            self.assertEqual(tuple(fingerprint(path) for path in paths), before)
            self.assertFalse(material_state.material_state_journal_path(paths[0]).exists())
            self.assertFalse(material_state.material_state_last_good_path(paths[0]).exists())

    def test_warm_updates_watch_and_calendar_reads_remain_authoritative(self):
        cases = [
            ('updates', update_assignment_store.load_updates_strict, update_assignment_store.UpdateAssignmentStoreError),
            ('watch', watch_store.load_watch_strict, watch_store.WatchStoreReadError),
            ('calendar', school_calendar_store.load_school_calendar_snapshot, school_calendar_store.SchoolCalendarUnavailableError),
        ]
        for name, loader, error in cases:
            path = self.root / (name + '.json')
            write_json(path, {'unknown': {'keep': '한글'}})
            loader(path)
            stores.get_store(name, path).read()
            before = fingerprint(path)
            with denied_read(path), self.assertRaises(error):
                loader(path)
            self.assertEqual(fingerprint(path), before)
            self.assertEqual(sorted(p.name for p in self.root.iterdir()), sorted(case[0] + '.json' for case in cases[:cases.index((name, loader, error)) + 1]))

    def test_warm_calendar_replace_denies_before_primary_save(self):
        path = self.root / 'calendar.json'
        write_json(path, {'unknown': {'keep': '한글'}})
        _document, revision = school_calendar_store.load_school_calendar_snapshot(path)
        stores.get_store('calendar', path).read()
        before = fingerprint(path)
        with denied_read(path), patch.object(school_calendar_store, 'save_atomic', wraps=school_calendar_store.save_atomic) as writer:
            with self.assertRaises(school_calendar_store.SchoolCalendarUnavailableError):
                school_calendar_store.replace_school_calendar(path, {'new': {}}, expected_revision=revision)
            writer.assert_not_called()
        self.assertEqual(fingerprint(path), before)

    def test_whole_auth_blueprint_warm_me_denial_is_503_without_writes(self):
        students = self.root / 'students.json'
        write_json(students, [{'id': 's1', 'name': 'Synthetic', 'school': 'S', 'grade': '1', 'curriculum': 'Math'}])
        paths_stub = types.ModuleType('core.paths')
        paths_stub.STU_PATH = students
        module = types.ModuleType('_json_store_owners_auth')
        module.__file__ = str(self.root / 'routes/api_auth.py')
        with patch.dict(sys.modules, {'core.paths': paths_stub}), patch.dict(os.environ, {'AUTH_SECRET': 'synthetic-owner-fixture-' + 'x' * 64, 'MASTER_PW': ''}):
            source = (ROOT / 'routes/api_auth.py').read_text(encoding='utf-8')
            exec(compile(source, str(ROOT / 'routes/api_auth.py'), 'exec'), module.__dict__)
        self.assertEqual(module.STU_PATH, students)
        self.assertEqual(module.ACCT_PATH, self.root / 'auth_accounts.json')
        write_json(module.ACCT_PATH, {'Synthetic': {'sids': ['s1'], 'pw_hash': 'synthetic-unneeded-for-me', 'legacy_session_id': 'synthetic-session', 'unknown': {'keep': 7}}})
        app = Flask('_json_store_owners_auth', static_folder=None, root_path=str(self.root))
        app.register_blueprint(module.bp_api_auth)
        app.config['TESTING'] = True
        token = module._issue_token('s1', 'Synthetic', ['s1'], session_id='synthetic-session')
        headers = {'Authorization': 'Bearer ' + token}
        with app.test_client() as client:
            response = client.get('/api/auth/me', headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['sid'], 's1')
            self.assertEqual(response.json['aid'], 'Synthetic')
            # Successful /me may persist SID refresh; fingerprint only afterward.
            module._load_acct_map()
            stores.get_store('accounts', module.ACCT_PATH).read()
            before = tuple(fingerprint(path) for path in (module.ACCT_PATH, students))
            with denied_read(module.ACCT_PATH), patch.object(module, 'save_atomic', wraps=module.save_atomic) as writer:
                response = client.get('/api/auth/me', headers=headers)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json, {'ok': False, 'error': 'account_store_unavailable'})
                writer.assert_not_called()
            self.assertEqual(tuple(fingerprint(path) for path in (module.ACCT_PATH, students)), before)
        self.assertFalse((RUNTIME / 'mirror/auth_accounts.json').exists())
        self.assertNotIn('core.paths', sys.modules, 'default runtime-path module must remain unimported')

    def test_named_fresh_read_copy_and_revision_work_is_measured_without_timing_claim(self):
        path = self.root / 'updates.json'
        write_json(path, {'day': {'s1': {'videos': ['v1'], 'unknown': 'keep'}}})
        original_copy, original_revision = json_store.copy.deepcopy, json_store.semantic_revision
        with patch.object(json_store.copy, 'deepcopy', wraps=original_copy) as copying, patch.object(json_store, 'semantic_revision', wraps=original_revision) as hashing:
            value, _revision = stores.get_store('updates', path).read_locked()
        self.assertEqual(value, {'day': {'s1': {'videos': ['v1'], 'unknown': 'keep'}}})
        print(json.dumps({'fresh_named_read_top_level_deepcopy_calls': copying.call_count, 'fresh_named_read_canonical_revision_calls': hashing.call_count}))
        self.assertGreaterEqual(copying.call_count, 1)
        self.assertEqual(hashing.call_count, 1)

    def test_data_seams_keep_values_private_and_skip_unused_revisions(self):
        path = self.root / 'updates.json'
        value = {'unknown': {'rows': ['keep']}}
        write_json(path, value)
        store = json_store.JsonStore(path, dict, dict, mirror=False)
        store.read()
        with patch.object(json_store, 'semantic_revision', side_effect=AssertionError('unused revision')):
            result = store.read_data_locked()
            result['unknown']['rows'].append('caller change')
            writer = unittest.mock.Mock(wraps=storage.save_atomic)
            store.write_data_locked(value, writer=writer)
        writer.assert_called_once_with(path, value, mirror=False)
        value['unknown']['rows'].append('caller change after save')
        self.assertEqual(store.read_data_locked(), {'unknown': {'rows': ['keep']}})
        shared = {'shared': {'rows': ['keep']}}
        missing = json_store.JsonStore(self.root / 'missing.json', lambda: shared, dict, mirror=False)
        first = missing.read_data_locked()
        first['shared']['rows'].append('caller change')
        self.assertEqual(shared, {'shared': {'rows': ['keep']}})
        self.assertEqual(missing.read_data_locked(), shared)
        self.assertFalse(missing.path.exists())

    def test_public_revision_failure_remains_typed_and_read_only(self):
        path = self.root / 'surrogate.json'
        path.write_text(json.dumps({'unknown': chr(0xD800)}, ensure_ascii=True), encoding='utf-8')
        store = json_store.JsonStore(path, dict, dict, mirror=False)
        before = fingerprint(path)
        with self.assertRaises(json_store.StoreCorrupt):
            store.read()
        self.assertEqual(fingerprint(path), before)


if __name__ == '__main__':
    try:
        result = unittest.main(argv=[__file__, *unittest_args], verbosity=2, exit=False).result
    finally:
        os.chdir(ORIGINAL_CWD)
        assert storage.shutdown_mirrors(2), 'fixture workers must stop before temp cleanup'
        temporary.cleanup()
    raise SystemExit(0 if result.wasSuccessful() else 1)
