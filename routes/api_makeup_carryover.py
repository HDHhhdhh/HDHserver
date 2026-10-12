from __future__ import annotations

import datetime as dt
import json
from typing import Any

from flask import Blueprint, abort, jsonify, request

from core.absent import load_absent
from core.makeup_payload_rules import (
    normalize_makeup_date as _norm_date,
    normalize_makeup_sid as _norm_sid,
    normalize_makeup_slots as _norm_slot_list,
    normalize_makeup_schedule as _normalize_schedule,
    normalize_manual_makeups as _normalize_manual,
    normalize_makeup_payload as _normalize_payload,
    makeup_student_ids as _makeup_student_ids,
    makeup_revision as _makeup_revision,
)
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


def _sheet_sync_error(message: str, status: int, code: str):
    response = jsonify({"ok": False, "error": code, "message": message})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


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
        # Old row-action clients must not reopen a server-classified self-study absence.
        for date, rows in previous["by_absence"].items():
            for sid, row in rows.items():
                requested = normalized["by_absence"].get(date, {}).get(sid)
                if row.get("state") == "self-study" and requested and requested.get("state") == "open":
                    requested["state"] = "self-study"
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
        exclusions = _sheet_sync_exclusions()
    except RuntimeError as exc:
        return _sheet_sync_error(str(exc), 400, "sheet_sync_config_invalid")
    try:
        sheet = read_additive_sheet_candidate_window(sheet_url, date_key, months_back=1)
        included_candidates, excluded_candidates = partition_excluded_sheet_candidates(
            sheet.get("candidates") or [],
            exclusions,
        )
        sheet = {**sheet, "candidates": included_candidates}
    except RuntimeError as exc:
        return _sheet_sync_error(str(exc), 400, "sheet_read_failed")

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
        return _sheet_sync_error(
            f"결석 처리 복구가 필요합니다: {exc}",
            503,
            "absence_recovery_required",
        )
    except TimeoutError as exc:
        return _sheet_sync_error(
            f"결석 저장 요청이 잠시 겹쳤습니다: {exc}",
            409,
            "absence_lock_timeout",
        )
    except Exception as exc:
        return _sheet_sync_error(
            f"시트 결석 반영에 실패했습니다: {exc}",
            500,
            "sheet_sync_apply_failed",
        )
    if result.get("added"):
        enqueue_current_schedule_changes(result.get("addedSids") or [])
    result["sheetSource"] = sheet_source
    result["excludedCount"] = len(excluded_candidates)
    result["excludedCandidates"] = excluded_candidates
    return _makeup_response(result, revision_payload=result.get("carryover"))
