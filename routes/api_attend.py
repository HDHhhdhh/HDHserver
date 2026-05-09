# /routes/api_attend.py
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Any

from flask import Blueprint, abort, jsonify, request

from core.paths import STU_PATH, EXTRA_PATH, ATTENDANCE_PATH, CONTACT_PATH
from core.storage import load, save_atomic, file_lock
from core.absent import load_absent, save_absent

bp_api_attend = Blueprint("api_attend", __name__)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _date_key_from_query(default: dt.date | None = None) -> str:
    if default is None:
        default = dt.date.today()
    date_str_full = request.args.get("date", default.isoformat())
    date_str = (date_str_full or default.isoformat()).split("T")[0]
    try:
        dt.date.fromisoformat(date_str)
    except ValueError:
        abort(400, description="Invalid date format")
    return date_str


def _norm_date(date_key: str) -> str:
    s = (str(date_key or "")).split("T")[0].strip()
    try:
        dt.date.fromisoformat(s)
    except Exception:
        abort(400, description="Invalid date format")
    return s


def _load_flag_all(path) -> Dict[str, Dict[str, int]]:
    """
    schema:
      {
        "YYYY-MM-DD": { "sid": 1, ... }
      }
    """
    try:
        data = load(path)
        if isinstance(data, dict):
            out: Dict[str, Dict[str, int]] = {}
            for dk, mp in data.items():
                if isinstance(dk, str) and isinstance(mp, dict):
                    out[dk] = {str(sid): 1 for sid in mp.keys() if str(sid).strip()}
            return out
    except Exception:
        pass
    return {}


def _save_flag_all(path, data: Dict[str, Dict[str, int]]) -> None:
    try:
        save_atomic(path, data)
    except Exception as e:
        abort(500, description=f"Failed to save: {e}")


def _patch_flag(path, date_key: str, sid: str, checked: bool) -> None:
    with file_lock(path):
        all_map = _load_flag_all(path)
        day = all_map.get(date_key)
        if not isinstance(day, dict):
            day = {}
            all_map[date_key] = day

        if checked:
            day[sid] = 1
        else:
            day.pop(sid, None)

        _save_flag_all(path, all_map)


def _merge_day_map(base_day: Dict[str, int] | None, patch_day: Dict[str, Any]) -> Dict[str, int]:
    out = dict(base_day or {})
    for sid_raw, value in patch_day.items():
        sid = str(sid_raw).strip()
        if not sid:
            continue
        if bool(value):
            out[sid] = 1
        else:
            out.pop(sid, None)
    return out


def _apply_day_map(path, date_key: str, day_map: Dict[str, Any], replace_mode: bool) -> Dict[str, int]:
    with file_lock(path):
        all_map = _load_flag_all(path)
        if replace_mode:
            next_day = {
                str(sid): 1
                for sid, value in day_map.items()
                if str(sid).strip() and bool(value)
            }
        else:
            next_day = _merge_day_map(all_map.get(date_key, {}), day_map)
        all_map[date_key] = next_day
        _save_flag_all(path, all_map)
        return next_day


# ------------------------------------------------------------------
# Today students / date-scoped students
# ------------------------------------------------------------------
@bp_api_attend.get("/api/today")
def api_today():
    today = dt.date.today()
    wchr = "월화수목금토일"[today.weekday()]
    students_arr: List[dict] = load(STU_PATH)

    regular = [
        s for s in students_arr
        if any(((s.get(d, "") or "").startswith(wchr) for d in ("day1", "day2", "day3")))
    ]

    extra_ids = load(EXTRA_PATH).get(today.isoformat(), [])
    extra_students = [
        s for s in students_arr
        if str(s.get("id")) in map(str, extra_ids)
    ]

    all_today = {str(s["id"]): s for s in (regular + extra_students)}

    abs_all = load_absent()
    absent_ids = set(map(str, abs_all.get("by_date", {}).get(today.isoformat(), [])))
    for sid in list(all_today.keys()):
        if sid in absent_ids:
            del all_today[sid]

    return jsonify(list(all_today.values()))


@bp_api_attend.get("/api/attend")
def api_attend():
    date_str = _date_key_from_query()
    target = dt.date.fromisoformat(date_str)
    wchr = "월화수목금토일"[target.weekday()]

    students_arr: List[dict] = load(STU_PATH)

    regular = [
        s for s in students_arr
        if any(((s.get(d, "") or "").startswith(wchr) for d in ("day1", "day2", "day3")))
    ]

    extra_ids = load(EXTRA_PATH).get(target.isoformat(), [])
    extra_students = [
        s for s in students_arr
        if str(s.get("id")) in map(str, extra_ids)
    ]

    all_today = {str(s["id"]): s for s in (regular + extra_students)}

    abs_all = load_absent()
    absent_ids = set(map(str, abs_all.get("by_date", {}).get(target.isoformat(), [])))
    for sid in list(all_today.keys()):
        if sid in absent_ids:
            del all_today[sid]

    return jsonify(list(all_today.values()))


