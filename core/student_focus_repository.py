"""Explicit-migration SQLite repository for privacy-minimized focus sessions."""
from __future__ import annotations
import json
import secrets
import sqlite3
import time
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
from .student_focus_rules import (
    FocusConflictError,
    FocusInputError,
    FocusSessionNotFoundError,
    MAX_SESSION_EVENTS,
    STALE_GRACE_SECONDS,
    session_summary,
)
from .student_focus_retention import StudentFocusRetentionMixin
class FocusNotInitializedError(RuntimeError):
    code = "focus_not_initialized"
class StudentFocusRepository(StudentFocusRetentionMixin):
    """Store server-timestamped focus transitions without creating schema on reads."""

    REQUIRED_TABLES = frozenset({"student_focus_sessions", "student_focus_events"})

    def __init__(self, db_path: str | Path, *, clock=time.time, timeout: float = 5.0):
        self.db_path = Path(db_path)
        self.clock = clock
        self.timeout = float(timeout)

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        mode = "ro" if readonly else "rw"
        absolute = quote(self.db_path.resolve().as_posix(), safe="/:")
        try:
            db = sqlite3.connect(f"file:{absolute}?mode={mode}", uri=True, timeout=self.timeout)
        except sqlite3.Error as exc:
            raise FocusNotInitializedError("focus database is unavailable") from exc
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def apply_migration(self, sql: str) -> None:
        if not isinstance(sql, str) or not sql.strip():
            raise FocusInputError(message="focus migration is invalid")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path, timeout=self.timeout)) as db:
            db.executescript(sql)
            db.commit()

    def schema_ready(self) -> bool:
        try:
            with closing(self._connect(readonly=True)) as db:
                rows = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)",
                    tuple(sorted(self.REQUIRED_TABLES)),
                ).fetchall()
        except (FocusNotInitializedError, sqlite3.Error):
            return False
        return {str(row[0]) for row in rows} == self.REQUIRED_TABLES

    def _now(self, value: float | int | None = None) -> float:
        selected = self.clock() if value is None else value
        if isinstance(selected, bool) or not isinstance(selected, (int, float)) or float(selected) < 0:
            raise FocusInputError(message="focus server clock is invalid")
        return float(selected)

    @staticmethod
    def _row(db: sqlite3.Connection, session_id: str, sid: str) -> sqlite3.Row | None:
        return db.execute(
            "SELECT * FROM student_focus_sessions WHERE id=? AND sid=?",
            (session_id, sid),
        ).fetchone()

    @staticmethod
    def _delta_ms(row: Mapping[str, object], current: float) -> int:
        end = min(current, float(row["schedule_end_at"]))
        return max(0, round((end - float(row["segment_started_at"])) * 1000))

    @classmethod
    def _unknown_values(cls, row: Mapping[str, object], current: float) -> tuple[int, float]:
        delta = cls._delta_ms(row, current)
        return int(row["unknown_ms"]) + delta, min(current, float(row["schedule_end_at"]))

    def start(self, sid: str, schedule: Mapping[str, object], *, now: float | int | None = None) -> tuple[dict, bool]:
        current = self._now(now)
        with closing(self._connect(readonly=False)) as db:
            db.execute("BEGIN IMMEDIATE")
            same = db.execute(
                "SELECT * FROM student_focus_sessions WHERE sid=? AND schedule_key=?",
                (sid, schedule["scheduleKey"]),
            ).fetchone()
            if same is not None:
                if same["state"] == "active":
                    db.execute("COMMIT")
                    return dict(same), True
                db.execute("ROLLBACK")
                raise FocusConflictError("focus_already_finished")
            active = db.execute(
                "SELECT * FROM student_focus_sessions WHERE sid=? AND state='active' ORDER BY started_at DESC LIMIT 1",
                (sid,),
            ).fetchone()
            if active is not None:
                if current >= float(active["schedule_end_at"]) + STALE_GRACE_SECONDS:
                    unknown_ms, ended = self._unknown_values(active, current)
                    db.execute(
                        "UPDATE student_focus_sessions SET state='unknown',visibility_state='unknown',unknown_ms=?,"
                        "ended_at=?,updated_at=? WHERE id=?",
                        (unknown_ms, ended, current, active["id"]),
                    )
                else:
                    db.execute("ROLLBACK")
                    raise FocusConflictError("focus_session_active")
            focus_id = "fcs_" + secrets.token_urlsafe(24)
            db.execute(
                "INSERT INTO student_focus_sessions(id,sid,schedule_key,schedule_kind,schedule_date,"
                "schedule_start_at,schedule_end_at,schedule_time_label,schedule_slots_json,started_at,state,"
                "visibility_state,segment_started_at,last_event_at,last_seq,event_count,visible_ms,hidden_count,"
                "hidden_ms,longest_hidden_ms,unknown_ms,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    focus_id, sid, schedule["scheduleKey"], schedule["kind"], schedule["date"],
                    schedule["startEpoch"], schedule["endEpoch"], schedule["timeLabel"],
                    json.dumps(schedule["slots"], separators=(",", ":")), current, "active", "visible",
                    current, current, 0, 0, 0, 0, 0, 0, 0, current, current,
                ),
            )
            row = self._row(db, focus_id, sid)
            db.execute("COMMIT")
        return dict(row), False

    def append_events(self, sid: str, focus_id: str, events: Sequence[Mapping[str, object]], *,
                      now: float | int | None = None) -> dict:
        current = self._now(now)
        with closing(self._connect(readonly=False)) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, focus_id, sid)
            if row is None:
                db.execute("ROLLBACK")
                raise FocusSessionNotFoundError("focus session not found")
            if row["state"] != "active" or current >= float(row["schedule_end_at"]) + STALE_GRACE_SECONDS:
                db.execute("ROLLBACK")
                raise FocusConflictError("focus_session_closed")
            if current < float(row["last_event_at"]):
                db.execute("ROLLBACK")
                raise FocusConflictError("focus_clock_conflict")
            if int(row["event_count"]) + len(events) > MAX_SESSION_EVENTS:
                db.execute("ROLLBACK")
                raise FocusConflictError("focus_event_limit")
            values = dict(row)
            for event in events:
                expected = int(values["last_seq"]) + 1
                if int(event["seq"]) != expected:
                    db.execute("ROLLBACK")
                    raise FocusConflictError("focus_sequence_conflict")
                event_type, previous = str(event["type"]), str(values["visibility_state"])
                if event_type == previous:
                    db.execute("ROLLBACK")
                    raise FocusConflictError("focus_invalid_transition")
                delta = self._delta_ms(values, current)
                if event_type == "unknown" or previous == "unknown":
                    values["unknown_ms"] = int(values["unknown_ms"]) + delta
                elif previous == "visible" and event_type == "hidden":
                    values["visible_ms"] = int(values["visible_ms"]) + delta
                    values["hidden_count"] = int(values["hidden_count"]) + 1
                elif previous == "hidden" and event_type == "visible":
                    values["hidden_ms"] = int(values["hidden_ms"]) + delta
                    values["longest_hidden_ms"] = max(int(values["longest_hidden_ms"]), delta)
                else:
                    db.execute("ROLLBACK")
                    raise FocusConflictError("focus_invalid_transition")
                db.execute(
                    "INSERT INTO student_focus_events(session_id,seq,event_type,server_at,duration_ms) VALUES(?,?,?,?,?)",
                    (focus_id, expected, event_type, current, delta),
                )
                values.update(
                    visibility_state=event_type, segment_started_at=current, last_event_at=current,
                    last_seq=expected, event_count=int(values["event_count"]) + 1,
                )
            db.execute(
                "UPDATE student_focus_sessions SET visibility_state=?,segment_started_at=?,last_event_at=?,"
                "last_seq=?,event_count=?,visible_ms=?,hidden_count=?,hidden_ms=?,longest_hidden_ms=?,unknown_ms=?,updated_at=? WHERE id=?",
                (
                    values["visibility_state"], values["segment_started_at"], values["last_event_at"],
                    values["last_seq"], values["event_count"], values["visible_ms"], values["hidden_count"],
                    values["hidden_ms"], values["longest_hidden_ms"], values["unknown_ms"], current, focus_id,
                ),
            )
            result = self._row(db, focus_id, sid)
            db.execute("COMMIT")
        return dict(result)

    def end(self, sid: str, focus_id: str, seq: int, *, now: float | int | None = None) -> dict:
        current = self._now(now)
        with closing(self._connect(readonly=False)) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, focus_id, sid)
            if row is None:
                db.execute("ROLLBACK")
                raise FocusSessionNotFoundError("focus session not found")
            if row["state"] != "active":
                db.execute("ROLLBACK")
                raise FocusConflictError("focus_session_closed")
            if type(seq) is not int or seq != int(row["last_seq"]) + 1:
                db.execute("ROLLBACK")
                raise FocusConflictError("focus_sequence_conflict")
            if current < float(row["last_event_at"]):
                db.execute("ROLLBACK")
                raise FocusConflictError("focus_clock_conflict")
            if current >= float(row["schedule_end_at"]) + STALE_GRACE_SECONDS:
                return self._close_stale(db, row, focus_id, sid, seq, current)
            values, delta, previous = dict(row), self._delta_ms(row, current), str(row["visibility_state"])
            field = "visible_ms" if previous == "visible" else "hidden_ms" if previous == "hidden" else "unknown_ms"
            values[field] = int(values[field]) + delta
            if previous == "hidden":
                values["longest_hidden_ms"] = max(int(values["longest_hidden_ms"]), delta)
            db.execute(
                "INSERT INTO student_focus_events(session_id,seq,event_type,server_at,duration_ms) VALUES(?,?,?,?,?)",
                (focus_id, seq, "finished", current, delta),
            )
            ended = min(current, float(row["schedule_end_at"]))
            db.execute(
                "UPDATE student_focus_sessions SET state='finished',visibility_state='unknown',ended_at=?,last_event_at=?,"
                "last_seq=?,event_count=event_count+1,visible_ms=?,hidden_ms=?,longest_hidden_ms=?,unknown_ms=?,updated_at=? WHERE id=?",
                (ended, current, seq, values["visible_ms"], values["hidden_ms"], values["longest_hidden_ms"], values["unknown_ms"], current, focus_id),
            )
            result = self._row(db, focus_id, sid)
            db.execute("COMMIT")
        return dict(result)

    def current_for_sid(self, sid: str) -> dict | None:
        with closing(self._connect(readonly=True)) as db:
            row = db.execute(
                "SELECT * FROM student_focus_sessions WHERE sid=? ORDER BY (state='active') DESC,started_at DESC LIMIT 1",
                (sid,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_for_date(self, date_key: str) -> list[dict]:
        with closing(self._connect(readonly=True)) as db:
            rows = db.execute(
                "SELECT * FROM student_focus_sessions WHERE schedule_date=? ORDER BY schedule_start_at,sid,id",
                (date_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self, row: Mapping[str, object], *, now: float | int | None = None) -> dict[str, object]:
        return session_summary(row, now=self._now(now))


__all__ = ("FocusNotInitializedError", "StudentFocusRepository")
