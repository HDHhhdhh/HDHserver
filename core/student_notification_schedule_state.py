"""Durable schedule-notification revisions and projection recovery."""

from __future__ import annotations

from datetime import datetime

from core.student_notification_events import NotificationInputError, deterministic_event_id, valid_event_id


class StudentNotificationScheduleStateMixin:
    """Keep source mutations distinct while allowing the scanner to recover projections."""

    @staticmethod
    def _schedule_sid(value: object) -> str:
        sid = value.strip() if isinstance(value, str) else ""
        if not sid or len(sid) > 128 or any(ord(char) < 32 for char in sid):
            raise NotificationInputError(message="schedule sid is invalid")
        return sid

    def mark_schedule_pending(
        self,
        sids: object,
        *,
        now: float | int | datetime | None = None,
    ) -> dict[str, int]:
        if isinstance(sids, (str, bytes, bytearray)):
            raise NotificationInputError(message="schedule sid collection is invalid")
        try:
            selected = tuple(dict.fromkeys(self._schedule_sid(value) for value in sids))
        except TypeError as exc:
            raise NotificationInputError(message="schedule sid collection is invalid") from exc
        if not selected:
            return {}
        current = self._now(now)
        revisions: dict[str, int] = {}
        with self._connect(readonly=False) as db:
            db.execute("BEGIN IMMEDIATE")
            for sid in selected:
                row = db.execute(
                    "SELECT revision FROM student_notification_schedule_state WHERE sid=?", (sid,),
                ).fetchone()
                revision = (int(row["revision"]) if row is not None else 0) + 1
                db.execute(
                    "INSERT INTO student_notification_schedule_state("
                    "sid,revision,snapshot_key,event_id,pending,updated_at) VALUES(?,?,NULL,NULL,1,?) "
                    "ON CONFLICT(sid) DO UPDATE SET revision=excluded.revision,pending=1,updated_at=excluded.updated_at",
                    (sid, revision, current),
                )
                revisions[sid] = revision
            db.execute("COMMIT")
        return revisions

    def pending_schedule_revisions(self, *, limit: int = 500) -> tuple[dict[str, object], ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise NotificationInputError(message="schedule pending limit is invalid")
        with self._connect(readonly=True) as db:
            rows = db.execute(
                "SELECT sid,revision,updated_at FROM student_notification_schedule_state "
                "WHERE pending=1 ORDER BY updated_at,sid LIMIT ?", (limit,),
            ).fetchall()
        return tuple({"sid": str(row["sid"]), "revision": int(row["revision"]),
                      "updatedAt": float(row["updated_at"])} for row in rows)

    def commit_schedule_projection(
        self,
        sid: object,
        revision: object,
        snapshot_key: object,
        *,
        scheduled_at: float | int | datetime | None = None,
        now: float | int | datetime | None = None,
    ) -> dict[str, object]:
        student_id = self._schedule_sid(sid)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise NotificationInputError(message="schedule revision is invalid")
        if not valid_event_id(snapshot_key):
            raise NotificationInputError(message="schedule snapshot is invalid")
        current = self._now(now)
        selected_time = current + 10.0 if scheduled_at is None else scheduled_at
        event_id = deterministic_event_id("schedule_changed", student_id, revision, snapshot_key)
        with self._connect(readonly=False) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision,pending FROM student_notification_schedule_state WHERE sid=?", (student_id,),
            ).fetchone()
            if row is None or int(row["revision"]) != revision or int(row["pending"]) != 1:
                db.execute("ROLLBACK")
                return {"inserted": False, "superseded": True, "eventId": event_id}
            event = self._insert_event(db, "schedule_changed", event_id, student_id, selected_time, current)
            db.execute(
                "UPDATE student_notification_schedule_state SET snapshot_key=?,event_id=?,pending=0,updated_at=? "
                "WHERE sid=? AND revision=? AND pending=1",
                (snapshot_key, event_id, current, student_id, revision),
            )
            db.execute("COMMIT")
        return {"inserted": bool(event["inserted"]), "superseded": False,
                "eventId": event_id, "id": int(event["id"])}

    def discard_schedule_projection(
        self,
        sid: object,
        revision: object,
        *,
        now: float | int | datetime | None = None,
    ) -> bool:
        student_id = self._schedule_sid(sid)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise NotificationInputError(message="schedule revision is invalid")
        current = self._now(now)
        with self._connect(readonly=False) as db:
            cursor = db.execute(
                "UPDATE student_notification_schedule_state SET snapshot_key=NULL,event_id=NULL,pending=0,updated_at=? "
                "WHERE sid=? AND revision=? AND pending=1", (current, student_id, revision),
            )
        return cursor.rowcount == 1

    def schedule_event_current(self, sid: object, event_id: object, snapshot_key: object) -> bool:
        try:
            student_id = self._schedule_sid(sid)
        except NotificationInputError:
            return False
        if not valid_event_id(event_id) or not valid_event_id(snapshot_key):
            return False
        with self._connect(readonly=True) as db:
            row = db.execute(
                "SELECT event_id,snapshot_key,pending FROM student_notification_schedule_state WHERE sid=?",
                (student_id,),
            ).fetchone()
        return bool(row is not None and int(row["pending"]) == 0
                    and row["event_id"] == event_id and row["snapshot_key"] == snapshot_key)


__all__ = ["StudentNotificationScheduleStateMixin"]
