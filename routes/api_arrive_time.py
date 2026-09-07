from __future__ import annotations

import datetime as dt
from typing import Dict, Any

from flask import Blueprint, abort, jsonify, request

from core.absent import load_absent
from core.paths import ARRIVE_TIME_PATH, EXTRA_PATH, STU_PATH
from core.student_schedule_projection import effective_attendance_student_ids
from core.storage import load, save_atomic, file_lock
from routes.absence_assignment_cleanup import MAKEUP_CARRYOVER_PATH
from routes.log_repository_provider import get_log_repository

bp_api_arrive_time = Blueprint("api_arrive_time", __name__)
MISSING_LEAVE_WARNING_START_DATE = "2026-08-29"


def _norm_date(date_str_full: str) -> str:
    s = (date_str_full or "").strip()
    if not s:
        return dt.date.today().isoformat()
    s = s.split("T")[0]
    try:
        d = dt.date.fromisoformat(s)
    except ValueError:
        abort(400, description="Invalid date format")
    return d.isoformat()


def _is_time_like(v: str) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    return len(s) <= 20


def _load_all_arrive_times() -> Dict[str, Dict[str, str]]:
    all_map: Dict[str, Dict[str, str]] = load(ARRIVE_TIME_PATH) or {}
    return all_map if isinstance(all_map, dict) else {}


def _filter_arrivals_to_effective_roster(
    arrivals_by_date: Any,
    absent: Any,
) -> tuple[Dict[str, Dict[str, str]], bool]:
    """Keep arrival traces only while the SID remains on that date's roster."""
    try:
        students = load(STU_PATH)
        extra = load(EXTRA_PATH)
        makeup = load(MAKEUP_CARRYOVER_PATH)
    except Exception:
        return {}, False

    if not isinstance(students, list):
        return {}, False
    extra_map = extra if isinstance(extra, dict) else {}
    makeup_map = makeup if isinstance(makeup, dict) else {}
    absence_map = absent if isinstance(absent, dict) else {}
    scoped: Dict[str, Dict[str, str]] = {}

    if not isinstance(arrivals_by_date, dict):
        return scoped, True

    for date_raw, by_sid in arrivals_by_date.items():
        date_key = str(date_raw or "").strip()
        if not isinstance(by_sid, dict):
            continue
        roster_ids = effective_attendance_student_ids(
            students,
            date_key=date_key,
            absence=absence_map,
            extra=extra_map,
            makeup=makeup_map,
        )
        day: Dict[str, str] = {}
        for sid_raw, arrive_raw in by_sid.items():
            sid = str(sid_raw or "").strip()
            if not sid or sid not in roster_ids:
                continue
            day[sid] = arrive_raw
        if day:
            scoped[date_key] = day
    return scoped, True


def _day_map(all_map: Dict[str, Dict[str, str]], date_key: str) -> Dict[str, str]:
    cur = all_map.get(date_key, {})
    return cur if isinstance(cur, dict) else {}


def _apply_time_value(day_map: Dict[str, str], sid: str, value: Any) -> str:
    v = "" if value is None else str(value).strip()
    if not v:
        day_map.pop(sid, None)
        return ""
    if not _is_time_like(v):
        abort(400, description="Invalid time value")
    day_map[sid] = v
    return v


@bp_api_arrive_time.get("/api/arrive-time")
def api_arrive_time_get():
    """
    GET /api/arrive-time?date=YYYY-MM-DD  -> { "sid": "HH:MM", ... }
    GET /api/arrive-time                  -> 전체(디버그용)
    """
    date_q = request.args.get("date", "")
    all_map = _load_all_arrive_times()

    if not date_q:
        return jsonify(all_map)

    date_key = _norm_date(date_q)
    return jsonify(_day_map(all_map, date_key))


@bp_api_arrive_time.get("/api/arrive-time/missing-leave-summary")
def api_arrive_time_missing_leave_summary():
    exclude_raw = str(
        request.args.get("exclude_date")
        or request.args.get("excludeDate")
        or ""
    ).strip()
    exclude_date = _norm_date(exclude_raw) if exclude_raw else ""
    absent = load_absent()
    absent_by_date = absent.get("by_date") if isinstance(absent, dict) else {}
    scoped_arrivals, roster_available = _filter_arrivals_to_effective_roster(
        _load_all_arrive_times(),
        absent,
    )
    result = get_log_repository().summarize_missing_leave(
        scoped_arrivals,
        absent_by_date,
        since_date=MISSING_LEAVE_WARNING_START_DATE,
        exclude_date=exclude_date,
    )
    if not roster_available:
        result["rowsAvailable"] = False
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp_api_arrive_time.post("/api/arrive-time")
def api_arrive_time_post():
    """
    POST /api/arrive-time
    body: { "YYYY-MM-DD": { "sid": "HH:MM", ... } }
    -> 해당 날짜만 merge
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not payload:
        abort(400, description="Invalid JSON body")

    with file_lock(ARRIVE_TIME_PATH):
        all_map = _load_all_arrive_times()

        for date_key_raw, day_patch in payload.items():
            date_key = _norm_date(str(date_key_raw))
            if not isinstance(day_patch, dict):
                abort(400, description="Invalid day map")

            cur = _day_map(all_map, date_key)

            for sid_raw, time_raw in day_patch.items():
                sid = str(sid_raw).strip()
                if not sid:
                    continue

                _apply_time_value(cur, sid, time_raw)

            all_map[date_key] = cur

        save_atomic(ARRIVE_TIME_PATH, all_map)
    return jsonify({"ok": True})


@bp_api_arrive_time.post("/api/arrive-time/patch")
def api_arrive_time_patch():
    """
    POST /api/arrive-time/patch
    body: { "date": "YYYY-MM-DD", "sid": "xxx", "value": "HH:MM" }
    - value가 None/"" 이면 삭제
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    date_key = _norm_date(str(payload.get("date", "")))
    sid = str(payload.get("sid") or "").strip()
    if not sid:
        abort(400, description="sid is required")

    value = payload.get("value", "")

    with file_lock(ARRIVE_TIME_PATH):
        all_map = _load_all_arrive_times()
        cur = _day_map(all_map, date_key)
        v = _apply_time_value(cur, sid, value)

        all_map[date_key] = cur
        save_atomic(ARRIVE_TIME_PATH, all_map)
    return jsonify({"ok": True, "date": date_key, "sid": sid, "value": v})
