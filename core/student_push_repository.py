"""Push subscription, outbox lease, and bypass persistence."""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from types import TracebackType

from core.student_push_outbox import OutboxLease, StudentPushOutboxMixin
from core.student_push_payload import (
    JsonValue,
    StudentPushRepositoryInputError,
    parse_endpoint,
    parse_subscription_key,
    serialize_payload,
)
from core.student_push_repository_schema import ensure_push_schema
from core.student_push_repository_support import (
    PushSubscription,
    active_subscriptions,
    bypass_expiry,
    capability_json,
    has_active_subscription,
)


class _Connection(sqlite3.Connection):
    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        try:
            super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


class StudentPushRepository(StudentPushOutboxMixin):
    """Store HTTPS subscriptions and privacy-minimal delivery state."""
    RETRY_BACKOFF_SECONDS = (60.0, 300.0, 1800.0, 7200.0, 21600.0)
    MAX_ATTEMPTS = len(RETRY_BACKOFF_SECONDS) + 1
    MAX_ACTIVE_SUBSCRIPTIONS_PER_ACCOUNT_SID = 5

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
        ensure_push_schema(self)

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
            db.execute("BEGIN IMMEDIATE")
            target = db.execute(
                "SELECT id,revoked_at FROM student_push_subscriptions WHERE aid=? AND sid=? AND device_digest=?",
                binding[:3],
            ).fetchone()
            target_id = None if target is None else int(target["id"])
            endpoint_owners = db.execute(
                "SELECT id,aid,sid FROM student_push_subscriptions WHERE endpoint=? AND revoked_at IS NULL",
                (binding[3],),
            ).fetchall()
            active_row = db.execute(
                "SELECT COUNT(*) FROM student_push_subscriptions WHERE aid=? AND sid=? AND revoked_at IS NULL",
                (account_id, student_id),
            ).fetchone()
            active_count = 0 if active_row is None else int(active_row[0])
            transferred_from_binding = sum(
                1
                for owner in endpoint_owners
                if int(owner["id"]) != target_id and str(owner["aid"]) == account_id and str(owner["sid"]) == student_id
            )
            activates_target = target is None or target["revoked_at"] is not None
            resulting_count = active_count - transferred_from_binding + int(activates_target)
            if resulting_count > self.MAX_ACTIVE_SUBSCRIPTIONS_PER_ACCOUNT_SID:
                db.execute("ROLLBACK")
                raise StudentPushRepositoryInputError("active subscription limit reached")
            for owner in endpoint_owners:
                owner_id = int(owner["id"])
                if owner_id != target_id:
                    db.execute(
                        "UPDATE student_push_subscriptions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                        (current, owner_id),
                    )
            if target_id is None:
                cursor = db.execute(
                    "INSERT INTO student_push_subscriptions(aid,sid,device_digest,endpoint,p256dh,auth,session_id,created_at,last_seen) VALUES(?,?,?,?,?,?,?,?,?)",
                    (*binding, session_id, current, current),
                )
                target_id = int(cursor.lastrowid)
            else:
                db.execute(
                    "UPDATE student_push_subscriptions SET endpoint=?,p256dh=?,auth=?,session_id=?,last_seen=?,revoked_at=NULL WHERE id=?",
                    (binding[3], binding[4], binding[5], session_id, current, target_id),
                )
            db.execute("COMMIT")
            return target_id

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

    def revoke_account(self, aid: str, *, now: float | int | datetime | None = None) -> int:
        """Revoke every active subscription bound to one exact account ID."""
        account_id = str(aid).strip() if isinstance(aid, str) else ""
        if not account_id:
            raise StudentPushRepositoryInputError("account id is required")
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE student_push_subscriptions SET revoked_at=? "
                "WHERE aid=? AND revoked_at IS NULL",
                (self._now(now), account_id),
            )
            return max(0, cursor.rowcount)

    revoke_all = revoke_account

    def active_count(self, aid: str) -> int:
        """Count active subscriptions without selecting endpoint or key data."""
        account_id = str(aid).strip() if isinstance(aid, str) else ""
        if not account_id:
            return 0
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM student_push_subscriptions "
                "WHERE aid=? AND revoked_at IS NULL",
                (account_id,),
            ).fetchone()
        return 0 if row is None else max(0, int(row[0]))

    def has_active_subscription(self, aid: str, sid: str, device_id: str) -> bool:
        """Check one exact account/SID/device binding without exposing secrets."""
        return has_active_subscription(self._connect, self._digest, aid, sid, device_id)

    def active_subscriptions(self, sid: str, subscription_id: int | None = None) -> list[PushSubscription]:
        """Return the internal delivery material for one exact target SID."""
        return active_subscriptions(self._connect, sid, subscription_id)

    def grant_bypass(self, aid: str, device_id: str, *, expires_at: float | int | datetime, capabilities: Mapping[str, bool] | None = None, now: float | int | datetime | None = None) -> bool:
        current, expiry = self._now(now), self._now(expires_at)
        account_id, device = str(aid).strip(), str(device_id).strip()
        if not account_id or not device or expiry <= current:
            raise StudentPushRepositoryInputError("invalid bypass")
        encoded = capability_json(capabilities or {})
        with self._connect() as db:
            db.execute("INSERT INTO student_push_bypasses(aid_digest,device_digest,expires_at,created_at,capabilities_json) VALUES(?,?,?,?,?) ON CONFLICT(aid_digest,device_digest) DO UPDATE SET expires_at=excluded.expires_at,capabilities_json=excluded.capabilities_json", (self._digest(account_id), self._digest(device), expiry, current, encoded))
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

    def bypass_expiry(self, aid: str, device_id: str, *, now: float | int | datetime | None = None) -> float | None:
        """Return a future server expiry for one exact digest binding."""
        return bypass_expiry(self._connect, self._digest, aid, device_id, self._now(now))

    def expire_bypasses(self, *, now: float | int | datetime | None = None) -> int:
        with self._connect() as db:
            cur = db.execute("DELETE FROM student_push_bypasses WHERE expires_at<=?", (self._now(now),))
            return max(0, cur.rowcount)
