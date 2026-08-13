"""Pure focus-session eligibility, validation, and privacy-safe projections."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Final


KST: Final = timezone(timedelta(hours=9), "KST")
CLASS_SECONDS: Final = 120 * 60
EARLY_START_SECONDS: Final = 30 * 60
STALE_GRACE_SECONDS: Final = 15 * 60
MAX_BATCH_EVENTS: Final = 50
MAX_SESSION_EVENTS: Final = 2_000
KINDS: Final = frozenset({"regular", "extra", "makeup"})
EVENT_TYPES: Final = frozenset({"hidden", "visible", "unknown"})
_SESSION_RE: Final = re.compile(r"^fcs_[A-Za-z0-9_-]{24,64}$")


class FocusInputError(ValueError):
    code = "invalid_request"

    def __init__(self, code: str = "invalid_request", message: str = "focus input is invalid"):
        super().__init__(message)
        self.code = code


class FocusConflictError(RuntimeError):
    def __init__(self, code: str, message: str = "focus state conflicts"):
        super().__init__(message)
        self.code = code


class FocusSessionNotFoundError(LookupError):
    code = "focus_session_not_found"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _instant(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return datetime.fromtimestamp(float(value), tz=KST)
    else:
        raw = _text(value)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(KST)


def epoch(value: object) -> float:
    parsed = _instant(value)
    if parsed is None:
        raise FocusInputError(message="focus timestamp is invalid")
    return parsed.timestamp()


def kst_iso(value: object) -> str:
    parsed = _instant(value)
    if parsed is None:
        raise FocusInputError(message="focus timestamp is invalid")
    return parsed.isoformat(timespec="seconds")


def _slots(value: object) -> list[int]:
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        return []
    slots = sorted({item for item in value if type(item) is int and item in {1, 2, 3}})
    return slots if len(slots) == len(value) and len(slots) <= 3 else []


def schedule_key(sid: object, row: Mapping[str, object]) -> str:
    target_sid = _text(sid)
    if not target_sid:
        raise FocusInputError(message="focus SID is invalid")
    canonical = json.dumps(
        [target_sid, row["kind"], row["date"], row["startAt"], row["slots"]],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).digest()[:18]
    return "fse_" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def class_key(row: Mapping[str, object]) -> str:
    """Return an opaque SID-independent key for one scheduled class window."""
    kind, date_key = _text(row.get("kind")), _text(row.get("date"))
    start, end, slots = _instant(row.get("startAt")), _instant(row.get("endAt")), _slots(row.get("slots"))
    if kind not in KINDS or start is None or end is None or end <= start or not slots:
        raise FocusInputError(message="focus class schedule is invalid")
    if start.date().isoformat() != date_key:
        raise FocusInputError(message="focus class date is invalid")
    canonical = json.dumps(
        [kind, date_key, start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"), slots],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).digest()[:18]
    return "fcl_" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def normalize_schedule(row: object, *, sid: object) -> dict[str, object] | None:
    if not isinstance(row, Mapping):
        return None
    kind, status = _text(row.get("kind")), _text(row.get("status"))
    date_key, label = _text(row.get("date")), _text(row.get("timeLabel"))
    start, slots = _instant(row.get("startAt")), _slots(row.get("slots"))
    if kind not in KINDS or status != "scheduled" or start is None or not slots:
        return None
    if start.date().isoformat() != date_key or not re.fullmatch(r"\d{2}:\d{2}", label):
        return None
    public = {
        "kind": kind,
        "date": date_key,
        "startAt": start.isoformat(timespec="seconds"),
        "endAt": (start + timedelta(seconds=CLASS_SECONDS)).isoformat(timespec="seconds"),
        "timeLabel": label,
        "slots": slots,
    }
    return {
        **public,
        "scheduleKey": schedule_key(sid, public),
        "startEpoch": start.timestamp(),
        "endEpoch": start.timestamp() + CLASS_SECONDS,
    }


def public_schedule(row: Mapping[str, object] | None) -> dict[str, object] | None:
    if not isinstance(row, Mapping):
        return None
    keys = ("kind", "date", "startAt", "endAt", "timeLabel", "slots")
    return {key: list(row[key]) if key == "slots" else row[key] for key in keys}


def select_eligibility(schedule: object, *, sid: object, now: object) -> dict[str, object]:
    current = epoch(now)
    values = schedule if isinstance(schedule, Iterable) and not isinstance(schedule, (str, bytes, Mapping)) else ()
    rows = [normalized for raw in values if (normalized := normalize_schedule(raw, sid=sid)) is not None]
    rows.sort(key=lambda item: (float(item["startEpoch"]), str(item["scheduleKey"])))
    eligible = [row for row in rows if float(row["startEpoch"]) - EARLY_START_SECONDS <= current < float(row["endEpoch"])]
    selected = eligible[0] if eligible else next((row for row in rows if float(row["startEpoch"]) > current), None)
    state = "eligible" if eligible else "upcoming" if selected is not None else "unavailable"
    return {
        "state": state,
        "schedule": selected,
        "opensAt": kst_iso(float(selected["startEpoch"]) - EARLY_START_SECONDS) if selected else None,
        "closesAt": kst_iso(selected["endEpoch"]) if selected else None,
    }


def session_id(value: object) -> str:
    text = _text(value)
    if not _SESSION_RE.fullmatch(text):
        raise FocusInputError(message="focus session ID is invalid")
    return text


def event_batch(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise FocusInputError(message="focus events must be an array")
    if not value or len(value) > MAX_BATCH_EVENTS:
        code = "focus_event_limit" if len(value) > MAX_BATCH_EVENTS else "invalid_request"
        raise FocusInputError(code, "focus event batch size is invalid")
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"seq", "type"}:
            raise FocusInputError(message="focus event fields are invalid")
        seq, event_type = item.get("seq"), _text(item.get("type"))
        if type(seq) is not int or seq < 1 or event_type not in EVENT_TYPES:
            raise FocusInputError(message="focus event is invalid")
        result.append({"seq": seq, "type": event_type})
    return result


def session_summary(row: Mapping[str, object], *, now: object) -> dict[str, object]:
    current = epoch(now)
    visible_ms, hidden_ms = int(row["visible_ms"]), int(row["hidden_ms"])
    longest_ms, unknown_ms = int(row["longest_hidden_ms"]), int(row["unknown_ms"])
    state, visibility = str(row["state"]), str(row["visibility_state"])
    segment_start, schedule_end = float(row["segment_started_at"]), float(row["schedule_end_at"])
    preview_end = min(current, schedule_end)
    delta_ms = max(0, round((preview_end - segment_start) * 1000)) if state == "active" else 0
    projected_state = state
    if state == "active" and current >= schedule_end + STALE_GRACE_SECONDS:
        unknown_ms += delta_ms
        projected_state, visibility = "unknown", "unknown"
    elif state == "active" and visibility == "visible":
        visible_ms += delta_ms
    elif state == "active" and visibility == "hidden":
        hidden_ms += delta_ms
        longest_ms = max(longest_ms, delta_ms)
    elif state == "active":
        unknown_ms += delta_ms
    schedule = {
        "kind": row["schedule_kind"], "date": row["schedule_date"],
        "startAt": kst_iso(row["schedule_start_at"]), "endAt": kst_iso(row["schedule_end_at"]),
        "timeLabel": row["schedule_time_label"], "slots": json.loads(str(row["schedule_slots_json"])),
    }
    return {
        "id": row["id"], "state": projected_state, "startedAt": kst_iso(row["started_at"]),
        "endedAt": kst_iso(row["ended_at"]) if row["ended_at"] is not None else None,
        "lastSeq": int(row["last_seq"]), "visibility": visibility, "focusMs": visible_ms,
        "hiddenCount": int(row["hidden_count"]), "hiddenMs": hidden_ms,
        "longestHiddenMs": longest_ms, "unknownMs": unknown_ms, "schedule": schedule,
    }


__all__ = (
    "CLASS_SECONDS", "EARLY_START_SECONDS", "EVENT_TYPES", "FocusConflictError",
    "FocusInputError", "FocusSessionNotFoundError", "MAX_BATCH_EVENTS", "MAX_SESSION_EVENTS",
    "STALE_GRACE_SECONDS", "class_key", "event_batch", "kst_iso", "normalize_schedule", "public_schedule",
    "schedule_key", "select_eligibility", "session_id", "session_summary",
)
