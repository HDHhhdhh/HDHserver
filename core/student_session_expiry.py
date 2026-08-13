"""Terminal expiry transitions for persisted student sessions."""
from __future__ import annotations

import math
import sqlite3


def stored_number(value: str | float | int | None) -> float | None:
    """Parse a persisted finite, non-negative numeric session field."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def row_usable(row: sqlite3.Row, now: float) -> bool:
    """Return whether a row is active and strictly before its expiry."""
    expires = stored_number(row["expires_at"])
    return row["revoked_at"] is None and expires is not None and expires > now


def mark_expired(db: sqlite3.Connection, row: sqlite3.Row, now: float) -> bool:
    """Atomically terminally revoke an active row whose expiry was observed."""
    if row["revoked_at"] is not None:
        return False
    expires = stored_number(row["expires_at"])
    if expires is None or expires > now:
        return False
    updated = db.execute(
        "UPDATE student_app_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL AND expires_at<=?",
        (now, row["id"], now),
    )
    return updated.rowcount == 1


__all__ = ["mark_expired", "row_usable", "stored_number"]
