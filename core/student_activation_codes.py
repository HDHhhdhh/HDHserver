"""One-use six-digit activation-code storage backed by SQLite."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from types import TracebackType

from core.student_activation_input import (
    ActivationRedemption,
    DEFAULT_TTL_SECONDS,
    MAX_ATTEMPTS,
    StudentActivationInputError,
    StudentActivationStateError,
    parse_number,
    parse_sids,
    parse_stored_row,
    parse_text,
    parse_timeout,
    parse_ttl,
    safe_code,
    safe_text,
    state_usable,
)


class _Connection(sqlite3.Connection):
    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        try: super().__exit__(exc_type, exc, traceback)
        finally: self.close()


class StudentActivationCodeRepository:
    """Issue and redeem identity-bound activation codes without storing codes."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        timeout: float = 5.0,
        clock: Callable[[], float | int | datetime] | None = None,
        pepper: bytes | str = b"student-app-activation-code-v1",
    ) -> None:
        if not isinstance(db_path, (str, Path)):
            raise StudentActivationInputError("db_path", "must be a path")
        if clock is not None and not callable(clock):
            raise StudentActivationInputError("clock", "must be callable")
        if not isinstance(pepper, (bytes, str)):
            raise StudentActivationInputError("pepper", "must be bytes or text")
        self.db_path = str(db_path)
        self.timeout = parse_timeout(timeout)
        self.clock = clock or time.time
        self.pepper = pepper.encode() if isinstance(pepper, str) else pepper
        if not self.pepper:
            raise StudentActivationInputError("pepper", "is required")
        self._ensure_schema()

    def _now(self, value: float | int | datetime | None = None) -> float:
        raw = self.clock() if value is None else value
        return parse_number(raw, "now")

    def _connect(self) -> sqlite3.Connection:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            isolation_level=None,
            check_same_thread=False,
            factory=_Connection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
        connection.execute("PRAGMA foreign_keys=ON")
        if self.db_path != ":memory:":
            connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS student_activation_codes (
                  id INTEGER PRIMARY KEY,
                  identity_key TEXT NOT NULL,
                  sids_json TEXT NOT NULL,
                  code_digest TEXT NOT NULL UNIQUE,
                  created_at REAL NOT NULL,
                  expires_at REAL NOT NULL,
                  used INTEGER NOT NULL DEFAULT 0 CHECK (used IN (0, 1)),
                  attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                  used_at REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_student_activation_active
                  ON student_activation_codes(identity_key) WHERE used=0;
                CREATE INDEX IF NOT EXISTS idx_student_activation_expiry
                  ON student_activation_codes(expires_at, used);
                """
            )

    def _digest(self, value: str) -> str:
        return hmac.new(self.pepper, value.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _sids(value: Iterable[str]) -> list[str]:
        return parse_sids(value)

    @staticmethod
    def _state_usable(expires_at: float, attempts: int, now: float) -> bool:
        """Provide a narrow lifecycle seam for tests and subclasses."""
        return state_usable(expires_at, attempts, now)

    def issue(
        self,
        identity_key: str,
        sids: Iterable[str],
        *,
        ttl_seconds: float | int = DEFAULT_TTL_SECONDS,
        now: float | int | datetime | None = None,
    ) -> str:
        identity_text = parse_text(identity_key, "identity_key")
        sid_list, ttl, current = parse_sids(sids), parse_ttl(ttl_seconds), self._now(now)
        code = f"{secrets.randbelow(1_000_000):06d}"
        digest = self._digest(code)
        identity = self._digest(identity_text)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                active_rows = connection.execute(
                    "SELECT * FROM student_activation_codes WHERE identity_key=? AND used=0",
                    (identity,),
                ).fetchall()
                for row in active_rows:
                    parse_stored_row(row)
                connection.execute(
                    "UPDATE student_activation_codes SET used=1, used_at=? "
                    "WHERE identity_key=? AND used=0",
                    (current, identity),
                )
                connection.execute(
                    """
                    INSERT INTO student_activation_codes
                      (identity_key, sids_json, code_digest, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        identity,
                        json.dumps(sid_list, ensure_ascii=False, separators=(",", ":")),
                        digest,
                        current,
                        current + ttl,
                    ),
                )
                connection.execute("COMMIT")
                return code
            except sqlite3.Error:
                connection.execute("ROLLBACK")
                raise

    create = issue; issue_code = issue

    def redeem(
        self,
        identity_key: str,
        code: str,
        *,
        now: float | int | datetime | None = None,
    ) -> ActivationRedemption | None:
        identity_text = safe_text(identity_key, "identity_key")
        code_text = safe_code(code)
        if identity_text is None or code_text is None:
            return None
        current = self._now(now)
        identity = self._digest(identity_text)
        supplied = self._digest(code_text).encode("ascii")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM student_activation_codes WHERE identity_key=? AND used=0",
                    (identity,),
                ).fetchone()
                if row is None:
                    connection.execute("ROLLBACK")
                    return None
                activation_id, stored_identity, sid_list, expected_digest, expires, attempts = parse_stored_row(row)
                if not hmac.compare_digest(stored_identity, identity):
                    connection.execute("ROLLBACK")
                    return None
                if not self._state_usable(expires, attempts, current):
                    connection.execute(
                        "UPDATE student_activation_codes SET used=1, used_at=? WHERE id=? AND used=0",
                        (current, activation_id),
                    )
                    connection.execute("COMMIT")
                    return None
                if not hmac.compare_digest(expected_digest.encode("ascii"), supplied):
                    next_attempts = attempts + 1
                    connection.execute(
                        "UPDATE student_activation_codes SET attempts=?, used=?, used_at=? WHERE id=? AND used=0",
                        (next_attempts, int(next_attempts >= MAX_ATTEMPTS), current if next_attempts >= MAX_ATTEMPTS else None, activation_id),
                    )
                    connection.execute("COMMIT")
                    return None
                updated = connection.execute(
                    "UPDATE student_activation_codes SET used=1, used_at=? WHERE id=? AND used=0",
                    (current, activation_id),
                )
                if updated.rowcount != 1:
                    connection.execute("ROLLBACK")
                    return None
                connection.execute("COMMIT")
                return {
                    "activation_id": activation_id,
                    "identity_key": identity_text,
                    "sids": sid_list,
                    "attempts": attempts,
                    "used_at": current,
                }
            except StudentActivationStateError:
                connection.execute("ROLLBACK")
                return None
            except sqlite3.Error:
                connection.execute("ROLLBACK")
                raise

    consume = redeem
    use = redeem
    verify = redeem

    def expire(self, *, now: float | int | datetime | None = None) -> int:
        current = self._now(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute("SELECT * FROM student_activation_codes WHERE used=0").fetchall()
                expired_ids: list[int] = []
                for row in rows:
                    activation_id, _identity, _sids, _digest, expires, _attempts = parse_stored_row(row)
                    if expires <= current:
                        expired_ids.append(activation_id)
                for activation_id in expired_ids:
                    connection.execute(
                        "UPDATE student_activation_codes SET used=1, used_at=? WHERE id=? AND used=0",
                        (current, activation_id),
                    )
                connection.execute("COMMIT")
                return len(expired_ids)
            except StudentActivationStateError:
                connection.execute("ROLLBACK")
                return 0
            except sqlite3.Error:
                connection.execute("ROLLBACK")
                raise


__all__ = [
    "ActivationRedemption",
    "StudentActivationCodeRepository",
    "StudentActivationInputError",
    "StudentActivationStateError",
]
