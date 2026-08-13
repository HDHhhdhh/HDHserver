"""Privacy-preserving identifier/IP login throttling in SQLite."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Literal, TypeAlias, TypedDict

from core.student_login_throttle_input import (
    StudentLoginThrottleInputError,
    parse_client_ip,
    parse_clock,
    parse_db_path,
    parse_identifier,
    parse_max_failures,
    parse_now,
    parse_pepper,
    parse_timeout,
    parse_window_seconds,
)


ClockValue: TypeAlias = float | int | datetime
TimeInput: TypeAlias = ClockValue | None
BucketType: TypeAlias = Literal["identifier", "ip"]


class _Connection(sqlite3.Connection):
    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        try:
            super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


class ThrottleStatus(TypedDict):
    """Privacy-safe bucket status used by the login boundary."""

    blocked: bool
    blocked_until: float | None
    retry_after: int
    identifier_failures: int
    ip_failures: int


class StudentLoginThrottleRepository:
    """Track five failures per identifier and client-IP bucket in ten minutes."""

    WINDOW_SECONDS: Final = 10 * 60
    MAX_FAILURES: Final = 5

    def __init__(
        self,
        db_path: str | Path,
        *,
        timeout: float = 5.0,
        clock: Callable[[], ClockValue] | None = None,
        pepper: bytes | str = b"student-app-login-throttle-v1",
        window_seconds: int = WINDOW_SECONDS,
        max_failures: int = MAX_FAILURES,
    ) -> None:
        self.db_path = parse_db_path(db_path)
        self.timeout = parse_timeout(timeout)
        parsed_clock = parse_clock(clock)
        self.clock = time.time if parsed_clock is None else parsed_clock
        self.pepper = parse_pepper(pepper)
        self.window_seconds = parse_window_seconds(window_seconds)
        self.max_failures = parse_max_failures(max_failures)
        self._ensure_schema()

    def _now(self, value: TimeInput = None) -> float:
        """Parse an explicit or injected clock value before any database access."""
        raw = self.clock() if value is None else value
        return parse_now(raw)

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
                CREATE TABLE IF NOT EXISTS student_login_throttle (
                  id INTEGER PRIMARY KEY,
                  bucket_type TEXT NOT NULL CHECK (bucket_type IN ('identifier', 'ip')),
                  key_digest TEXT NOT NULL,
                  window_started REAL NOT NULL,
                  failures INTEGER NOT NULL DEFAULT 0 CHECK (failures >= 0),
                  blocked_until REAL,
                  updated_at REAL NOT NULL,
                  UNIQUE(bucket_type, key_digest)
                );
                CREATE INDEX IF NOT EXISTS idx_student_throttle_blocked
                  ON student_login_throttle(blocked_until);
                """
            )

    def _digest(self, value: str, bucket_type: BucketType = "identifier") -> str:
        """Return only a domain-separated HMAC digest for a parsed value."""
        domain = f"student-login-throttle:{bucket_type}:".encode("ascii")
        return hmac.new(self.pepper, domain + value.encode("utf-8"), hashlib.sha256).hexdigest()

    def _keys(self, identifier: str, client_ip: str) -> tuple[tuple[BucketType, str], tuple[BucketType, str]]:
        account_id = parse_identifier(identifier)
        address = parse_client_ip(client_ip)
        return (("identifier", self._digest(account_id)), ("ip", self._digest(address, "ip")))

    def _state(self, row: sqlite3.Row | None, now: float) -> tuple[int, float | None]:
        if row is None or float(row["window_started"]) + self.window_seconds <= now:
            return 0, None
        blocked = row["blocked_until"]
        if blocked is None or float(blocked) <= now:
            return min(self.max_failures, int(row["failures"])), None
        return min(self.max_failures, int(row["failures"])), float(blocked)

    def status(self, identifier: str, client_ip: str, *, now: TimeInput = None) -> ThrottleStatus:
        """Read both digest buckets without writing or exposing caller values."""
        current = self._now(now)
        keys = self._keys(identifier, client_ip)
        with self._connect() as connection:
            rows = tuple(
                connection.execute(
                    "SELECT * FROM student_login_throttle WHERE bucket_type=? AND key_digest=?",
                    key,
                ).fetchone()
                for key in keys
            )
        states = tuple(self._state(row, current) for row in rows)
        blocked_values = tuple(state[1] for state in states if state[1] is not None)
        blocked_until = max(blocked_values) if blocked_values else None
        blocked = blocked_until is not None and blocked_until > current
        retry_after = max(0, int(blocked_until - current)) if blocked else 0
        return {
            "blocked": blocked,
            "blocked_until": blocked_until,
            "retry_after": retry_after,
            "identifier_failures": states[0][0],
            "ip_failures": states[1][0],
        }

    check = status

    def is_blocked(self, identifier: str, client_ip: str, *, now: TimeInput = None) -> bool:
        """Return the privacy-safe blocked bit for one identifier/IP pair."""
        return self.status(identifier, client_ip, now=now)["blocked"]

    def record_failure(self, identifier: str, client_ip: str, *, now: TimeInput = None) -> ThrottleStatus:
        """Atomically add one failure to both digest buckets."""
        current = self._now(now)
        keys = self._keys(identifier, client_ip)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for bucket_type, digest in keys:
                    row = connection.execute(
                        "SELECT * FROM student_login_throttle WHERE bucket_type=? AND key_digest=?",
                        (bucket_type, digest),
                    ).fetchone()
                    failures, _blocked = self._state(row, current)
                    started = current if row is None or float(row["window_started"]) + self.window_seconds <= current else float(row["window_started"])
                    failures = min(self.max_failures, failures + 1)
                    blocked_until = started + self.window_seconds if failures >= self.max_failures else None
                    connection.execute(
                        """
                        INSERT INTO student_login_throttle
                          (bucket_type, key_digest, window_started, failures, blocked_until, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(bucket_type, key_digest) DO UPDATE SET
                          window_started=excluded.window_started,
                          failures=excluded.failures,
                          blocked_until=excluded.blocked_until,
                          updated_at=excluded.updated_at
                        """,
                        (bucket_type, digest, started, failures, blocked_until, current),
                    )
                connection.execute("COMMIT")
            except sqlite3.Error:
                connection.execute("ROLLBACK")
                raise
        return self.status(identifier, client_ip, now=current)

    fail = record_failure

    def record_success(self, identifier: str, *, now: TimeInput = None) -> bool:
        """Clear only the identifier digest bucket; every IP bucket survives."""
        current = self._now(now)
        account_id = parse_identifier(identifier)
        del current
        digest = self._digest(account_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM student_login_throttle WHERE bucket_type='identifier' AND key_digest=?",
                (digest,),
            )
        return cursor.rowcount > 0

    success = record_success


__all__ = ["StudentLoginThrottleInputError", "StudentLoginThrottleRepository", "ThrottleStatus"]
