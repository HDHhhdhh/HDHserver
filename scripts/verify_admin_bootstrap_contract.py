"""Actual P6 blueprints/owners with literal OS-temp fixtures; no app import.

The three request-barrier functions are compiled verbatim from app.py's AST.
Application construction, recovery, public-host routing, servers, and Windows
ACL changes are deliberately outside this fixture. Actual auth is process-only
synthetic HTTP Basic; no authorizer override or network call is used.
"""
from __future__ import annotations

import argparse
import ast
import base64
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
from unittest.mock import Mock, patch
import urllib.parse

sys.dont_write_bytecode = True
parser = argparse.ArgumentParser()
parser.add_argument('--repo-root', default=str(Path(__file__).resolve().parents[1]))
args, test_args = parser.parse_known_args()
REPO = Path(args.repo_root).resolve()
sys.path.insert(0, str(REPO))
temporary = tempfile.TemporaryDirectory(prefix='p6-admin-state-fixture-')
RUNTIME = Path(temporary.name).resolve()
os.environ.update(DATA_DIR=str(RUNTIME / 'data'), DB_PATH=str(RUNTIME / 'app.sqlite'),
                  DATA_MIRROR_DIR=str(RUNTIME / 'mirror'), DATA_MIRROR_SYNC='1',
                  DATA_MIRROR_SNAPSHOTS='0', LOG_STORE_MODE='dual', LOG_JSON_EXPORT='0',
                  UPDATES_GET_ENSURE='1', ACADEMY_ADMIN_USERNAME='synthetic-admin')


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
        runtime = path.suffix in {'.json', '.sqlite', '.db', '.lock', '.tmp'} or str(path).endswith(('-wal', '-shm'))
        if (writing or runtime) and not path.is_relative_to(RUNTIME):
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
# Execute only the real declaration module with its path owner moved to temp.
# Do not call initialize_runtime_paths(). All other imports remain real modules.
paths = types.ModuleType('core.paths')
paths.__file__ = str(RUNTIME / 'core' / 'paths.py')
sys.modules['core.paths'] = paths
exec(compile((REPO / 'core/paths.py').read_text('utf-8-sig'), str(REPO / 'core/paths.py'), 'exec'), paths.__dict__)

from flask import Flask, abort, g, request
from werkzeug.security import generate_password_hash
from core import admin_revisions, json_store, log_repository, progress_store, stores
from core.admin_api_guard import install_admin_api_guard
from core.api_errors import install_api_error_handlers
from core.person_identity import new_directory
from core.request_consistency import POST_DATE_ENDPOINTS, absence_barrier_mode, request_has_invalid_scoped_date
from routes import api_admin_state, api_attend, api_logs, api_progress, api_school_calendar, api_students, api_updates, api_videos
from routes.absence_assignment_cleanup import AbsenceRecoveryRequiredError, absence_read_barrier

PASSWORD = 'process-only-synthetic-password'
os.environ['ACADEMY_ADMIN_PASSWORD_HASH'] = generate_password_hash(PASSWORD, method='pbkdf2:sha256:1000')
AUTH = {'Authorization': 'Basic ' + base64.b64encode(('synthetic-admin:' + PASSWORD).encode()).decode()}
DAY, PRIOR, FUTURE, MISSING = '2026-10-13', '2026-10-12', '2026-10-14', '2026-10-15'
STAMP = '2026-10-13T12:00:00+09:00'
MARKER = '__logRepositoryCompleteV1'
REVISION_KEYS = {'students', 'videos', 'updates', 'logs', 'logHistory', 'absent', 'progress',
                 'progressHistory', 'schoolCal', 'weekend', 'attendance', 'contact', 'arriveTime',
                 'arriveHistory', 'makeupCarryover', 'extra', 'todayOrder'}
