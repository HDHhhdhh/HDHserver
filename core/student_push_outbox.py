"""Outbox enqueue, lease, completion, and cancellation lifecycle."""

from __future__ import annotations

import hmac
import json
import secrets
from collections.abc import Mapping
from datetime import datetime
from typing import TypedDict

from core.student_push_payload import JsonValue, StudentPushRepositoryInputError


class OutboxLease(TypedDict):
    """Lease projection; the raw lease token is returned only to the worker."""

    outbox_id: int
    announcement_id: str
    sid: str
    subscription_id: int | None
    payload: JsonValue
    attempts: int
    lease_token: str
    lease_until: float
    worker_id: str | None


class StudentPushOutboxMixin:
    """Repository mixin for the independently transactional outbox lifecycle."""

    def enqueue(self, announcement_id: str, sid: str, payload: Mapping[str, JsonValue], *, subscription_id: int | None = None, now: float | int | datetime | None = None) -> int:
        announcement, student_id = str(announcement_id).strip(), str(sid).strip()
        if not announcement or not student_id:
            raise StudentPushRepositoryInputError("announcement_id and sid are required")
        current = self._now(now)
        with self._connect() as db:
            if subscription_id is not None:
                owned = db.execute(
                    "SELECT 1 FROM student_push_subscriptions WHERE id=? AND sid=? AND revoked_at IS NULL",
                    (int(subscription_id), student_id),
                ).fetchone()
                if owned is None:
                    raise StudentPushRepositoryInputError("subscription binding is invalid")
            protected_values = tuple(str(item) for row in db.execute("SELECT endpoint,p256dh,auth FROM student_push_subscriptions").fetchall() for item in row)
            body = self._payload(payload, protected_values)
            cursor = db.execute("INSERT INTO student_push_outbox(announcement_id,sid,subscription_id,payload_json,state,next_attempt,created_at,updated_at) VALUES(?,?,?,?,'pending',?,?,?) ON CONFLICT(announcement_id,sid) DO NOTHING", (announcement, student_id, subscription_id, body, current, current, current))
            if cursor.rowcount:
                return int(cursor.lastrowid)
            return int(db.execute("SELECT id FROM student_push_outbox WHERE announcement_id=? AND sid=?", (announcement, student_id)).fetchone()[0])

    enqueue_outbox = enqueue

    def lease(self, *, now: float | int | datetime | None = None, lease_seconds: float = 60.0, worker_id: str | None = None) -> OutboxLease | None:
        if lease_seconds <= 0:
            raise StudentPushRepositoryInputError("lease_seconds must be positive")
        current, token = self._now(now), secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM student_push_outbox WHERE (state='pending' AND next_attempt<=?) OR (state='leased' AND lease_until IS NOT NULL AND lease_until<=?) ORDER BY id LIMIT 1", (current, current)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                return None
            digest = self._digest(token)
            cursor = db.execute("UPDATE student_push_outbox SET state='leased',lease_until=?,lease_digest=?,updated_at=? WHERE id=? AND ((state='pending' AND next_attempt<=?) OR (state='leased' AND lease_until IS NOT NULL AND lease_until<=?))", (current + lease_seconds, digest, current, row["id"], current, current))
            if cursor.rowcount != 1:
                db.execute("ROLLBACK")
                return None
            db.execute("COMMIT")
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        return {"outbox_id": int(row["id"]), "announcement_id": str(row["announcement_id"]), "sid": str(row["sid"]), "subscription_id": row["subscription_id"], "payload": payload, "attempts": int(row["attempts"]), "lease_token": token, "lease_until": current + lease_seconds, "worker_id": worker_id}

    claim = lease

    def complete(self, outbox_id: int, lease_token: str, *, success: bool = True, permanent: bool = False, error: str | int | None = None, status_code: int | None = None, now: float | int | datetime | None = None) -> bool:
        if not lease_token:
            return False
        current = self._now(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM student_push_outbox WHERE id=?", (int(outbox_id),)).fetchone()
            if row is None or row["state"] != "leased" or row["lease_until"] is None or float(row["lease_until"]) <= current or not hmac.compare_digest(str(row["lease_digest"]).encode(), self._digest(lease_token).encode()):
                db.execute("ROLLBACK")
                return False
            error_text = None if error is None else str(error)
            permanent = permanent or status_code in {404, 410} or error_text in {"404", "410", "invalid_subscription", "permanent"}
            if success and not permanent:
                db.execute("UPDATE student_push_outbox SET state='sent',lease_until=NULL,lease_digest=NULL,updated_at=? WHERE id=?", (current, outbox_id))
            else:
                attempts = int(row["attempts"]) + 1
                terminal = permanent or attempts >= self.MAX_ATTEMPTS
                state = "failed" if terminal else "pending"
                next_at = current if terminal else current + self.RETRY_BACKOFF_SECONDS[attempts - 1]
                code = "permanent" if permanent else error_text if error_text in {"timeout", "429", "5xx"} else "delivery_failed"
                db.execute("UPDATE student_push_outbox SET state=?,attempts=?,next_attempt=?,lease_until=NULL,lease_digest=NULL,last_error=?,updated_at=? WHERE id=?", (state, attempts, next_at, code, current, outbox_id))
                if permanent and row["subscription_id"] is not None:
                    db.execute("UPDATE student_push_subscriptions SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (current, row["subscription_id"]))
            db.execute("COMMIT")
            return True

    mark_sent = complete
    finish = complete
    retry = complete

    def cancel(self, outbox_id: int, lease_token: str, *, now: float | int | datetime | None = None) -> bool:
        """Terminally cancel a stale-authority row without revoking a subscription."""

        if not lease_token:
            return False
        current = self._now(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,lease_until,lease_digest FROM student_push_outbox WHERE id=?", (int(outbox_id),)).fetchone()
            if row is None or row["state"] != "leased" or row["lease_until"] is None or float(row["lease_until"]) <= current or not hmac.compare_digest(str(row["lease_digest"]).encode(), self._digest(lease_token).encode()):
                db.execute("ROLLBACK")
                return False
            db.execute("UPDATE student_push_outbox SET state='failed',next_attempt=?,lease_until=NULL,lease_digest=NULL,last_error='cancelled',updated_at=? WHERE id=?", (current, current, int(outbox_id)))
            db.execute("COMMIT")
            return True


__all__ = ["OutboxLease", "StudentPushOutboxMixin"]
