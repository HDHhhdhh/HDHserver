"""Literal native-SQLite/log-owner proofs in owned OS temp; no app/network."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
sys.dont_write_bytecode = True
import tempfile
import types
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--repo-root', default=str(Path(__file__).resolve().parents[1]))
parser.add_argument('--draft-root', default=str(Path(__file__).resolve().parents[1]))
args, test_args = parser.parse_known_args()
REPO = Path(args.repo_root).resolve()
DRAFT = REPO
sys.path.insert(0, str(REPO))
temporary = tempfile.TemporaryDirectory(prefix='p5-log-fixture-')
RUNTIME = Path(temporary.name).resolve()


def target(value):
    return Path(os.path.abspath(os.fsdecode(value))) if isinstance(value, (str, bytes, os.PathLike)) else None


def audit(event, values):
    if event == 'import' and values[0] == 'app':
        raise AssertionError('app import prohibited')
    if event in {'socket.bind', 'socket.connect'}:
        raise AssertionError('network prohibited')
    if event == 'open':
        path = target(values[0])
        if path is None:
            return
        mode, flags = values[1], values[2] or 0
        writing = (isinstance(mode, str) and any(flag in mode for flag in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        if (writing or path.suffix in {'.json', '.sqlite', '.db', '.lock', '.tmp'}) and not path.is_relative_to(RUNTIME):
            raise AssertionError('non-temp runtime I/O: ' + str(path))
    elif event == 'sqlite3.connect':
        path = target(values[0])
        if path is not None and not path.is_relative_to(RUNTIME):
            raise AssertionError('non-temp SQLite connection')
    elif event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime'}:
        path = target(values[0])
        if path is not None and not path.is_relative_to(RUNTIME):
            raise AssertionError('non-temp mutation')
    elif event == 'os.rename':
        for value in values[:2]:
            path = target(value)
            if path is not None and not path.is_relative_to(RUNTIME):
                raise AssertionError('non-temp rename')


sys.addaudithook(audit)
paths = types.ModuleType('core.paths')
paths.LOGS_PATH, paths.STU_PATH = RUNTIME / 'default-must-not-exist.json', RUNTIME / 'default-students-must-not-exist.json'
sys.modules['core.paths'] = paths
os.environ.update(DATA_MIRROR_DIR=str(RUNTIME / 'mirror'), DATA_MIRROR_SYNC='1', DATA_MIRROR_SNAPSHOTS='0')
from core.log_repository import LogRepository, _public_map
from core.log_rules import merge_log_entry_safe, log_entry_conflicts_with_base
from core import storage
spec = importlib.util.spec_from_file_location('_p5_log_reconcile_draft', DRAFT / 'core/log_reconcile.py')
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)
TIME = '2026-10-13T00:00:00+09:00'
DAY = '2026-10-13'
MARKER = '__logRepositoryCompleteV1'


class ReconcileContracts(unittest.TestCase):
    def setUp(self):
        self.root = RUNTIME / self._testMethodName
        self.root.mkdir()
        self.logs = self.root / 'logs.json'
        self.db = self.root / 'app.sqlite'
        self.repository = LogRepository(logs_path=self.logs, db_path=str(self.db),
            merge_entry=merge_log_entry_safe, entry_conflicts=log_entry_conflicts_with_base,
            lock_factory=lambda: storage.file_lock(self.logs))
        self.connection = sqlite3.connect(self.db, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.repository._ensure_schema(self.connection)
        self.connection.execute('CREATE TABLE unrelated(k TEXT PRIMARY KEY,value TEXT)')
        self.connection.execute('INSERT INTO unrelated VALUES(?,?)', ('synthetic', 'preserve'))

    def tearDown(self):
        self.connection.close()

    def seed(self, rows, compatibility):
        for date, sid, value in rows:
            raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            self.connection.execute('INSERT INTO logs VALUES(?,?,?,?)', (date, sid, raw, TIME))
        self.logs.write_text(json.dumps(compatibility, ensure_ascii=False), encoding='utf-8')

    def plan(self, compatibility):
        return model.build_plan(model.read_rows(self.connection), compatibility, self.repository, inserted_updated_at=TIME)

    def test_fill_reuses_owner_and_preserves_false_zero_unknown_and_marker_type(self):
        primary = {'done': False, 'score': 0, 'notes': 'SQLite', 'blank': '', 'absent': None,
                   'unknown': {'keep': True}, MARKER: 1}
        fallback = {'done': 0, 'score': False, 'notes': 'JSON', 'blank': 'filled', 'absent': 'fallback',
                    'unknown': {'json': True}, 'new': {'values': [False, 0]}, MARKER: True}
        compatibility = {DAY: {'s1': fallback}}
        before_primary, before_json = copy.deepcopy(primary), copy.deepcopy(compatibility)
        self.seed([(DAY, 's1', primary)], compatibility)
        plan = self.plan(compatibility)
        self.assertTrue(plan.parity)
        self.assertEqual(plan.counts['filled_fields'], 3)
        self.assertEqual(plan.counts['nonempty_sql_primary_conflict_fields'], 4)
        model.apply_plan(self.connection, plan, self.repository, owned_root=RUNTIME)
        value = json.loads(model.read_rows(self.connection)[0][2])
        self.assertIs(value['done'], False)
        self.assertEqual(type(value['score']), int)
        self.assertEqual(value['score'], 0)
        self.assertEqual(value['unknown'], {'keep': True})
        self.assertEqual(value['new'], {'values': [False, 0]})
        self.assertEqual(type(value[MARKER]), int)
        self.assertEqual(value[MARKER], 1)
        self.assertEqual(primary, before_primary)
        self.assertEqual(compatibility, before_json)

    def test_sealed_snapshot_never_resurrects_absent_fields(self):
        primary = {'done': False, 'score': 0, MARKER: True}
        fallback = {'done': True, 'notes': 'stale', 'unknown': {'stale': True}, 'score': 7}
        compatibility = {DAY: {'s1': fallback}}
        self.seed([(DAY, 's1', primary)], compatibility)
        plan = self.plan(compatibility)
        self.assertTrue(plan.parity)
        self.assertEqual(plan.mutations, ())
        self.assertGreater(plan.counts['sealed_ignored_difference_fields'], 0)
        self.assertEqual(model.sqlite_public_map(plan.after_rows, self.repository), {DAY: {'s1': {'done': False, 'score': 0}}})

    def test_json_only_unknown_rows_insert_without_mass_sealing(self):
        compatibility = {DAY: {'s1': {'unknown': {'nested': [False, 0]}, 'homeworkTable': [{'book': 'Book', 'extra': {'keep': 1}}]}}}
        self.seed([], compatibility)
        plan = self.plan(compatibility)
        self.assertTrue(plan.parity)
        self.assertEqual(plan.counts['inserted'], 1)
        model.apply_plan(self.connection, plan, self.repository, owned_root=RUNTIME)
        entry = json.loads(model.read_rows(self.connection)[0][2])
        self.assertNotIn(MARKER, entry)
        self.assertEqual(entry, compatibility[DAY]['s1'])

    def test_actual_clear_and_failed_json_mirror_keep_snapshot_authority(self):
        compatibility = {DAY: {'s1': {'notes': 'old', 'unknown': {'keep': True}, 'done': False, 'score': 0}}}
        self.seed([(DAY, 's1', {'done': False, 'score': 0})], compatibility)
        with patch('core.log_repository.save_atomic', side_effect=PermissionError('synthetic JSON mirror failure')):
            result = self.repository.patch_entry(DAY, 's1', {'__clear': ['notes'], 'done': False}, {})
        self.assertTrue(result.sqlite_ok)
        self.assertFalse(result.json_ok)
        self.assertNotIn('notes', result.merged)
        self.assertEqual(result.merged['unknown'], {'keep': True})
        self.assertIs(result.merged['done'], False)
        plan = self.plan(compatibility)
        self.assertTrue(plan.parity)
        self.assertEqual(plan.mutations, ())
        self.assertNotIn('notes', model.sqlite_public_map(plan.after_rows, self.repository)[DAY]['s1'])
        self.assertEqual(json.loads(self.logs.read_bytes()), compatibility)

    def test_full_map_gate_sees_empty_day_beyond_thirty_sample_rows(self):
        compatibility = {}
        rows = []
        first = dt.date(2026, 1, 1)
        for index in range(40):
            date = (first + dt.timedelta(days=index)).isoformat()
            rows.append((date, 's1', {'value': index}))
            compatibility[date] = {'s1': {'value': index}}
        compatibility['2026-10-13'] = {}
        self.seed(rows, compatibility)
        before = model.row_digest(model.read_rows(self.connection))
        plan = self.plan(compatibility)
        self.assertFalse(plan.parity)
        self.assertEqual(plan.counts['full_public_dates'], 41)
        with self.assertRaisesRegex(model.ReconcileError, 'parity'):
            model.apply_plan(self.connection, plan, self.repository, owned_root=RUNTIME)
        self.assertEqual(model.row_digest(model.read_rows(self.connection)), before)

    def test_apply_idempotence_exact_rollback_and_unrelated_table_preservation(self):
        compatibility = {DAY: {'s1': {'new': 7}, 's2': {'jsonOnly': True}}}
        self.seed([(DAY, 's1', ' { "unknown": {"keep": true} } '), (DAY, 's3', '{ "untouched": 0 }')], compatibility)
        original = model.read_rows(self.connection)
        json_bytes = self.logs.read_bytes()
        plan = self.plan(compatibility)
        self.assertTrue(plan.parity)
        model.apply_plan(self.connection, plan, self.repository, owned_root=RUNTIME)
        self.assertEqual(self.plan(compatibility).mutations, ())
        untouched = next(row for row in model.read_rows(self.connection) if row[1] == 's3')
        self.assertEqual(untouched[2:], ('{ "untouched": 0 }', TIME))
        model.rollback_plan(self.connection, plan, owned_root=RUNTIME)
        self.assertEqual(model.read_rows(self.connection), original)
        self.assertEqual(self.logs.read_bytes(), json_bytes)
        self.assertEqual(tuple(self.connection.execute('SELECT * FROM unrelated').fetchone()), ('synthetic', 'preserve'))

    def test_injected_partial_apply_uses_one_native_transaction(self):
        compatibility = {DAY: {'s1': {'new': 7}, 's2': {'jsonOnly': True}}}
        self.seed([(DAY, 's1', {'unknown': 'keep'})], compatibility)
        before = model.read_rows(self.connection)
        plan = self.plan(compatibility)
        def fail(_index):
            raise PermissionError('synthetic transaction failure')
        with self.assertRaises(PermissionError):
            model.apply_plan(self.connection, plan, self.repository, owned_root=RUNTIME, failure_injector=fail)
        self.assertEqual(model.read_rows(self.connection), before)

    def test_same_second_update_delete_restore_and_stale_rollback_are_detected(self):
        compatibility = {DAY: {'s1': {'new': 7}}}
        self.seed([(DAY, 's1', {'value': 'A'}), (DAY, 's2', {'other': True})], compatibility)
        original = model.read_rows(self.connection)
        original_digest = model.row_digest(original)
        max_time = self.connection.execute('SELECT MAX(updated_at) FROM logs').fetchone()[0]
        plan = self.plan(compatibility)
        self.connection.execute('UPDATE logs SET entry_json=? WHERE sid=?', ('{"value":"B"}', 's1'))
        self.assertEqual(self.connection.execute('SELECT MAX(updated_at) FROM logs').fetchone()[0], max_time)
        self.assertNotEqual(model.row_digest(model.read_rows(self.connection)), original_digest)
        with self.assertRaisesRegex(model.ReconcileError, 'changed'):
            model.apply_plan(self.connection, plan, self.repository, owned_root=RUNTIME)
        self.connection.execute('DELETE FROM logs WHERE sid=?', ('s2',))
        after_delete = model.row_digest(model.read_rows(self.connection))
        self.connection.execute('INSERT INTO logs VALUES(?,?,?,?)', original[1])
        self.assertNotEqual(model.row_digest(model.read_rows(self.connection)), after_delete)
        self.assertEqual(self.connection.execute('SELECT MAX(updated_at) FROM logs').fetchone()[0], max_time)
        fresh = self.plan(compatibility)
        model.apply_plan(self.connection, fresh, self.repository, owned_root=RUNTIME)
        self.connection.execute('UPDATE logs SET entry_json=? WHERE sid=?', ('{"external":false}', 's2'))
        changed = model.read_rows(self.connection)
        with self.assertRaisesRegex(model.ReconcileError, 'later log writes'):
            model.rollback_plan(self.connection, fresh, owned_root=RUNTIME)
        self.assertEqual(model.read_rows(self.connection), changed)

    def test_malformed_rows_or_date_maps_refuse_reconciliation(self):
        self.seed([(DAY, 's1', '{broken')], {})
        original = model.read_rows(self.connection)
        with self.assertRaises(model.ReconcileError):
            self.plan({})
        self.assertEqual(model.read_rows(self.connection), original)
        self.connection.execute('DELETE FROM logs')
        with self.assertRaises(model.ReconcileError):
            self.plan({'2026-02-30': {}})

    def test_actual_repair_projection_difference_fails_full_parity_before_apply(self):
        students = self.root / 'students.json'
        students.write_text('[{"id":"s1","subBook1":"Book"}]', encoding='utf-8')
        provider = types.ModuleType('_p5_actual_log_provider')
        provider.__file__ = str(REPO / 'routes/log_repository_provider.py')
        source = (REPO / 'routes/log_repository_provider.py').read_text(encoding='utf-8')
        exec(compile(source, provider.__file__, 'exec'), provider.__dict__)
        provider.STU_PATH = students
        books = provider._load_student_homework_books_by_sid()
        provider._student_homework_books = lambda sid: list(books.get(sid, []))
        self.repository.repair_entry = provider.repair_log_entry_placeholders
        compatibility = {DAY: {'s1': {'notes': 'valid JSON note'}}}
        self.seed([(DAY, 's1', {'notes': '???'})], compatibility)
        self.assertEqual(self.repository.read_logs(), {DAY: {'s1': {'notes': 'valid JSON note'}}})
        plan = self.plan(compatibility)
        self.assertFalse(plan.parity, 'raw fill-only policy must not silently rewrite nonempty placeholder text')

    def test_full_map_parity_does_not_prove_batch_empty_row_shape(self):
        compatibility = {DAY: {'s1': {}}}
        self.seed([(DAY, 's1', {})], compatibility)
        self.assertTrue(self.plan(compatibility).parity)
        dual_batch = self.repository.read_logs(sid_filters=['s1'])
        sqlite_batch = _public_map(self.repository._sqlite_dump_sids(self.connection, ['s1']))
        self.assertEqual(dual_batch, {DAY: {'s1': {}}})
        self.assertEqual(sqlite_batch, {})
        self.assertNotEqual(dual_batch, sqlite_batch)

    def test_full_map_parity_does_not_prove_numeric_alias_entry_shape(self):
        compatibility = {DAY: {'1': {'notes': 'JSON alias'}}}
        self.seed([(DAY, '1', {'notes': 'SQLite exact'})], compatibility)
        self.assertTrue(self.plan(compatibility).parity)
        dual_alias = self.repository.read_entry(DAY, '001')
        sqlite_exact = self.repository._sqlite_get_entry(self.connection, DAY, '001')
        self.assertEqual(dual_alias.entry, {'notes': 'JSON alias'})
        self.assertEqual(sqlite_exact, {})
        self.assertNotEqual(dual_alias.entry, sqlite_exact)


if __name__ == '__main__':
    try:
        result = unittest.main(argv=[__file__, *test_args], verbosity=2, exit=False).result
        assert not paths.LOGS_PATH.exists() and not paths.STU_PATH.exists(), 'default path must never be created'
    finally:
        assert storage.shutdown_mirrors(2), 'fixture worker must stop before OS-temp cleanup'
        temporary.cleanup()
    raise SystemExit(0 if result.wasSuccessful() else 1)
