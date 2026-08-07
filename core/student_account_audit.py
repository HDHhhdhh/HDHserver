"""Redacted account-audit events stored in the application SQLite database."""

from __future__ import annotations

import hashlib
import hmac
import math
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TypedDict

from core.student_audit_privacy import (
    AuditInputValue,
    JsonValue,
    StudentAccountAuditInputError,
    parse_action,
    parse_actor_surface,
    parse_serialized_metadata,
    serialize_metadata,
)


class _Connection(sqlite3.Connection):
    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        try:
            super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


class AuditEvent(TypedDict):
    """Redacted account event projection with only hashed target identity."""

    id: int
    action: str
    target_aid_digest: str
    actor_surface: str
    occurred_at: float
    metadata: JsonValue


class StudentAccountAuditRepository:
    """Record stable, non-secret account events and reject sensitive metadata."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        timeout: float = 5.0,
        clock: Callable[[], float | int | datetime] | None = None,
        pepper: bytes | str = b"student-app-audit-v1",
    ) -> None:
        self.db_path = str(db_path)
        try:
            self.timeout = max(0.1, float(timeout))
        except (TypeError, ValueError, OverflowError) as exc:
            raise StudentAccountAuditInputError("timeout is invalid") from exc
        if not math.isfinite(self.timeout):
            raise StudentAccountAuditInputError("timeout is invalid")
        self.clock = clock or time.time
        match pepper:  # noqa: MATCH_OK - runtime callers may provide malformed boundary values
            case str():
                try:
                    self.pepper = pepper.encode("utf-8")
                except UnicodeError as exc:
                    raise StudentAccountAuditInputError("pepper is invalid") from exc
            case bytes():
                self.pepper = pepper
            case _:
                raise StudentAccountAuditInputError("pepper is invalid")
        if not self.pepper:
            raise StudentAccountAuditInputError("pepper is required")
        self._ensure_schema()

    def _now(self, value: float | int | datetime | None = None) -> float:
        raw = self.clock() if value is None else value
        if isinstance(raw, datetime):
            try:
                raw = raw.timestamp()
            except (OverflowError, OSError, ValueError) as exc:
                raise StudentAccountAuditInputError("timestamp is invalid") from exc
        try:
            current = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise StudentAccountAuditInputError("timestamp is invalid") from exc
        if not math.isfinite(current) or current < 0:
            raise StudentAccountAuditInputError("timestamp must be non-negative")
        return current

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
                CREATE TABLE IF NOT EXISTS student_account_audit (
                  id INTEGER PRIMARY KEY,
                  action TEXT NOT NULL,
                  target_aid_digest TEXT,
                  actor_surface TEXT NOT NULL,
                  occurred_at REAL NOT NULL,
                  metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_student_audit_target
                  ON student_account_audit(target_aid_digest, occurred_at);
                """
            )

    def _digest(self, value: str) -> str:
        return hmac.new(self.pepper, str(value).encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _action(value: str) -> str:
        return parse_action(value)

    @staticmethod
    def _actor(value: str) -> str:
        return parse_actor_surface(value)

    @staticmethod
    def _metadata(value: Mapping[str, AuditInputValue] | None) -> str:
        return serialize_metadata(value)

    def record(
        self,
        action: str,
        *,
        target_aid: str | None = None,
        target_ref: str | None = None,
        actor_surface: str,
        metadata: Mapping[str, AuditInputValue] | None = None,
        now: float | int | datetime | None = None,
    ) -> int:
        action_label = self._action(action)
        surface = self._actor(actor_surface)
        if target_aid is not None and target_ref is not None:
            raise StudentAccountAuditInputError("audit target is ambiguous")
        target = target_aid if target_aid is not None else target_ref
        if not isinstance(target, str) or not target.strip():
            raise StudentAccountAuditInputError("audit target is required")
        current = self._now(now)
        payload = self._metadata(metadata)
        target_digest = self._digest(target.strip())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO student_account_audit
                  (action, target_aid_digest, actor_surface, occurred_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (action_label, target_digest, surface, current, payload),
            )
            if cursor.lastrowid is None:
                raise StudentAccountAuditInputError("audit row id is unavailable")
            return int(cursor.lastrowid)

    write = record

    def list_events(
        self,
        *,
        target_aid: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 1000:
            raise StudentAccountAuditInputError("audit limit is out of range")
        where = ""
        params: tuple[str | int, ...] = ()
        if target_aid is not None:
            where, params = "WHERE target_aid_digest=?", (self._digest(target_aid),)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, action, target_aid_digest, actor_surface, occurred_at, metadata_json "
                f"FROM student_account_audit {where} ORDER BY id DESC LIMIT ?",
                (*params, int(limit)),
            ).fetchall()
        output: list[AuditEvent] = []
        for row in rows:
            try:
                action = self._action(row["action"])
                actor = self._actor(row["actor_surface"])
                metadata = parse_serialized_metadata(str(row["metadata_json"]))
            except StudentAccountAuditInputError:
                continue
            target_digest = str(row["target_aid_digest"] or "")
            if len(target_digest) != 64:
                continue
            output.append({
                "id": int(row["id"]),
                "action": action,
                "target_aid_digest": target_digest,
                "actor_surface": actor,
                "occurred_at": float(row["occurred_at"]),
                "metadata": metadata,
            })
        return output

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM student_account_audit").fetchone()
        if row is None:
            raise StudentAccountAuditInputError("audit count is unavailable")
        return int(row["n"])


__all__ = ["AuditEvent", "JsonValue", "StudentAccountAuditInputError", "StudentAccountAuditRepository"]
