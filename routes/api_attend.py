# /routes/api_attend.py
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
from typing import Dict, List, Any

from flask import Blueprint, abort, jsonify, request
from core.date_rules import is_iso_date_key

from core.paths import STU_PATH, EXTRA_PATH, ATTENDANCE_PATH, CONTACT_PATH, PRG_PATH, UPD_PATH, ABS_PATH
from core.student_schedule_projection import scheduled_makeup_student_ids
from core.student_schedule_rules import student_has_started_on_date
from core.student_notification_hooks import enqueue_current_schedule_changes
from core.storage import load, save_atomic, file_lock
from core.absent import load_absent, normalize_absent, save_absent, DATE_RE
from routes.absence_assignment_cleanup import (
    AbsenceRecoveryRequiredError,
    MAKEUP_CARRYOVER_PATH,
    absence_write_scope,
    commit_new_absences_locked,
)

bp_api_attend = Blueprint("api_attend", __name__)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _date_key_from_query(default: dt.date | None = None) -> str:
    if default is None:
        default = dt.date.today()
    date_str_full = request.args.get("date", default.isoformat())
    date_str = str(date_str_full or default.isoformat()).strip()
    if not is_iso_date_key(date_str):
        abort(400, description="Invalid date format")
    return date_str


def _norm_date(date_key: str) -> str:
    s = str(date_key or "").strip()
    if not is_iso_date_key(s):
        abort(400, description="Invalid date format")
    return s


