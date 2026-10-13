from __future__ import annotations

import datetime as dt
import re

from core import log_rules
from core.student_auto_assignment_rules import student_auto_video_assign_count
from core.update_assignment_rules import sid_lookup


SELF_STUDY_DAY_FIELDS = ("day1", "day2", "day3", "day4", "day5")


def student_has_schedule_on_date(student: dict, date_key: str) -> bool:
    try:
        target = dt.date.fromisoformat(date_key)
    except ValueError:
        return False
    weekday = "월화수목금토일"[target.weekday()]
    return any(
        re.fullmatch(r"day\d+", str(key))
        and str(value or "").startswith(weekday)
        for key, value in (student or {}).items()
    )


def weekday_char_for_date(date_key: str) -> str:
    try:
        target = dt.date.fromisoformat(str(date_key or "").strip())
    except ValueError:
        return ""
    return "월화수목금토일"[target.weekday()]


def normalize_schedule_slots(raw) -> list[int]:
    values = raw if isinstance(raw, list) else [raw]
    out: list[int] = []
    seen: set[int] = set()
    for value in values:
        for token in re.findall(r"(?<!\d)([1-6])(?!\d)", str(value or "")):
            slot = int(token)
            if slot in seen:
                continue
            seen.add(slot)
            out.append(slot)
    return sorted(out)


def student_slots_for_date(
    student: dict,
    sid: str,
    date_key: str,
    weekend_slots=None,
    absent=None,
) -> list[int]:
    """Return date-specific class slots after slot absences are removed."""
    weekend = weekend_slots if isinstance(weekend_slots, dict) else {}
    day_override = weekend.get(str(date_key or ""))
    slots: list[int] = []
    if isinstance(day_override, dict):
        override_slots = normalize_schedule_slots(
            sid_lookup(day_override, sid)
        )
        if override_slots:
            slots = override_slots

    if not slots:
        weekday = weekday_char_for_date(date_key)
        if not weekday:
            return []
        for key, value in (student or {}).items():
            if not re.fullmatch(r"day\d+", str(key)):
                continue
            text = str(value or "")
            if text.startswith(weekday):
                slots.extend(normalize_schedule_slots(text))

    absent_map = absent if isinstance(absent, dict) else {}
    by_slot = absent_map.get("by_slot")
    day_absences = (
        by_slot.get(str(date_key or "")) if isinstance(by_slot, dict) else None
    )
    absent_slots = set(
        normalize_schedule_slots(sid_lookup(day_absences, sid))
        if isinstance(day_absences, dict)
        else []
    )
    return [
        slot for slot in sorted(set(slots)) if slot not in absent_slots
    ]


def has_consecutive_slots(slots) -> bool:
    ordered = sorted(
        {int(slot) for slot in (slots or []) if str(slot).isdigit()}
    )
    return any(
        right == left + 1
        for left, right in zip(ordered, ordered[1:])
    )


def effective_auto_video_assign_count(
    student: dict,
    sid: str,
    date_key: str,
    weekend_slots=None,
    absent=None,
) -> int:
    configured = student_auto_video_assign_count(student)
    slots = student_slots_for_date(
        student,
        sid,
        date_key,
        weekend_slots,
        absent,
    )
    return configured * 2 if has_consecutive_slots(slots) else configured


def student_has_scheduled_self_study_on_date(
    student: dict,
    date_key: str,
) -> bool:
    try:
        target = dt.date.fromisoformat(date_key)
    except ValueError:
        return False

    raw = student.get("selfStudyDays") if isinstance(student, dict) else None
    scheduled_fields: set[str] = set()
    if isinstance(raw, list):
        scheduled_fields = {str(field or "").strip() for field in raw}
    elif isinstance(raw, dict):
        scheduled_fields = {
            str(field or "").strip()
            for field, enabled in raw.items()
            if log_rules.truthy(enabled)
        }
    else:
        scheduled_fields = {
            field
            for field in SELF_STUDY_DAY_FIELDS
            if log_rules.truthy(student.get(f"{field}SelfStudy"))
        }

    weekday = "월화수목금토일"[target.weekday()]
    return any(
        field in scheduled_fields
        and str(student.get(field) or "").strip().startswith(weekday)
        for field in SELF_STUDY_DAY_FIELDS
    )


def student_is_self_study_on_date(
    logs: dict,
    date_key: str,
    sid: str,
    student: dict,
) -> bool:
    day_logs = logs.get(date_key) if isinstance(logs, dict) else None
    entry = sid_lookup(
        day_logs if isinstance(day_logs, dict) else {},
        sid,
    )
    if isinstance(entry, dict) and "selfStudy" in entry:
        return log_rules.truthy(entry.get("selfStudy"))
    return student_has_scheduled_self_study_on_date(student, date_key)


def log_entry_for_date(logs, date_key: str, sid: str):
    if not isinstance(logs, dict):
        return None
    day_logs = logs.get(date_key)
    if not isinstance(day_logs, dict):
        day_logs = logs
    return sid_lookup(day_logs, sid)


def student_absent_on_date(absent, date_key: str, sid: str) -> bool:
    if not isinstance(absent, dict):
        return False
    by_date = absent.get("by_date") or {}
    ids = by_date.get(date_key, []) if isinstance(by_date, dict) else []
    if str(sid) in {str(value) for value in (ids or [])}:
        return True
    by_student = absent.get("by_student") or {}
    return isinstance(by_student, dict) and str(
        sid_lookup(by_student, sid) or ""
    ) == str(date_key)


__all__ = (
    "effective_auto_video_assign_count",
    "has_consecutive_slots",
    "log_entry_for_date",
    "normalize_schedule_slots",
    "student_absent_on_date",
    "student_has_schedule_on_date",
    "student_has_scheduled_self_study_on_date",
    "student_is_self_study_on_date",
    "student_slots_for_date",
    "weekday_char_for_date",
)
