"""Opaque student sessions with typed, fail-closed input boundaries."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from types import TracebackType
from core.student_session_input import (
    SessionCreated,
    SessionView,
    StudentSessionInputError,
    parse_number,
    parse_secret,
    parse_sids,
    parse_text,
    parse_ttl,
    safe_text,
    stored_sids,
)
from core.student_session_expiry import mark_expired, row_usable, stored_number


class _Connection(sqlite3.Connection):
    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        try: return super().__exit__(exc_type, exc, traceback)
        finally: self.close()


class StudentSessionRepository:
    """SQLite session lifecycle with injected storage, clock, and short writes."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        timeout: float = 5.0,
        clock: Callable[[], float | int | datetime] | None = None,
    ) -> None:
        if not isinstance(db_path, (str, Path)):
            raise StudentSessionInputError("db_path", "must be a path")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise StudentSessionInputError("timeout", "must be a number")
        try:
            parsed_timeout = float(timeout)
        except (OverflowError, TypeError, ValueError) as exc:
            raise StudentSessionInputError("timeout", "is invalid") from exc
        if not math.isfinite(parsed_timeout) or parsed_timeout < 0:
            raise StudentSessionInputError("timeout", "must be finite and non-negative")
        self.db_path = str(db_path)
        self.timeout = max(0.1, parsed_timeout)
        self.clock = clock or time.time
        self._ensure_schema()

    def _now(self, value: float | int | datetime | None = None) -> float:
        """Parse an injected or explicit clock value."""
        raw = self.clock() if value is None else value
        return parse_number(raw, "timestamp")

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
        with self._connect() as db:
            db.executescript("CREATE TABLE IF NOT EXISTS student_app_sessions (id INTEGER PRIMARY KEY, token_digest TEXT NOT NULL UNIQUE, aid TEXT NOT NULL, active_sid TEXT NOT NULL, allowed_sids_json TEXT NOT NULL, csrf_digest TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked_at REAL, last_seen REAL NOT NULL, rotation_parent INTEGER, rotation_count INTEGER NOT NULL DEFAULT 0); CREATE INDEX IF NOT EXISTS idx_student_sessions_aid ON student_app_sessions(aid); CREATE INDEX IF NOT EXISTS idx_student_sessions_expiry ON student_app_sessions(expires_at, revoked_at);")

    @staticmethod
    def _digest(value: str) -> str:
        """Return the only persisted representation of a caller secret."""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _row_usable(row: sqlite3.Row, now: float) -> bool:
        return row_usable(row, now)

    @staticmethod
    def _mark_expired(db: sqlite3.Connection, row: sqlite3.Row, now: float) -> bool:
        return mark_expired(db, row, now)

    def _insert(
        self,
        db: sqlite3.Connection,
        aid: str,
        active_sid: str,
        sids: list[str],
        now: float,
        expires: float,
        parent: int | None = None,
        count: int = 0,
    ) -> SessionCreated:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        cursor = db.execute(
            "INSERT INTO student_app_sessions(token_digest,aid,active_sid,allowed_sids_json,csrf_digest,created_at,expires_at,last_seen,rotation_parent,rotation_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (self._digest(token), aid, active_sid, json.dumps(sids, ensure_ascii=False, separators=(",", ":")), self._digest(csrf), now, expires, now, parent, count),
        )
        if cursor.lastrowid is None:
            raise sqlite3.IntegrityError("session row id unavailable")
        return {"session_id": int(cursor.lastrowid), "token": token, "csrf_token": csrf, "aid": aid, "active_sid": active_sid, "allowed_sids": list(sids), "created_at": now, "expires_at": expires}

    def create_session(
        self,
        aid: str,
        active_sid: str,
        allowed_sids: Iterable[str],
        *,
        ttl_seconds: float | int = 30 * 86400,
        now: float | int | datetime | None = None,
    ) -> SessionCreated:
        """Create one session after parsing every caller-controlled field."""
        account_id, selected_sid = parse_text(aid, "aid"), parse_text(active_sid, "active_sid")
        sids, ttl, current = parse_sids(allowed_sids), parse_ttl(ttl_seconds), self._now(now)
        if selected_sid not in sids:
            raise StudentSessionInputError("active_sid", "must be allowed")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                result = self._insert(db, account_id, selected_sid, sids, current, current + ttl)
                db.execute("COMMIT")
                return result
            except sqlite3.Error:
                db.execute("ROLLBACK")
                raise

    create = create_session

    def resolve(
        self,
        token: str,
        *,
        csrf_token: str | None = None,
        now: float | int | datetime | None = None,
    ) -> SessionView | None:
        """Resolve an active token and atomically update its last-seen timestamp."""
        token_text = parse_secret(token, "token")
        csrf_text = parse_secret(csrf_token, "csrf_token") if csrf_token is not None else None
        if token_text is None or (csrf_token is not None and csrf_text is None):
            return None
        current, digest = self._now(now), self._digest(token_text)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT * FROM student_app_sessions WHERE token_digest=?", (digest,)).fetchone()
                if row is None or not hmac.compare_digest(str(row["token_digest"]), digest):
                    db.execute("ROLLBACK")
                    return None
                if self._mark_expired(db, row, current):
                    db.execute("COMMIT")
                    return None
                if not self._row_usable(row, current):
                    db.execute("ROLLBACK")
                    return None
                if csrf_text is not None and not hmac.compare_digest(str(row["csrf_digest"] or ""), self._digest(csrf_text)):
                    db.execute("ROLLBACK")
                    return None
                sids = stored_sids(str(row["allowed_sids_json"]))
                aid, active_sid = safe_text(str(row["aid"]), "stored_aid"), safe_text(str(row["active_sid"]), "stored_active_sid")
                created, expires = stored_number(row["created_at"]), stored_number(row["expires_at"])
                if sids is None or active_sid not in sids or created is None or expires is None:
                    db.execute("ROLLBACK")
                    return None
                updated = db.execute("UPDATE student_app_sessions SET last_seen=? WHERE id=? AND revoked_at IS NULL", (current, row["id"]))
                if updated.rowcount != 1:
                    db.execute("ROLLBACK")
                    return None
                db.execute("COMMIT")
            except sqlite3.Error:
                db.execute("ROLLBACK")
                raise
        return {"session_id": int(row["id"]), "aid": aid, "active_sid": active_sid, "allowed_sids": sids, "created_at": created, "expires_at": expires, "last_seen": current}

    get = resolve

    def rotate(
        self,
        token: str,
        *,
        active_sid: str | None = None,
        now: float | int | datetime | None = None,
        ttl_seconds: float | int | None = None,
    ) -> SessionCreated | None:
        """Revoke an active predecessor and create one allowlisted successor."""
        token_text = parse_secret(token, "token")
        selected = None if active_sid is None else safe_text(active_sid, "active_sid")
        if active_sid is not None and selected is None:
            return None
        if token_text is None:
            return None
        current = self._now(now)
        ttl = None if ttl_seconds is None else parse_ttl(ttl_seconds)
        digest = self._digest(token_text)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT * FROM student_app_sessions WHERE token_digest=?", (digest,)).fetchone()
                if row is None or not hmac.compare_digest(str(row["token_digest"]), digest):
                    db.execute("ROLLBACK")
                    return None
                if self._mark_expired(db, row, current):
                    db.execute("COMMIT")
                    return None
                if not self._row_usable(row, current):
                    db.execute("ROLLBACK")
                    return None
                sids = stored_sids(str(row["allowed_sids_json"]))
                if sids is None:
                    db.execute("ROLLBACK")
                    return None
                selected_sid = str(row["active_sid"]) if selected is None else selected
                if selected_sid not in sids:
                    db.execute("ROLLBACK")
                    return None
                old_expires = stored_number(row["expires_at"])
                expires = current + ttl if ttl is not None else old_expires
                if expires is None or expires <= current:
                    db.execute("ROLLBACK")
                    return None
                db.execute("UPDATE student_app_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (current, row["id"]))
                result = self._insert(db, str(row["aid"]), selected_sid, sids, current, expires, int(row["id"]), int(row["rotation_count"]) + 1)
                db.execute("COMMIT")
                return result
            except sqlite3.Error:
                db.execute("ROLLBACK")
                raise

    def revoke(self, token: str, *, now: float | int | datetime | None = None) -> bool:
        """Revoke one token; malformed and unknown tokens are safe misses."""
        token_text = parse_secret(token, "token")
        if token_text is None:
            return False
        current = self._now(now)
        with self._connect() as db:
            cursor = db.execute("UPDATE student_app_sessions SET revoked_at=? WHERE token_digest=? AND revoked_at IS NULL", (current, self._digest(token_text)))
            return cursor.rowcount == 1

    def revoke_account(self, aid: str, *, now: float | int | datetime | None = None) -> int:
        """Revoke all active sessions for one account without coercing malformed IDs."""
        account_id = safe_text(aid, "aid")
        if account_id is None:
            return 0
        current = self._now(now)
        with self._connect() as db:
            cursor = db.execute("UPDATE student_app_sessions SET revoked_at=? WHERE aid=? AND revoked_at IS NULL", (current, account_id))
            return max(0, cursor.rowcount)

    revoke_all = revoke_account

    def expire(self, *, now: float | int | datetime | None = None) -> int:
        """Mark every active session at or beyond its expiry boundary revoked."""
        current = self._now(now)
        with self._connect() as db:
            cursor = db.execute("UPDATE student_app_sessions SET revoked_at=? WHERE revoked_at IS NULL AND expires_at<=?", (current, current))
            return max(0, cursor.rowcount)
__all__ = ["SessionCreated", "SessionView", "StudentSessionInputError", "StudentSessionRepository"]
