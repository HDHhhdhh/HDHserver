"""Pure, privacy-minimized student schedule projection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Final


KST: Final = timezone(timedelta(hours=9), "KST")
MAX_RANGE_DAYS: Final = 62
WEEKDAYS: Final = "월화수목금토일"
SLOT_DEFAULTS: Final = {1: "13:00", 2: "18:00", 3: "18:00"}
KINDS: Final = frozenset({"regular", "extra", "makeup", "absence"})
STATUSES: Final = frozenset({"scheduled", "completed", "cancelled"})


def _text(value: object) -> str:
    return str(value or "").strip()


def _date(value: object) -> date | None:
    raw = _text(value)
    if len(raw) != 10: return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError: return None
    return parsed if parsed.isoformat() == raw else None


def _time_label(value: object) -> str:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*", _text(value))
    if not match: return ""
    hour, minute = int(match.group(1)), int(match.group(2))
    return f"{hour:02d}:{minute:02d}" if hour < 24 and minute < 60 else ""


def _slots(value: object) -> list[int]:
    values = value if isinstance(value, (list, tuple, set, frozenset)) else (value,)
    found: set[int] = set()
    for item in values:
        for token in re.findall(r"(?<!\d)([123])(?!\d)", _text(item)):
            found.add(int(token))
    return sorted(found)


def _sid_value(source: object, sid: str) -> object | None:
    if not isinstance(source, Mapping): return None
    for raw_sid, value in source.items():
        if _text(raw_sid) == sid:
            return value
    return None


def _has_sid(source: object, sid: str) -> bool:
    if isinstance(source, Mapping):
        value = _sid_value(source, sid)
        return value is not None and value is not False
    if isinstance(source, (list, tuple, set, frozenset)):
        return any(_text(value) == sid for value in source)
    return _text(source) == sid


def _day_value(source: object, date_key: str) -> object | None:
    if not isinstance(source, Mapping): return None
    for raw_date, value in source.items():
        if _text(raw_date) == date_key:
            return value
    return None


def _regular_plan(student: Mapping[object, object], target: date) -> tuple[list[int], dict[int, str]]:
    weekday = WEEKDAYS[target.weekday()]
    slots: set[int] = set()
    times: dict[int, str] = {}
    for raw_key, raw_value in student.items():
        match = re.fullmatch(r"day(\d+)", _text(raw_key))
        day_value = _text(raw_value)
        if not match or not day_value.startswith(weekday):
            continue
        label = _time_label(student.get(f"visitTime{match.group(1)}"))
        row_slots = _slots(day_value)
        if not row_slots:
            row_slots = [1 if not label or int(label[:2]) < 17 else 2]
        for slot in row_slots:
            slots.add(slot)
            if label and (slot not in times or label < times[slot]):
                times[slot] = label
    return sorted(slots), times


def _weekend_slots(weekend: object, date_key: str, sid: str) -> list[int]:
    return _slots(_sid_value(_day_value(weekend, date_key), sid))


def _absence(absence: object, date_key: str, sid: str) -> tuple[bool, list[int]]:
    if not isinstance(absence, Mapping): return False, []
    present = _has_sid(_day_value(absence.get("by_date"), date_key), sid)
    by_student = _sid_value(absence.get("by_student"), sid)
    present = present or _text(by_student) == date_key
    if "by_date" not in absence and "by_student" not in absence:
        present = _text(_sid_value(absence, sid)) == date_key
    day_slots = _day_value(absence.get("by_slot"), date_key)
    return present, _slots(_sid_value(day_slots, sid))


def _iter_makeup_rows(makeup: object):
    if isinstance(makeup, (list, tuple)):
        for row in makeup:
            if isinstance(row, Mapping):
                yield row, _text(row.get("studentId") or row.get("student_id") or row.get("sid"))
        return
    if not isinstance(makeup, Mapping): return
    schedules = makeup.get("schedules")
    if isinstance(schedules, (list, tuple)):
        yield from _iter_makeup_rows(schedules)
    sections: list[Mapping[object, object]] = []
    for key in ("by_absence", "manual"):
        section = makeup.get(key)
        if isinstance(section, Mapping):
            sections.append(section)
    if "by_absence" not in makeup:
        sections.append(makeup)
    for section in sections:
        for rows in section.values():
            if not isinstance(rows, Mapping):
                continue
            for raw_key, raw_row in rows.items():
                if not isinstance(raw_row, Mapping):
                    continue
                schedule = raw_row.get("scheduledMakeup") or raw_row.get("scheduled_makeup")
                if not isinstance(schedule, Mapping):
                    continue
                fallback = _text(raw_row.get("sid")) or _text(raw_key).split("|", 1)[0]
                yield schedule, fallback


def scheduled_makeup_student_ids(makeup: object, *, date_key: str) -> set[str]:
    """Return students with an active makeup reservation on one real date."""
    target = _date(date_key)
    if target is None:
        return set()

    student_ids: set[str] = set()
    for raw, fallback_sid in _iter_makeup_rows(makeup):
        row_sid = _text(raw.get("studentId") or raw.get("student_id")) or fallback_sid
        raw_date = _text(raw.get("makeupDate") or raw.get("makeup_date")).split("T", 1)[0]
        status = _text(raw.get("status") or "scheduled").lower()
        if status not in STATUSES:
            status = "scheduled"
        if row_sid and _date(raw_date) == target and status == "scheduled":
            student_ids.add(row_sid)
    return student_ids


def effective_attendance_student_ids(
    students: object,
    *,
    date_key: str,
    absence: object = None,
    extra: object = None,
    makeup: object = None,
) -> set[str]:
    """Return the exact-date regular/extra/active-makeup roster after absences."""
    target = _date(date_key)
    if target is None or isinstance(students, (str, bytes, Mapping)) or not isinstance(students, Iterable):
        return set()

    extra_rows = _day_value(extra, date_key)
    makeup_ids = scheduled_makeup_student_ids(makeup, date_key=date_key)
    roster: set[str] = set()
    for student in students:
        if not isinstance(student, Mapping):
            continue
        sid = _text(student.get("id"))
        if not sid:
            continue
        is_absent, _ = _absence(absence, date_key, sid)
        regular_slots, _ = _regular_plan(student, target)
        if not is_absent and (regular_slots or _has_sid(extra_rows, sid) or sid in makeup_ids):
            roster.add(sid)
    return roster


def _makeup(makeup: object, target: date, sid: str) -> tuple[str, list[int]] | None:
    chosen_status = ""
    chosen_slots: set[int] = set()
    rank = {"completed": 1, "scheduled": 2, "cancelled": 3}
    for raw, fallback_sid in _iter_makeup_rows(makeup):
        row_sid = _text(raw.get("studentId") or raw.get("student_id")) or fallback_sid
        raw_date = _text(raw.get("makeupDate") or raw.get("makeup_date")).split("T", 1)[0]
        if row_sid != sid or _date(raw_date) != target:
            continue
        status = _text(raw.get("status") or "scheduled").lower()
        status = status if status in rank else "scheduled"
        row_slots = _slots(
            raw.get("makeupTimes") or raw.get("makeup_times") or raw.get("slots") or raw.get("slot")
        ) or [1]
        if rank[status] > rank.get(chosen_status, 0):
            chosen_status, chosen_slots = status, set(row_slots)
        elif status == chosen_status:
            chosen_slots.update(row_slots)
    return (chosen_status, sorted(chosen_slots)) if chosen_status else None


def _event(kind: str, status: str, target: date, slots: Iterable[int],
           paired_times: Mapping[int, str] | None = None) -> dict[str, object]:
    normalized_slots = sorted({slot for slot in slots if slot in SLOT_DEFAULTS}) or [1]
    times = paired_times or {}
    labels = [_time_label(times.get(slot)) or SLOT_DEFAULTS[slot] for slot in normalized_slots]
    label = min(labels)
    hour, minute = map(int, label.split(":"))
    start = datetime.combine(target, time(hour, minute), tzinfo=KST)
    return {"kind": kind, "status": status, "date": target.isoformat(),
            "startAt": start.isoformat(timespec="seconds"), "timeLabel": label,
            "slots": normalized_slots}


def project_student_schedule(student: object, *, sid: str, start_date: str, end_date: str,
                             absence: object = None, extra: object = None,
                             weekend: object = None, makeup: object = None) -> list[dict[str, object]]:
    """Return at most one priority-resolved, SID-free schedule row per date."""
    start, end, target_sid = _date(start_date), _date(end_date), _text(sid)
    student_map = student if isinstance(student, Mapping) else {}
    student_sid = _text(student_map.get("id"))
    if not start or not end or not target_sid or end < start or (end - start).days >= MAX_RANGE_DAYS:
        return []
    if student_sid != target_sid: return []

    rows: list[dict[str, object]] = []
    for offset in range((end - start).days + 1):
        target = start + timedelta(days=offset)
        date_key = target.isoformat()
        regular_slots, paired_times = _regular_plan(student_map, target)
        override_slots = _weekend_slots(weekend, date_key, target_sid)
        is_absent, absent_slots = _absence(absence, date_key, target_sid)
        makeup_row = _makeup(makeup, target, target_sid)
        is_extra = _has_sid(_day_value(extra, date_key), target_sid)
        if is_absent:
            rows.append(_event("absence", "cancelled", target, absent_slots or override_slots or regular_slots, paired_times))
        elif makeup_row:
            rows.append(_event("makeup", makeup_row[0], target, makeup_row[1], paired_times))
        elif is_extra:
            rows.append(_event("extra", "scheduled", target, override_slots or regular_slots, paired_times))
        elif regular_slots:
            rows.append(_event("regular", "scheduled", target, override_slots or regular_slots, paired_times))
    return rows


def _instant(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = _text(value)
        if _date(raw):
            parsed = datetime.combine(date.fromisoformat(raw), time.min, tzinfo=KST)
        else:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError: return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def select_next_schedule(schedule: object, *, as_of: str) -> dict[str, object] | None:
    """Select the next row; today's cancellation remains visible."""
    reference = _instant(as_of)
    if reference is None or isinstance(schedule, (str, bytes, Mapping)) or not isinstance(schedule, Iterable):
        return None
    candidates: list[tuple[date, int, datetime, dict[str, object]]] = []
    priority = {"regular": 1, "extra": 2, "makeup": 3, "absence": 4}
    for raw in schedule:
        if not isinstance(raw, Mapping):
            continue
        kind, status = _text(raw.get("kind")), _text(raw.get("status"))
        target, start = _date(raw.get("date")), _instant(raw.get("startAt"))
        if kind not in KINDS or status not in STATUSES or status == "completed" or not target or not start or start.date() != target:
            continue
        if status != "cancelled" and start < reference:
            continue
        if status == "cancelled" and target < reference.date():
            continue
        public = _event(kind, status, target, _slots(raw.get("slots")), {1: raw.get("timeLabel"), 2: raw.get("timeLabel"), 3: raw.get("timeLabel")})
        event_priority = 4 if status == "cancelled" else priority[kind]
        candidates.append((target, -event_priority, start, public))
    return min(candidates, default=(None, 0, None, None), key=lambda item: item[:3])[3]


build_student_schedule_projection = project_student_schedule

__all__ = [
    "MAX_RANGE_DAYS",
    "build_student_schedule_projection",
    "effective_attendance_student_ids",
    "project_student_schedule",
    "scheduled_makeup_student_ids",
    "select_next_schedule",
]
