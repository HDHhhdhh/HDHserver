from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import os
import pathlib
import sqlite3
import threading
from contextlib import nullcontext
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict

from core.date_rules import is_iso_date_key
from core.log_rules import is_empty_value, truthy as default_truthy
from core.json_store import StoreCorrupt
from core.json_revision import json_revision
from core.paths import LOGS_PATH
from core.storage import load, save_atomic

KST = dt.timezone(dt.timedelta(hours=9))
# Internal storage marker: this row was hydrated and committed as a full snapshot.
# It is never accepted from the caller or exposed in public log projections.
_COMPLETE_ENTRY = "__logRepositoryCompleteV1"


def _public_entry(entry: dict) -> dict:
    return {key: copy.deepcopy(value) for key, value in entry.items() if key != _COMPLETE_ENTRY}


def _public_map(data: dict) -> dict:
    return {date: {sid: _public_entry(entry) if isinstance(entry, dict) else entry
                   for sid, entry in day.items()} if isinstance(day, dict) else day
            for date, day in data.items()}


EntryFn = Callable[[dict, str], dict]
MergeFn = Callable[[dict, dict], dict]
ConflictFn = Callable[[dict, dict], bool]
TruthyFn = Callable[[Any], bool]
LockFactory = Callable[[], Any]


_LOG_JSON_READ_CACHE_LOCK = threading.Lock()
_LOG_JSON_READ_CACHE: dict[
    str,
    tuple[tuple[int, int, int, int] | None, dict, str],
] = {}
_LOG_JSON_READ_CACHE_MAX_PATHS = 16
_LOG_PROJECTION_CACHE_LOCK = threading.Lock()
_LOG_PROJECTION_CACHE = OrderedDict()


def _log_json_signature(path: pathlib.Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return (
        int(stat.st_mtime_ns),
        int(getattr(stat, "st_ctime_ns", 0)),
        int(stat.st_size),
        int(getattr(stat, "st_ino", 0)),
    )


def _read_log_json_map_with_status(path: pathlib.Path) -> tuple[dict, str]:
    try:
        raw = json.loads(path.read_text("utf-8-sig"))
    except FileNotFoundError:
        return {}, "missing"
    except Exception:
        return {}, "invalid"
    return (raw, "available") if isinstance(raw, dict) else ({}, "invalid")


_read_log_json_for_cache = _read_log_json_map_with_status


def _cached_log_json_for_read(path_value: Any) -> tuple[dict, str]:
    path = pathlib.Path(path_value)
    key = os.path.normcase(os.path.abspath(str(path)))
    with _LOG_JSON_READ_CACHE_LOCK:
        signature = _log_json_signature(path)
        cached = _LOG_JSON_READ_CACHE.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1], cached[2]
        if cached is not None:
            _LOG_JSON_READ_CACHE.pop(key, None)

        data: dict = {}
        status = "invalid"
        stable = False
        for _attempt in range(2):
            data, status = _read_log_json_for_cache(path)
            final_signature = _log_json_signature(path)
            if final_signature == signature:
                stable = True
                signature = final_signature
                break
            signature = final_signature

        if stable:
            if key not in _LOG_JSON_READ_CACHE and len(_LOG_JSON_READ_CACHE) >= _LOG_JSON_READ_CACHE_MAX_PATHS:
                _LOG_JSON_READ_CACHE.pop(next(iter(_LOG_JSON_READ_CACHE)), None)
            _LOG_JSON_READ_CACHE[key] = (signature, data, status)
        return data, status


@dataclass
class LogEntryResult:
    source: str
    entry: dict


@dataclass
class LogPostResult:
    sqlite_ok: bool
    sqlite_error: Exception | None = None
    json_ok: bool = False
    json_error: Exception | None = None
    export_pending: bool = False


@dataclass
class LogPatchResult:
    merged: dict
    sqlite_ok: bool
    sqlite_error: Exception | None = None
    sqlite_base_conflict: bool = False
    sqlite_conflict_entry: dict | None = None
    json_ok: bool = False
    json_error: Exception | None = None
    json_conflict_entry: dict | None = None
    export_pending: bool = False


def _identity_entry(entry: dict, _sid: str) -> dict:
    return entry if isinstance(entry, dict) else {}


def _replace_merge(_cur: dict, inc: dict) -> dict:
    return dict(inc) if isinstance(inc, dict) else {}


def _no_conflict(_cur: dict, _base: dict) -> bool:
    return False