BARRIER_NAMES = ('needs_absence_consistency_barrier', 'wait_for_absence_transaction', 'release_absence_transaction_barrier')
tree = ast.parse((REPO / 'app.py').read_text('utf-8-sig'))
create = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'create_app')
BARRIER_NODES = [next(node for node in create.body if isinstance(node, ast.FunctionDef) and node.name == name) for name in BARRIER_NAMES]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')


def fingerprints():
    out = {}
    for path in RUNTIME.rglob('*'):
        if path.is_file():
            info = path.stat()
            out[str(path.relative_to(RUNTIME))] = (info.st_mtime_ns, info.st_size, hashlib.sha256(path.read_bytes()).hexdigest())
    return out


@contextmanager
def denied_read(path):
    read_bytes, read_text = Path.read_bytes, Path.read_text
    blocked = Path(path)
    def binary(value, *args, **kwargs):
        if Path(value) == blocked:
            raise PermissionError('synthetic primary read denied')
        return read_bytes(value, *args, **kwargs)
    def text(value, *args, **kwargs):
        if Path(value) == blocked:
            raise PermissionError('synthetic primary read denied')
        return read_text(value, *args, **kwargs)
    with patch.object(Path, 'read_bytes', binary), patch.object(Path, 'read_text', text):
        yield


