"""Atomic activation-code selection across duplicate identity groups."""
from __future__ import annotations

import hmac
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from core.student_activation_input import ActivationRedemption, StudentActivationStateError, parse_stored_row, safe_code, safe_text


class _ActivationRepository(Protocol):
    def _connect(self) -> sqlite3.Connection: ...
    def _digest(self, value: str) -> str: ...
    def _now(self, value: float | int | datetime | None = None) -> float: ...
    def _state_usable(self, expires_at: float, attempts: int, now: float) -> bool: ...


def redeem_candidates(
    repository: _ActivationRepository,
    identity_keys: Iterable[str],
    code: str,
    *,
    now: float | int | datetime | None = None,
) -> ActivationRedemption | None:
    """Consume only the row whose code and canonical identity both match."""
    if isinstance(identity_keys, (str, bytes, bytearray)):
        return None
    identities: dict[str, str] = {}
    for value in identity_keys:
        identity = safe_text(value, "identity_key")
        if identity is not None:
            identities[repository._digest(identity)] = identity
    code_text = safe_code(code)
    if not identities or code_text is None:
        return None
    current = repository._now(now)
    supplied = repository._digest(code_text)
    with repository._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT * FROM student_activation_codes WHERE code_digest=? AND used=0",
                (supplied,),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                return None
            activation_id, stored_identity, sids, expected, expires, attempts = parse_stored_row(row)
            identity = identities.get(stored_identity)
            if identity is None or not hmac.compare_digest(expected, supplied):
                connection.execute("ROLLBACK")
                return None
            if not repository._state_usable(expires, attempts, current):
                connection.execute("UPDATE student_activation_codes SET used=1,used_at=? WHERE id=? AND used=0", (current, activation_id))
                connection.execute("COMMIT")
                return None
            updated = connection.execute("UPDATE student_activation_codes SET used=1,used_at=? WHERE id=? AND used=0", (current, activation_id))
            if updated.rowcount != 1:
                connection.execute("ROLLBACK")
                return None
            connection.execute("COMMIT")
            return {"activation_id": activation_id, "identity_key": identity, "sids": sids, "attempts": attempts, "used_at": current}
        except StudentActivationStateError:
            connection.execute("ROLLBACK")
            return None
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise


__all__ = ["redeem_candidates"]
