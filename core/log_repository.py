from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Dict

from core.log_rules import is_empty_value, truthy as default_truthy
from core.paths import LOGS_PATH
from core.storage import file_lock, load, save_atomic

DATE_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KST = dt.timezone(dt.timedelta(hours=9))


EntryFn = Callable[[dict, str], dict]
MergeFn = Callable[[dict, dict], dict]
ConflictFn = Callable[[dict, dict], bool]
TruthyFn = Callable[[Any], bool]
LockFactory = Callable[[], Any]


@dataclass
class LogEntryResult:
    source: str
    entry: dict


@dataclass
class LogPostResult:
    sqlite_ok: bool
    sqlite_error: Exception | None = None


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
    ):
        self.logs_path = logs_path
        self.repair_entry = repair_entry
        self.merge_entry = merge_entry
        self.entry_conflicts = entry_conflicts
        self.lock_factory = lock_factory
        self.truthy = truthy
        self.today_key = today_key or (lambda: dt.datetime.now(KST).date().isoformat())
        self.db_path = db_path

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
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        con = sqlite3.connect(
            db_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=30000;")
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    def _ensure_schema(self, con: sqlite3.Connection) -> None:
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

    def _sqlite_get_entry(self, con: sqlite3.Connection, date: str, sid: str) -> dict:
        row = con.execute("SELECT entry_json FROM logs WHERE date=? AND sid=?;", (date, sid)).fetchone()
        if not row:
            return {}
        try:
            entry = json.loads(row["entry_json"]) if row["entry_json"] else {}
        except Exception:
            entry = {}
        return self.repair_entry(entry, sid)

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
            (date, sid, json.dumps(safe_entry, ensure_ascii=False), self._now_kst_iso()),
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
        path = pathlib.Path(self.logs_path)
        try:
            raw = json.loads(path.read_text("utf-8-sig"))
        except FileNotFoundError:
            return {}, "missing"
        except Exception:
            return {}, "invalid"
        return (raw, "available") if isinstance(raw, dict) else ({}, "invalid")

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
                    out.setdefault(str(date), {})[str(sid_filter)] = self.repair_entry(entry, sid_filter)
                elif date_filter:
                    out.setdefault(str(date), {})
                continue

            out[str(date)] = {
                str(sid): self.repair_entry(entry, str(sid))
                for sid, entry in by_sid.items()
                if isinstance(entry, dict)
            }

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
        logs = self.read_json_map()
        day = logs.get(date) if isinstance(logs, dict) else None
        entry = self._sid_lookup(day if isinstance(day, dict) else {}, sid)
        if not isinstance(entry, dict):
            entry = {}
        return self.repair_entry(entry, sid)

    def _merge_json_fallback_fields(self, primary: dict, fallback: dict, sid: str) -> dict:
        if not isinstance(primary, dict):
            primary = {}
        if not isinstance(fallback, dict) or not fallback:
            return self.repair_entry(primary, sid)

        out = dict(primary)
        for key, value in fallback.items():
            if key not in out or (is_empty_value(out.get(key)) and not is_empty_value(value)):
                out[key] = value
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
                day[sid_s] = self.repair_entry(entry, sid_s)

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
        con = None
        try:
            con = self._connect()
            self._ensure_schema(con)
            entry = self._sqlite_get_entry(con, date, sid) or {}
            if isinstance(entry, dict) and entry:
                fallback = self._json_entry(date, sid)
                return LogEntryResult("sqlite", self._merge_json_fallback_fields(entry, fallback, sid))
        except Exception as exc:
            print("[logs.entry] sqlite failed:", exc, flush=True)
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        return LogEntryResult("json", self._json_entry(date, sid))

    def read_logs(self, date_filter: str = "", sid_filter: str = "") -> dict:
        sqlite_map = {}
        sqlite_ok = False
        con = None
        try:
            con = self._connect()
            self._ensure_schema(con)
            if date_filter and sid_filter:
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

        json_map = self.read_json_map()
        if date_filter or sid_filter:
            json_map = self._filter_json_map(json_map, date_filter, sid_filter)

        if not sqlite_ok:
            return json_map

        return self._merge_json_fallback_map(sqlite_map, json_map)

    def legacy_post(self, incoming: dict) -> LogPostResult:
        sqlite_ok = False
        sqlite_err = None
        con = None

        try:
            con = self._connect()
            self._ensure_schema(con)
            con.execute("BEGIN IMMEDIATE;")
            for date, by_sid in incoming.items():
                if not isinstance(by_sid, dict) or not DATE_KEY_RE.match(str(date)):
                    continue
                for sid, entry in by_sid.items():
                    if not isinstance(entry, dict):
                        continue
                    date_s = str(date)
                    sid_s = str(sid)
                    safe_entry = self.repair_entry(entry, sid_s)
                    cur = self._sqlite_get_entry(con, date_s, sid_s)
                    merged = self.merge_entry(cur, safe_entry)
                    self._sqlite_upsert_entry(con, date_s, sid_s, merged)
            con.execute("COMMIT;")
            sqlite_ok = True
        except Exception as exc:
            sqlite_err = exc
            try:
                if con is not None:
                    con.execute("ROLLBACK;")
            except Exception:
                pass
            print("[logs] sqlite legacy POST failed:", exc, flush=True)
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        self._save_legacy_json(incoming)
        return LogPostResult(sqlite_ok=sqlite_ok, sqlite_error=sqlite_err)

    def _save_legacy_json(self, incoming: dict) -> None:
        lock = self.lock_factory() if self.lock_factory else None
        context = lock if lock is not None else _NullContext()
        with context:
            current = self.read_json_map()
            for date, by_sid in incoming.items():
                if not isinstance(by_sid, dict):
                    continue
                cur_day = current.setdefault(date, {})
                if not isinstance(cur_day, dict):
                    current[date] = {}
                    cur_day = current[date]

                for sid, entry in by_sid.items():
                    if not isinstance(entry, dict):
                        continue
                    sid_s = str(sid)
                    safe_entry = self.repair_entry(entry, sid_s)
                    cur_entry = cur_day.get(sid_s, {})
                    cur_day[sid_s] = self.merge_entry(cur_entry, safe_entry)

            save_atomic(self.logs_path, current)

    def patch_entry(self, date: str, sid: str, entry: dict, base: dict) -> LogPatchResult:
        lock = self.lock_factory() if self.lock_factory else file_lock(self.logs_path)
        with lock:
            return self._patch_entry_locked(date, sid, entry, base)

    def _patch_entry_locked(self, date: str, sid: str, entry: dict, base: dict) -> LogPatchResult:
        entry = self.repair_entry(entry, sid)
        base = self.repair_entry(base, sid)
        merged: dict = {}

        sqlite_ok = False
        sqlite_err = None
        sqlite_base_conflict = False
        sqlite_conflict_entry = None
        json_ok = False
        json_err = None
        con = None

        try:
            con = self._connect()
            self._ensure_schema(con)
            con.execute("BEGIN IMMEDIATE;")
            cur = self.repair_entry(self._sqlite_get_entry(con, date, sid), sid)
            if self.entry_conflicts(cur, base):
                con.execute("ROLLBACK;")
                sqlite_base_conflict = True
                sqlite_conflict_entry = cur
                return LogPatchResult(
                    merged={}, sqlite_ok=False, sqlite_base_conflict=True,
                    sqlite_conflict_entry=cur,
                )
            else:
                merged = self.merge_entry(cur, entry)
                self._sqlite_upsert_entry(con, date, sid, merged)
                con.execute("COMMIT;")
                sqlite_ok = True
        except Exception as exc:
            sqlite_err = exc
            try:
                if con is not None:
                    con.execute("ROLLBACK;")
            except Exception:
                pass
            print("[logs] sqlite PATCH failed:", exc, flush=True)
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        try:
            with _NullContext():
                current = self.read_json_map()
                day = current.setdefault(date, {})
                if not isinstance(day, dict):
                    current[date] = {}
                    day = current[date]

                cur_json = day.get(sid, {})
                if not isinstance(cur_json, dict):
                    cur_json = {}
                cur_json = self.repair_entry(cur_json, sid)

                if not sqlite_ok and self.entry_conflicts(cur_json, base):
                    return LogPatchResult(
                        merged=merged,
                        sqlite_ok=sqlite_ok,
                        sqlite_error=sqlite_err,
                        sqlite_base_conflict=sqlite_base_conflict,
                        sqlite_conflict_entry=sqlite_conflict_entry,
                        json_ok=json_ok,
                        json_error=json_err,
                        json_conflict_entry=cur_json,
                    )

                if not merged:
                    merged = self.merge_entry(cur_json, entry)
                merged = self.repair_entry(merged, sid)
                day[sid] = merged
                save_atomic(self.logs_path, current)
                json_ok = True
        except Exception as exc:
            json_err = exc
            print("[logs] json PATCH failed:", exc, flush=True)

        if not sqlite_ok and not sqlite_base_conflict and merged:
            con2 = None
            try:
                con2 = self._connect()
                self._ensure_schema(con2)
                self._sqlite_upsert_entry(con2, date, sid, merged)
                con2.commit()
                sqlite_ok = True
                sqlite_err = None
            except Exception as exc:
                sqlite_err = exc
                sqlite_ok = False
            finally:
                try:
                    if con2 is not None:
                        con2.close()
                except Exception:
                    pass

        return LogPatchResult(
            merged=merged,
            sqlite_ok=sqlite_ok,
            sqlite_error=sqlite_err,
            sqlite_base_conflict=sqlite_base_conflict,
            sqlite_conflict_entry=sqlite_conflict_entry,
            json_ok=json_ok,
            json_error=json_err,
        )

    def append_record(self, date: str, sid: str, record: dict, append_fn: MergeFn) -> bool:
        logs_saved = False
        merged_entry = {}
        con = None

        try:
            con = self._connect()
            self._ensure_schema(con)
            con.execute("BEGIN IMMEDIATE;")
            cur = self._sqlite_get_entry(con, date, sid)
            merged_entry = append_fn(cur, record)
            self._sqlite_upsert_entry(con, date, sid, merged_entry)
            con.execute("COMMIT;")
        except Exception as exc:
            try:
                if con is not None:
                    con.execute("ROLLBACK;")
            except Exception:
                pass
            print("[submit-test] sqlite logs save failed:", exc, flush=True)
            merged_entry = {}
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        try:
            lock = self.lock_factory() if self.lock_factory else None
            context = lock if lock is not None else _NullContext()
            with context:
                logs = self.read_json_map()
                day = logs.setdefault(date, {})
                if not isinstance(day, dict):
                    logs[date] = {}
                    day = logs[date]

                cur_json = day.get(sid, {})
                day[sid] = merged_entry if isinstance(merged_entry, dict) and merged_entry else append_fn(cur_json, record)
                logs[date] = day
                save_atomic(self.logs_path, logs)
                logs_saved = True
        except Exception as exc:
            print("[submit-test] json logs save failed:", exc, flush=True)

        return logs_saved

    def transform_entries(self, pairs: set[tuple[str, str]], transform_fn: Callable[[dict, str], tuple[dict, bool]]) -> None:
        if not pairs:
            return

        con = None
        try:
            con = self._connect()
            self._ensure_schema(con)
            con.execute("BEGIN IMMEDIATE;")
            for date, sid in sorted(pairs):
                entry = self.repair_entry(self._sqlite_get_entry(con, date, sid), sid)
                next_entry, changed = transform_fn(entry, sid)
                if changed:
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

        changed_json = False
        lock = self.lock_factory() if self.lock_factory else None
        context = lock if lock is not None else _NullContext()
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
                next_entry, changed = transform_fn(entry, sid)
                if not changed:
                    continue
                self._write_sid_mapping(day, sid, next_entry)
                changed_json = True

            if changed_json:
                save_atomic(self.logs_path, logs)

    def summarize_unarchived_done(self, exclude_date: str = "") -> dict:
        entries: Dict[str, Dict[str, dict]] = {}
        sqlite_keys: set[tuple[str, str]] = set()
        sqlite_available = False
        con = None

        def valid_date(value: Any) -> str:
            date_s = str(value or "").strip()
            if not DATE_KEY_RE.fullmatch(date_s):
                return ""
            try:
                dt.date.fromisoformat(date_s)
            except ValueError:
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
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

        json_map, json_status = self._read_json_map_with_status()
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


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False
