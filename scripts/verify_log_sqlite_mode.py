"""Actual log modules with literal native SQLite/JSON fixtures in OS temp only."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import urllib.parse

sys.dont_write_bytecode = True
parser = argparse.ArgumentParser()
parser.add_argument('--repo-root', default=str(Path(__file__).resolve().parents[1]))
args, test_args = parser.parse_known_args()
REPO = Path(args.repo_root).resolve()
sys.path.insert(0, str(REPO))
temporary = tempfile.TemporaryDirectory(prefix='p5-sqlite-mode-fixture-')
RUNTIME = Path(temporary.name).resolve()


def target(value):
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    text = os.fsdecode(value)
    if text.startswith('file:'):
        text = urllib.parse.unquote(urllib.parse.urlsplit(text).path)
        if os.name == 'nt' and len(text) > 2 and text[0] == '/' and text[2] == ':':
            text = text[1:]
    return Path(os.path.abspath(text))


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
paths.LOGS_PATH = RUNTIME / 'default-log-must-not-exist.json'
paths.STU_PATH = RUNTIME / 'default-roster-must-not-exist.json'
sys.modules['core.paths'] = paths
os.environ.update(DATA_MIRROR_DIR=str(RUNTIME / 'mirror'), DATA_MIRROR_SYNC='1',
                  DATA_MIRROR_SNAPSHOTS='0', LOG_STORE_MODE='dual', LOG_JSON_EXPORT='1')
from flask import Flask
from core import log_json_export as exports, log_repository as repository_module, storage
from core.json_store import StoreCorrupt
from core.log_repository import LogRepository
from core.log_rules import merge_log_entry_safe, log_entry_conflicts_with_base
from routes import api_logs, log_repository_provider as provider

DAY, PRIOR, FUTURE = '2026-10-13', '2026-10-12', '2026-10-14'
STAMP = '2026-10-13T12:00:00+09:00'
MARKER = '__logRepositoryCompleteV1'
OBSERVATIONS = []


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def file_fingerprint(path):
    if not path.exists():
        return None
    info = path.stat()
    return info.st_mtime_ns, info.st_size, hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def deny_compatibility_reads(logs_path):
    original_text, original_bytes, original_open = Path.read_text, Path.read_bytes, Path.open
    def text(path, *args, **kwargs):
        if Path(path) == logs_path:
            raise AssertionError('SQLite mode read logs.json')
        return original_text(path, *args, **kwargs)
    def binary(path, *args, **kwargs):
        if Path(path) == logs_path:
            raise AssertionError('SQLite mode read logs.json')
        return original_bytes(path, *args, **kwargs)
    def opened(path, *args, **kwargs):
        if Path(path) == logs_path:
            raise AssertionError('SQLite mode opened logs.json')
        return original_open(path, *args, **kwargs)
    with patch.object(Path, 'read_text', text), patch.object(Path, 'read_bytes', binary), patch.object(Path, 'open', opened), \
         patch.object(repository_module, 'load', side_effect=AssertionError('SQLite mode invoked JSON loader')), \
         patch.object(repository_module, '_cached_log_json_for_read', side_effect=AssertionError('SQLite mode invoked JSON cache')):
        yield


class SQLiteModeContracts(unittest.TestCase):
    def setUp(self):
        self.root = RUNTIME / self._testMethodName
        self.root.mkdir()
        self.logs, self.db, self.roster = self.root / 'logs.json', self.root / 'app.sqlite', self.root / 'students.json'
        self.logs.write_text('{}', 'utf-8')
        self.roster.write_text('[]', 'utf-8')
        self.con = sqlite3.connect(self.db, isolation_level=None, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute('PRAGMA journal_mode=WAL')
        self.con.execute('CREATE TABLE logs(date TEXT NOT NULL,sid TEXT NOT NULL,entry_json TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(date,sid))')
        self.con.execute('CREATE TABLE unrelated(k TEXT PRIMARY KEY,v TEXT)')
        self.con.execute('INSERT INTO unrelated VALUES(?,?)', ('keep', 'literal'))
        with repository_module._LOG_JSON_READ_CACHE_LOCK:
            repository_module._LOG_JSON_READ_CACHE.clear()
        with repository_module._LOG_PROJECTION_CACHE_LOCK:
            repository_module._LOG_PROJECTION_CACHE.clear()
        self.blocked_releases = []

    def tearDown(self):
        for event in self.blocked_releases:
            event.set()
        self.assertTrue(exports.drain_log_exports(5), 'export worker did not drain')
        self.assertTrue(exports.shutdown_log_exports(5), 'export worker did not shut down')
        with exports._queue_lock:
            exports._queue = None
        self.con.close()

    def repo(self, mode='sqlite', *, export=False, **kwargs):
        options = dict(logs_path=self.logs, db_path=str(self.db), store_mode=mode, json_export=export,
                       merge_entry=merge_log_entry_safe, entry_conflicts=log_entry_conflicts_with_base,
                       lock_factory=lambda: storage.file_lock(self.logs, timeout_sec=15, poll_sec=0.005, stale_sec=30),
                       today_key=lambda: FUTURE)
        options.update(kwargs)
        return LogRepository(**options)

    def seed(self, rows, legacy=None):
        self.con.execute('DELETE FROM logs')
        for date, sid, value in rows:
            raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            self.con.execute('INSERT INTO logs VALUES(?,?,?,?)', (date, sid, raw, STAMP))
        self.logs.write_text(json.dumps(legacy or {}, ensure_ascii=False), 'utf-8')

    def rows(self):
        return [tuple(row) for row in self.con.execute('SELECT date,sid,entry_json,updated_at FROM logs ORDER BY date,sid')]

    def client(self, repository):
        app = Flask('_p5_actual_log_routes')
        app.testing = True
        app.register_blueprint(api_logs.bp_api_logs)
        return app.test_client(), patch.object(api_logs, 'get_log_repository', return_value=repository)

    def test_default_dual_invalid_mode_and_io_free_constructor(self):
        absent = self.root / 'missing-dir' / 'missing.json'
        repo = LogRepository(logs_path=absent, db_path=str(absent.with_suffix('.sqlite')))
        self.assertEqual(repo.store_mode, 'dual')
        self.assertFalse(absent.parent.exists())
        with self.assertRaises(StoreCorrupt):
            LogRepository(logs_path=absent, store_mode='other')
        self.assertFalse(absent.parent.exists())

    def test_supported_reconciled_full_date_sid_batch_entry_export_and_summary_parity(self):
        entry = {'done': False, 'score': 0, 'notes': '보존', 'unknown': {'types': [False, 0]},
                 'assignedTests': [{'id': 'a', 'state': 'assigned', 'extra': {'keep': True}}]}
        sealed = {'done': True, 'hwChecked': True, 'unknown': {'keep': 'SQL'}, MARKER: True}
        rows = [(PRIOR, 's1', entry), (DAY, 's1', sealed), (DAY, 'raw-empty', {}),
                (DAY, 'public-empty', {MARKER: True}), (DAY, '1', {'done': False, 'score': 0})]
        # Literal post-reconciliation state: SQL-only raw{} remains absent in JSON.
        legacy = {PRIOR: {'s1': copy.deepcopy(entry)}, DAY: {'s1': {'notes': 'stale', 'done': False},
                  '1': {'done': False, 'score': 0}, 'public-empty': {MARKER: True}}}
        self.seed(rows, legacy)
        dual, sqlite = self.repo('dual'), self.repo()
        scopes = [('', '', None), (DAY, '', None), ('', 's1', None), (DAY, 's1', None),
                  ('', '', ['s1', 'raw-empty', 'public-empty']), (DAY, '', ['raw-empty', 'public-empty']),
                  (DAY, '001', None), ('', '', ['001']), ('', '', ['missing']), (FUTURE, '', ['missing'])]
        for date, sid, sids in scopes:
            with self.subTest(date=date, sid=sid, sids=sids):
                self.assertEqual(canonical(dual.read_logs(date, sid, sids)), canonical(sqlite.read_logs(date, sid, sids)))
        for sid in ('s1', '001', 'missing', 'public-empty', 'raw-empty'):
            self.assertEqual(canonical(dual.read_entry(DAY, sid).entry), canonical(sqlite.read_entry(DAY, sid).entry))
        targets = {'s1': DAY, '1': DAY}
        self.assertEqual(canonical(dual.read_export_history(targets)), canonical(sqlite.read_export_history(targets)))
        self.assertEqual(canonical(dual.summarize_unarchived_done()), canonical(sqlite.summarize_unarchived_done()))
        arrivals = {PRIOR: {'s1': '12:00'}, DAY: {'s1': '13:00', '1': '14:00', 'missing': '15:00'}}
        self.assertEqual(canonical(dual.summarize_missing_leave(arrivals)), canonical(sqlite.summarize_missing_leave(arrivals)))
        self.assertNotIn(MARKER, canonical(sqlite.read_logs()))
        actual = sqlite.read_logs(PRIOR)['2026-10-12']['s1']
        self.assertIs(actual['done'], False)
        self.assertIs(type(actual['score']), int)
        actual['unknown']['types'].append('caller')
        self.assertEqual(sqlite.read_logs(PRIOR)[PRIOR]['s1']['unknown']['types'], [False, 0])

    def test_unsupported_json_raw_empty_scope_is_a_rollout_blocker(self):
        self.seed([(DAY, 'empty', {})], {DAY: {'empty': {}}})
        dual, sqlite = self.repo('dual'), self.repo()
        self.assertEqual(canonical(dual.read_logs()), canonical(sqlite.read_logs()))
        legacy_batch, sqlite_batch = dual.read_logs(sid_filters=['empty']), sqlite.read_logs(sid_filters=['empty'])
        self.assertNotEqual(canonical(legacy_batch), canonical(sqlite_batch), 'negative must retain provenance-dependent scope difference')
        OBSERVATIONS.append({'unsupported_scope': 'JSON raw empty row batch SID', 'rollout_blocker': True})

    def test_unsupported_numeric_alias_primary_conflict_is_a_rollout_blocker(self):
        self.seed([(DAY, '1', {'notes': 'SQL'})], {DAY: {'1': {'notes': 'JSON'}}})
        dual, sqlite = self.repo('dual'), self.repo()
        self.assertEqual(canonical(dual.read_logs()), canonical(sqlite.read_logs()))
        self.assertNotEqual(canonical(dual.read_entry(DAY, '001').entry), canonical(sqlite.read_entry(DAY, '001').entry))
        OBSERVATIONS.append({'unsupported_scope': 'numeric alias with nonempty canonical conflict', 'rollout_blocker': True})

    def test_sqlite_reads_writes_exports_and_summaries_never_read_compatibility_json(self):
        self.seed([(DAY, 's1', {'notes': 'keep', 'unknown': {'v': False}, 'score': 0})],
                  {DAY: {'s1': {'notes': 'stale', 'jsonOnly': True}}})
        repo = self.repo()
        before_json = file_fingerprint(self.logs)
        with deny_compatibility_reads(self.logs):
            self.assertEqual(repo.read_entry(DAY, 's1').entry['notes'], 'keep')
            repo.read_logs()
            repo.read_logs(DAY, sid_filters=['s1', 'missing'])
            repo.read_export_history({'s1': DAY})
            repo.summarize_unarchived_done()
            repo.summarize_missing_leave({DAY: {'s1': '12:00'}})
            changed = repo.patch_entry(DAY, 's1', {'done': False, 'new': 0}, {})
            batch = repo.legacy_post({DAY: {'s1': {'flag': False}, 's2': {'notes': 'batch'}}})
            self.assertTrue(changed.sqlite_ok)
            self.assertTrue(batch.sqlite_ok)
            self.assertFalse(changed.json_ok)
            self.assertFalse(batch.json_ok)
        self.assertEqual(file_fingerprint(self.logs), before_json)
        self.assertEqual(repo.read_entry(DAY, 's1').entry['unknown'], {'v': False})
        self.assertNotIn('jsonOnly', repo.read_entry(DAY, 's1').entry)

    def test_missing_db_and_schema_fail_closed_without_auto_creation(self):
        missing = self.root / 'missing-directory' / 'app.sqlite'
        repo = self.repo(db_path=str(missing))
        with deny_compatibility_reads(self.logs):
            with self.assertRaises(StoreCorrupt):
                repo.read_logs()
            result = repo.patch_entry(DAY, 's1', {'notes': 'new'}, {})
        self.assertFalse(result.sqlite_ok)
        self.assertIsInstance(result.sqlite_error, StoreCorrupt)
        self.assertFalse(missing.exists())
        self.assertFalse(missing.parent.exists())
        self.con.execute('DROP TABLE logs')
        with deny_compatibility_reads(self.logs):
            with self.assertRaises(StoreCorrupt):
                self.repo().read_logs()
        self.assertIsNone(self.con.execute("SELECT name FROM sqlite_master WHERE name='logs'").fetchone())

    def test_unavailable_warm_cache_raises_typed_without_fallback_or_writes(self):
        self.seed([(DAY, 's1', {'notes': 'before'})], {DAY: {'s1': {'notes': 'JSON fallback'}}})
        repo = self.repo()
        for _ in range(3):
            repo.read_logs()
        before_rows, before_json = self.rows(), file_fingerprint(self.logs)
        with patch.object(repo, '_connect', side_effect=PermissionError('synthetic DB ACL denial')), deny_compatibility_reads(self.logs):
            with self.assertRaises(StoreCorrupt):
                repo.read_logs()
            with self.assertRaises(StoreCorrupt):
                repo.read_entry(DAY, 's1')
            with self.assertRaises(StoreCorrupt):
                repo.read_export_history({'s1': DAY})
            with self.assertRaises(StoreCorrupt):
                repo.summarize_unarchived_done()
            with self.assertRaises(StoreCorrupt):
                repo.summarize_missing_leave({DAY: {'s1': '12:00'}})
            result = repo.patch_entry(DAY, 's1', {'notes': 'blocked'}, {})
            self.assertFalse(result.sqlite_ok)
        self.assertEqual(self.rows(), before_rows)
        self.assertEqual(file_fingerprint(self.logs), before_json)

    def test_malformed_sql_objects_fail_closed_and_batch_rolls_back_earlier_row(self):
        for raw in ('{', '[]', 'null', '', '42'):
            with self.subTest(raw=raw):
                self.seed([(DAY, 'good', {'notes': 'before'}), (DAY, 'bad', raw)], {DAY: {'bad': {'notes': 'JSON'}}})
                repo = self.repo()
                before_rows, before_json = self.rows(), file_fingerprint(self.logs)
                with deny_compatibility_reads(self.logs):
                    with self.assertRaises(StoreCorrupt):
                        repo.read_logs()
                    with self.assertRaises(StoreCorrupt):
                        repo.read_entry(DAY, 'bad')
                    result = repo.patch_entry(DAY, 'bad', {'notes': 'blocked'}, {})
                    batch = repo.legacy_post({DAY: {'good': {'new': 'must rollback'}, 'bad': {'notes': 'blocked'}}})
                self.assertFalse(result.sqlite_ok)
                self.assertIsInstance(result.sqlite_error, StoreCorrupt)
                self.assertFalse(batch.sqlite_ok)
                self.assertIsInstance(batch.sqlite_error, StoreCorrupt)
                self.assertEqual(self.rows(), before_rows)
                self.assertEqual(file_fingerprint(self.logs), before_json)

    def test_malformed_sql_root_is_not_silently_accepted_by_summary_reads(self):
        self.seed([(DAY, 'bad', '[]')], {DAY: {'bad': {'done': True}}})
        with deny_compatibility_reads(self.logs):
            with self.assertRaises(StoreCorrupt):
                self.repo().summarize_unarchived_done()
            with self.assertRaises(StoreCorrupt):
                self.repo().summarize_missing_leave({DAY: {'bad': '12:00'}})

    def test_missing_db_between_check_and_connect_never_creates_a_replacement(self):
        race_db = self.root / 'race.sqlite'
        other = sqlite3.connect(race_db)
        other.execute('CREATE TABLE logs(date TEXT,sid TEXT,entry_json TEXT,updated_at TEXT)')
        other.close()
        original_connect = sqlite3.connect
        def disappear(database, *values, **options):
            if target(database) == race_db:
                race_db.unlink()
            return original_connect(database, *values, **options)
        with patch.object(sqlite3, 'connect', disappear), deny_compatibility_reads(self.logs):
            with self.assertRaises(StoreCorrupt):
                self.repo(db_path=str(race_db)).read_logs()
        self.assertFalse(race_db.exists(), 'strict sqlite open must use no-create mode after the existence check')

    def test_zero_byte_database_preflight_is_byte_identical_and_creates_no_sidecars(self):
        zero = self.root / 'zero.sqlite'
        zero.write_bytes(b'')
        before = file_fingerprint(zero)
        repo = self.repo(db_path=str(zero))
        with deny_compatibility_reads(self.logs):
            with self.assertRaises(StoreCorrupt):
                repo.read_logs()
            result = repo.patch_entry(DAY, 's1', {'notes': 'blocked'}, {})
        self.assertFalse(result.sqlite_ok)
        self.assertEqual(file_fingerprint(zero), before)
        self.assertFalse(Path(str(zero) + '-wal').exists())
        self.assertFalse(Path(str(zero) + '-shm').exists())

    def test_missing_or_partial_schema_preflight_keeps_hash_and_sidecars_unchanged(self):
        for schema in ('CREATE TABLE unrelated(value TEXT)', 'CREATE TABLE logs(date TEXT)'):
            with self.subTest(schema=schema):
                candidate = self.root / ('missing-schema.sqlite' if 'unrelated' in schema else 'partial-schema.sqlite')
                connection = sqlite3.connect(candidate)
                connection.execute(schema)
                connection.commit()
                connection.close()
                before = file_fingerprint(candidate)
                repo = self.repo(db_path=str(candidate))
                with deny_compatibility_reads(self.logs):
                    with self.assertRaises(StoreCorrupt):
                        repo.read_logs()
                    result = repo.patch_entry(DAY, 's1', {'notes': 'blocked'}, {})
                self.assertFalse(result.sqlite_ok)
                self.assertEqual(file_fingerprint(candidate), before)
                self.assertFalse(Path(str(candidate) + '-wal').exists())
                self.assertFalse(Path(str(candidate) + '-shm').exists())

    def test_nonfinite_number_write_rolls_back_without_compatibility_or_export_writes(self):
        self.seed([(DAY, 's1', {'notes': 'before', 'unknown': {'keep': False}})], {DAY: {'s1': {'notes': 'before'}}})
        repo = self.repo(export=True)
        before_rows, before_json = self.rows(), file_fingerprint(self.logs)
        with deny_compatibility_reads(self.logs):
            for number in (float('nan'), float('inf'), float('-inf')):
                with self.subTest(number=str(number)):
                    result = repo.patch_entry(DAY, 's1', {'unknown': {'bad': number}}, {})
                    self.assertFalse(result.sqlite_ok)
                    self.assertFalse(result.json_ok)
                    self.assertFalse(result.export_pending)
                    self.assertEqual(self.rows(), before_rows)
        self.assertEqual(file_fingerprint(self.logs), before_json)
        self.assertIsNone(exports._queue)

    def test_sixteen_same_pair_writers_preserve_all_distinct_fields(self):
        self.seed([(DAY, 's1', {'unknown': {'keep': True}, 'done': False, 'score': 0})])
        barrier = threading.Barrier(16)
        def write(index):
            repo = self.repo()
            barrier.wait(10)
            for round_no in range(4):
                result = repo.patch_entry(DAY, 's1', {f'writer_{index}': round_no}, {})
                if not result.sqlite_ok:
                    raise AssertionError(str(result.sqlite_error))
            return index
        with deny_compatibility_reads(self.logs), ThreadPoolExecutor(max_workers=16) as workers:
            completed = list(workers.map(write, range(16)))
        self.assertEqual(sorted(completed), list(range(16)))
        value = self.repo().read_entry(DAY, 's1').entry
        for index in range(16):
            self.assertEqual(value[f'writer_{index}'], 3)
        self.assertEqual(value['unknown'], {'keep': True})
        self.assertIs(value['done'], False)
        self.assertIs(type(value['score']), int)

    def test_clear_reload_new_repository_and_conflict_never_resurrect_legacy_json(self):
        self.seed([(DAY, 's1', {'notes': 'old', 'unknown': {'keep': False}, 'score': 0})],
                  {DAY: {'s1': {'notes': 'stale', 'deleted': 'must not resurrect'}}})
        repo = self.repo()
        before_json = file_fingerprint(self.logs)
        result = repo.patch_entry(DAY, 's1', {'__clear': ['notes'], 'done': False, MARKER: False}, {})
        self.assertTrue(result.sqlite_ok)
        self.assertNotIn('notes', result.merged)
        self.assertNotIn(MARKER, result.merged)
        raw = json.loads(self.rows()[0][2])
        self.assertIs(raw[MARKER], True)
        for _ in range(3):
            restored = self.repo().read_entry(DAY, 's1').entry
            self.assertNotIn('notes', restored)
            self.assertNotIn('deleted', restored)
            self.assertIs(restored['done'], False)
        before_rows = self.rows()
        conflict = repo.patch_entry(DAY, 's1', {'notes': 'blocked'}, {'notes': 'stale-base'})
        self.assertFalse(conflict.sqlite_ok)
        self.assertTrue(conflict.sqlite_base_conflict)
        self.assertEqual(self.rows(), before_rows)
        self.assertEqual(file_fingerprint(self.logs), before_json)

    def test_actual_route_success_flags_batch_clear_and_failure_are_preserved(self):
        self.seed([(DAY, 's1', {'notes': 'before', 'unknown': {'keep': 0}})])
        repo = self.repo()
        client, injected = self.client(repo)
        with injected, deny_compatibility_reads(self.logs):
            response = client.post('/api/logs/patch', json={'date': DAY, 'sid': 's1', 'entry': {'done': False}, '__clear': ['notes']})
            body = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertIs(body['ok'], True)
            self.assertIs(body['sqlite'], True)
            self.assertIs(body['json'], False)
            self.assertIn('warning', body)
            self.assertNotIn('notes', body['entry'])
            batch = client.post('/api/logs/patch-batch', json={'patches': [
                {'date': DAY, 'sid': 's1', 'entry': {'notes': 'new'}},
                {'date': DAY, 'sid': 's2', 'entry': {'flag': False, 'score': 0}}]})
            body = batch.get_json()
            self.assertEqual(batch.status_code, 200)
            self.assertEqual(body['count'], 2)
            self.assertIs(body['sqlite'], True)
            self.assertIs(body['json'], False)
            entry = client.get('/api/logs/entry', query_string={'date': DAY, 'sid': 's1'}).get_json()
            self.assertEqual(entry['source'], 'sqlite')
            self.assertEqual(entry['entry']['unknown'], {'keep': 0})
            before_rows = self.rows()
            conflict = client.post('/api/logs/patch', json={'date': DAY, 'sid': 's1', 'entry': {'notes': 'blocked'}, 'base': {'notes': 'old'}})
            self.assertEqual(conflict.status_code, 409)
            self.assertIs(conflict.get_json()['sqlite'], False)
            self.assertIs(conflict.get_json()['json'], False)
            self.assertEqual(self.rows(), before_rows)

    def test_content_revision_detects_same_second_change_delete_and_restore(self):
        entry = {'done': False, 'score': 0, 'unknown': {'keep': False}}
        self.seed([(DAY, 's1', entry)])
        repo = self.repo()
        first = repo.revision(DAY)
        stamp = self.con.execute('SELECT MAX(updated_at) FROM logs').fetchone()[0]
        self.con.execute('UPDATE logs SET entry_json=? WHERE date=? AND sid=?', (json.dumps({**entry, 'score': 1}), DAY, 's1'))
        changed = repo.revision(DAY)
        self.assertNotEqual(first, changed)
        self.assertEqual(self.con.execute('SELECT MAX(updated_at) FROM logs').fetchone()[0], stamp)
        self.con.execute('DELETE FROM logs WHERE date=? AND sid=?', (DAY, 's1'))
        deleted = repo.revision(DAY)
        self.assertNotEqual(changed, deleted)
        self.con.execute('INSERT INTO logs VALUES(?,?,?,?)', (DAY, 's1', json.dumps(entry), STAMP))
        self.assertEqual(repo.revision(DAY), first, 'digest is current content, not an irreversible history generation')
        self.con.execute('UPDATE logs SET entry_json=? WHERE date=? AND sid=?', (json.dumps({**entry, 'score': False}), DAY, 's1'))
        self.assertNotEqual(repo.revision(DAY), first, 'False and numeric 0 must have distinct revisions')

    def test_db_wal_shm_and_actual_roster_projection_invalidate_cache(self):
        self.seed([(DAY, 's1', {'homeworkTable': [{'book': '???', 'this': 'p1', 'pct': 0}], 'unknown': {'keep': True}})])
        self.roster.write_text(json.dumps([{'id': 's1', 'subBook1': '책A'}], ensure_ascii=False), 'utf-8')
        with patch.object(provider, 'STU_PATH', self.roster):
            repo = self.repo(repair_entry=provider.repair_log_entry_placeholders, projection_signature=provider._roster_signature)
            first = repo.read_logs(DAY)
            self.assertEqual(first[DAY]['s1']['homeworkTable'][0]['book'], '책A')
            for suffix, index in (('', 0), ('-wal', 1), ('-shm', 2)):
                path = Path(str(self.db) + suffix)
                self.assertTrue(path.exists(), 'native WAL fixture did not create ' + suffix)
                before = repo.cache_signature()
                info = path.stat()
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 100_000_000))
                after = repo.cache_signature()
                self.assertNotEqual(before[1][index], after[1][index])
            self.roster.write_text(json.dumps([{'id': 's1', 'subBook1': '책B_변경'}], ensure_ascii=False), 'utf-8')
            refreshed = repo.read_logs(DAY)
            self.assertEqual(refreshed[DAY]['s1']['homeworkTable'][0]['book'], '책B_변경')
            refreshed[DAY]['s1']['unknown']['keep'] = False
            self.assertIs(repo.read_logs(DAY)[DAY]['s1']['unknown']['keep'], True)

    def test_export_queue_creation_failure_does_not_turn_committed_primary_into_request_failure(self):
        self.seed([(DAY, 's1', {'notes': 'before'})], {DAY: {'s1': {'notes': 'before'}}})
        repo = self.repo(export=True)
        before_json = file_fingerprint(self.logs)
        with patch.object(exports, 'MirrorQueue', side_effect=RuntimeError('synthetic queue creation failure')):
            result = repo.patch_entry(DAY, 's1', {'notes': 'committed primary'}, {})
        self.assertTrue(result.sqlite_ok)
        self.assertFalse(result.json_ok)
        self.assertFalse(result.export_pending)
        self.assertEqual(repo.read_entry(DAY, 's1').entry['notes'], 'committed primary')
        self.assertEqual(file_fingerprint(self.logs), before_json)

    def paused_publisher(self):
        entered, release = threading.Event(), threading.Event()
        self.blocked_releases.append(release)
        publish = exports._publish
        calls = []
        def blocked(job):
            calls.append((job.date, job.sid))
            entered.set()
            if not release.wait(8):
                raise AssertionError('fixture publisher release timed out')
            publish(job)
        return entered, release, calls, patch.object(exports, '_publish', blocked)

    def test_blocked_export_primary_ack_is_fast_and_dirty_replay_uses_latest(self):
        self.seed([(DAY, 's1', {'notes': 'before', 'unknown': {'keep': False}, 'score': 0})], {DAY: {'s1': {'notes': 'before'}}})
        entered, release, calls, blocked = self.paused_publisher()
        repo = self.repo(export=True)
        with blocked:
            first = repo.patch_entry(DAY, 's1', {'notes': 'first'}, {})
            self.assertTrue(first.sqlite_ok)
            self.assertTrue(first.export_pending)
            self.assertFalse(first.json_ok)
            self.assertTrue(entered.wait(3))
            self.assertFalse(exports.drain_log_exports(0.01))
            before_compat = file_fingerprint(self.logs)
            second = repo.patch_entry(DAY, 's1', {'notes': 'second'}, {})
            latest = repo.patch_entry(DAY, 's1', {'__clear': ['notes'], 'done': False, 'latest': 0}, {})
            self.assertTrue(second.sqlite_ok and latest.sqlite_ok)
            self.assertFalse(release.is_set(), 'primary acknowledgement must finish while worker is still blocked')
            self.assertEqual(file_fingerprint(self.logs), before_compat)
            self.assertNotIn('notes', repo.read_entry(DAY, 's1').entry)
            release.set()
            self.assertTrue(exports.drain_log_exports(5))
        actual = json.loads(self.logs.read_text('utf-8'))[DAY]['s1']
        self.assertIs(actual[MARKER], True)
        self.assertNotIn('notes', actual)
        self.assertIs(actual['done'], False)
        self.assertIs(type(actual['latest']), int)
        self.assertEqual(actual['unknown'], {'keep': False})
        self.assertEqual(len(calls), 2, 'one in-flight job plus one coalesced dirty replay expected')

    def test_failed_export_keeps_primary_success_and_honest_route_pending_flags(self):
        self.seed([(DAY, 's1', {'notes': 'before'})], {DAY: {'s1': {'notes': 'before'}}})
        repo = self.repo(export=True)
        client, injected = self.client(repo)
        before_json = file_fingerprint(self.logs)
        with patch.object(exports, 'save_atomic', side_effect=PermissionError('synthetic export denial')), injected:
            response = client.post('/api/logs/patch', json={'date': DAY, 'sid': 's1', 'entry': {'notes': 'SQL committed'}})
            body = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertIs(body['sqlite'], True)
            self.assertIs(body['json'], False)
            self.assertIn('pending', body['warning'])
            self.assertTrue(exports.drain_log_exports(5))
        self.assertEqual(repo.read_entry(DAY, 's1').entry['notes'], 'SQL committed')
        self.assertEqual(file_fingerprint(self.logs), before_json)

    def test_delayed_export_after_raw_snapshot_restore_observes_rollback(self):
        original_raw = '{ "notes" : "before", "unknown" : {"keep":false}, "__logRepositoryCompleteV1" : true }'
        legacy = {DAY: {'s1': json.loads(original_raw), 'other': {'notes': 'unrelated'}}, PRIOR: {'other-date': {'score': 0}}}
        self.seed([(DAY, 's1', original_raw), (DAY, 'other', {'notes': 'unrelated'}), (PRIOR, 'other-date', {'score': 0})], legacy)
        repo = self.repo(export=True)
        snapshot, effective = repo.snapshot_entries_raw({(DAY, 's1'), (DAY, 'new')})
        self.assertNotIn(MARKER, effective[(DAY, 's1')])
        before_rows, before_json = self.rows(), file_fingerprint(self.logs)
        entered, release, calls, blocked = self.paused_publisher()
        with blocked:
            changed = repo.patch_entry(DAY, 's1', {'notes': 'must not resurrect'}, {})
            self.assertTrue(changed.sqlite_ok)
            self.assertTrue(entered.wait(3))
            inserted = repo.patch_entry(DAY, 'new', {'notes': 'must disappear'}, {})
            self.assertTrue(inserted.sqlite_ok)
            with repo.mutation_lock():
                repo.restore_entries_raw(snapshot, json_lock_held=True)
            self.assertEqual(self.rows(), before_rows)
            release.set()
            self.assertTrue(exports.drain_log_exports(5))
        self.assertEqual(self.rows(), before_rows)
        self.assertEqual(file_fingerprint(self.logs), before_json)
        self.assertEqual(next(row[2] for row in self.rows() if row[:2] == (DAY, 's1')), original_raw)
        self.assertNotIn('new', json.loads(self.logs.read_text('utf-8'))[DAY])
        self.assertEqual(self.con.execute('SELECT v FROM unrelated').fetchone()[0], 'literal')


if __name__ == '__main__':
    try:
        result = unittest.main(argv=[sys.argv[0], *test_args], exit=False).result
        print(json.dumps({'literal_tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
                          'scope_rollout_blockers': OBSERVATIONS, 'root': str(REPO)}, ensure_ascii=False))
    finally:
        assert exports.shutdown_log_exports(5)
        assert storage.shutdown_mirrors(5)
        temporary.cleanup()
    raise SystemExit(0 if result.wasSuccessful() else 1)
