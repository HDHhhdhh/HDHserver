from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Dict

from flask import Blueprint, abort, jsonify, request

from core.absent import load_absent
from core.makeup_sheet_sync import (
    build_additive_sheet_sync_result,
    partition_excluded_sheet_candidates,
    read_additive_sheet_candidate_window,
)
from core.paths import ABS_PATH, BASE, PRG_PATH, UPD_PATH
from core.student_notification_hooks import enqueue_current_schedule_changes
from core.storage import load, save_atomic, file_lock
from routes.absence_assignment_cleanup import (
    AbsenceRecoveryRequiredError,
    absence_write_scope,
    commit_new_absences_locked,
)

bp_api_makeup_carryover = Blueprint("api_makeup_carryover", __name__)

MAKEUP_CARRYOVER_PATH = BASE / "makeup_carryover.json"
MAKEUP_SHEET_SYNC_CONFIG_PATH = BASE / "instance" / "makeup_sheet_sync.json"
KST = dt.timezone(dt.timedelta(hours=9))


def _load_sheet_sync_config() -> dict[str, Any]:
    try:
        raw = json.loads(MAKEUP_SHEET_SYNC_CONFIG_PATH.read_text("utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("서버 시트 설정을 읽지 못했습니다.") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("서버 시트 설정 형식이 올바르지 않습니다.")
    return raw


def _validate_sheet_url(value: Any) -> str:
    sheet_url = str(value or "").strip()
    if "docs.google.com/spreadsheets/d/" not in sheet_url:
        raise RuntimeError("Google Sheets 링크가 올바르지 않습니다.")
    return sheet_url


def _configured_sheet_url() -> str:
    raw = _load_sheet_sync_config()
    sheet_url = str(raw.get("sheetUrl") or "").strip()
    return _validate_sheet_url(sheet_url) if sheet_url else ""


def _sheet_sync_url(payload: dict[str, Any]) -> tuple[str, str]:
    configured = _configured_sheet_url()
    if configured:
        return configured, "server-config"
    requested = str(payload.get("sheetUrl") or payload.get("sheet_url") or "").strip()
    if requested:
        return _validate_sheet_url(requested), "request"
    raise RuntimeError("서버에 동기화할 Google Sheets 링크가 설정되지 않았습니다.")


def _sheet_sync_exclusions() -> list[dict[str, Any]]:
    raw = _load_sheet_sync_config().get("excludedCandidates")
    return raw if isinstance(raw, list) else []


def _sheet_sync_date(value: Any, *, today: dt.date | None = None) -> str:
    date_key = _norm_date(value)
    if not date_key:
        raise RuntimeError("동기화 기준 날짜가 올바르지 않습니다.")
    target = dt.date.fromisoformat(date_key)
    current = today or dt.datetime.now(KST).date()
    if target < current - dt.timedelta(days=400) or target > current + dt.timedelta(days=62):
        raise RuntimeError("시트 동기화 기준 날짜가 현재 운영 범위를 벗어났습니다.")
    return date_key

def _makeup_revision(payload: Any) -> str:
    normalized = _normalize_payload(payload)
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _makeup_response(
    payload: Any,
    status: int = 200,
    *,
    revision_payload: Any | None = None,
):
    response = jsonify(payload)
    response.status_code = status
    revision = _makeup_revision(payload if revision_payload is None else revision_payload)
    response.headers["X-Makeup-Carryover-Revision"] = revision
    response.headers["ETag"] = f'"{revision}"'
    response.headers["Cache-Control"] = "no-store"
    return response


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


@bp_api_makeup_carryover.get("/api/makeup-sheet-sync/config")
def api_makeup_sheet_sync_config_get():
    try:
        sheet_url = _configured_sheet_url()
    except RuntimeError as exc:
        abort(500, description=str(exc))
    response = jsonify({"ok": True, "sheetUrl": sheet_url})
    response.headers["Cache-Control"] = "no-store"
    return response


@bp_api_makeup_carryover.post("/api/makeup-sheet-sync/config")
def api_makeup_sheet_sync_config_post():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) - {"sheetUrl"}:
        abort(400, description="Invalid JSON body")
    try:
        sheet_url = _validate_sheet_url(payload.get("sheetUrl"))
        with file_lock(MAKEUP_SHEET_SYNC_CONFIG_PATH, timeout_sec=5.0):
            current = _load_sheet_sync_config()
            save_atomic(MAKEUP_SHEET_SYNC_CONFIG_PATH, {**current, "sheetUrl": sheet_url})
    except TimeoutError:
        abort(409, description="시트 설정이 다른 작업에서 사용 중입니다.")
    except RuntimeError as exc:
        abort(400, description=str(exc))
    response = jsonify({"ok": True, "sheetUrl": sheet_url})
    response.headers["Cache-Control"] = "no-store"
    return response

@bp_api_makeup_carryover.get("/api/makeup-carryover")
def api_makeup_carryover_get():
    return _makeup_response(_normalize_payload(load(MAKEUP_CARRYOVER_PATH)))


@bp_api_makeup_carryover.post("/api/makeup-carryover")
def api_makeup_carryover_post():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")
    normalized = _normalize_payload(payload)
    expected_revision = str(request.headers.get("If-Match") or "").strip().strip('"')
    with file_lock(MAKEUP_CARRYOVER_PATH):
        previous = _normalize_payload(load(MAKEUP_CARRYOVER_PATH))
        if not expected_revision:
            return _makeup_response(
                {"ok": False, "error": "makeup_revision_required"},
                428,
                revision_payload=previous,
            )
        if expected_revision != _makeup_revision(previous):
            return _makeup_response(
                {"ok": False, "error": "makeup_revision_conflict"},
                409,
                revision_payload=previous,
            )
        save_atomic(MAKEUP_CARRYOVER_PATH, normalized)
    enqueue_current_schedule_changes(_makeup_student_ids(previous) | _makeup_student_ids(normalized))
    return _makeup_response(normalized)


@bp_api_makeup_carryover.post("/api/makeup-sheet-sync")
def api_makeup_sheet_sync_post():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")
    try:
        date_key = _sheet_sync_date(payload.get("date") or dt.datetime.now(KST).date().isoformat())
        sheet_url, sheet_source = _sheet_sync_url(payload)
        sheet = read_additive_sheet_candidate_window(sheet_url, date_key, months_back=1)
        included_candidates, excluded_candidates = partition_excluded_sheet_candidates(
            sheet.get("candidates") or [],
            _sheet_sync_exclusions(),
        )
        sheet = {**sheet, "candidates": included_candidates}
    except RuntimeError as exc:
        abort(400, description=str(exc))

    # Network parsing is complete before live transaction locks are acquired.
    try:
        with absence_write_scope(
            absent_path=ABS_PATH,
            carryover_path=MAKEUP_CARRYOVER_PATH,
            updates_path=UPD_PATH,
            progress_path=PRG_PATH,
        ) as journal_dir:
            current = _normalize_payload(load(MAKEUP_CARRYOVER_PATH))
            current_absent = load_absent()
            result = build_additive_sheet_sync_result(sheet, current, current_absent)
            if result.get("added"):
                new_pairs = {
                    (str(item.get("date") or ""), str(item.get("sid") or ""))
                    for item in result.get("addedPairs") or []
                }
                commit_new_absences_locked(
                    new_pairs,
                    absent_after=result["absent"],
                    carryover_after=result["carryover"],
                    absent_path=ABS_PATH,
                    carryover_path=MAKEUP_CARRYOVER_PATH,
                    updates_path=UPD_PATH,
                    progress_path=PRG_PATH,
                    journal_dir=journal_dir,
                    kind="makeup-sheet-api",
                )
    except AbsenceRecoveryRequiredError as exc:
        abort(503, description=f"Absence transaction recovery required: {exc}")
    except TimeoutError as exc:
        abort(409, description=f"Failed to apply makeup sheet absences: {exc}")
    except Exception as exc:
        abort(500, description=f"Failed to apply makeup sheet absences: {exc}")
    if result.get("added"):
        enqueue_current_schedule_changes(result.get("addedSids") or [])
    result["sheetSource"] = sheet_source
    result["excludedCount"] = len(excluded_candidates)
    result["excludedCandidates"] = excluded_candidates
    return _makeup_response(result, revision_payload=result.get("carryover"))