class AdminStateContracts(unittest.TestCase):
    def setUp(self):
        self.initializer = Mock(side_effect=AssertionError('GET must not initialize today'))
        self.students = [{'id': 's1', 'name': '합성 학생', 'subBook1': '교재 A', 'unknown': {'flag': False, 'n': 0}},
                         {'id': '7', 'name': '숫자 SID', 'unknown': 'keep'}]
        self.videos = [{'id': 'v1', 'mid': 'M1', 'url': 'https://v.kollus.com/M1', 'title': '합성 영상',
                        'unknown': {'flag': False, 'n': 0}}]
        self.updates = {DAY: {'s1': {'videos': ['v1'], 'source': 'manual', 'unknown': False}},
                        FUTURE: {'s1': {'videos': [], 'source': 'unknown', 'n': 0}}}
        self.s1 = {'m1': 'none', 'tests': [{'id': 'T1', 'done': False, 'score': 0, 'unknown': {'token': '한글'}}],
                   'unknown': False, 'n': 0, '__manualProgressMids': ['m1']}
        self.progress = {DAY: {'s1': self.s1, '7': {'mid': 'numeric', 'zero': 0}, '007': {}, '8': {'mid': 'done'},
                               'bad': 'legacy text', 'blank': '', 'zero': 0, 'false': False},
                         PRIOR: {'s1': {'mid': 'done', 'old': False}, '7': {'mid': 'skip'}, 'rawlist': [1]},
                         FUTURE: {'s1': {'mid': 'interrupted'}, '007': {'mid': 'exactfuture'}},
                         '2026-10-11': [], '_unknown': {'s1': {'unknown': 'preserve old history'}}, '2024-02-29': {}}
        self.absent = {'by_date': {DAY: ['7', '7', '']}, 'by_student': {'7': DAY},
                       'by_slot': {DAY: {'s1': [2, 1, 2]}}, 'unknown': 'not public'}
        self.calendar = {'QA': {'rows': [{'date': DAY, 'note': '', 'unknown': 0}]}, 'unknown': False}
        documents = {paths.STU_PATH: self.students, paths.VID_PATH: self.videos, paths.UPD_PATH: self.updates,
                     paths.PRG_PATH: self.progress, paths.ABS_PATH: self.absent, paths.CAL_PATH: self.calendar,
                     paths.LOGS_PATH: {DAY: {'s1': {'note': 'JSON retained', 'jsonOnly': False}}, PRIOR: {}},
                     paths.WEEKEND_SLOTS_PATH: {DAY: {'s1': [1, 2]}}, paths.ATTENDANCE_PATH: {DAY: {'s1': False}},
                     paths.CONTACT_PATH: {DAY: {'s1': 0}}, paths.ARRIVE_TIME_PATH: {DAY: {'s1': '15:00'}, PRIOR: {'s1': '14:00'}},
                     paths.EXTRA_PATH: {DAY: ['s1']}, paths.TODAY_ORDER_PATH: {DAY: ['s1', '7']},
                     paths.BASE / 'makeup_carryover.json': {'s1': [{'date': PRIOR, 'status': 'assigned'}]}}
        for path, value in documents.items():
            write_json(path, value)
        for path in (paths.PERSONS_PATH, paths.PERSON_IDENTITY_JOURNAL_PATH,
                     paths.BASE / 'instance/absence_transactions/pending.json'):
            if path.exists():
                path.unlink()
        (RUNTIME / 'instance/absence_transactions').mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(RUNTIME / 'app.sqlite', isolation_level=None, check_same_thread=False)
        self.con.execute('PRAGMA journal_mode=WAL')
        self.con.execute('CREATE TABLE IF NOT EXISTS logs(date TEXT NOT NULL,sid TEXT NOT NULL,entry_json TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(date,sid))')
        self.con.execute('CREATE INDEX IF NOT EXISTS idx_logs_sid ON logs(sid)')
        self.con.execute('DELETE FROM logs')
        self.con.execute('INSERT INTO logs VALUES(?,?,?,?)', (DAY, 's1', json.dumps({'done': False, 'score': 0, 'unknown': {'nested': 'SQL priority'}}), STAMP))
        self.con.execute('INSERT INTO logs VALUES(?,?,?,?)', (PRIOR, 's1', json.dumps({'done': True, 'leaveAt': '18:00', MARKER: True}), STAMP))
        self.con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        stores.invalidate_stores()
        with admin_revisions._LOG_REVISION_LOCK:
            admin_revisions._LOG_REVISIONS.clear()
        with log_repository._LOG_PROJECTION_CACHE_LOCK:
            log_repository._LOG_PROJECTION_CACHE.clear()
        self.app = Flask('_p6_actual_admin_routes')
        self.app.testing = True
        self.app.config['ADMIN_API_GUARD'] = 'enforce'
        install_api_error_handlers(self.app)
        for module, name in ((api_students, 'bp_api_students'), (api_videos, 'bp_api_videos'),
                             (api_updates, 'bp_api_updates'), (api_logs, 'bp_api_logs'),
                             (api_attend, 'bp_api_attend'), (api_progress, 'bp_api_progress'),
                             (api_school_calendar, 'bp_api_school_calendar'), (api_admin_state, 'bp_api_admin_state')):
            self.app.register_blueprint(getattr(module, name))
        api_updates.configure_updates_assignment_hooks(self.app, initialize_today=self.initializer, reconcile_self_study=Mock())
        install_admin_api_guard(self.app)
        self.barrier_calls = []
        @contextmanager
        def observed_barrier(*, shared=False):
            self.barrier_calls.append(shared)
            with absence_read_barrier(shared=shared, lock_timeout_sec=2):
                yield
        namespace = {'app': self.app, 'g': g, 'request': request, 'abort': abort,
                     'POST_DATE_ENDPOINTS': POST_DATE_ENDPOINTS, 'absence_barrier_mode': absence_barrier_mode,
                     'request_has_invalid_scoped_date': request_has_invalid_scoped_date,
                     'absence_read_barrier': observed_barrier, 'AbsenceRecoveryRequiredError': AbsenceRecoveryRequiredError}
        exec(compile(ast.Module(body=copy.deepcopy(BARRIER_NODES), type_ignores=[]), str(REPO / 'app.py'), 'exec'), namespace)
        self.client = self.app.test_client()
        self.baseline = fingerprints()

    def tearDown(self):
        self.initializer.assert_not_called()
        self.con.close()

    def get(self, url, *, headers=None, remote='127.0.0.1'):
        return self.client.get(url, headers=AUTH if headers is None else headers, environ_overrides={'REMOTE_ADDR': remote})

    def assert_unchanged(self, before=None):
        self.assertEqual(fingerprints(), self.baseline if before is None else before)

    def test_bootstrap_deep_equal_to_all_seven_canonical_http_payloads_no_write(self):
        endpoints = {'students': '/api/students', 'videos': '/api/videos', 'updates': '/api/updates?readOnly=1',
                     'logs': '/api/logs?date=' + DAY, 'absent': '/api/absent',
                     'progress': '/api/progress?date=' + DAY, 'schoolCal': '/api/school-calendar'}
        individual = {}
        for key, endpoint in endpoints.items():
            response = self.get(endpoint)
            self.assertEqual(response.status_code, 200, (key, response.get_json()))
            individual[key] = response.get_json()
        combined = self.get('/api/admin/bootstrap?date=' + DAY)
        self.assertEqual(combined.status_code, 200, combined.get_json())
        payload = combined.get_json()
        self.assertEqual(set(payload), {'date', 'revisions', *individual})
        self.assertEqual(payload['date'], DAY)
        self.assertEqual({key: payload[key] for key in individual}, individual)
        self.assertEqual(payload['students'], self.students)
        self.assertEqual(payload['videos'], self.videos)
        self.assertEqual(payload['progress'], {DAY: self.progress[DAY]})
        self.assertEqual(payload['absent'], {'by_date': {DAY: ['7']}, 'by_student': {'7': DAY}, 'by_slot': {DAY: {'s1': [1, 2]}}})
        self.assertEqual(payload['logs'][DAY]['s1']['score'], 0)
        self.assertIs(payload['logs'][DAY]['s1']['done'], False)
        self.assertIs(payload['logs'][DAY]['s1']['jsonOnly'], False)
        self.assertEqual(payload['logs'][DAY]['s1']['unknown'], {'nested': 'SQL priority'})
        for key, value in individual.items():
            self.assertEqual(payload['revisions'][key], hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        self.assertEqual(combined.headers['Cache-Control'], 'no-store')
        self.assert_unchanged()

    def test_sqlite_bootstrap_uses_strict_sql_primary_no_json_read(self):
        original = Path.read_bytes
        def no_logs(path, *args, **kwargs):
            if Path(path) == paths.LOGS_PATH:
                raise AssertionError('SQLite bootstrap read compatibility JSON')
            return original(path, *args, **kwargs)
        with patch.dict(os.environ, {'LOG_STORE_MODE': 'sqlite'}), patch.object(Path, 'read_bytes', no_logs), \
             patch.object(log_repository, 'load', side_effect=AssertionError('SQLite JSON fallback')):
            response = self.get('/api/admin/bootstrap?date=' + DAY)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNotIn('jsonOnly', response.get_json()['logs'][DAY]['s1'])
        self.assert_unchanged()

    def test_bad_bootstrap_and_revision_dates_reject_before_lease_or_any_reader(self):
        for endpoint in ('/api/admin/bootstrap', '/api/admin/revisions'):
            for query in ('', '?date=2026-02-30', '?date=2025-02-29', '?date=20261013', '?date=2026-10-13T00:00:00Z'):
                with self.subTest(endpoint=endpoint, query=query), patch.object(api_admin_state, 'read_admin_students', side_effect=AssertionError('invalid date read')):
                    before_calls = len(self.barrier_calls)
                    response = self.get(endpoint + query)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(len(self.barrier_calls), before_calls)
        self.assert_unchanged()

    def test_real_basic_auth_denies_before_leases_and_readers_on_all_networks(self):
        bad = {'Authorization': 'Basic ' + base64.b64encode(b'synthetic-admin:wrong').decode()}
        for endpoint in ('/api/admin/bootstrap?date=' + DAY, '/api/admin/revisions?date=' + DAY):
            for remote in ('127.0.0.1', '198.51.100.5'):
                for headers in ({}, bad, {'Authorization': 'Bearer fake'}, {'Authorization': 'Basic invalid'}):
                    with self.subTest(endpoint=endpoint, remote=remote, headers=headers), \
                         patch.object(api_admin_state, 'read_admin_students', side_effect=AssertionError('unauthorized read')):
                        before_calls = len(self.barrier_calls)
                        response = self.get(endpoint, headers=headers, remote=remote)
                        self.assertEqual(response.status_code, 401)
                        self.assertEqual(response.get_json()['code'], 'admin_auth_required')
                        self.assertIn('Basic realm=', response.headers['WWW-Authenticate'])
                        self.assertEqual(len(self.barrier_calls), before_calls)
        self.assertEqual(self.get('/api/admin/bootstrap?date=' + DAY, remote='198.51.100.5').status_code, 200)
        self.assert_unchanged()

    def test_critical_reader_failure_and_invalid_shape_are_503_without_partial_payload_or_writes(self):
        for reader in ('read_admin_students', 'read_admin_videos', 'load_updates_strict', 'get_log_repository', 'read_progress_projection'):
            with self.subTest(reader=reader), patch.object(api_admin_state, reader, side_effect=PermissionError('synthetic denied')):
                response = self.get('/api/admin/bootstrap?date=' + DAY)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.get_json(), {'ok': False, 'error': 'admin_bootstrap_unavailable'})
        for path, malformed in ((paths.STU_PATH, [None]), (paths.VID_PATH, [{}]), (paths.UPD_PATH, []), (paths.PRG_PATH, [])):
            original = path.read_bytes()
            write_json(path, malformed)
            stores.invalidate_stores()
            before = fingerprints()
            with self.subTest(path=path):
                self.assertEqual(self.get('/api/admin/bootstrap?date=' + DAY).status_code, 503)
                self.assert_unchanged(before)
            path.write_bytes(original)
            stores.invalidate_stores()

    def test_actual_optional_read_failures_keep_legacy_empty_fallback_no_primary_writes(self):
        for reader in ('load_absent', 'load_school_calendar_snapshot'):
            with self.subTest(reader=reader), patch.object(api_admin_state, reader, side_effect=PermissionError('synthetic denied')):
                response = self.get('/api/admin/bootstrap?date=' + DAY)
                self.assertEqual(response.status_code, 200)
                key = 'absent' if reader == 'load_absent' else 'schoolCal'
                self.assertEqual(response.get_json()[key], {})
                self.assertEqual(response.get_json()['students'], self.students)
        self.assert_unchanged()

    def test_identity_partial_store_stays_503_after_warm_bootstrap_and_is_not_recreated(self):
        self.assertEqual(self.get('/api/admin/bootstrap?date=' + DAY).status_code, 200)
        write_json(paths.PERSONS_PATH, new_directory(now='2026-10-13T00:00:00Z'))
        paths.STU_PATH.unlink()
        before = fingerprints()
        self.assertEqual(self.get('/api/students').status_code, 503)
        self.assertEqual(self.get('/api/admin/bootstrap?date=' + DAY).status_code, 503)
        self.assertFalse(paths.STU_PATH.exists())
        self.assertFalse(paths.PERSON_IDENTITY_JOURNAL_PATH.exists())
        self.assert_unchanged(before)

    def test_pending_absence_denies_shared_bootstrap_without_recovery_or_data_read(self):
        pending = RUNTIME / 'instance/absence_transactions/pending.json'
        write_json(pending, {'version': 1, 'state': 'PREPARED'})
        before = fingerprints()
        with patch.object(api_admin_state, 'read_admin_students', side_effect=AssertionError('pending transaction read')):
            for endpoint in ('/api/admin/bootstrap', '/api/admin/revisions'):
                response = self.get(endpoint + '?date=' + DAY)
                self.assertEqual(response.status_code, 503)
        self.assert_unchanged(before)

    def test_concurrent_bootstrap_shared_barrier_joins_native_lease(self):
        rendezvous = threading.Barrier(2)
        original = api_admin_state.read_admin_students
        def synchronized_reader():
            rendezvous.wait(timeout=2)
            return original()
        def request_one():
            with self.app.test_client() as client:
                response = client.get('/api/admin/bootstrap?date=' + DAY, headers=AUTH)
                return response.status_code, response.get_json()
        with patch.object(api_admin_state, 'read_admin_students', synchronized_reader), ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: request_one(), range(2)))
        self.assertEqual([row[0] for row in replies], [200, 200], replies)
        self.assertEqual(replies[0][1], replies[1][1])
        self.assertEqual(self.barrier_calls, [True, True])
        self.assert_unchanged()

    def test_progress_date_shapes_false_zero_unknowns_and_legacy_scalars(self):
        cases = [({'date': DAY}, {DAY: self.progress[DAY]}), ({'date': MISSING}, {MISSING: {}}),
                 ({'date': '2026-10-11'}, {'2026-10-11': {}}),
                 ({'date': DAY, 'sid': 's1'}, {DAY: {'s1': self.s1}}),
                 ({'date': DAY, 'sid': 'absent'}, {DAY: {'absent': {}}}),
                 ({'date': DAY, 'sid': '007'}, {DAY: {'007': {}}}),
                 ({'date': DAY, 'sid': '0008'}, {DAY: {'0008': {'mid': 'done'}}}),
                 ({'date': PRIOR, 'sid': '007'}, {PRIOR: {'007': {'mid': 'skip'}}}),
                 ({'date': DAY, 'sid': 'bad'}, {DAY: {'bad': 'legacy text'}}),
                 ({'date': DAY, 'sid': 'zero'}, {DAY: {'zero': {}}}),
                 ({'date': DAY, 'sid': 'false'}, {DAY: {'false': {}}}),
                 ({'date': DAY, 'sids': '007,0008,s1,blank,bad'}, {DAY: {'0008': {'mid': 'done'}, 's1': self.s1}})]
        for query, expected in cases:
            with self.subTest(query=query):
                response = self.get('/api/progress?' + urllib.parse.urlencode(query))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), expected)
                self.assertEqual(response.headers['X-Video-Watch-Cycles'], '1')
        self.assert_unchanged()

    def test_progress_history_batch_and_repeated_sid_queries_keep_alias_precedence(self):
        s1_history = {DAY: {'s1': self.s1}, PRIOR: {'s1': {'mid': 'done', 'old': False}},
                      FUTURE: {'s1': {'mid': 'interrupted'}}, '_unknown': {'s1': {'unknown': 'preserve old history'}}}
        numeric_history = {PRIOR: {'007': {'mid': 'skip'}}, FUTURE: {'007': {'mid': 'exactfuture'}}}
        self.assertEqual(self.get('/api/progress?sid=s1').get_json(), s1_history)
        self.assertEqual(self.get('/api/progress?sid=007').get_json(), numeric_history)
        expected = copy.deepcopy(s1_history)
        for date, day in numeric_history.items():
            expected.setdefault(date, {}).update(day)
        for query in ('sids=s1,007,s1', 'sid=s1&sid=007', 'sids=007&sid=s1'):
            response = self.get('/api/progress?' + query)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), expected)
        self.assert_unchanged()

    def test_progress_since_is_validated_and_selected_date_still_has_empty_day_shape(self):
        expected = {DAY: {'s1': self.s1}, FUTURE: {'s1': {'mid': 'interrupted'}},
                    '_unknown': {'s1': {'unknown': 'preserve old history'}}}
        self.assertEqual(self.get('/api/progress?sid=s1&since=' + DAY).get_json(), expected)
        self.assertEqual(self.get('/api/progress?date=' + PRIOR + '&sid=s1&since=' + DAY).get_json(), {PRIOR: {'s1': {}}})
        self.assertEqual(self.get('/api/progress?date=2024-02-29').status_code, 200)
        self.assert_unchanged()

    def test_progress_invalid_date_since_and_missing_filter_do_not_read_progress(self):
        urls = ['/api/progress', '/api/progress?since=' + DAY, '/api/progress?date=2026-02-30',
                '/api/progress?date=2025-02-29', '/api/progress?sid=s1&since=2026-02-30',
                '/api/progress?sid=s1&since=20261013', '/api/progress?sid=s1&since=2026-10-13T00:00:00Z']
        with patch.object(api_progress, 'load_progress_scope', side_effect=AssertionError('400 read progress')):
            for url in urls:
                with self.subTest(url=url):
                    self.assertEqual(self.get(url).status_code, 400)
        self.assert_unchanged()

    def test_progress_invalid_since_skips_absence_lease(self):
        before = len(self.barrier_calls)
        response = self.get('/api/progress?sid=s1&since=2026-02-30')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.barrier_calls), before, 'invalid since acquired an absence lease before 400')
        self.assert_unchanged()

    def test_single_raw_sid_with_commas_keeps_route_contract_and_shared_lease(self):
        entry = {'m1': 'none', 'unknown': False, 'n': 0}
        write_json(paths.PRG_PATH, {DAY: {',,': entry}})
        before = fingerprints()
        calls = len(self.barrier_calls)
        response = self.get('/api/progress?' + urllib.parse.urlencode({'sid': ',,'}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {DAY: {',,': entry}})
        self.assertEqual(len(self.barrier_calls), calls + 1, 'valid literal SID read skipped its shared absence lease')
        self.assertTrue(self.barrier_calls[-1])
        self.assert_unchanged(before)

    def test_progress_nested_copy_does_not_copy_whole_store_and_returns_defensive_values(self):
        store = stores.get_store('progress', paths.PRG_PATH)
        store.revision()
        raw = store._cache.data
        original_copy = copy.deepcopy
        seen = []
        def observed_copy(value, *args, **kwargs):
            self.assertIsNot(value, raw, 'whole progress store copied for a date/SID GET')
            if isinstance(value, dict):
                seen.append(tuple(value))
            return original_copy(value, *args, **kwargs)
        with patch.object(json_store.copy, 'deepcopy', observed_copy):
            response = self.get('/api/progress?date=' + DAY + '&sid=s1')
        self.assertEqual(response.get_json(), {DAY: {'s1': self.s1}})
        self.assertEqual(seen, [(DAY,)])
        private = progress_store.load_progress_scope(paths.PRG_PATH, date=DAY, sids=['s1'])
        private[DAY]['s1']['tests'][0]['unknown']['token'] = 'mutated private copy'
        self.assertEqual(self.get('/api/progress?date=' + DAY + '&sid=s1').get_json(), {DAY: {'s1': self.s1}})
        self.assert_unchanged()

    def test_progress_external_edit_delete_reappear_and_explicit_empty_survive_warm_cache(self):
        self.assertEqual(self.get('/api/progress?date=' + DAY + '&sid=s1').get_json(), {DAY: {'s1': self.s1}})
        changed = copy.deepcopy(self.progress)
        changed[DAY]['s1'] = {'m1': 'none', 'n': 0, 'unknown': False}
        write_json(paths.PRG_PATH, changed)
        self.assertEqual(self.get('/api/progress?date=' + DAY + '&sid=s1').get_json(), {DAY: {'s1': changed[DAY]['s1']}})
        del changed[DAY]['s1']
        write_json(paths.PRG_PATH, changed)
        self.assertEqual(self.get('/api/progress?date=' + DAY + '&sid=s1').get_json(), {DAY: {'s1': {}}})
        changed[DAY]['s1'] = self.s1
        write_json(paths.PRG_PATH, changed)
        self.assertEqual(self.get('/api/progress?date=' + DAY + '&sid=s1').get_json(), {DAY: {'s1': self.s1}})

    def test_revisions_cover_all_seventeen_scopes_and_content_not_max_timestamp(self):
        initial = self.get('/api/admin/revisions?date=' + DAY)
        self.assertEqual(initial.status_code, 200, initial.get_json())
        old = initial.get_json()['revisions']
        self.assertEqual(set(old), REVISION_KEYS)
        self.assertTrue(all(isinstance(value, str) and len(value) == 64 for value in old.values()))
        self.assertEqual(initial.headers['Cache-Control'], 'no-store')
        self.assert_unchanged()
        # Change a historical log while keeping updated_at exactly the same.
        self.con.execute('UPDATE logs SET entry_json=? WHERE date=? AND sid=?',
                         (json.dumps({'done': False, 'score': 0, MARKER: True}), PRIOR, 's1'))
        after = self.get('/api/admin/revisions?date=' + DAY).get_json()['revisions']
        self.assertEqual(after['logs'], old['logs'])
        self.assertNotEqual(after['logHistory'], old['logHistory'])
        prior_row = self.con.execute('SELECT entry_json,updated_at FROM logs WHERE date=? AND sid=?', (PRIOR, 's1')).fetchone()
        self.con.execute('DELETE FROM logs WHERE date=? AND sid=?', (PRIOR, 's1'))
        deleted = self.get('/api/admin/revisions?date=' + DAY).get_json()['revisions']
        self.assertNotEqual(deleted['logHistory'], after['logHistory'])
        self.con.execute('INSERT INTO logs VALUES(?,?,?,?)', (PRIOR, 's1', *prior_row))
        restored = self.get('/api/admin/revisions?date=' + DAY).get_json()['revisions']
        self.assertEqual(restored['logHistory'], after['logHistory'])
        self.assertEqual(restored['logs'], old['logs'])

    def test_global_and_date_revision_dependency_changes_are_isolated(self):
        old = self.get('/api/admin/revisions?date=' + DAY).get_json()['revisions']
        for path, revision, value in ((paths.WEEKEND_SLOTS_PATH, 'weekend', {DAY: {'s1': [2]}}),
                                     (paths.EXTRA_PATH, 'extra', {DAY: ['7']}),
                                     (paths.TODAY_ORDER_PATH, 'todayOrder', {DAY: ['7', 's1']}),
                                     (paths.BASE / 'makeup_carryover.json', 'makeupCarryover', {'s1': []}),
                                     (paths.CAL_PATH, 'schoolCal', {'unknown': 0}),
                                     (paths.UPD_PATH, 'updates', {DAY: {'s1': {'videos': []}}})):
            write_json(path, value)
            new = self.get('/api/admin/revisions?date=' + DAY).get_json()['revisions']
            self.assertNotEqual(old[revision], new[revision], revision)
            self.assertEqual(old['logs'], new['logs'])
            self.assertEqual(old['progress'], new['progress'])
            old = new
        arrivals = {DAY: {'s1': '15:00'}, PRIOR: {'s1': '14:30'}}
        write_json(paths.ARRIVE_TIME_PATH, arrivals)
        new = self.get('/api/admin/revisions?date=' + DAY).get_json()['revisions']
        self.assertEqual(new['arriveTime'], old['arriveTime'])
        self.assertNotEqual(new['arriveHistory'], old['arriveHistory'])

    def test_sqlite_revision_cache_hit_rechecks_database_availability_no_fallback(self):
        with patch.dict(os.environ, {'LOG_STORE_MODE': 'sqlite'}):
            self.assertEqual(self.get('/api/admin/revisions?date=' + DAY).status_code, 200)
            before = fingerprints()
            with patch.object(log_repository.LogRepository, '_connect', side_effect=PermissionError('synthetic SQL denial')):
                response = self.get('/api/admin/revisions?date=' + DAY)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json(), {'ok': False, 'error': 'admin_revisions_unavailable'})
            self.assert_unchanged(before)


if __name__ == '__main__':
    try:
        program = unittest.main(argv=[sys.argv[0], *test_args], verbosity=2, exit=False)
        successful = program.result.wasSuccessful()
    finally:
        temporary.cleanup()
    sys.exit(0 if successful else 1)
