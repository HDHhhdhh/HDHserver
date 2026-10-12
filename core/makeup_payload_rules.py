"""Pure legacy makeup payload, reservation, manual-row and revision rules."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Dict


def makeup_revision(payload: Any) -> str:
    normalized = normalize_makeup_payload(payload)
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_makeup_date(value: Any) -> str:
    text = str(value or "").split("T")[0].strip()
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        return ""
    return text


def normalize_makeup_sid(value: Any) -> str:
    return str(value or "").strip()


def normalize_makeup_slots(value: Any) -> list[int]:
    values = value if isinstance(value, list) else [value]
    out: list[int] = []
    seen = set()
    for item in values:
        try:
            slot = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if slot not in (1, 2) or slot in seen:
            continue
        seen.add(slot)
        out.append(slot)
    out.sort()
    return out


def normalize_makeup_schedule(
    raw: Any,
    *,
    fallback_original_absence_id: str = "",
    fallback_student_id: str = "",
) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    original_absence_id = str(
        raw.get("originalAbsenceId")
        or raw.get("original_absence_id")
        or fallback_original_absence_id
        or ""
    ).strip()
    student_id = str(raw.get("studentId") or raw.get("student_id") or fallback_student_id or "").strip()
    makeup_date = normalize_makeup_date(raw.get("makeupDate") or raw.get("makeup_date"))
    status = str(raw.get("status") or "scheduled").strip().lower()
    if status not in {"scheduled", "completed", "cancelled"}:
        status = "scheduled"
    makeup_times = normalize_makeup_slots(
        raw.get("makeupTimes")
        or raw.get("makeup_times")
        or raw.get("ownedSlots")
        or raw.get("owned_slots")
        or raw.get("slots")
        or raw.get("slot")
    )
    if not makeup_times:
        makeup_times = [1]
    if not original_absence_id or not student_id:
        return None
    if status == "scheduled" and not makeup_date:
        return None
    schedule: Dict[str, Any] = {
        "originalAbsenceId": original_absence_id,
        "studentId": student_id,
        "makeupDate": makeup_date,
        "makeupTimes": makeup_times,
        "status": status,
        "createdAt": str(raw.get("createdAt") or raw.get("created_at") or "").strip(),
        "updatedAt": str(raw.get("updatedAt") or raw.get("updated_at") or "").strip(),
    }
    created_by = str(raw.get("createdBy") or raw.get("created_by") or "").strip()
    if created_by:
        schedule["createdBy"] = created_by
    schedule["ownedExtra"] = bool(raw.get("ownedExtra") or raw.get("owned_extra"))
    owned_slots = normalize_makeup_slots(raw.get("ownedSlots") or raw.get("owned_slots"))
    if owned_slots:
        schedule["ownedSlots"] = owned_slots
    return schedule


def normalize_manual_makeups(raw: Any) -> Dict[str, Dict[str, Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for date_raw, rows_raw in raw.items():
        date_key = normalize_makeup_date(date_raw)
        if not date_key or not isinstance(rows_raw, dict):
            continue
        rows: Dict[str, Dict[str, Any]] = {}
        for key_raw, value in rows_raw.items():
            key = str(key_raw or "").strip()
            if not key or value is False or value is None:
                continue
            row = value if isinstance(value, dict) else {}
            sid = normalize_makeup_sid(row.get("sid"))
            if not sid:
                continue
            date_only = bool(row.get("dateOnly") or row.get("date_only") or row.get("slotless"))
            slots = normalize_makeup_slots(row.get("slots", row.get("slot")))
            if not slots and not date_only:
                slots = [1]
            normalized_row: Dict[str, Any] = {
                "sid": sid,
                "slots": [] if date_only else slots,
                "dateOnly": date_only,
                "state": str(row.get("state") or "").strip(),
                "createdAt": str(row.get("createdAt") or "").strip(),
                "updatedAt": str(row.get("updatedAt") or "").strip(),
                "note": str(row.get("note") or "").strip(),
                "course": str(row.get("course") or "").strip(),
            }
            schedule = normalize_makeup_schedule(
                row.get("scheduledMakeup") or row.get("scheduled_makeup"),
                fallback_original_absence_id=f"manual|{date_key}|{key}",
                fallback_student_id=sid,
            )
            if schedule:
                normalized_row["scheduledMakeup"] = schedule
            # An explicit deletion must continue to suppress legacy note reservations.
            if row.get("scheduledMakeup", row.get("scheduled_makeup", False)) is None:
                normalized_row["scheduledMakeup"] = None
            rows[key] = normalized_row
        if rows:
            out[date_key] = rows
    return out


def normalize_makeup_payload(raw: Any) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    by_absence = source.get("by_absence")
    if not isinstance(by_absence, dict):
        by_absence = source

    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for date_raw, sid_map in by_absence.items():
        date_key = normalize_makeup_date(date_raw)
        if not date_key or not isinstance(sid_map, dict):
            continue
        rows: Dict[str, Dict[str, Any]] = {}
        for sid_raw, value in sid_map.items():
            sid = normalize_makeup_sid(sid_raw)
            if not sid:
                continue
            if value is False or value is None:
                continue
            row = value if isinstance(value, dict) else {}
            state = str(row.get("state") or "").strip().lower()
            if state not in {"open", "carried", "self-study"}:
                state = "carried"
            normalized_row: Dict[str, Any] = {
                "state": state,
                "updatedAt": str(row.get("updatedAt") or "").strip(),
                "note": str(row.get("note") or "").strip(),
            }
            student_id = sid.split("|", 1)[0].strip()
            schedule = normalize_makeup_schedule(
                row.get("scheduledMakeup") or row.get("scheduled_makeup"),
                fallback_original_absence_id=f"absence|{date_key}|{sid}",
                fallback_student_id=student_id,
            )
            if schedule:
                normalized_row["scheduledMakeup"] = schedule
            # An explicit deletion must continue to suppress legacy note reservations.
            if row.get("scheduledMakeup", row.get("scheduled_makeup", False)) is None:
                normalized_row["scheduledMakeup"] = None
            rows[sid] = normalized_row
        if rows:
            out[date_key] = rows

    return {
        "by_absence": out,
        "manual": normalize_manual_makeups(source.get("manual")),
    }


def makeup_student_ids(raw: Any) -> set[str]:
    """Collect only normalized student identifiers affected by makeup rows."""
    normalized = normalize_makeup_payload(raw)
    out: set[str] = set()
    for rows in normalized.get("by_absence", {}).values():
        if not isinstance(rows, dict):
            continue
        for key, row in rows.items():
            sid = str(key or "").split("|", 1)[0].strip()
            if sid:
                out.add(sid)
            schedule = row.get("scheduledMakeup") if isinstance(row, dict) else None
            scheduled_sid = str(schedule.get("studentId") or "").strip() if isinstance(schedule, dict) else ""
            if scheduled_sid:
                out.add(scheduled_sid)
    for rows in normalized.get("manual", {}).values():
        if not isinstance(rows, dict):
            continue
        for row in rows.values():
            if not isinstance(row, dict):
                continue
            sid = str(row.get("sid") or "").strip()
            if sid:
                out.add(sid)
            schedule = row.get("scheduledMakeup")
            scheduled_sid = str(schedule.get("studentId") or "").strip() if isinstance(schedule, dict) else ""
            if scheduled_sid:
                out.add(scheduled_sid)
    return out


__all__ = [
    "normalize_makeup_date",
    "normalize_makeup_sid",
    "normalize_makeup_slots",
    "normalize_makeup_schedule",
    "normalize_manual_makeups",
    "normalize_makeup_payload",
    "makeup_student_ids",
    "makeup_revision",
]
