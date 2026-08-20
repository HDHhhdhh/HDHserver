"""Small SQL projections kept outside the Push lifecycle repository."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Callable, TypedDict

from core.student_push_payload import StudentPushRepositoryInputError


class PushSubscription(TypedDict):
    """Internal delivery projection; callers must never log these values."""

    subscription_id: int
    aid: str
    session_id: int | None
    endpoint: str
    keys: dict[str, str]


def ensure_capability_column(db: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in db.execute("PRAGMA table_info(student_push_bypasses)")}
    if "capabilities_json" not in columns:
        try:
            db.execute("ALTER TABLE student_push_bypasses ADD COLUMN capabilities_json TEXT NOT NULL DEFAULT '{}'")
        except sqlite3.OperationalError:
            current = {str(row[1]) for row in db.execute("PRAGMA table_info(student_push_bypasses)")}
            if "capabilities_json" not in current:
                raise


def capability_json(report: Mapping[str, bool]) -> str:
    if any(not isinstance(key, str) or type(value) is not bool for key, value in report.items()):
        raise StudentPushRepositoryInputError("invalid capability report")
    return json.dumps(dict(sorted(report.items())), separators=(",", ":"), sort_keys=True)


def has_active_subscription(
    connect: Callable[[], sqlite3.Connection],
    digest: Callable[[str], str],
    aid: str,
    sid: str,
    device_id: str,
) -> bool:
    account_id, student_id, device = str(aid).strip(), str(sid).strip(), str(device_id).strip()
    if not account_id or not student_id or not device:
        return False
    with connect() as db:
        row = db.execute(
            "SELECT 1 FROM student_push_subscriptions WHERE aid=? AND sid=? "
            "AND device_digest=? AND revoked_at IS NULL",
            (account_id, student_id, digest(device)),
        ).fetchone()
    return row is not None


def active_subscriptions(
    connect: Callable[[], sqlite3.Connection],
    sid: str,
    subscription_id: int | None = None,
) -> list[PushSubscription]:
    student_id = str(sid).strip()
    if not student_id:
        return []
    where, params = "sid=?", [student_id]
    if subscription_id is not None:
        where += " AND id=?"
        params.append(int(subscription_id))
    with connect() as db:
        rows = db.execute(
            f"SELECT id,aid,session_id,endpoint,p256dh,auth FROM student_push_subscriptions WHERE {where} "
            "AND revoked_at IS NULL ORDER BY last_seen DESC,id DESC",
            tuple(params),
        ).fetchall()
    return [
        {
            "subscription_id": int(row["id"]),
            "aid": str(row["aid"]),
            "session_id": None if row["session_id"] is None else int(row["session_id"]),
            "endpoint": str(row["endpoint"]),
            "keys": {"p256dh": str(row["p256dh"]), "auth": str(row["auth"])},
        }
        for row in rows
    ]


def bypass_expiry(
    connect: Callable[[], sqlite3.Connection],
    digest: Callable[[str], str],
    aid: str,
    device_id: str,
    current: float,
) -> float | None:
    account_id, device = str(aid).strip(), str(device_id).strip()
    if not account_id or not device:
        return None
    with connect() as db:
        row = db.execute(
            "SELECT expires_at FROM student_push_bypasses WHERE aid_digest=? AND device_digest=?",
            (digest(account_id), digest(device)),
        ).fetchone()
    return None if row is None or float(row["expires_at"]) <= current else float(row["expires_at"])


__all__ = ["PushSubscription", "active_subscriptions", "bypass_expiry", "capability_json", "ensure_capability_column", "has_active_subscription"]
