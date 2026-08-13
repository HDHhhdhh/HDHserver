"""Pure current-authority rules for queued student Push delivery."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Protocol

from .student_board_projection import student_board_announcement_visible


class PushRolloutConfig(Protocol):
    public_enabled: bool

    def allows_canary_sid(self, sid: str) -> bool: ...


def _utc(value: dt.datetime | float | int) -> dt.datetime | None:
    try:
        if isinstance(value, dt.datetime):
            parsed = value
        else:
            parsed = dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    except (OSError, OverflowError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _parse_time(value: object) -> dt.datetime | None:
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _visible_announcement(
    announcements: object,
    announcement_id: str,
    sid: str,
    current: dt.datetime,
) -> bool:
    if not isinstance(announcements, Sequence) or isinstance(announcements, (str, bytes, bytearray)):
        return False
    for raw in announcements:
        if not isinstance(raw, Mapping) or raw.get("id") != announcement_id:
            continue
        return student_board_announcement_visible(dict(raw), sid, current)
    return False


def eligible_push_account_ids(
    config: PushRolloutConfig,
    announcements: object,
    students: object,
    accounts: object,
    announcement_id: str,
    sid: str,
    *,
    now: dt.datetime | float | int,
) -> frozenset[str]:
    """Return current non-disabled account owners allowed to receive one row."""

    student_id, identifier = str(sid).strip(), str(announcement_id).strip()
    current = _utc(now)
    if (
        current is None
        or not identifier
        or not student_id
        or config.public_enabled is not True
        or not config.allows_canary_sid(student_id)
        or not _visible_announcement(announcements, identifier, student_id, current)
        or not isinstance(students, list)
        or not any(isinstance(row, Mapping) and row.get("id") == student_id for row in students)
        or not isinstance(accounts, Mapping)
    ):
        return frozenset()
    allowed: set[str] = set()
    for aid, raw in accounts.items():
        if not isinstance(aid, str) or not aid or not isinstance(raw, Mapping) or raw.get("disabled") is True:
            continue
        linked = raw.get("sids")
        if isinstance(linked, list) and student_id in linked:
            allowed.add(aid)
    return frozenset(allowed)


__all__ = ["PushRolloutConfig", "eligible_push_account_ids"]
