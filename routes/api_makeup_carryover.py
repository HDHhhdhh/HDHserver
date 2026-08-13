from __future__ import annotations

import datetime as dt
from typing import Any, Dict

from flask import Blueprint, abort, jsonify, request

from core.makeup_sheet_sync import sync_makeups_from_sheet
from core.paths import BASE
from core.student_notification_hooks import enqueue_current_schedule_changes
from core.storage import load, save_atomic, file_lock

bp_api_makeup_carryover = Blueprint("api_makeup_carryover", __name__)

MAKEUP_CARRYOVER_PATH = BASE / "makeup_carryover.json"


def _norm_date(value: Any) -> str:
    text = str(value or "").split("T")[0].strip()
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        return ""
    return text


def _norm_sid(value: Any) -> str:
    return str(value or "").strip()


def _norm_slot_list(value: Any) -> list[int]:
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


def _normalize_schedule(
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
    makeup_date = _norm_date(raw.get("makeupDate") or raw.get("makeup_date"))
    status = str(raw.get("status") or "scheduled").strip().lower()
    if status not in {"scheduled", "completed", "cancelled"}:
        status = "scheduled"
    makeup_times = _norm_slot_list(
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
    owned_slots = _norm_slot_list(raw.get("ownedSlots") or raw.get("owned_slots"))
    if owned_slots:
        schedule["ownedSlots"] = owned_slots
    return schedule


def _normalize_manual(raw: Any) -> Dict[str, Dict[str, Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for date_raw, rows_raw in raw.items():
        date_key = _norm_date(date_raw)
        if not date_key or not isinstance(rows_raw, dict):
            continue
        rows: Dict[str, Dict[str, Any]] = {}
        for key_raw, value in rows_raw.items():
            key = str(key_raw or "").strip()
            if not key or value is False or value is None:
                continue
            row = value if isinstance(value, dict) else {}
            sid = _norm_sid(row.get("sid"))
            if not sid:
                continue
            date_only = bool(row.get("dateOnly") or row.get("date_only") or row.get("slotless"))
            slots = _norm_slot_list(row.get("slots", row.get("slot")))
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
            schedule = _normalize_schedule(
                row.get("scheduledMakeup") or row.get("scheduled_makeup"),
                fallback_original_absence_id=f"manual|{date_key}|{key}",
                fallback_student_id=sid,
            )
            if schedule:
                normalized_row["scheduledMakeup"] = schedule
            rows[key] = normalized_row
        if rows:
            out[date_key] = rows
    return out


def _normalize_payload(raw: Any) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    by_absence = source.get("by_absence")
    if not isinstance(by_absence, dict):
        by_absence = source

    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for date_raw, sid_map in by_absence.items():
        date_key = _norm_date(date_raw)
        if not date_key or not isinstance(sid_map, dict):
            continue
        rows: Dict[str, Dict[str, Any]] = {}
        for sid_raw, value in sid_map.items():
            sid = _norm_sid(sid_raw)
            if not sid:
                continue
            if value is False or value is None:
                continue
            row = value if isinstance(value, dict) else {}
            state = str(row.get("state") or "").strip().lower()
            if state not in {"open", "carried"}:
                state = "carried"
            normalized_row: Dict[str, Any] = {
                "state": state,
                "updatedAt": str(row.get("updatedAt") or "").strip(),
                "note": str(row.get("note") or "").strip(),
            }
            student_id = sid.split("|", 1)[0].strip()
            schedule = _normalize_schedule(
                row.get("scheduledMakeup") or row.get("scheduled_makeup"),
                fallback_original_absence_id=f"absence|{date_key}|{sid}",
                fallback_student_id=student_id,
            )
            if schedule:
                normalized_row["scheduledMakeup"] = schedule
            rows[sid] = normalized_row
        if rows:
            out[date_key] = rows

    return {
        "by_absence": out,
        "manual": _normalize_manual(source.get("manual")),
    }


def _makeup_student_ids(raw: Any) -> set[str]:
    """Collect only normalized student identifiers affected by makeup rows."""
    normalized = _normalize_payload(raw)
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


@bp_api_makeup_carryover.get("/api/makeup-carryover")
def api_makeup_carryover_get():
    return jsonify(_normalize_payload(load(MAKEUP_CARRYOVER_PATH)))


@bp_api_makeup_carryover.post("/api/makeup-carryover")
def api_makeup_carryover_post():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")
    normalized = _normalize_payload(payload)
    with file_lock(MAKEUP_CARRYOVER_PATH):
        previous = _normalize_payload(load(MAKEUP_CARRYOVER_PATH))
        save_atomic(MAKEUP_CARRYOVER_PATH, normalized)
    enqueue_current_schedule_changes(_makeup_student_ids(previous) | _makeup_student_ids(normalized))
    return jsonify(normalized)


@bp_api_makeup_carryover.post("/api/makeup-sheet-sync")
def api_makeup_sheet_sync_post():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")
    sheet_url = str(payload.get("sheetUrl") or payload.get("sheet_url") or "").strip()
    date_key = _norm_date(payload.get("date") or dt.date.today().isoformat())
    if not sheet_url:
        abort(400, description="Missing sheetUrl")
    with file_lock(MAKEUP_CARRYOVER_PATH):
        current = _normalize_payload(load(MAKEUP_CARRYOVER_PATH))
        try:
            result = sync_makeups_from_sheet(sheet_url, date_key, current)
        except RuntimeError as exc:
            abort(400, description=str(exc))
        save_atomic(MAKEUP_CARRYOVER_PATH, result["carryover"])
    enqueue_current_schedule_changes(
        _makeup_student_ids(current) | _makeup_student_ids(result.get("carryover"))
    )
    return jsonify(result)
