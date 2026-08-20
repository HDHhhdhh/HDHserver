"""Pure KST reminder candidate projection for class and homework events."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Final

from core.student_notification_events import NotificationEvent, NotificationInputError, build_event


KST: Final = dt.timezone(dt.timedelta(hours=9), "KST")
CLASS_LEAD_SECONDS: Final = 2 * 60 * 60
HOMEWORK_LEAD_SECONDS: Final = 24 * 60 * 60
DEFAULT_WINDOW_SECONDS: Final = 5 * 60
MAX_CANDIDATES: Final = 500
_CLASS_KINDS: Final = frozenset({"regular", "extra", "makeup"})


def _now(value: object) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None:
        raise NotificationInputError(message="KST-aware clock is required")
    if value.utcoffset() != dt.timedelta(hours=9):
        raise NotificationInputError(message="clock must use KST")
    return value.replace(microsecond=0)


def _instant(value: object) -> dt.datetime | None:
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(hours=9):
        return None
    return parsed.replace(microsecond=0)


def _rows(value: object) -> Iterable[Mapping[object, object]]:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
        for row in value:
            if isinstance(row, Mapping):
                yield row


def _window(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3600:
        raise NotificationInputError(message="reminder window is invalid")
    return value


def _sid(value: object) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text or len(text) > 128:
        raise NotificationInputError(message="sid is invalid")
    return text


def _slots(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    found = sorted({item for item in value if isinstance(item, int) and not isinstance(item, bool) and item in {1, 2, 3}})
    return tuple(found)


def _candidate(
    event_type: str,
    sid: str,
    identity: tuple[object, ...],
    target: dt.datetime,
    lead_seconds: int,
    current: dt.datetime,
) -> NotificationEvent:
    reminder_at = target - dt.timedelta(seconds=lead_seconds)
    scheduled = max(current, reminder_at)
    return build_event(event_type, sid, identity, scheduled.timestamp())


def class_reminder_candidates(
    sid: object,
    schedule: object,
    *,
    now: dt.datetime,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> list[NotificationEvent]:
    student_id, current, window = _sid(sid), _now(now), _window(window_seconds)
    candidates: list[NotificationEvent] = []
    for row in _rows(schedule):
        kind = str(row.get("kind") or "").strip()
        status = str(row.get("status") or "").strip()
        start = _instant(row.get("startAt") or row.get("start_at"))
        if kind not in _CLASS_KINDS or status != "scheduled" or start is None:
            continue
        seconds_until = (start - current).total_seconds()
        if not 0 < seconds_until <= CLASS_LEAD_SECONDS + window:
            continue
        slots = _slots(row.get("slots"))
        date_key = str(row.get("date") or start.date().isoformat()).strip()
        candidates.append(_candidate(
            "class_reminder", student_id,
            (student_id, kind, date_key, start.isoformat(timespec="seconds"), ",".join(map(str, slots))),
            start, CLASS_LEAD_SECONDS, current,
        ))
    return candidates


def homework_due_candidates(
    sid: object,
    assignments: object,
    *,
    now: dt.datetime,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> list[NotificationEvent]:
    student_id, current, window = _sid(sid), _now(now), _window(window_seconds)
    candidates: list[NotificationEvent] = []
    for row in _rows(assignments):
        row_sid = str(row.get("sid") or student_id).strip()
        status = str(row.get("status") or "").strip()
        assignment_id = str(row.get("id") or row.get("assignmentId") or "").strip()
        due = _instant(row.get("due_at") or row.get("dueAt"))
        if row_sid != student_id or status != "assigned" or not assignment_id or due is None:
            continue
        seconds_until = (due - current).total_seconds()
        if not 0 < seconds_until <= HOMEWORK_LEAD_SECONDS + window:
            continue
        candidates.append(_candidate(
            "homework_due", student_id,
            (assignment_id, due.isoformat(timespec="seconds")),
            due, HOMEWORK_LEAD_SECONDS, current,
        ))
    return candidates


def build_reminder_candidates(
    *,
    sid: object,
    schedule: object,
    homework: object,
    now: dt.datetime,
    max_events: int = MAX_CANDIDATES,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> list[NotificationEvent]:
    if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= MAX_CANDIDATES:
        raise NotificationInputError(message="candidate limit is invalid")
    rows = class_reminder_candidates(sid, schedule, now=now, window_seconds=window_seconds)
    rows.extend(homework_due_candidates(sid, homework, now=now, window_seconds=window_seconds))
    unique = {(row["event_type"], row["event_id"], row["sid"]): row for row in rows}
    return sorted(unique.values(), key=lambda row: (row["scheduled_at"], row["event_type"], row["event_id"]))[:max_events]


__all__ = [
    "CLASS_LEAD_SECONDS", "DEFAULT_WINDOW_SECONDS", "HOMEWORK_LEAD_SECONDS", "KST",
    "MAX_CANDIDATES", "build_reminder_candidates", "class_reminder_candidates",
    "homework_due_candidates",
]