class LogRepository:
    """Dual-store repository for class logs backed by SQLite plus logs.json."""

    def __init__(
        self,
        *,
        logs_path=LOGS_PATH,
        repair_entry: EntryFn = _identity_entry,
        merge_entry: MergeFn = _replace_merge,
        entry_conflicts: ConflictFn = _no_conflict,
        lock_factory: LockFactory | None = None,
        truthy: TruthyFn = default_truthy,
        today_key: Callable[[], str] | None = None,
        db_path: str | None = None,
        store_mode: str | None = None,
        json_export: bool | None = None,
        projection_signature: Callable[[], Any] | None = None,
    ):
        self.logs_path = logs_path
        self.repair_entry = repair_entry
        self.merge_entry = merge_entry
        self.entry_conflicts = entry_conflicts
        self.lock_factory = lock_factory
        self.truthy = truthy
        self.today_key = today_key or (lambda: dt.datetime.now(KST).date().isoformat())
        self.db_path = db_path
        self.store_mode = (store_mode or os.environ.get("LOG_STORE_MODE", "dual")).strip().lower()
        if self.store_mode not in {"dual", "sqlite"}:
            raise StoreCorrupt("Invalid class-log storage mode")
        export_setting = os.environ.get("LOG_JSON_EXPORT", "1")
        if json_export is None and export_setting not in {"0", "1"}:
            raise StoreCorrupt("Invalid class-log export setting")
        self.json_export = export_setting == "1" if json_export is None else bool(json_export)
        self.projection_signature = projection_signature

    def _default_db_path(self) -> str:
        if self.db_path:
            return self.db_path
        env_path = os.environ.get("DB_PATH")
        if env_path:
            return env_path
        logs_json = str(getattr(self.logs_path, "__fspath__", lambda: str(self.logs_path))())
        base_dir = os.path.dirname(os.path.abspath(logs_json))
        return os.path.join(base_dir, "app.sqlite")

    def _connect(self) -> sqlite3.Connection:
        db_path = self._default_db_path()
        if self.store_mode == "sqlite" and not pathlib.Path(db_path).is_file():
            raise StoreCorrupt("Class-log database is unavailable")
        if self.store_mode != "sqlite":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        con = sqlite3.connect(
            pathlib.Path(db_path).resolve().as_uri() + "?mode=rw" if self.store_mode == "sqlite" else db_path,
            uri=self.store_mode == "sqlite",
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        con.row_factory = sqlite3.Row
        try:
            if self.store_mode == "sqlite":
                con.execute("SELECT date,sid,entry_json,updated_at FROM logs LIMIT 0")
            con.execute("PRAGMA busy_timeout=30000;")
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
        except Exception:
            con.close()
            raise
        return con

    def _ensure_schema(self, con: sqlite3.Connection) -> None:
        if self.store_mode == "sqlite":
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='logs'").fetchone() is None:
                raise StoreCorrupt("Class-log schema is unavailable")
            return
        con.execute("""
        CREATE TABLE IF NOT EXISTS logs (
          date TEXT NOT NULL,
          sid TEXT NOT NULL,
          entry_json TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(date, sid)
        );
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_logs_sid ON logs(sid);")

    def _now_kst_iso(self) -> str:
        return dt.datetime.now(KST).isoformat(timespec="seconds")

    def _validate_sqlite_objects(self, con) -> None:
        if self.store_mode == "sqlite" and con.execute(
            "SELECT 1 FROM logs WHERE json_type(entry_json) IS NULL OR json_type(entry_json)<>'object' LIMIT 1"
        ).fetchone() is not None:
            raise StoreCorrupt("Class-log entry is unavailable")

    def _decode_sqlite_entry(self, raw: str, sid: str) -> dict:
        try:
            if self.store_mode == "sqlite" and not raw:
                raise ValueError("missing class-log entry")
            entry = json.loads(raw) if raw else {}
            if not isinstance(entry, dict):
                raise ValueError("invalid class-log entry")
        except (TypeError, ValueError) as exc:
            if self.store_mode == "sqlite":
                raise StoreCorrupt("Class-log entry is unavailable") from exc
            entry = {}
        return self.repair_entry(entry, sid)

    def _sqlite_mode_map(self, con, date="", sid="", sids=None) -> dict:
        wanted = self._normalize_sid_filters(sids or ([sid] if sid else []))
        clauses, args = [], []
        if date:
            clauses.append("date=?")
            args.append(date)
        if wanted:
            slots = ",".join("?" for _ in wanted)
            clause = f"sid IN ({slots})"
            args.extend(wanted)
            clauses.append("(" + clause + ")")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = con.execute("SELECT date,sid,entry_json FROM logs" + where, args).fetchall()
        out = {date: {}} if date else {}
        for row in rows:
            row_date, row_sid = str(row["date"]), str(row["sid"])
            entry = self._decode_sqlite_entry(row["entry_json"], row_sid)
            if wanted and not entry:
                continue
            out.setdefault(row_date, {})[row_sid] = entry
        if sids:
            out = self._filter_json_map_sids(out, wanted, date)
        elif sid:
            out = self._filter_json_map(out, date, sid)
        return out

    def _queue_exports(self, pairs) -> bool:
        if not self.json_export or not pairs:
            return False
        try:
            from core.log_json_export import enqueue_log_export
            return enqueue_log_export(self.logs_path, self._default_db_path(), pairs, self.lock_factory)
        except Exception:
            logging.getLogger(__name__).exception("Class-log export could not be initialized")
            return False

    def _sqlite_current_entry(self, con, date: str, sid: str) -> dict:
        keys = [sid]
        if sid.isdigit() and str(int(sid)) != sid:
            keys.append(str(int(sid)))
        for key in keys:
            row = con.execute("SELECT entry_json FROM logs WHERE date=? AND sid=?", (date, key)).fetchone()
            if row is not None:
                return _public_entry(self._decode_sqlite_entry(row[0], sid))
        return self.repair_entry({}, sid)

    def _sqlite_patch(self, date, sid, entry, base) -> LogPatchResult:
        result = LogPatchResult(merged={}, sqlite_ok=False)
        with self.mutation_lock():
            con = None
            try:
                con = self._connect()
                self._ensure_schema(con)
                con.execute("BEGIN IMMEDIATE")
                current = self._sqlite_current_entry(con, date, sid)
                if self.entry_conflicts(current, base):
                    con.rollback()
                    result.sqlite_base_conflict = True
                    result.sqlite_conflict_entry = current
                    return result
                merged = self.repair_entry(self.merge_entry(current, entry), sid)
                self._sqlite_upsert_entry(con, date, sid, {**merged, _COMPLETE_ENTRY: True})
                con.commit()
                result.sqlite_ok = True
                result.merged = _public_entry(merged)
            except Exception as exc:
                result.sqlite_error = exc
                if con is not None and con.in_transaction:
                    con.rollback()
                return result
            finally:
                if con is not None:
                    con.close()
            result.export_pending = self._queue_exports({(date, sid)})
        return result

    def _sqlite_post(self, incoming) -> LogPostResult:
        result = LogPostResult(sqlite_ok=False)
        pairs = set()
        with self.mutation_lock():
            con = None
            try:
                con = self._connect()
                self._ensure_schema(con)
                con.execute("BEGIN IMMEDIATE")
                for date, day in incoming.items():
                    if not isinstance(day, dict) or not is_iso_date_key(str(date)):
                        continue
                    for sid, entry in day.items():
                        if not isinstance(entry, dict):
                            continue
                        date, sid = str(date), str(sid)
                        current = self._sqlite_current_entry(con, date, sid)
                        merged = self.merge_entry(current, self.repair_entry(_public_entry(entry), sid))
                        self._sqlite_upsert_entry(con, date, sid, {**merged, _COMPLETE_ENTRY: True})
                        pairs.add((date, sid))
                con.commit()
                result.sqlite_ok = True
            except Exception as exc:
                result.sqlite_error = exc
                if con is not None and con.in_transaction:
                    con.rollback()
                return result
            finally:
                if con is not None:
                    con.close()
            result.export_pending = self._queue_exports(pairs)
        return result

    def revision(self, date_filter: str = "", sid_filters=None) -> str:
        return json_revision(self.read_logs(date_filter, sid_filters=sid_filters))

    def cache_signature(self) -> tuple:
        database = pathlib.Path(self._default_db_path())
        db_signature = tuple(_log_json_signature(pathlib.Path(str(database) + suffix))
                             for suffix in ("", "-wal", "-shm"))
        json_signature = _log_json_signature(pathlib.Path(self.logs_path)) if self.store_mode == "dual" else None
        projection = self.projection_signature() if self.projection_signature else None
        return self.store_mode, db_signature, json_signature, projection

    def verify_available(self) -> None:
        con = None
        try:
            con = self._connect()
            self._ensure_schema(con)
        except Exception as exc:
            if isinstance(exc, StoreCorrupt):
                raise
            raise StoreCorrupt("Class-log storage is unavailable") from exc
        finally:
            if con is not None:
                con.close()

    def _sqlite_get_entry(self, con: sqlite3.Connection, date: str, sid: str) -> dict:
        row = con.execute("SELECT entry_json FROM logs WHERE date=? AND sid=?;", (date, sid)).fetchone()
        if not row:
            return {}
        return self._decode_sqlite_entry(row["entry_json"], sid)

    def _sqlite_upsert_entry(self, con: sqlite3.Connection, date: str, sid: str, entry: dict) -> None:
        safe_entry = self.repair_entry(entry or {}, sid)
        con.execute(
            """
            INSERT INTO logs(date, sid, entry_json, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(date, sid) DO UPDATE SET
              entry_json=excluded.entry_json,
              updated_at=excluded.updated_at;
            """,
            (date, sid, json.dumps(safe_entry, ensure_ascii=False, allow_nan=self.store_mode != "sqlite"), self._now_kst_iso()),
        )

    def _sqlite_dump_all(self, con: sqlite3.Connection) -> dict:
        out: Dict[str, Dict[str, dict]] = {}
        rows = con.execute("SELECT date, sid, entry_json FROM logs;").fetchall()
        for row in rows:
            date = str(row["date"])
            sid = str(row["sid"])
            try:
                entry = json.loads(row["entry_json"]) if row["entry_json"] else {}
            except Exception:
                entry = {}
            out.setdefault(date, {})[sid] = self.repair_entry(entry, sid)
        return out

    def _sqlite_dump_date(self, con: sqlite3.Connection, date: str) -> dict:
        out: Dict[str, Dict[str, dict]] = {date: {}}
        rows = con.execute("SELECT sid, entry_json FROM logs WHERE date=?;", (date,)).fetchall()
        for row in rows:
            sid = str(row["sid"])
            try:
                entry = json.loads(row["entry_json"]) if row["entry_json"] else {}
            except Exception:
                entry = {}
            out[date][sid] = self.repair_entry(entry, sid)
        return out

    def _sqlite_dump_sid(self, con: sqlite3.Connection, sid: str) -> dict:
        out: Dict[str, Dict[str, dict]] = {}
        rows = con.execute("SELECT date, sid, entry_json FROM logs WHERE sid=?;", (sid,)).fetchall()
        for row in rows:
            date = str(row["date"])
            sid_s = str(row["sid"])
            try:
                entry = json.loads(row["entry_json"]) if row["entry_json"] else {}
            except Exception:
                entry = {}
            if isinstance(entry, dict) and entry:
                out.setdefault(date, {})[sid_s] = self.repair_entry(entry, sid_s)
        return out

    def _sqlite_dump_sids(
        self,
        con: sqlite3.Connection,
        sids: list[str],
        date: str = "",
    ) -> dict:
        wanted = self._normalize_sid_filters(sids)
        if not wanted:
            return {date: {}} if date else {}

        placeholders = ",".join("?" for _ in wanted)
        if date:
            rows = con.execute(
                f"SELECT date, sid, entry_json FROM logs WHERE date=? AND sid IN ({placeholders});",
                (date, *wanted),
            ).fetchall()
        else:
            rows = con.execute(
                f"SELECT date, sid, entry_json FROM logs WHERE sid IN ({placeholders});",
                tuple(wanted),
            ).fetchall()

        out: Dict[str, Dict[str, dict]] = {date: {}} if date else {}
        for row in rows:
            date_s = str(row["date"])
            sid_s = str(row["sid"])
            try:
                entry = json.loads(row["entry_json"]) if row["entry_json"] else {}
            except Exception:
                entry = {}
            if isinstance(entry, dict) and entry:
                out.setdefault(date_s, {})[sid_s] = self.repair_entry(entry, sid_s)
        return out

    def _sqlite_dump_date_sid(self, con: sqlite3.Connection, date: str, sid: str) -> dict:
        out: Dict[str, Dict[str, dict]] = {date: {}}
        entry = self._sqlite_get_entry(con, date, sid)
        if isinstance(entry, dict) and entry:
            out[date][sid] = self.repair_entry(entry, sid)
        return out

    def read_json_map(self) -> dict:
        try:
            logs = load(self.logs_path) or {}
        except Exception:
            return {}
        return logs if isinstance(logs, dict) else {}

    def _read_json_map_with_status(self) -> tuple[dict, str]:
        """Return the compatibility map plus an explicit availability state.

        A missing compatibility file is an acceptable SQLite-only deployment.
        An existing but unreadable/malformed file is different: treating it as
        an authoritative empty fallback could hide rows that still exist there.
        """
        return _read_log_json_map_with_status(pathlib.Path(self.logs_path))

    def _filter_json_map(self, data: dict, date_filter: str = "", sid_filter: str = "") -> dict:
        if not isinstance(data, dict):
            return {}

        dates = [date_filter] if date_filter else sorted(data.keys())
        out: Dict[str, Dict[str, dict]] = {}

        for date in dates:
            by_sid = data.get(date) if isinstance(data, dict) else None
            if not isinstance(by_sid, dict):
                if date_filter:
                    out.setdefault(str(date), {})
                continue

            if sid_filter:
                entry = self._sid_lookup(by_sid, sid_filter)
                if isinstance(entry, dict) and entry:
                    out.setdefault(str(date), {})[str(sid_filter)] = self.repair_entry(
                        copy.deepcopy(entry),
                        sid_filter,
                    )
                elif date_filter:
                    out.setdefault(str(date), {})
                continue

            out[str(date)] = {
                str(sid): self.repair_entry(copy.deepcopy(entry), str(sid))
                for sid, entry in by_sid.items()
                if isinstance(entry, dict)
            }

        return out

    @staticmethod
    def _normalize_sid_filters(sids) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw_sid in sids or []:
            sid = str(raw_sid or "").strip()
            if not sid:
                continue
            aliases = [sid]
            if sid.isdigit():
                aliases.append(str(int(sid)))
            for alias in aliases:
                if alias and alias not in seen:
                    seen.add(alias)
                    out.append(alias)
        return out

    def _filter_json_map_sids(self, data: dict, sids: list[str], date_filter: str = "") -> dict:
        if not isinstance(data, dict):
            return {}
        wanted = set(self._normalize_sid_filters(sids))
        dates = [date_filter] if date_filter else sorted(data.keys())
        out: Dict[str, Dict[str, dict]] = {date_filter: {}} if date_filter else {}
        for date in dates:
            by_sid = data.get(date)
            if not isinstance(by_sid, dict):
                continue
            for sid, entry in by_sid.items():
                sid_s = str(sid or "").strip()
                aliases = {sid_s}
                if sid_s.isdigit():
                    aliases.add(str(int(sid_s)))
                if not (aliases & wanted) or not isinstance(entry, dict):
                    continue
                out.setdefault(str(date), {})[sid_s] = self.repair_entry(
                    copy.deepcopy(entry),
                    sid_s,
                )
        return out

    @staticmethod
    def _sid_lookup(mapping: dict, sid: str):
        if not isinstance(mapping, dict):
            return None
        keys = [str(sid or "").strip()]
        if keys[0].isdigit():
            alt = str(int(keys[0]))
            if alt not in keys:
                keys.append(alt)
        for key in keys:
            if key and key in mapping:
                return mapping.get(key)
        return None

    @staticmethod
    def _write_sid_mapping(mapping: dict, sid: str, value) -> None:
        key = str(sid or "").strip()
        if not key:
            return
        num_key = str(int(key)) if key.isdigit() else None
        if num_key and num_key != key:
            mapping.pop(num_key, None)
        if value is None:
            mapping.pop(key, None)
        else:
            mapping[key] = value

    def _json_entry(self, date: str, sid: str) -> dict:
        logs, _status = _cached_log_json_for_read(self.logs_path)
        day = logs.get(date) if isinstance(logs, dict) else None
        entry = self._sid_lookup(day if isinstance(day, dict) else {}, sid)
        if not isinstance(entry, dict):
            entry = {}
        return self.repair_entry(copy.deepcopy(entry), sid)

    def _merge_json_fallback_fields(self, primary: dict, fallback: dict, sid: str) -> dict:
        if not isinstance(primary, dict):
            primary = {}
        if primary.get(_COMPLETE_ENTRY) is True:
            return self.repair_entry(_public_entry(primary), sid)
        if not isinstance(fallback, dict) or not fallback:
            return self.repair_entry(_public_entry(primary), sid)

        out = dict(primary)
        for key, value in fallback.items():
            if key == _COMPLETE_ENTRY:
                continue
            if key not in out or (is_empty_value(out.get(key)) and not is_empty_value(value)):
                out[key] = copy.deepcopy(value)
        return self.repair_entry(out, sid)

    def _merge_json_fallback_day(self, day: dict, by_sid: dict) -> None:
        for sid, entry in by_sid.items():
            sid_s = str(sid)
            if not isinstance(entry, dict):
                continue
            existing = day.get(sid_s)
            if isinstance(existing, dict):
                day[sid_s] = self._merge_json_fallback_fields(existing, entry, sid_s)
            elif sid_s not in day:
                day[sid_s] = self.repair_entry(copy.deepcopy(entry), sid_s)

    def _merge_json_fallback_map(self, sqlite_map: dict, json_map: dict) -> dict:
        out = dict(sqlite_map)
        for date, by_sid in (json_map.items() if isinstance(json_map, dict) else []):
            if not isinstance(by_sid, dict):
                continue
            day = out.setdefault(date, {})
            if not isinstance(day, dict):
                out[date] = {}
                day = out[date]
            self._merge_json_fallback_day(day, by_sid)
        return out

    def read_entry(self, date: str, sid: str) -> LogEntryResult:
        if self.store_mode == "sqlite":
            rows = self.read_logs(date, sid)
            return LogEntryResult("sqlite", rows.get(date, {}).get(sid, {}))
        con = None
        try:
            con = self._connect()
            self._ensure_schema(con)
            entry = self._sqlite_get_entry(con, date, sid) or {}
            if isinstance(entry, dict) and entry:
                fallback = {} if entry.get(_COMPLETE_ENTRY) is True else self._json_entry(date, sid)
                return LogEntryResult("sqlite", self._merge_json_fallback_fields(entry, fallback, sid))
        except Exception as exc:
            print("[logs.entry] sqlite failed:", exc, flush=True)
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        return LogEntryResult("json", _public_entry(self._json_entry(date, sid)))

    def read_logs(
        self,
        date_filter: str = "",
        sid_filter: str = "",
        sid_filters: list[str] | None = None,
    ) -> dict:
        if self.repair_entry is not _identity_entry and self.projection_signature is None:
            return self._read_logs_uncached(date_filter, sid_filter, sid_filters)
        key = (os.path.normcase(os.path.abspath(self._default_db_path())),
               os.path.normcase(os.path.abspath(os.fspath(self.logs_path))),
               self.repair_entry, date_filter, sid_filter, tuple(sid_filters or []))
        before = self.cache_signature()
        if before[1][0] is not None:
            with _LOG_PROJECTION_CACHE_LOCK:
                cached = _LOG_PROJECTION_CACHE.get(key)
                if cached is not None and cached[0] == before:
                    _LOG_PROJECTION_CACHE.move_to_end(key)
                    data = copy.deepcopy(cached[1])
                else:
                    data = None
            if data is not None:
                if self.store_mode == "sqlite":
                    self.verify_available()
                return data
        data = self._read_logs_uncached(date_filter, sid_filter, sid_filters)
        after = self.cache_signature()
        if before == after and after[1][0] is not None:
            with _LOG_PROJECTION_CACHE_LOCK:
                _LOG_PROJECTION_CACHE[key] = (after, copy.deepcopy(data))
                _LOG_PROJECTION_CACHE.move_to_end(key)
                while len(_LOG_PROJECTION_CACHE) > 64:
                    _LOG_PROJECTION_CACHE.popitem(last=False)
        return data

    def _read_logs_uncached(
        self,
        date_filter: str = "",
        sid_filter: str = "",
        sid_filters: list[str] | None = None,
    ) -> dict:
        if self.store_mode == "sqlite":
            con = None
            try:
                con = self._connect()
                self._ensure_schema(con)
                return _public_map(self._sqlite_mode_map(con, date_filter, sid_filter, sid_filters))
            except Exception as exc:
                if isinstance(exc, StoreCorrupt):
                    raise
                raise StoreCorrupt("Class-log storage is unavailable") from exc
            finally:
                if con is not None:
                    con.close()
        requested_sids = self._normalize_sid_filters(sid_filters)
        sqlite_map = {}
        sqlite_ok = False
        con = None
        try:
            con = self._connect()
            self._ensure_schema(con)
            if requested_sids:
                sqlite_map = self._sqlite_dump_sids(con, requested_sids, date_filter)
            elif date_filter and sid_filter:
                sqlite_map = self._sqlite_dump_date_sid(con, date_filter, sid_filter)
            elif date_filter:
                sqlite_map = self._sqlite_dump_date(con, date_filter)
            elif sid_filter:
                sqlite_map = self._sqlite_dump_sid(con, sid_filter)
            else:
                sqlite_map = self._sqlite_dump_all(con)
            sqlite_ok = True
        except Exception as exc:
            print("[logs] sqlite GET failed:", exc, flush=True)
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        json_map, _json_status = _cached_log_json_for_read(self.logs_path)
        if requested_sids:
            json_map = self._filter_json_map_sids(json_map, requested_sids, date_filter)
        elif date_filter or sid_filter:
            json_map = self._filter_json_map(json_map, date_filter, sid_filter)

        if not sqlite_ok:
            return _public_map(json_map)

        return _public_map(self._merge_json_fallback_map(sqlite_map, json_map))

    def _export_history_entry(self, entry: dict, sid: str, *, full: bool) -> dict:
        if not isinstance(entry, dict) or not entry:
            return {}
        if full:
            return self.repair_entry(copy.deepcopy(entry), sid)

        # Previous rows reconstruct assigned-test carry-over for exports and
        # retain only the absence provenance needed by quick-printer filtering.
        out = {"__exportHistoryActivity": True}
        if entry.get(_COMPLETE_ENTRY) is True:
            out[_COMPLETE_ENTRY] = True
        for key in ("testAssignmentDailyTests", "assignedTests"):
            value = entry.get(key)
            if isinstance(value, list):
                out[key] = copy.deepcopy(value)
        carryover = entry.get("testAssignmentAbsenceCarryover")
        if isinstance(carryover, dict):
            out["testAssignmentAbsenceCarryover"] = copy.deepcopy(carryover)
        source_date = str(entry.get("testAssignmentAbsenceSourceDate") or "").strip()
        if source_date:
            out["testAssignmentAbsenceSourceDate"] = source_date
        return out

    def read_export_history(self, target_dates: dict[str, str]) -> dict:
        normalized_targets: dict[str, str] = {}
        for raw_sid, raw_date in (target_dates.items() if isinstance(target_dates, dict) else []):
            date = str(raw_date or "").strip()
            if not date:
                continue
            for sid in self._normalize_sid_filters([raw_sid]):
                previous = normalized_targets.get(sid, "")
                if date > previous:
                    normalized_targets[sid] = date
        if not normalized_targets:
            return {}

        wanted = list(normalized_targets)
        placeholders = ",".join("?" for _ in wanted)
        sqlite_map: Dict[str, Dict[str, dict]] = {}
        sqlite_ok = False
        con = None
        try:
            con = self._connect()
            self._ensure_schema(con)
            rows = con.execute(
                f"SELECT date, sid, entry_json FROM logs WHERE sid IN ({placeholders});",
                tuple(wanted),
            ).fetchall()
            for row in rows:
                date = str(row["date"])
                sid = str(row["sid"])
                target_date = normalized_targets.get(sid)
                if not target_date or date > target_date:
                    continue
                entry = self._decode_sqlite_entry(row["entry_json"], sid)
                projected = self._export_history_entry(entry, sid, full=date == target_date)
                if projected:
                    sqlite_map.setdefault(date, {})[sid] = projected
            sqlite_ok = True
        except Exception as exc:
            print("[logs.export-history] sqlite GET failed:", exc, flush=True)
            if self.store_mode == "sqlite":
                raise StoreCorrupt("Class-log storage is unavailable") from exc
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        if self.store_mode == "sqlite":
            return _public_map(sqlite_map)
        json_projected: Dict[str, Dict[str, dict]] = {}
        json_map, _json_status = _cached_log_json_for_read(self.logs_path)
        for date, by_sid in (json_map.items() if isinstance(json_map, dict) else []):
            if not isinstance(by_sid, dict):
                continue
            date_s = str(date)
            for raw_sid, entry in by_sid.items():
                sid = str(raw_sid or "").strip()
                target_date = normalized_targets.get(sid)
                if not target_date or date_s > target_date:
                    continue
                projected = self._export_history_entry(entry, sid, full=date_s == target_date)
                if projected:
                    json_projected.setdefault(date_s, {})[sid] = projected

        if not sqlite_ok:
            return _public_map(json_projected)

        out = {date: dict(by_sid) for date, by_sid in sqlite_map.items()}
        for date, by_sid in json_projected.items():
            day = out.setdefault(date, {})
            for sid, fallback in by_sid.items():
                existing = day.get(sid)
                target_date = normalized_targets.get(sid)
                if not isinstance(existing, dict):
                    day[sid] = fallback
                    continue
                if existing.get(_COMPLETE_ENTRY) is True:
                    continue
                if date == target_date:
                    day[sid] = self._merge_json_fallback_fields(existing, fallback, sid)
                    continue
                merged = dict(existing)
                for key, value in fallback.items():
                    if key not in merged or (
                        is_empty_value(merged.get(key)) and not is_empty_value(value)
                    ):
                        merged[key] = value
                day[sid] = merged
        return _public_map(out)

    def legacy_post(self, incoming: dict) -> LogPostResult:
        if self.store_mode == "sqlite":
            return self._sqlite_post(incoming)
        result = LogPostResult(sqlite_ok=False)
        with self.mutation_lock():
            current, status = self._read_json_map_with_status()
            if status == "invalid":
                result.sqlite_error = ValueError("logs.json is unreadable or malformed")
                return result
            con = None
            try:
                con = self._connect()
                self._ensure_schema(con)
                con.execute("BEGIN IMMEDIATE;")
                for date, by_sid in incoming.items():
                    if not isinstance(by_sid, dict) or not is_iso_date_key(str(date)):
                        continue
                    date_s = str(date)
                    day = current.setdefault(date_s, {})
                    if not isinstance(day, dict):
                        raise ValueError("invalid log date map")
                    for sid, entry in by_sid.items():
                        if not isinstance(entry, dict):
                            continue
                        sid_s = str(sid)
                        cur = self._merge_json_fallback_fields(
                            self._sqlite_get_entry(con, date_s, sid_s), self._sid_lookup(day, sid_s), sid_s)
                        merged = self.merge_entry(cur, self.repair_entry(_public_entry(entry), sid_s))
                        stored = {**merged, _COMPLETE_ENTRY: True}
                        self._sqlite_upsert_entry(con, date_s, sid_s, stored)
                        self._write_sid_mapping(day, sid_s, stored)
                con.execute("COMMIT;")
                result.sqlite_ok = True
            except Exception as exc:
                result.sqlite_error = exc
                if con is not None and con.in_transaction:
                    con.rollback()
                return result
            finally:
                if con is not None:
                    con.close()
            try:
                save_atomic(self.logs_path, current, compact=True)
                result.json_ok = True
            except Exception as exc:
                result.json_error = exc
            return result

    def patch_entry(self, date: str, sid: str, entry: dict, base: dict) -> LogPatchResult:
        entry = self.repair_entry(_public_entry(entry), sid)
        base = self.repair_entry(base, sid)
        if self.store_mode == "sqlite":
            return self._sqlite_patch(date, sid, entry, base)
        result = LogPatchResult(merged={}, sqlite_ok=False)
        # One canonical lock order and one conflict decision, before either write.
        # JSON-only legacy fields are hydrated once, then the complete SQLite row
        # owns both field presence and absence, even if the mirror write fails.
        with self.mutation_lock():
            current, status = self._read_json_map_with_status()
            if status == "invalid":
                result.sqlite_error = ValueError("logs.json is unreadable or malformed")
                return result
            day = current.setdefault(date, {})
            if not isinstance(day, dict):
                result.sqlite_error = ValueError("invalid log date map")
                return result
            fallback = self._sid_lookup(day, sid)
            fallback = fallback if isinstance(fallback, dict) else {}
            con = None
            try:
                con = self._connect()
                self._ensure_schema(con)
                con.execute("BEGIN IMMEDIATE;")
                cur = self._merge_json_fallback_fields(self._sqlite_get_entry(con, date, sid), fallback, sid)
                if self.entry_conflicts(cur, base):
                    con.execute("ROLLBACK;")
                    result.sqlite_base_conflict = True
                    result.sqlite_conflict_entry = cur
                    return result
                merged = self.repair_entry(self.merge_entry(cur, entry), sid)
                stored = {**merged, _COMPLETE_ENTRY: True}
                self._sqlite_upsert_entry(con, date, sid, stored)
                con.execute("COMMIT;")
                result.sqlite_ok = True
                result.merged = _public_entry(merged)
            except Exception as exc:
                result.sqlite_error = exc
                if con is not None and con.in_transaction:
                    con.rollback()
                return result
            finally:
                if con is not None:
                    con.close()
            try:
                self._write_sid_mapping(day, sid, stored)
                save_atomic(self.logs_path, current, compact=True)
                result.json_ok = True
            except Exception as exc:
                result.json_error = exc
                print("[logs] json PATCH failed:", exc, flush=True)
            return result

    def mutation_lock(self):
        lock = self.lock_factory() if self.lock_factory else None
        return lock if lock is not None else nullcontext()

    def snapshot_entries_raw(
        self,
        pairs: set[tuple[str, str]],
        *,
        json_lock_held: bool = False,
    ) -> tuple[dict, dict[tuple[str, str], dict]]:
        """Capture exact dual-store rows plus the effective entries seen by readers."""
        context = nullcontext() if json_lock_held else self.mutation_lock()
        with context:
            json_map, json_status = self._read_json_map_with_status()
            if json_status == "invalid":
                raise ValueError("logs.json is unreadable or malformed")
            json_compact = False
            if json_status == "available":
                with pathlib.Path(self.logs_path).open("rb") as source:
                    prefix = source.read(64).removeprefix(b"\xef\xbb\xbf")
                json_compact = prefix.startswith((b'{"', b'{}'))

            dates = sorted({str(date) for date, _sid in pairs})
            json_dates = [
                {
                    "date": date,
                    "exists": date in json_map,
                    "value": copy.deepcopy(json_map.get(date)),
                }
                for date in dates
            ]

            sqlite_rows: list[dict] = []
            effective: dict[tuple[str, str], dict] = {}
            con = None
            try:
                con = self._connect()
                self._ensure_schema(con)
                for date, sid in sorted(pairs):
                    row = con.execute(
                        "SELECT entry_json, updated_at FROM logs WHERE date=? AND sid=?;",
                        (date, sid),
                    ).fetchone()
                    sqlite_rows.append({
                        "date": date,
                        "sid": sid,
                        "exists": row is not None,
                        "entryJson": str(row["entry_json"]) if row is not None else "",
                        "updatedAt": str(row["updated_at"]) if row is not None else "",
                    })

                    sqlite_entry: dict = {}
                    if row is not None:
                        try:
                            decoded = json.loads(row["entry_json"]) if row["entry_json"] else {}
                        except Exception:
                            decoded = {}
                        if isinstance(decoded, dict):
                            sqlite_entry = self.repair_entry(decoded, sid)

                    day = json_map.get(date)
                    fallback = self._sid_lookup(day if isinstance(day, dict) else {}, sid)
                    if not isinstance(fallback, dict):
                        fallback = {}
                    fallback = self.repair_entry(fallback, sid)

                    if self.store_mode == "sqlite":
                        effective[(date, sid)] = _public_entry(sqlite_entry)
                    elif sqlite_entry:
                        effective[(date, sid)] = self._merge_json_fallback_fields(
                            sqlite_entry,
                            fallback,
                            sid,
                        )
                    else:
                        effective[(date, sid)] = fallback
            finally:
                try:
                    if con is not None:
                        con.close()
                except Exception:
                    pass

        return {
            "version": 1,
            "sqliteRows": sqlite_rows,
            "jsonStatus": json_status,
            "jsonCompact": json_compact,
            "jsonDates": json_dates,
        }, effective

    def restore_entries_raw(self, snapshot: dict, *, json_lock_held: bool = False) -> None:
        """Restore an exact narrow snapshot for rollback or crash recovery."""
        if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
            raise ValueError("invalid log entry snapshot")
        if "jsonCompact" in snapshot and not isinstance(snapshot["jsonCompact"], bool):
            raise ValueError("invalid log JSON snapshot format")

        sqlite_rows = snapshot.get("sqliteRows")
        json_dates = snapshot.get("jsonDates")
        if not isinstance(sqlite_rows, list) or not isinstance(json_dates, list):
            raise ValueError("invalid log entry snapshot rows")

        context = nullcontext() if json_lock_held else self.mutation_lock()
        with context:
            current_json, current_status = self._read_json_map_with_status()
            if current_status == "invalid":
                raise ValueError("logs.json is unreadable or malformed")
            restored_json = copy.deepcopy(current_json)

            for item in json_dates:
                if not isinstance(item, dict):
                    raise ValueError("invalid log JSON snapshot row")
                date = str(item.get("date") or "")
                if not date:
                    raise ValueError("invalid log JSON snapshot date")
                if item.get("exists") is True:
                    restored_json[date] = copy.deepcopy(item.get("value"))
                else:
                    restored_json.pop(date, None)

            con = None
            try:
                con = self._connect()
                self._ensure_schema(con)
                con.execute("BEGIN IMMEDIATE;")
                for item in sqlite_rows:
                    if not isinstance(item, dict):
                        raise ValueError("invalid log SQLite snapshot row")
                    date = str(item.get("date") or "")
                    sid = str(item.get("sid") or "")
                    if not date or not sid:
                        raise ValueError("invalid log SQLite snapshot key")
                    if item.get("exists") is True:
                        con.execute(
                            """
                            INSERT INTO logs(date, sid, entry_json, updated_at)
                            VALUES(?,?,?,?)
                            ON CONFLICT(date, sid) DO UPDATE SET
                              entry_json=excluded.entry_json,
                              updated_at=excluded.updated_at;
                            """,
                            (
                                date,
                                sid,
                                str(item.get("entryJson") or ""),
                                str(item.get("updatedAt")) if item.get("updatedAt") is not None else self._now_kst_iso(),
                            ),
                        )
                    else:
                        con.execute("DELETE FROM logs WHERE date=? AND sid=?;", (date, sid))

                if restored_json != current_json:
                    save_atomic(self.logs_path, restored_json, compact=snapshot.get("jsonCompact") is True)
                con.execute("COMMIT;")
            except Exception:
                try:
                    if con is not None:
                        con.execute("ROLLBACK;")
                except Exception:
                    pass
                raise
            finally:
                try:
                    if con is not None:
                        con.close()
                except Exception:
                    pass

    def transform_entries(
        self,
        pairs: set[tuple[str, str]],
        transform_fn: Callable[[dict, str], tuple[dict, bool]],
        *,
        json_lock_held: bool = False,
    ) -> None:
        self.transform_entries_by_pair(
            pairs,
            lambda entry, date, sid: transform_fn(entry, sid),
            json_lock_held=json_lock_held,
        )

    def transform_entries_by_pair(
        self,
        pairs: set[tuple[str, str]],
        transform_fn: Callable[[dict, str, str], tuple[dict, bool]],
        *,
        json_lock_held: bool = False,
    ) -> None:
        if not pairs:
            return

        con = None
        try:
            con = self._connect()
            self._ensure_schema(con)
            con.execute("BEGIN IMMEDIATE;")
            for date, sid in sorted(pairs):
                entry = self.repair_entry(self._sqlite_get_entry(con, date, sid), sid)
                next_entry, changed = transform_fn(entry, date, sid)
                if changed:
                    if self.store_mode == "sqlite":
                        next_entry = {**next_entry, _COMPLETE_ENTRY: True}
                    self._sqlite_upsert_entry(con, date, sid, next_entry)
            con.execute("COMMIT;")
        except Exception:
            try:
                if con is not None:
                    con.execute("ROLLBACK;")
            except Exception:
                pass
            raise
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        if self.store_mode == "sqlite":
            self._queue_exports(pairs)
            return
        changed_json = False
        context = nullcontext() if json_lock_held else self.mutation_lock()
        with context:
            logs = self.read_json_map()
            if not isinstance(logs, dict):
                return

            for date, sid in sorted(pairs):
                day = logs.get(date)
                if not isinstance(day, dict):
                    continue
                entry = self._sid_lookup(day, sid)
                if not isinstance(entry, dict):
                    continue
                entry = self.repair_entry(entry, sid)
                next_entry, changed = transform_fn(entry, date, sid)
                if not changed:
                    continue
                self._write_sid_mapping(day, sid, next_entry)
                changed_json = True

            if changed_json:
                save_atomic(self.logs_path, logs, compact=True)

    def summarize_missing_leave(
        self,
        arrivals_by_date: Any,
        absent_by_date: Any = None,
        *,
        since_date: str = "",
        exclude_date: str = "",
    ) -> dict:
        """Summarize arrived students whose exact-date log never reached done."""
        today = self.today_key()
        absent_map = absent_by_date if isinstance(absent_by_date, dict) else {}
        candidates: list[dict[str, str]] = []

        if isinstance(arrivals_by_date, dict):
            for date_raw, by_sid in arrivals_by_date.items():
                date = str(date_raw or "").strip()
                if (
                    not is_iso_date_key(date)
                    or date >= today
                    or (since_date and date < since_date)
                    or (exclude_date and date == exclude_date)
                    or not isinstance(by_sid, dict)
                ):
                    continue
                absent_sids = {
                    str(sid or "").strip()
                    for sid in (absent_map.get(date) if isinstance(absent_map.get(date), list) else [])
                    if str(sid or "").strip()
                }
                for sid_raw, arrive_raw in by_sid.items():
                    sid = str(sid_raw or "").strip()
                    arrive_time = str(arrive_raw or "").strip()
                    if not sid or not arrive_time or sid in absent_sids:
                        continue
                    candidates.append({"date": date, "sid": sid, "arriveTime": arrive_time})

        candidates.sort(key=lambda row: str(row["sid"]))
        candidates.sort(key=lambda row: str(row["date"]), reverse=True)
        candidate_keys = {(row["date"], row["sid"]) for row in candidates}
        if not candidate_keys:
            return {
                "ok": True,
                "sinceDate": since_date,
                "excludeDate": exclude_date,
                "total": 0,
                "students": 0,
                "byDate": [],
                "rowsAvailable": True,
                "rows": [],
            }

        sqlite_entries: dict[tuple[str, str], dict] = {}
        done_keys: set[tuple[str, str]] = set()
        sqlite_available = False
        con = None
        try:
            con = self._connect()
            self._ensure_schema(con)
            self._validate_sqlite_objects(con)
            rows = con.execute(
                """
                SELECT date, sid, json_extract(entry_json, '$.done') AS done,
                       json_type(entry_json, '$.done') AS done_type,
                       json_type(entry_json, '$.__logRepositoryCompleteV1') AS complete_type
                FROM logs
                WHERE date >= ? AND date < ?
                ORDER BY date, sid;
                """,
                (since_date or "0000-01-01", today),
            ).fetchall()
            for row in rows:
                key = (str(row["date"] or "").strip(), str(row["sid"] or "").strip())
                if key not in candidate_keys:
                    continue
                entry = {}
                if row["complete_type"] == "true":
                    entry[_COMPLETE_ENTRY] = True
                if row["done_type"] is not None:
                    value = row["done"]
                    if row["done_type"] in {"array", "object"}:
                        value = json.loads(value)
                    entry["done"] = value
                sqlite_entries[key] = entry
            sqlite_available = True
        except Exception as exc:
            print("[logs.missing-leave-summary] sqlite failed:", exc, flush=True)
            if self.store_mode == "sqlite":
                raise StoreCorrupt("Class-log storage is unavailable") from exc
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        if self.store_mode == "sqlite":
            json_map, json_status = {}, "missing"
            numeric_candidates = [(date, sid) for date, sid in candidate_keys if sid.isdigit()]
            for date, sid in numeric_candidates:
                sqlite_entries[(date, sid)] = self.read_entry(date, sid).entry
        else:
            json_map, json_status = _cached_log_json_for_read(self.logs_path)
        for date, sid in candidate_keys:
            day = json_map.get(date) if isinstance(json_map, dict) else None
            entry = self._sid_lookup(day, sid) if isinstance(day, dict) else None
            fallback = {"done": entry["done"]} if isinstance(entry, dict) and "done" in entry else {}
            primary = sqlite_entries.get((date, sid))
            resolved = self._merge_json_fallback_fields(primary, fallback, sid) if primary is not None else fallback
            if self.truthy(resolved.get("done")):
                done_keys.add((date, sid))

        rows_available = bool(
            (sqlite_available and json_status != "invalid")
            or (not sqlite_available and json_status == "available")
        )
        missing_rows = [row for row in candidates if (row["date"], row["sid"]) not in done_keys]
        if not rows_available:
            missing_rows = []

        by_date: Dict[str, int] = {}
        students: set[str] = set()
        for row in missing_rows:
            date = row["date"]
            by_date[date] = by_date.get(date, 0) + 1
            students.add(row["sid"])

        return {
            "ok": True,
            "sinceDate": since_date,
            "excludeDate": exclude_date,
            "total": len(missing_rows),
            "students": len(students),
            "byDate": [
                {"date": date, "count": by_date[date]}
                for date in sorted(by_date.keys(), reverse=True)
            ],
            "rowsAvailable": rows_available,
            "rows": missing_rows if rows_available else [],
        }

    def summarize_unarchived_done(self, exclude_date: str = "") -> dict:
        entries: Dict[str, Dict[str, dict]] = {}
        sqlite_keys: set[tuple[str, str]] = set()
        sqlite_available = False
        con = None

        def valid_date(value: Any) -> str:
            date_s = str(value or "").strip()
            if not is_iso_date_key(date_s):
                return ""
            return date_s

        def projected_entry(value: Any) -> dict | None:
            if not isinstance(value, dict):
                return None
            if not self.truthy(value.get("done")) or self.truthy(value.get("archived")):
                return None
            out = {"done": True, "archived": False}
            if self.truthy(value.get("hwChecked")):
                out["hwChecked"] = True
            if self.truthy(value.get("selfStudy")):
                out["selfStudy"] = True
            return out

        try:
            con = self._connect()
            self._ensure_schema(con)
            self._validate_sqlite_objects(con)
            candidate_keys: set[tuple[str, str]] = set()
            for row in con.execute("SELECT date, sid FROM logs ORDER BY date, sid;").fetchall():
                date = valid_date(row["date"])
                sid = str(row["sid"] or "").strip()
                if date and sid:
                    candidate_keys.add((date, sid))

            rows = con.execute(
                """
                SELECT date, sid, entry_json
                FROM logs
                WHERE json_extract(entry_json, ?) IN (1, '1', 'true')
                  AND COALESCE(json_extract(entry_json, ?), 0) NOT IN (1, '1', 'true')
                ORDER BY date, sid;
                """,
                ("$.done", "$.archived"),
            ).fetchall()
            candidate_entries: Dict[str, Dict[str, dict]] = {}
            for row in rows:
                date = valid_date(row["date"])
                sid = str(row["sid"] or "").strip()
                if not date or not sid:
                    continue
                try:
                    entry = json.loads(row["entry_json"]) if row["entry_json"] else {}
                except Exception:
                    entry = {}
                projected = projected_entry(entry)
                if projected is None:
                    continue
                candidate_entries.setdefault(date, {})[sid] = projected
            sqlite_keys = candidate_keys
            entries = candidate_entries
            sqlite_available = True
        except Exception as exc:
            print("[logs.unarchived-summary] sqlite failed:", exc, flush=True)
            if self.store_mode == "sqlite":
                raise StoreCorrupt("Class-log storage is unavailable") from exc
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        json_map, json_status = ({}, "missing") if self.store_mode == "sqlite" else _cached_log_json_for_read(self.logs_path)
        for date, by_sid in json_map.items():
            if not isinstance(by_sid, dict):
                continue
            date_s = valid_date(date)
            if not date_s:
                continue
            day = entries.setdefault(date_s, {})
            for sid, entry in by_sid.items():
                sid_s = str(sid or "").strip()
                if not sid_s or (date_s, sid_s) in sqlite_keys or sid_s in day:
                    continue
                projected = projected_entry(entry)
                if projected is None:
                    continue
                day[sid_s] = projected

        latest_by_sid: Dict[str, tuple[str, dict]] = {}
        for date, by_sid in entries.items():
            date_s = str(date)
            if not valid_date(date_s):
                continue
            if not isinstance(by_sid, dict):
                continue
            for sid, entry in by_sid.items():
                if not isinstance(entry, dict):
                    continue
                if not self.truthy(entry.get("done")) or self.truthy(entry.get("archived")):
                    continue
                sid_s = str(sid or "").strip()
                if not sid_s:
                    continue
                previous = latest_by_sid.get(sid_s)
                if previous is None or date_s > previous[0]:
                    latest_by_sid[sid_s] = (date_s, entry)

        latest_rows = [
            {"date": date, "sid": sid, "entry": entry}
            for sid, (date, entry) in latest_by_sid.items()
        ]
        latest_rows.sort(key=lambda row: str(row["sid"]))
        latest_rows.sort(key=lambda row: str(row["date"]), reverse=True)

        by_date: Dict[str, int] = {}
        students = set()
        total = 0
        today = self.today_key()
        for date, by_sid in entries.items():
            date_s = str(date)
            if not valid_date(date_s):
                continue
            if exclude_date and date_s == exclude_date:
                continue
            if date_s >= today:
                continue
            if not isinstance(by_sid, dict):
                continue
            for sid, entry in by_sid.items():
                if not isinstance(entry, dict):
                    continue
                sid_s = str(sid or "").strip()
                if not sid_s:
                    continue
                if not self.truthy(entry.get("done")) or self.truthy(entry.get("archived")):
                    continue
                by_date[date_s] = by_date.get(date_s, 0) + 1
                students.add(sid_s)
                total += 1

        result = {
            "ok": True,
            "excludeDate": exclude_date,
            "total": total,
            "students": len(students),
            "byDate": [
                {"date": date, "count": by_date[date]}
                for date in sorted(by_date.keys(), reverse=True)
            ],
            "rowsAvailable": bool(
                (sqlite_available and json_status != "invalid")
                or (not sqlite_available and json_status == "available")
            ),
        }
        if result["rowsAvailable"]:
            result["rows"] = latest_rows
        return result
