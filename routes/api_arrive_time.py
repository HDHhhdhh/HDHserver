from __future__ import annotations

import datetime as dt
from typing import Dict, Any

from flask import Blueprint, abort, jsonify, request

from core.paths import ARRIVE_TIME_PATH
from core.storage import load, save_atomic, file_lock

bp_api_arrive_time = Blueprint("api_arrive_time", __name__)


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


@bp_api_arrive_time.get("/arrive-time")
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


@bp_api_arrive_time.post("/arrive-time")
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


@bp_api_arrive_time.post("/arrive-time/patch")
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
