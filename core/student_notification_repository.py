"""Explicitly migrated notification preferences, milestones, and outbox."""

from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import TracebackType

from core.student_notification_events import (
    DEFAULT_PREFERENCES,
    MILESTONES,
    NotificationInputError,
    deterministic_event_id,
    normalize_preferences,
)
from core.student_notification_outbox import (
    NotificationConflictError,
    NotificationNotInitializedError,
    NotificationRepositoryError,
    StudentNotificationOutboxMixin,
)
from core.student_notification_schedule_state import StudentNotificationScheduleStateMixin


_TABLES = frozenset({
    "student_notification_preferences",
    "student_notification_events",
    "student_notification_milestones",
    "student_notification_deliveries",
    "student_notification_schedule_state",
})


class _Connection(sqlite3.Connection):
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


class StudentNotificationRepository(StudentNotificationScheduleStateMixin, StudentNotificationOutboxMixin):
    """I/O-free constructor; every operation requires an explicit migration."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        timeout: float = 5.0,
        clock: Callable[[], float | int | datetime] | None = None,
    ) -> None:
        if not isinstance(db_path, (str, Path)):
            raise NotificationInputError(message="database path is invalid")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise NotificationInputError(message="database timeout is invalid")
        self.db_path = str(db_path)
        self.timeout = float(timeout)
        self.clock = clock or time.time

    def _now(self, value: float | int | datetime | None = None) -> float:
        raw = self.clock() if value is None else value
        try:
            current = raw.timestamp() if isinstance(raw, datetime) else float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise NotificationInputError(message="timestamp is invalid") from exc
        if not math.isfinite(current) or current < 0:
            raise NotificationInputError(message="timestamp is invalid")
        return current

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        path = Path(self.db_path).absolute()
        if not path.is_file():
            raise NotificationNotInitializedError()
        mode = "ro" if readonly else "rw"
        try:
            db = sqlite3.connect(
                f"{path.as_uri()}?mode={mode}", uri=True, timeout=self.timeout,
                isolation_level=None, check_same_thread=False, factory=_Connection,
            )
        except sqlite3.Error as exc:
            raise NotificationNotInitializedError() from exc
        try:
            db.row_factory = sqlite3.Row
            db.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
            if readonly:
                db.execute("PRAGMA query_only=ON")
            names = {
                str(row[0]) for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?,?)",
                    tuple(sorted(_TABLES)),
                )
            }
        except sqlite3.Error as exc:
            db.close()
            raise NotificationNotInitializedError() from exc
        if names != _TABLES:
            db.close()
            raise NotificationNotInitializedError()
        return db

    def schema_ready(self) -> bool:
        try:
            with self._connect(readonly=True):
                return True
        except NotificationNotInitializedError:
            return False

    @staticmethod
    def _aid(value: object) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if not text or len(text) > 128 or any(ord(char) < 32 for char in text):
            raise NotificationInputError(message="account id is invalid")
        return text

    @staticmethod
    def _preference_result(row: sqlite3.Row | None) -> dict[str, object]:
        if row is None:
            return {"categories": dict(DEFAULT_PREFERENCES), "revision": 0, "updatedAt": None}
        categories = {
            "announcement": bool(row["announcement_enabled"]),
            "homework": bool(row["homework_enabled"]),
            "progress": bool(row["progress_enabled"]),
            "schedule": bool(row["schedule_enabled"]),
        }
        return {"categories": categories, "revision": int(row["revision"]), "updatedAt": float(row["updated_at"])}

    def get_preferences(self, aid: object) -> dict[str, object]:
        account_id = self._aid(aid)
        with self._connect(readonly=True) as db:
            row = db.execute(
                "SELECT * FROM student_notification_preferences WHERE aid=?",
                (account_id,),
            ).fetchone()
        return self._preference_result(row)

    def update_preferences(
        self,
        aid: object,
        categories: object,
        *,
        expected_revision: int,
        now: float | int | datetime | None = None,
    ) -> dict[str, object]:
        account_id, selected = self._aid(aid), normalize_preferences(categories)
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise NotificationInputError(message="expected revision is invalid")
        current = self._now(now)
        values = tuple(int(selected[name]) for name in ("schedule", "homework", "progress", "announcement"))
        with self._connect(readonly=False) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM student_notification_preferences WHERE aid=?", (account_id,)
            ).fetchone()
            revision = 0 if row is None else int(row["revision"])
            if revision != expected_revision:
                db.execute("ROLLBACK")
                raise NotificationConflictError("preference_revision_conflict", "preference revision changed")
            next_revision = revision + 1
            if row is None:
                db.execute(
                    "INSERT INTO student_notification_preferences("
                    "aid,schedule_enabled,homework_enabled,progress_enabled,announcement_enabled,revision,updated_at"
                    ") VALUES(?,?,?,?,?,?,?)",
                    (account_id, *values, next_revision, current),
                )
            else:
                changed = db.execute(
                    "UPDATE student_notification_preferences SET schedule_enabled=?,homework_enabled=?,"
                    "progress_enabled=?,announcement_enabled=?,revision=?,updated_at=? "
                    "WHERE aid=? AND revision=?",
                    (*values, next_revision, current, account_id, revision),
                )
                if changed.rowcount != 1:
                    db.execute("ROLLBACK")
                    raise NotificationConflictError("preference_revision_conflict", "preference revision changed")
            saved = db.execute("SELECT * FROM student_notification_preferences WHERE aid=?", (account_id,)).fetchone()
            db.execute("COMMIT")
        return self._preference_result(saved)

    @staticmethod
    def _milestone_values(sid: object, curriculum_key: object, milestone: object) -> tuple[str, str, int]:
        student_id = sid.strip() if isinstance(sid, str) else ""
        key = curriculum_key.strip() if isinstance(curriculum_key, str) else ""
        if not student_id or len(student_id) > 128 or not key or len(key) > 128 or milestone not in MILESTONES:
            raise NotificationInputError(message="milestone identity is invalid")
        return student_id, key, int(milestone)

    def record_milestone(
        self,
        sid: object,
        curriculum_key: object,
        milestone: object,
        *,
        reached_at: float | int | datetime | None = None,
        now: float | int | datetime | None = None,
    ) -> dict[str, object]:
        student_id, key, threshold = self._milestone_values(sid, curriculum_key, milestone)
        current = self._now(now)
        reached = current if reached_at is None else self._now(reached_at)
        event_id = deterministic_event_id("progress_milestone", student_id, key, threshold)
        with self._connect(readonly=False) as db:
            db.execute("BEGIN IMMEDIATE")
            marker = db.execute(
                "INSERT INTO student_notification_milestones(sid,curriculum_key,milestone,reached_at) "
                "VALUES(?,?,?,?) ON CONFLICT(sid,curriculum_key,milestone) DO NOTHING",
                (student_id, key, threshold, reached),
            )
            event = self._insert_event(db, "progress_milestone", event_id, student_id, current, current)
            db.execute("COMMIT")
        return {"eventId": event_id, "inserted": marker.rowcount == 1, "eventRowId": event["id"]}

    def milestone_event_current(self, sid: object, event_id: object) -> bool:
        student_id = sid.strip() if isinstance(sid, str) else ""
        if not student_id or not isinstance(event_id, str):
            return False
        with self._connect(readonly=True) as db:
            rows = db.execute(
                "SELECT curriculum_key,milestone FROM student_notification_milestones WHERE sid=?",
                (student_id,),
            ).fetchall()
        return any(
            deterministic_event_id("progress_milestone", student_id, row["curriculum_key"], row["milestone"]) == event_id
            for row in rows
        )


__all__ = [
    "NotificationConflictError", "NotificationNotInitializedError", "NotificationRepositoryError",
    "StudentNotificationRepository",
]
