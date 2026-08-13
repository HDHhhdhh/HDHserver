"""Pure event identity, category, payload, and milestone contracts."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, TypedDict


CATEGORIES: Final = frozenset({"schedule", "homework", "progress", "announcement"})
EVENT_CATEGORY: Final = {
    "class_reminder": "schedule",
    "schedule_changed": "schedule",
    "homework_assigned": "homework",
    "homework_due": "homework",
    "progress_milestone": "progress",
    "announcement_published": "announcement",
}
EVENT_TYPES: Final = frozenset(EVENT_CATEGORY)
MILESTONES: Final = (25, 50, 75, 100)
DEFAULT_PREFERENCES: Final = {category: True for category in sorted(CATEGORIES)}
_EVENT_ID_RE: Final = re.compile(r"^evt_[A-Za-z0-9_-]{32}$")


@dataclass(frozen=True, slots=True)
class NotificationInputError(ValueError):
    code: str = "invalid_notification"
    message: str = "invalid notification input"

    def __str__(self) -> str:
        return self.message


class NotificationEvent(TypedDict):
    event_type: str
    event_id: str
    sid: str
    scheduled_at: float


def _type(value: object) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if text not in EVENT_TYPES:
        raise NotificationInputError(message="unsupported event type")
    return text


def valid_event_id(value: object) -> bool:
    return isinstance(value, str) and _EVENT_ID_RE.fullmatch(value) is not None


def event_category(event_type: object) -> str:
    return EVENT_CATEGORY[_type(event_type)]


def deterministic_event_id(event_type: object, *identity_parts: object) -> str:
    """Return a stable opaque ID without exposing any identity part."""

    selected = _type(event_type)
    if not identity_parts:
        raise NotificationInputError(message="event identity is required")
    normalized: list[str] = []
    for part in identity_parts:
        if isinstance(part, bool) or not isinstance(part, (str, int, float)):
            raise NotificationInputError(message="event identity is invalid")
        if isinstance(part, float) and not math.isfinite(part):
            raise NotificationInputError(message="event identity is invalid")
        text = str(part).strip()
        if not text or len(text) > 2048:
            raise NotificationInputError(message="event identity is invalid")
        normalized.append(text)
    encoded = json.dumps([selected, *normalized], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = base64.urlsafe_b64encode(hashlib.sha256(encoded).digest()[:24]).decode("ascii").rstrip("=")
    return f"evt_{digest}"


def build_event_payload(event_type: object, event_id: object) -> dict[str, str]:
    selected = _type(event_type)
    if not valid_event_id(event_id):
        raise NotificationInputError(message="event id is invalid")
    category = EVENT_CATEGORY[selected]
    if category in {"schedule", "progress"}:
        url = "/app?view=home"
    else:
        view = "homework" if category == "homework" else "board"
        url = f"/app?view={view}&item={event_id}"
    return {"type": selected, "eventId": str(event_id), "url": url}


def serialize_event_payload(event_type: object, event_id: object) -> str:
    return json.dumps(build_event_payload(event_type, event_id), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def build_event(
    event_type: object,
    sid: object,
    identity_parts: Iterable[object],
    scheduled_at: object,
) -> NotificationEvent:
    student_id = sid.strip() if isinstance(sid, str) else ""
    if not student_id or len(student_id) > 128 or any(ord(char) < 32 for char in student_id):
        raise NotificationInputError(message="sid is invalid")
    if isinstance(identity_parts, (str, bytes, bytearray, Mapping)):
        raise NotificationInputError(message="event identity is invalid")
    try:
        when = float(scheduled_at)
    except (TypeError, ValueError, OverflowError) as exc:
        raise NotificationInputError(message="scheduled time is invalid") from exc
    if not math.isfinite(when) or when < 0:
        raise NotificationInputError(message="scheduled time is invalid")
    selected = _type(event_type)
    return {
        "event_type": selected,
        "event_id": deterministic_event_id(selected, *tuple(identity_parts)),
        "sid": student_id,
        "scheduled_at": when,
    }


def normalize_preferences(value: object) -> dict[str, bool]:
    if not isinstance(value, Mapping) or set(value) != CATEGORIES:
        raise NotificationInputError(message="preference snapshot is incomplete")
    if any(type(value[category]) is not bool for category in CATEGORIES):
        raise NotificationInputError(message="preference value is invalid")
    return {category: bool(value[category]) for category in sorted(CATEGORIES)}


def milestones_crossed(previous_percent: object, current_percent: object) -> tuple[int, ...]:
    before = 0 if previous_percent is None else previous_percent
    after = current_percent
    if isinstance(before, bool) or isinstance(after, bool) or not isinstance(before, int) or not isinstance(after, int):
        return ()
    if not 0 <= before <= 100 or not 0 <= after <= 100 or after <= before:
        return ()
    return tuple(milestone for milestone in MILESTONES if before < milestone <= after)


__all__ = [
    "CATEGORIES", "DEFAULT_PREFERENCES", "EVENT_CATEGORY", "EVENT_TYPES", "MILESTONES",
    "NotificationEvent", "NotificationInputError", "build_event", "build_event_payload",
    "deterministic_event_id", "event_category", "milestones_crossed", "normalize_preferences",
    "serialize_event_payload", "valid_event_id",
]
