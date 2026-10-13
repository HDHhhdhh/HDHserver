"""Offline reconciliation model; actual log owners supply projection semantics.

No default paths, schema creation, app imports, network or JSON writes here.
Mutation helpers intentionally accept only an owned OS-temp native database.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from core.date_rules import is_iso_date_key
from core.log_rules import is_empty_value
from core.log_repository import _COMPLETE_ENTRY, _public_map


class ReconcileError(RuntimeError):
    pass


def encoded(value: Any) -> bytes:
    # Wire types matter: False and 0 must not compare equal here.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def same(left: Any, right: Any) -> bool:
    return encoded(left) == encoded(right)


def digest(value: Any) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


def read_rows(connection) -> list[tuple[str, str, str, str]]:
    rows = connection.execute('SELECT date,sid,entry_json,updated_at FROM logs ORDER BY date,sid').fetchall()
    return [tuple(row) for row in rows]


def row_digest(rows) -> str:
    return digest(sorted(tuple(row) for row in rows))


def _decoded(rows) -> dict[tuple[str, str], dict]:
    values = {}
    for date, sid, raw, _updated in rows:
        if not isinstance(date, str) or not is_iso_date_key(date) or not isinstance(sid, str) or not sid.strip():
            raise ReconcileError('invalid SQLite date/SID')
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError('SQLite log root is not an object')
            encoded(value)
        except (TypeError, ValueError, UnicodeError) as error:
            raise ReconcileError('invalid SQLite entry JSON') from error
        if (date, sid) in values:
            raise ReconcileError('duplicate SQLite date/SID')
        values[(date, sid)] = value
    return values


def sqlite_public_map(rows, repository) -> dict:
    result = {}
    for (date, sid), value in _decoded(rows).items():
        result.setdefault(date, {})[sid] = repository.repair_entry(copy.deepcopy(value), sid)
    return _public_map(result)


@dataclass(frozen=True)
class LogReconcilePlan:
    before_rows: tuple[tuple[str, str, str, str], ...]
    after_rows: tuple[tuple[str, str, str, str], ...]
    mutations: tuple[dict, ...]
    expected_public_digest: str
    sqlite_only_public_digest: str
    counts: dict
    primary_conflicts: tuple[dict, ...]
    sealed_differences: tuple[dict, ...]
    parity: bool

    def report(self) -> dict:
        return {
            'version': 1, 'counts': self.counts, 'full_public_map_parity': self.parity,
            'before_rows_digest': row_digest(self.before_rows),
            'after_rows_digest': row_digest(self.after_rows),
            'effective_dual_public_digest': self.expected_public_digest,
            'reconciled_sqlite_only_public_digest': self.sqlite_only_public_digest,
            'nonempty_sql_primary_conflict_fields': sorted({item['field'] for item in self.primary_conflicts}),
            'nonempty_sql_primary_conflict_field_counts': {
                field: sum(item['field'] == field for item in self.primary_conflicts)
                for field in sorted({item['field'] for item in self.primary_conflicts})
            },
            'sealed_ignored_difference_fields': sorted({item['field'] for item in self.sealed_differences}),
            'sealed_ignored_difference_field_counts': {
                field: sum(item['field'] == field for item in self.sealed_differences)
                for field in sorted({item['field'] for item in self.sealed_differences})
            },
        }


def build_plan(rows, json_map: dict, repository, *, inserted_updated_at: str) -> LogReconcilePlan:
    if not isinstance(json_map, dict):
        raise ReconcileError('logs JSON root must be an object')
    original = _decoded(rows)
    raw_repository = copy.copy(repository)
    raw_repository.repair_entry = lambda entry, _sid: entry if isinstance(entry, dict) else {}
    sqlite_map = {}
    for (date, sid), entry in original.items():
        sqlite_map.setdefault(date, {})[sid] = repository.repair_entry(copy.deepcopy(entry), sid)
    effective_dual = _public_map(repository._merge_json_fallback_map(copy.deepcopy(sqlite_map), copy.deepcopy(json_map)))
    proposed = {(date, sid): (date, sid, raw, updated) for date, sid, raw, updated in rows}
    mutations, conflicts, sealed = [], [], []
    counts = {'sqlite_rows': len(rows), 'json_rows': 0, 'inserted': 0, 'filled_rows': 0,
              'filled_fields': 0, 'unchanged': 0, 'sqlite_sealed_rows': sum(v.get(_COMPLETE_ENTRY) is True for v in original.values()),
              'json_sealed_rows': 0, 'empty_json_days': 0}
    for date, day in sorted(json_map.items()):
        if not isinstance(date, str) or not is_iso_date_key(date) or not isinstance(day, dict):
            raise ReconcileError('invalid JSON date map')
        if not day:
            counts['empty_json_days'] += 1
        for sid, fallback in sorted(day.items()):
            if not isinstance(sid, str) or not sid.strip() or not isinstance(fallback, dict):
                raise ReconcileError('invalid JSON SID/entry')
            encoded(fallback)
            counts['json_rows'] += 1
            counts['json_sealed_rows'] += fallback.get(_COMPLETE_ENTRY) is True
            key = date, sid
            primary = original.get(key)
            if primary is None:
                candidate = copy.deepcopy(fallback)
                counts['inserted'] += 1
            else:
                candidate = raw_repository._merge_json_fallback_fields(copy.deepcopy(primary), fallback, sid)
                if _COMPLETE_ENTRY in primary:
                    candidate[_COMPLETE_ENTRY] = copy.deepcopy(primary[_COMPLETE_ENTRY])
                if primary.get(_COMPLETE_ENTRY) is True:
                    for field in sorted((set(primary) | set(fallback)) - {_COMPLETE_ENTRY}):
                        if (field in primary) != (field in fallback) or not same(primary.get(field), fallback.get(field)):
                            sealed.append({'date': date, 'sid': sid, 'field': field})
                else:
                    for field in sorted((set(primary) & set(fallback)) - {_COMPLETE_ENTRY}):
                        if not is_empty_value(primary[field]) and not is_empty_value(fallback[field]) and not same(primary[field], fallback[field]):
                            conflicts.append({'date': date, 'sid': sid, 'field': field})
                changed = [field for field in candidate if field not in primary or not same(primary[field], candidate[field])]
                if changed:
                    counts['filled_rows'] += 1
                    counts['filled_fields'] += len(changed)
                else:
                    counts['unchanged'] += 1
            if primary is not None and same(candidate, primary):
                continue
            before = proposed.get(key)
            raw_after = json.dumps(candidate, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            after = (date, sid, raw_after, before[3] if before is not None else inserted_updated_at)
            proposed[key] = after
            mutations.append({'key': key, 'before': before, 'after': after})
    after_rows = tuple(proposed[key] for key in sorted(proposed))
    sqlite_only = sqlite_public_map(after_rows, repository)
    counts.update(nonempty_sql_primary_conflict_fields=len(conflicts), sealed_ignored_difference_fields=len(sealed),
                  nonempty_sql_primary_conflict_rows=len({(item['date'], item['sid']) for item in conflicts}),
                  sealed_ignored_difference_rows=len({(item['date'], item['sid']) for item in sealed}))
    counts['full_public_dates'] = len(effective_dual)
    counts['full_public_rows'] = sum(len(day) for day in effective_dual.values())
    expected, actual = digest(effective_dual), digest(sqlite_only)
    return LogReconcilePlan(tuple(sorted(tuple(row) for row in rows)), after_rows, tuple(mutations),
                            expected, actual, counts, tuple(conflicts), tuple(sealed), expected == actual)


def _assert_owned_database(connection, owned_root) -> None:
    root = Path(owned_root).resolve()
    if not root.name.startswith(('p5-log-fixture-', 'p5-offline-eval-')) or not root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ReconcileError('owned OS-temp fixture root required')
    databases = connection.execute('PRAGMA database_list').fetchall()
    main = next((Path(row[2]).resolve() for row in databases if row[1] == 'main' and row[2]), None)
    if main is None or not main.is_relative_to(root):
        raise ReconcileError('refusing mutation outside owned OS-temp database')


def apply_plan(connection, plan: LogReconcilePlan, repository, *, owned_root, failure_injector=None) -> None:
    _assert_owned_database(connection, owned_root)
    if not plan.parity:
        raise ReconcileError('full public map parity failed; apply prohibited')
    if connection.in_transaction:
        raise ReconcileError('caller transaction must be closed')
    connection.execute('BEGIN IMMEDIATE')
    try:
        if row_digest(read_rows(connection)) != row_digest(plan.before_rows):
            raise ReconcileError('SQLite input changed after planning')
        for index, mutation in enumerate(plan.mutations):
            connection.execute('INSERT INTO logs(date,sid,entry_json,updated_at) VALUES(?,?,?,?) '
                'ON CONFLICT(date,sid) DO UPDATE SET entry_json=excluded.entry_json,updated_at=excluded.updated_at', mutation['after'])
            if failure_injector is not None:
                failure_injector(index)
        current = read_rows(connection)
        if row_digest(current) != row_digest(plan.after_rows) or digest(sqlite_public_map(current, repository)) != plan.expected_public_digest:
            raise ReconcileError('post-transform full public map parity failed')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def rollback_plan(connection, plan: LogReconcilePlan, *, owned_root) -> None:
    _assert_owned_database(connection, owned_root)
    if connection.in_transaction:
        raise ReconcileError('caller transaction must be closed')
    connection.execute('BEGIN IMMEDIATE')
    try:
        if row_digest(read_rows(connection)) != row_digest(plan.after_rows):
            raise ReconcileError('later log writes detected; rollback prohibited')
        for mutation in reversed(plan.mutations):
            if mutation['before'] is None:
                connection.execute('DELETE FROM logs WHERE date=? AND sid=?', mutation['key'])
            else:
                connection.execute('INSERT INTO logs(date,sid,entry_json,updated_at) VALUES(?,?,?,?) '
                    'ON CONFLICT(date,sid) DO UPDATE SET entry_json=excluded.entry_json,updated_at=excluded.updated_at', mutation['before'])
        if row_digest(read_rows(connection)) != row_digest(plan.before_rows):
            raise ReconcileError('exact row rollback verification failed')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
