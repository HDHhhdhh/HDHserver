"""Push repository schema creation and active-subscription migration."""

from __future__ import annotations

import sqlite3
from typing import Protocol

from core.student_push_payload import StudentPushRepositoryInputError
from core.student_push_repository_support import ensure_capability_column


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS student_push_subscriptions (
    id INTEGER PRIMARY KEY, aid TEXT NOT NULL, sid TEXT NOT NULL,
    device_digest TEXT NOT NULL, endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL, auth TEXT NOT NULL, session_id INTEGER,
    created_at REAL NOT NULL, last_seen REAL NOT NULL, revoked_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_student_push_device
    ON student_push_subscriptions(aid,sid,device_digest);
CREATE TABLE IF NOT EXISTS student_push_outbox (
    id INTEGER PRIMARY KEY, announcement_id TEXT NOT NULL, sid TEXT NOT NULL,
    subscription_id INTEGER, payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','leased','sent','failed')),
    attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL,
    lease_until REAL, lease_digest TEXT, last_error TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL,
    UNIQUE(announcement_id,sid)
);
CREATE INDEX IF NOT EXISTS idx_student_push_ready
    ON student_push_outbox(state,next_attempt,lease_until);
CREATE TABLE IF NOT EXISTS student_push_bypasses (
    id INTEGER PRIMARY KEY, aid_digest TEXT NOT NULL,
    device_digest TEXT NOT NULL, expires_at REAL NOT NULL,
    created_at REAL NOT NULL, UNIQUE(aid_digest,device_digest)
);
CREATE INDEX IF NOT EXISTS idx_student_push_bypass_expiry
    ON student_push_bypasses(expires_at);
"""


class PushSchemaRepository(Protocol):
    MAX_ACTIVE_SUBSCRIPTIONS_PER_ACCOUNT_SID: int

    def _connect(self) -> sqlite3.Connection: ...
    def _endpoint(self, value: str) -> str: ...


def ensure_push_schema(repository: PushSchemaRepository) -> None:
    """Create the schema and enforce canonical active endpoint ownership."""

    with repository._connect() as db:
        db.executescript(_SCHEMA_SQL)
        db.execute("BEGIN IMMEDIATE")
        raw_active_rows = db.execute(
            "SELECT id,endpoint,last_seen FROM student_push_subscriptions "
            "WHERE revoked_at IS NULL ORDER BY last_seen DESC,id DESC"
        ).fetchall()
        canonical_winners: dict[str, int] = {}
        canonical_endpoints: dict[int, str] = {}
        stale_rows: list[tuple[float, int]] = []
        for row in raw_active_rows:
            row_id, last_seen = int(row["id"]), float(row["last_seen"])
            try:
                canonical = repository._endpoint(str(row["endpoint"]))
            except StudentPushRepositoryInputError:
                stale_rows.append((last_seen, row_id))
                continue
            if canonical in canonical_winners:
                stale_rows.append((last_seen, row_id))
                continue
            canonical_winners[canonical] = row_id
            canonical_endpoints[row_id] = canonical
        for revoked_at, row_id in stale_rows:
            db.execute(
                "UPDATE student_push_subscriptions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (revoked_at, row_id),
            )
        for row_id, canonical in canonical_endpoints.items():
            db.execute(
                "UPDATE student_push_subscriptions SET endpoint=? WHERE id=? AND revoked_at IS NULL",
                (canonical, row_id),
            )
        active_rows = db.execute(
            "SELECT id,aid,sid,last_seen FROM student_push_subscriptions "
            "WHERE revoked_at IS NULL ORDER BY aid,sid,last_seen DESC,id DESC"
        ).fetchall()
        active_per_binding: dict[tuple[str, str], int] = {}
        for row in active_rows:
            key = (str(row["aid"]), str(row["sid"]))
            active_per_binding[key] = active_per_binding.get(key, 0) + 1
            if active_per_binding[key] > repository.MAX_ACTIVE_SUBSCRIPTIONS_PER_ACCOUNT_SID:
                db.execute(
                    "UPDATE student_push_subscriptions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                    (float(row["last_seen"]), int(row["id"])),
                )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_student_push_active_endpoint "
            "ON student_push_subscriptions(endpoint) WHERE revoked_at IS NULL"
        )
        db.execute("COMMIT")
        ensure_capability_column(db)


__all__ = ["PushSchemaRepository", "ensure_push_schema"]