# ------------------------------------------------------------------
# Absent state overwrite
# ------------------------------------------------------------------
@bp_api_attend.get("/api/absent")
def api_absent_get():
    return jsonify(load_absent())


@bp_api_attend.post("/api/absent")
def api_absent_post():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")
    save_absent(payload)
    return jsonify(load_absent())


# ------------------------------------------------------------------
# Attendance
# ------------------------------------------------------------------
@bp_api_attend.get("/api/attendance")
def api_attendance_get():
    date_key = _date_key_from_query()
    all_map = _load_flag_all(ATTENDANCE_PATH)
    return jsonify(all_map.get(date_key, {}))


@bp_api_attend.post("/api/attendance")
def api_attendance_post():
    """
    Overwrite mode:
      1) { "YYYY-MM-DD": { "sid": 1 } }
      2) { "date": "YYYY-MM-DD", "map": { "sid": 1 } }
    """
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    if "date" in payload and "map" in payload:
        date_key = _norm_date(str(payload.get("date") or ""))
        day_map = payload.get("map")
    else:
        if len(payload) != 1:
            abort(400, description="Body must contain exactly one date key")
        date_key = _norm_date(str(next(iter(payload.keys()))))
        day_map = payload.get(date_key)

    if not isinstance(day_map, dict):
        abort(400, description="Attendance map must be an object")

    replace_mode = bool(payload.get("replace") or payload.get("__replace__"))
    saved = _apply_day_map(ATTENDANCE_PATH, date_key, day_map, replace_mode)
    return jsonify({
        "ok": True,
        "date": date_key,
        "count": len(saved),
        "mode": "replace" if replace_mode else "merge",
    })


@bp_api_attend.post("/api/attendance/patch")
def api_attendance_patch():
    """
    Single-item patch for concurrent-safe writes.
    body: { "date":"YYYY-MM-DD", "sid":"...", "value": true/false }
    """
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    date_key = _norm_date(str(payload.get("date") or ""))
    sid = str(payload.get("sid") or "").strip()
    if not sid:
        abort(400, description="sid is required")

    checked = bool(payload.get("value", True))
    _patch_flag(ATTENDANCE_PATH, date_key, sid, checked)
    return jsonify({"ok": True, "date": date_key, "sid": sid, "value": 1 if checked else 0})


# ------------------------------------------------------------------
# Contact
# ------------------------------------------------------------------
@bp_api_attend.get("/api/contact")
def api_contact_get():
    date_key = _date_key_from_query()
    all_map = _load_flag_all(CONTACT_PATH)
    return jsonify(all_map.get(date_key, {}))


@bp_api_attend.post("/api/contact")
def api_contact_post():
    """
    Overwrite mode:
      1) { "YYYY-MM-DD": { "sid": 1 } }
      2) { "date": "YYYY-MM-DD", "map": { "sid": 1 } }
    """
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    if "date" in payload and "map" in payload:
        date_key = _norm_date(str(payload.get("date") or ""))
        day_map = payload.get("map")
    else:
        if len(payload) != 1:
            abort(400, description="Body must contain exactly one date key")
        date_key = _norm_date(str(next(iter(payload.keys()))))
        day_map = payload.get(date_key)

    if not isinstance(day_map, dict):
        abort(400, description="Contact map must be an object")

    replace_mode = bool(payload.get("replace") or payload.get("__replace__"))
    saved = _apply_day_map(CONTACT_PATH, date_key, day_map, replace_mode)
    return jsonify({
        "ok": True,
        "date": date_key,
        "count": len(saved),
        "mode": "replace" if replace_mode else "merge",
    })


@bp_api_attend.post("/api/contact/patch")
def api_contact_patch():
    """
    Single-item patch for concurrent-safe writes.
    body: { "date":"YYYY-MM-DD", "sid":"...", "value": true/false }
    """
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    date_key = _norm_date(str(payload.get("date") or ""))
    sid = str(payload.get("sid") or "").strip()
    if not sid:
        abort(400, description="sid is required")

    checked = bool(payload.get("value", True))
    _patch_flag(CONTACT_PATH, date_key, sid, checked)
    return jsonify({"ok": True, "date": date_key, "sid": sid, "value": 1 if checked else 0})

