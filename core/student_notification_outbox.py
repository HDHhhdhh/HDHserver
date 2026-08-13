"""Generic notification outbox lifecycle with per-subscription receipts."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from core.student_notification_events import NotificationInputError, build_event_payload, serialize_event_payload


@dataclass(frozen=True, slots=True)
class NotificationRepositoryError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class NotificationNotInitializedError(NotificationRepositoryError):
    def __init__(self) -> None:
        super().__init__("notification_not_initialized", "student notification schema is not initialized")


class NotificationConflictError(NotificationRepositoryError):
    pass


class NotificationLease(TypedDict):
    event_row_id: int
    event_type: str
    event_id: str
    sid: str
    payload: dict[str, str]
    payload_valid: bool
    scheduled_at: float
    attempts: int
    lease_token: str
    lease_until: float
    worker_id: str | None


class StudentNotificationOutboxMixin:
    RETRY_BACKOFF_SECONDS = (60.0, 300.0, 1800.0, 7200.0, 21600.0)
    MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS) + 1
    _CANCEL_CODES = frozenset({"cancelled", "authority_changed", "payload_invalid", "no_subscription"})

    @staticmethod
    def _lease_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _event_values(event_type: object, event_id: object, sid: object) -> tuple[str, str, str, str]:
        payload = build_event_payload(event_type, event_id)
        student_id = sid.strip() if isinstance(sid, str) else ""
        if not student_id or len(student_id) > 128 or any(ord(char) < 32 for char in student_id):
            raise NotificationInputError(message="sid is invalid")
        return payload["type"], payload["eventId"], student_id, serialize_event_payload(event_type, event_id)

    def _insert_event(self, db, event_type: object, event_id: object, sid: object,
                      scheduled_at: object, current: float) -> dict[str, int | bool]:
        selected, identifier, student_id, payload = self._event_values(event_type, event_id, sid)
        scheduled = self._now(scheduled_at)
        cursor = db.execute(
            "INSERT INTO student_notification_events("
            "event_type,event_id,sid,payload_json,scheduled_at,state,attempts,next_attempt,created_at,updated_at"
            ") VALUES(?,?,?,?,?,'pending',0,?,?,?) "
            "ON CONFLICT(event_type,event_id,sid) DO NOTHING",
            (selected, identifier, student_id, payload, scheduled, scheduled, current, current),
        )
        inserted = cursor.rowcount == 1
        if inserted:
            row_id = int(cursor.lastrowid)
        else:
            row = db.execute(
                "SELECT id FROM student_notification_events WHERE event_type=? AND event_id=? AND sid=?",
                (selected, identifier, student_id),
            ).fetchone()
            if row is None:
                raise NotificationRepositoryError("notification_storage_error", "event row is unavailable")
            row_id = int(row[0])
        return {"id": row_id, "inserted": inserted}

    def enqueue(self, event_type: object, event_id: object, sid: object, *,
                scheduled_at: float | int | datetime | None = None,
                now: float | int | datetime | None = None) -> dict[str, int | bool]:
        current = self._now(now)
        selected_time = current if scheduled_at is None else scheduled_at
        with self._connect(readonly=False) as db:
            return self._insert_event(db, event_type, event_id, sid, selected_time, current)

    def lease(self, *, now: float | int | datetime | None = None,
              lease_seconds: float = 60.0,
              worker_id: str | None = None) -> NotificationLease | None:
        if not isinstance(lease_seconds, (int, float)) or isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise NotificationInputError(message="lease duration is invalid")
        current, token = self._now(now), secrets.token_urlsafe(32)
        with self._connect(readonly=False) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM student_notification_events WHERE "
                "(state='pending' AND next_attempt<=?) OR "
                "(state='leased' AND lease_until IS NOT NULL AND lease_until<=?) "
                "ORDER BY next_attempt,id LIMIT 1",
                (current, current),
            ).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                return None
            lease_until = current + float(lease_seconds)
            changed = db.execute(
                "UPDATE student_notification_events SET state='leased',lease_until=?,lease_digest=?,updated_at=? "
                "WHERE id=? AND ((state='pending' AND next_attempt<=?) OR "
                "(state='leased' AND lease_until IS NOT NULL AND lease_until<=?))",
                (lease_until, self._lease_digest(token), current, row["id"], current, current),
            )
            if changed.rowcount != 1:
                db.execute("ROLLBACK")
                return None
            db.execute("COMMIT")
        canonical = build_event_payload(row["event_type"], row["event_id"])
        payload_valid = row["payload_json"] == serialize_event_payload(row["event_type"], row["event_id"])
        return {
            "event_row_id": int(row["id"]), "event_type": str(row["event_type"]),
            "event_id": str(row["event_id"]), "sid": str(row["sid"]), "payload": canonical,
            "payload_valid": payload_valid, "scheduled_at": float(row["scheduled_at"]),
            "attempts": int(row["attempts"]),
            "lease_token": token, "lease_until": lease_until, "worker_id": worker_id,
        }

    def _valid_lease(self, db, event_row_id: int, token: str, current: float):
        row = db.execute("SELECT * FROM student_notification_events WHERE id=?", (event_row_id,)).fetchone()
        valid = bool(
            row is not None and row["state"] == "leased" and isinstance(token, str) and token
            and hmac.compare_digest(str(row["lease_digest"] or ""), self._lease_digest(token))
        )
        return row if valid else None

    def renew_lease(self, event_row_id: int, lease_token: str, *, lease_seconds: float = 180.0,
                    now: float | int | datetime | None = None) -> bool:
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)) or lease_seconds <= 0:
            raise NotificationInputError(message="lease duration is invalid")
        current = self._now(now)
        with self._connect(readonly=False) as db:
            db.execute("BEGIN IMMEDIATE")
            if self._valid_lease(db, int(event_row_id), lease_token, current) is None:
                db.execute("ROLLBACK")
                return False
            db.execute("UPDATE student_notification_events SET lease_until=?,updated_at=? WHERE id=?",
                       (current + float(lease_seconds), current, int(event_row_id)))
            db.execute("COMMIT")
        return True

    def finished_subscription_ids(self, event_row_id: int) -> frozenset[int]:
        with self._connect(readonly=True) as db:
            rows = db.execute(
                "SELECT subscription_id FROM student_notification_deliveries WHERE event_row_id=? "
                "AND state IN ('sent','permanent_failure')",
                (int(event_row_id),),
            ).fetchall()
        return frozenset(int(row[0]) for row in rows)

    def successful_subscription_ids(self, event_row_id: int) -> frozenset[int]:
        with self._connect(readonly=True) as db:
            rows = db.execute(
                "SELECT subscription_id FROM student_notification_deliveries WHERE event_row_id=? AND state='sent'",
                (int(event_row_id),),
            ).fetchall()
        return frozenset(int(row[0]) for row in rows)

    def record_delivery(self, event_row_id: int, lease_token: str, subscription_id: int, *,
                        state: str = "sent",
                        now: float | int | datetime | None = None) -> bool:
        if state not in {"sent", "permanent_failure"} or isinstance(subscription_id, bool) \
                or not isinstance(subscription_id, int) or subscription_id < 1:
            raise NotificationInputError(message="delivery receipt is invalid")
        current = self._now(now)
        with self._connect(readonly=False) as db:
            db.execute("BEGIN IMMEDIATE")
            if self._valid_lease(db, int(event_row_id), lease_token, current) is None:
                db.execute("ROLLBACK")
                return False
            cursor = db.execute(
                "INSERT INTO student_notification_deliveries(event_row_id,subscription_id,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(event_row_id,subscription_id) DO NOTHING",
                (int(event_row_id), int(subscription_id), state, current, current),
            )
            db.execute("COMMIT")
            return cursor.rowcount == 1

    def complete(self, event_row_id: int, lease_token: str, *, success: bool,
                 permanent: bool = False, error: str = "delivery_failed",
                 now: float | int | datetime | None = None) -> bool:
        if type(success) is not bool or type(permanent) is not bool:
            raise NotificationInputError(message="delivery outcome is invalid")
        current = self._now(now)
        with self._connect(readonly=False) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._valid_lease(db, int(event_row_id), lease_token, current)
            if row is None:
                db.execute("ROLLBACK")
                return False
            if success and not permanent:
                state, attempts, next_at, code = "sent", int(row["attempts"]), current, None
            else:
                attempts = int(row["attempts"]) + 1
                terminal = permanent or attempts >= self.MAX_ATTEMPTS
                state = "failed" if terminal else "pending"
                next_at = current if terminal else current + self.RETRY_BACKOFF_SECONDS[attempts - 1]
                code = "permanent" if permanent else error if error in {"timeout", "429", "5xx"} else "delivery_failed"
            db.execute(
                "UPDATE student_notification_events SET state=?,attempts=?,next_attempt=?,lease_until=NULL,"
                "lease_digest=NULL,last_error=?,updated_at=? WHERE id=?",
                (state, attempts, next_at, code, current, int(event_row_id)),
            )
            db.execute("COMMIT")
            return True

    def cancel(self, event_row_id: int, lease_token: str, *, code: str = "cancelled",
               now: float | int | datetime | None = None) -> bool:
        if code not in self._CANCEL_CODES:
            raise NotificationInputError(message="cancellation code is invalid")
        current = self._now(now)
        with self._connect(readonly=False) as db:
            db.execute("BEGIN IMMEDIATE")
            if self._valid_lease(db, int(event_row_id), lease_token, current) is None:
                db.execute("ROLLBACK")
                return False
            db.execute(
                "UPDATE student_notification_events SET state='cancelled',next_attempt=?,lease_until=NULL,"
                "lease_digest=NULL,last_error=?,updated_at=? WHERE id=?",
                (current, code, current, int(event_row_id)),
            )
            db.execute("COMMIT")
            return True


__all__ = ["NotificationConflictError", "NotificationLease", "NotificationNotInitializedError",
           "NotificationRepositoryError", "StudentNotificationOutboxMixin"]
