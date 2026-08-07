"""Push subscription, outbox lease, and bypass persistence."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TypedDict

from core.student_push_payload import (
    JsonValue,
    StudentPushRepositoryInputError,
    parse_endpoint,
    parse_subscription_key,
    serialize_payload,
)


class _Connection(sqlite3.Connection):
    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        try:
            super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


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


class StudentPushRepository:
    """Store HTTPS subscriptions and privacy-minimal delivery state."""
    RETRY_BACKOFF_SECONDS = (60.0, 300.0, 1800.0, 7200.0, 21600.0)
    MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS) + 1

    def __init__(self, db_path: str | Path, *, timeout: float = 5.0, clock: Callable[[], float | int | datetime] | None = None, pepper: bytes | str = b"student-app-push-v1") -> None:
        self.db_path, self.timeout, self.clock = str(db_path), max(.1, float(timeout)), clock or time.time
        self.pepper = pepper.encode() if isinstance(pepper, str) else bytes(pepper)
        if not self.pepper:
            raise StudentPushRepositoryInputError("pepper required")
        self._ensure_schema()

    def _now(self, value: float | int | datetime | None = None) -> float:
        value = self.clock() if value is None else value
        try:
            current = value.timestamp() if isinstance(value, datetime) else float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise StudentPushRepositoryInputError("timestamp is invalid") from exc
        if current < 0:
            raise StudentPushRepositoryInputError("timestamp must be non-negative")
        return current

    def _connect(self) -> sqlite3.Connection:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=self.timeout, isolation_level=None, check_same_thread=False, factory=_Connection)
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
        db.execute("PRAGMA foreign_keys=ON")
        if self.db_path != ":memory:":
            db.execute("PRAGMA journal_mode=WAL")
        return db

    def _ensure_schema(self) -> None:
        sql = "CREATE TABLE IF NOT EXISTS student_push_subscriptions (id INTEGER PRIMARY KEY, aid TEXT NOT NULL, sid TEXT NOT NULL, device_digest TEXT NOT NULL, endpoint TEXT NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL, session_id INTEGER, created_at REAL NOT NULL, last_seen REAL NOT NULL, revoked_at REAL); CREATE UNIQUE INDEX IF NOT EXISTS uq_student_push_device ON student_push_subscriptions(aid,sid,device_digest); CREATE TABLE IF NOT EXISTS student_push_outbox (id INTEGER PRIMARY KEY, announcement_id TEXT NOT NULL, sid TEXT NOT NULL, subscription_id INTEGER, payload_json TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','leased','sent','failed')), attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL, lease_until REAL, lease_digest TEXT, last_error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL, UNIQUE(announcement_id,sid)); CREATE INDEX IF NOT EXISTS idx_student_push_ready ON student_push_outbox(state,next_attempt,lease_until); CREATE TABLE IF NOT EXISTS student_push_bypasses (id INTEGER PRIMARY KEY, aid_digest TEXT NOT NULL, device_digest TEXT NOT NULL, expires_at REAL NOT NULL, created_at REAL NOT NULL, UNIQUE(aid_digest,device_digest)); CREATE INDEX IF NOT EXISTS idx_student_push_bypass_expiry ON student_push_bypasses(expires_at);"
        with self._connect() as db:
            db.executescript(sql)

    def _digest(self, value: str) -> str:
        return hmac.new(self.pepper, str(value).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _endpoint(value: str) -> str:
        return parse_endpoint(value)

    @staticmethod
    def _key(value: str) -> str:
        return parse_subscription_key(value)

    @staticmethod
    def _payload(value: Mapping[str, JsonValue], protected_values: tuple[str, ...] = ()) -> str:
        return serialize_payload(value, protected_values)

    def upsert_subscription(self, aid: str, sid: str, device_id: str, endpoint: str, p256dh: str, auth: str, *, session_id: int | None = None, now: float | int | datetime | None = None) -> int:
        account_id, student_id, device = str(aid).strip(), str(sid).strip(), str(device_id).strip()
        if not account_id or not student_id or not device:
            raise StudentPushRepositoryInputError("subscription binding is required")
        current = self._now(now)
        binding = (account_id, student_id, self._digest(device), self._endpoint(endpoint), self._key(p256dh), self._key(auth))
        with self._connect() as db:
            db.execute("INSERT INTO student_push_subscriptions(aid,sid,device_digest,endpoint,p256dh,auth,session_id,created_at,last_seen) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(aid,sid,device_digest) DO UPDATE SET endpoint=excluded.endpoint,p256dh=excluded.p256dh,auth=excluded.auth,session_id=excluded.session_id,last_seen=excluded.last_seen,revoked_at=NULL", (*binding, session_id, current, current))
            row = db.execute("SELECT id FROM student_push_subscriptions WHERE aid=? AND sid=? AND device_digest=?", binding[:3]).fetchone()
            if row is None:
                raise sqlite3.IntegrityError("subscription upsert did not produce a row")
            return int(row[0])

    subscribe = upsert_subscription
    upsert = upsert_subscription

    def revoke_subscription(self, subscription_id: int | None = None, *, aid: str | None = None, sid: str | None = None, device_id: str | None = None, now: float | int | datetime | None = None) -> int:
        if subscription_id is None and (not str(aid or "").strip() or not str(sid or "").strip() or not str(device_id or "").strip()):
            raise StudentPushRepositoryInputError("subscription selector is required")
        current = self._now(now)
        where, params = (("id=?", (int(subscription_id),)) if subscription_id is not None else ("aid=? AND sid=? AND device_digest=?", (str(aid).strip(), str(sid).strip(), self._digest(str(device_id).strip()))))
        with self._connect() as db:
            cur = db.execute(f"UPDATE student_push_subscriptions SET revoked_at=? WHERE {where} AND revoked_at IS NULL", (current, *params))
            return max(0, cur.rowcount)

    revoke = revoke_subscription

    def enqueue(self, announcement_id: str, sid: str, payload: Mapping[str, JsonValue], *, subscription_id: int | None = None, now: float | int | datetime | None = None) -> int:
        announcement, student_id = str(announcement_id).strip(), str(sid).strip()
        if not announcement or not student_id:
            raise StudentPushRepositoryInputError("announcement_id and sid are required")
        current = self._now(now)
        with self._connect() as db:
            protected_values = tuple(str(item) for row in db.execute("SELECT endpoint,p256dh,auth FROM student_push_subscriptions").fetchall() for item in row)
            body = self._payload(payload, protected_values)
            cur = db.execute("INSERT INTO student_push_outbox(announcement_id,sid,subscription_id,payload_json,state,next_attempt,created_at,updated_at) VALUES(?,?,?,?,'pending',?,?,?) ON CONFLICT(announcement_id,sid) DO NOTHING", (announcement, student_id, subscription_id, body, current, current, current))
            if cur.rowcount:
                return int(cur.lastrowid)
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
            cur = db.execute("UPDATE student_push_outbox SET state='leased',lease_until=?,lease_digest=?,updated_at=? WHERE id=? AND ((state='pending' AND next_attempt<=?) OR (state='leased' AND lease_until IS NOT NULL AND lease_until<=?))", (current + lease_seconds, digest, current, row["id"], current, current))
            if cur.rowcount != 1:
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
                terminal, state = permanent or attempts >= self.MAX_ATTEMPTS, "failed" if permanent or attempts >= self.MAX_ATTEMPTS else "pending"
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

    def grant_bypass(self, aid: str, device_id: str, *, expires_at: float | int | datetime, now: float | int | datetime | None = None) -> bool:
        current, expiry = self._now(now), self._now(expires_at)
        account_id, device = str(aid).strip(), str(device_id).strip()
        if not account_id or not device or expiry <= current:
            raise StudentPushRepositoryInputError("invalid bypass")
        with self._connect() as db:
            db.execute("INSERT INTO student_push_bypasses(aid_digest,device_digest,expires_at,created_at) VALUES(?,?,?,?) ON CONFLICT(aid_digest,device_digest) DO UPDATE SET expires_at=excluded.expires_at", (self._digest(account_id), self._digest(device), expiry, current))
        return True

    def has_bypass(self, aid: str, device_id: str, *, now: float | int | datetime | None = None) -> bool:
        current = self._now(now)
        account_id, device = str(aid).strip(), str(device_id).strip()
        if not account_id or not device:
            return False
        with self._connect() as db:
            row = db.execute("SELECT expires_at FROM student_push_bypasses WHERE aid_digest=? AND device_digest=?", (self._digest(account_id), self._digest(device))).fetchone()
        return row is not None and float(row["expires_at"]) > current

    bypass_active = has_bypass

    def expire_bypasses(self, *, now: float | int | datetime | None = None) -> int:
        with self._connect() as db:
            cur = db.execute("DELETE FROM student_push_bypasses WHERE expires_at<=?", (self._now(now),))
            return max(0, cur.rowcount)