def _absence_revision(payload: dict) -> str:
    normalized = payload if isinstance(payload, dict) else {}
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _absence_response(payload: dict, status: int = 200, *, revision_payload: dict | None = None):
    response = jsonify(payload)
    response.status_code = status
    response.headers["X-Absence-Revision"] = _absence_revision(
        revision_payload if revision_payload is not None else payload
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _load_flag_all(path, *, for_write: bool = False) -> Dict[str, Dict[str, int]]:
    """
    schema:
      {
        "YYYY-MM-DD": { "sid": 1, ... }
      }
    """
    if for_write:
        try:
            data = json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            data = {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            abort(503, description="Attendance/contact store is unreadable")
        if not isinstance(data, dict) or any(not isinstance(day, dict) for day in data.values()):
            abort(503, description="Attendance/contact store is invalid")
    else:
        try:
            data = load(path)
        except Exception:
            return {}
    try:
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
        all_map = _load_flag_all(path, for_write=True)
        day = all_map.get(date_key)
        if not isinstance(day, dict):
            day = {}
            all_map[date_key] = day

        if checked:
            day[sid] = 1
        else:
            day.pop(sid, None)

        _save_flag_all(path, all_map)





def _absence_pairs(payload: Any) -> set[tuple[str, str]]:
    if not isinstance(payload, dict):
        return set()

    pairs: set[tuple[str, str]] = set()
    by_date = payload.get("by_date")
    if isinstance(by_date, dict):
        for date_raw, sids in by_date.items():
            date_key = str(date_raw or "").strip()
            if not DATE_RE.match(date_key) or not isinstance(sids, list):
                continue
            for sid_raw in sids:
                sid = str(sid_raw or "").strip()
                if sid:
                    pairs.add((date_key, sid))

    by_student = payload.get("by_student")
    if isinstance(by_student, dict):
        for sid_raw, date_raw in by_student.items():
            sid = str(sid_raw or "").strip()
            date_key = str(date_raw or "").strip()
            if sid and DATE_RE.match(date_key):
                pairs.add((date_key, sid))

    by_slot = payload.get("by_slot")
    if isinstance(by_slot, dict):
        for date_raw, sid_map in by_slot.items():
            date_key = str(date_raw or "").strip()
            if not DATE_RE.match(date_key) or not isinstance(sid_map, dict):
                continue
            for sid_raw, slots_raw in sid_map.items():
                sid = str(sid_raw or "").strip()
                if not sid:
                    continue
                slots = slots_raw if isinstance(slots_raw, list) else [slots_raw]
                if any(str(slot).strip() in {"1", "2"} for slot in slots):
                    pairs.add((date_key, sid))

    return pairs


def _load_scheduled_makeup_ids(date_key: str) -> set[str]:
    try:
        carryover = load(MAKEUP_CARRYOVER_PATH)
    except Exception:
        return set()
    return scheduled_makeup_student_ids(carryover, date_key=date_key)


def _attendance_roster_for_date(target: dt.date) -> List[dict]:
    date_key = target.isoformat()
    weekday = "월화수목금토일"[target.weekday()]
    students_arr: List[dict] = [
        student for student in load(STU_PATH)
        if student_has_started_on_date(student, date_key)
    ]

    regular = [
        student for student in students_arr
        if any(
            ((student.get(day_key, "") or "").startswith(weekday))
            for day_key in ("day1", "day2", "day3")
        )
    ]

    extra_ids = {
        str(sid).strip()
        for sid in (load(EXTRA_PATH).get(date_key, []) or [])
        if str(sid).strip()
    }
    supplemental_ids = extra_ids | _load_scheduled_makeup_ids(date_key)
    supplemental = [
        student for student in students_arr
        if str(student.get("id")).strip() in supplemental_ids
    ]
    roster = {str(student["id"]): student for student in (regular + supplemental)}

    absent_payload = load_absent()
    absent_ids = set(map(str, absent_payload.get("by_date", {}).get(date_key, [])))
    for sid in list(roster):
        if sid in absent_ids:
            del roster[sid]
    return list(roster.values())


# ------------------------------------------------------------------
# Today students / date-scoped students
# ------------------------------------------------------------------
@bp_api_attend.get("/api/today")
def api_today():
    return jsonify(_attendance_roster_for_date(dt.date.today()))


@bp_api_attend.get("/api/attend")
def api_attend():
    date_str = _date_key_from_query()
    target = dt.date.fromisoformat(date_str)
    return jsonify(_attendance_roster_for_date(target))


# ------------------------------------------------------------------
# Absent state overwrite
# ------------------------------------------------------------------
@bp_api_attend.get("/api/absent")
def api_absent_get():
    return _absence_response(load_absent())


@bp_api_attend.post("/api/absent")
def api_absent_post():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    try:
        with absence_write_scope(
            absent_path=ABS_PATH,
            carryover_path=MAKEUP_CARRYOVER_PATH,
            updates_path=UPD_PATH,
            progress_path=PRG_PATH,
        ) as journal_dir:
            before = load_absent()
            expected_revision = str(request.headers.get("If-Match") or "").strip().strip('"')
            if not expected_revision:
                return _absence_response(
                    {"ok": False, "error": "absence_revision_required"},
                    428,
                    revision_payload=before,
                )
            if expected_revision != _absence_revision(before):
                return _absence_response(
                    {"ok": False, "error": "absence_revision_conflict"},
                    409,
                    revision_payload=before,
                )

            before_pairs = _absence_pairs(before)
            after_pairs = _absence_pairs(payload)
            new_pairs = after_pairs - before_pairs
            if new_pairs:
                students = load(STU_PATH)
                if not isinstance(students, list):
                    raise ValueError("students must be readable before registering an absence")
                commit_new_absences_locked(
                    new_pairs,
                    absent_after=normalize_absent(payload, existing=before),
                    absent_path=ABS_PATH,
                    carryover_path=MAKEUP_CARRYOVER_PATH,
                    updates_path=UPD_PATH,
                    progress_path=PRG_PATH,
                    journal_dir=journal_dir,
                    students=students,
                    kind="absence-api",
                )
            else:
                save_absent(payload, locked=True)
            saved = load_absent()
    except AbsenceRecoveryRequiredError as exc:
        abort(503, description=f"Absence transaction recovery required: {exc}")
    except TimeoutError as exc:
        abort(409, description=f"Failed to clear absence assignments: {exc}")
    except Exception as exc:
        abort(500, description=f"Failed to clear absence assignments: {exc}")

    enqueue_current_schedule_changes(sid for _date, sid in before_pairs ^ after_pairs)
    return _absence_response(saved)


@bp_api_attend.post("/api/absent/recover")
def api_absent_recover():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    date_key = _norm_date(str(payload.get("date") or ""))
    raw_sids = payload.get("sids")
    if not isinstance(raw_sids, list):
        abort(400, description="sids must be a list")
    selected = tuple(dict.fromkeys(
        str(value or "").strip() for value in raw_sids if str(value or "").strip()
    ))
    if not selected:
        abort(400, description="sids must not be empty")

    selected_set = set(selected)
    with file_lock(ABS_PATH):
        latest = load_absent()
        by_date = dict(latest.get("by_date") or {})
        by_student = dict(latest.get("by_student") or {})
        by_slot = {
            str(date): dict(sid_map) if isinstance(sid_map, dict) else {}
            for date, sid_map in (latest.get("by_slot") or {}).items()
        }

        by_date[date_key] = [
            sid for sid in (by_date.get(date_key) or [])
            if str(sid).strip() not in selected_set
        ]
        for sid in selected:
            if str(by_student.get(sid) or "") == date_key:
                by_student.pop(sid, None)
            by_slot.get(date_key, {}).pop(sid, None)
        if date_key in by_slot and not by_slot[date_key]:
            by_slot.pop(date_key, None)

        save_absent({"by_date": by_date, "by_student": by_student, "by_slot": by_slot}, locked=True)
        saved = load_absent()

    enqueue_current_schedule_changes(selected)
    return _absence_response(saved)


# ------------------------------------------------------------------
# Attendance
# ------------------------------------------------------------------
@bp_api_attend.get("/api/attendance")
def api_attendance_get():
    date_key = _date_key_from_query()
    all_map = _load_flag_all(ATTENDANCE_PATH)
    return jsonify(all_map.get(date_key, {}))





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
