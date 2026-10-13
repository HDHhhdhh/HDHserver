from __future__ import annotations

import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.log_repository as module
from core.log_repository import LogRepository
from core.storage import file_lock


def rows(db: Path) -> list:
    with closing(sqlite3.connect(db)) as connection:
        return connection.execute('SELECT date,sid,entry_json,updated_at FROM logs ORDER BY date,sid').fetchall()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='verify-log-transform-batch-') as directory:
        root = Path(directory)
        logs, db = root / 'logs.json', root / 'app.sqlite'
        a, b, sid = '2026-10-01', '2026-10-02', '0007'
        document = {
            a: {sid: {'notes': '첫 날짜', 'unknown': {'keep': [1, 2]}, '__logRepositoryCompleteV1': True},
                'keep': {'notes': '보존'}},
            b: {sid: {'notes': '다음 날짜', 'unknown': {'keep': [3]}, '__logRepositoryCompleteV1': True}},
        }
        logs.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        with closing(sqlite3.connect(db)) as connection:
            connection.execute('CREATE TABLE logs(date TEXT,sid TEXT,entry_json TEXT,updated_at TEXT,PRIMARY KEY(date,sid))')
            for date, day in document.items():
                for target, entry in day.items():
                    connection.execute('INSERT INTO logs VALUES(?,?,?,?)',
                                       (date, target, json.dumps(entry, ensure_ascii=False), 'original'))
            connection.commit()
        repository = LogRepository(logs_path=logs, db_path=str(db),
                                   lock_factory=lambda: file_lock(logs, timeout_sec=5))
        calls, commits, saves = [], [], []
        actual_connect, actual_save = repository._connect, module.save_atomic

        def connect():
            connection = actual_connect()
            connection.set_trace_callback(lambda statement: commits.append(statement.strip()))
            return connection

        def save(path, value, *, compact=False, mirror=True):
            assert Path(path).resolve().is_relative_to(root.resolve())
            saves.append(Path(path))
            assert compact is True and mirror is True
            return actual_save(path, value, compact=compact, mirror=mirror)

        def transform(entry, date, target):
            calls.append((date, target))
            return {**entry, 'carryover': '첫 이월' if date == a else '다음 이월'}, True

        with mock.patch.object(repository, '_connect', connect), mock.patch.object(module, 'save_atomic', save):
            repository.transform_entries_by_pair({(b, sid), (a, sid)}, transform)
        assert calls == [(a, sid), (b, sid), (a, sid), (b, sid)]
        assert commits.count('BEGIN IMMEDIATE;') == 1 and commits.count('COMMIT;') == 1
        assert saves == [logs]
        expected = copy.deepcopy(document)
        expected[a][sid]['carryover'] = '첫 이월'
        expected[b][sid]['carryover'] = '다음 이월'
        assert json.loads(logs.read_text(encoding='utf-8')) == expected
        stored = {(date, target): json.loads(entry) for date, target, entry, _ in rows(db)}
        assert stored == {(date, target): entry for date, day in expected.items() for target, entry in day.items()}
        before_json, before_sql = logs.read_bytes(), rows(db)

        def fail_second(entry, date, target):
            if date == b:
                raise OSError('injected second-row failure')
            return {**entry, 'notes': '실패하면 보존'}, True

        try:
            repository.transform_entries_by_pair({(a, sid), (b, sid)}, fail_second)
            raise AssertionError('failure was not injected')
        except OSError:
            pass
        assert logs.read_bytes() == before_json and rows(db) == before_sql
        # The old two-argument API still applies independently to both dates.
        repository.transform_entries({(a, sid), (b, sid)}, lambda entry, target: ({**entry, 'legacy': target}, True))
        loaded = json.loads(logs.read_text(encoding='utf-8'))
        assert loaded[a][sid]['legacy'] == sid and loaded[b][sid]['legacy'] == sid
        assert loaded[a]['keep'] == document[a]['keep']
        assert all(loaded[date][sid]['__logRepositoryCompleteV1'] is True for date in [a, b])
    print('PASS log batch: one commit/write, per-date SID scope, unknown fields/marker, rollback and legacy adapter')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
