from __future__ import annotations

import datetime as dt
import json

from flask import Blueprint, current_app, jsonify, request

from core.date_rules import is_iso_date_key
from core.ghost_student import GHOST_STUDENT_WRITE_ERROR, is_ghost_student_sid
from core.paths import EXTRA_PATH, STU_PATH, WEEKEND_SLOTS_PATH
from core.storage import file_lock, load, save_atomic
from core.student_notification_hooks import enqueue_current_schedule_changes


bp_api_schedule_overrides = Blueprint("api_schedule_overrides", __name__)

KST = dt.timezone(dt.timedelta(hours=9))
_ASSIGNMENT_HOOKS_EXTENSION = "schedule_override_assignment_hooks"


def configure_schedule_override_assignment_hooks(
    app,
    *,
    initialize_today,
    reconcile,
) -> None:
    if not callable(initialize_today) or not callable(reconcile):
        raise TypeError("schedule override assignment hooks must be callable")
    app.extensions[_ASSIGNMENT_HOOKS_EXTENSION] = {
        "initialize_today": initialize_today,
        "reconcile": reconcile,
    }


def _assignment_hooks() -> tuple:
    hooks = current_app.extensions.get(_ASSIGNMENT_HOOKS_EXTENSION)
    if not isinstance(hooks, dict):
        raise RuntimeError("schedule override assignment hooks are not configured")
    initialize_today = hooks.get("initialize_today")
    reconcile = hooks.get("reconcile")
    if not callable(initialize_today) or not callable(reconcile):
        raise RuntimeError("schedule override assignment hooks are incomplete")
    return initialize_today, reconcile


def _today_kst_iso() -> str:
    return dt.datetime.now(KST).date().isoformat()


def _json_stable(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return ""


def _normalize_extra_attend_patch(payload) -> dict[str, list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSON body")

    if "dates" in payload:
        raw_dates = payload.get("dates")
        if not isinstance(raw_dates, dict):
            raise ValueError("dates must be an object")
    else:
        raw_dates = {payload.get("date"): payload.get("sids")}

    normalized: dict[str, list[str]] = {}
    for raw_date, raw_sids in raw_dates.items():
        date_key = str(raw_date or "").strip()
        if not is_iso_date_key(date_key):
            raise ValueError("invalid date")
        if not isinstance(raw_sids, list):
            raise ValueError("sids must be a list")

        sids: list[str] = []
        seen: set[str] = set()
        for raw_sid in raw_sids:
            if isinstance(raw_sid, (dict, list)):
                raise ValueError("invalid sid")
            sid = str(raw_sid or "").strip()
            if not sid or sid in seen:
                continue
            if is_ghost_student_sid(sid):
                raise PermissionError(GHOST_STUDENT_WRITE_ERROR)
            seen.add(sid)
            sids.append(sid)
        normalized[date_key] = sids

    if not normalized:
        raise ValueError("date patch is required")
    return normalized


def _extra_attend_sids(value) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(sid).strip() for sid in value if str(sid).strip()}


@bp_api_schedule_overrides.route("/api/extra-attend", methods=["GET", "PATCH"])
def api_extra_attend():
    if request.method == "GET":
        return jsonify(load(EXTRA_PATH))

    try:
        date_patch = _normalize_extra_attend_patch(request.get_json(silent=True))
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    initialize_today, _reconcile = _assignment_hooks()
    affected_sids: set[str] = set()
    changed_dates: set[str] = set()
    with file_lock(EXTRA_PATH):
        previous = load(EXTRA_PATH) or {}
        previous_map = previous if isinstance(previous, dict) else {}
        next_map = dict(previous_map)
        for date_key, sids in date_patch.items():
            previous_sids = previous_map.get(date_key)
            if _json_stable(previous_sids or []) == _json_stable(sids):
                continue
            changed_dates.add(date_key)
            affected_sids.update(_extra_attend_sids(previous_sids))
            affected_sids.update(sids)
            if sids:
                next_map[date_key] = sids
            else:
                next_map.pop(date_key, None)
        if changed_dates:
            save_atomic(EXTRA_PATH, next_map)

    real_today = _today_kst_iso()
    # Replay today's idempotent initializer even when this PATCH is now a
    # no-op. A prior attempt may have committed extra_attend.json and then
    # failed in this post-commit effect; the identical retry must repair it.
    if real_today in date_patch:
        initialize_today(date_key=real_today, extra=next_map)
    enqueue_current_schedule_changes(affected_sids)
    return jsonify({
        "ok": True,
        "dates": {date_key: date_patch[date_key] for date_key in date_patch},
        "changedDates": sorted(changed_dates),
    })


def _normalize_weekend_slot_value(value):
    if isinstance(value, list):
        return [int(item) for item in value if str(item).isdigit()]
    if str(value).isdigit():
        return int(value)
    return value


class _UnknownWeekendSlotStudentError(LookupError):
    def __init__(self, sid: str) -> None:
        super().__init__(sid)
        self.sid = sid


def _normalize_weekend_slots_patch(payload) -> dict[str, dict[str, object]]:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Invalid JSON body")

    normalized: dict[str, dict[str, object]] = {}
    for raw_date, raw_mapping in payload.items():
        date_key = str(raw_date or "").strip()
        if not is_iso_date_key(date_key):
            raise ValueError("invalid date")
        if not isinstance(raw_mapping, dict) or not raw_mapping:
            raise ValueError("slot mapping must be a non-empty object")

        mapping: dict[str, object] = {}
        for raw_sid, value in raw_mapping.items():
            sid = str(raw_sid or "").strip()
            if not sid:
                raise ValueError("invalid sid")
            if is_ghost_student_sid(sid):
                raise PermissionError(GHOST_STUDENT_WRITE_ERROR)
            mapping[sid] = value
        normalized[date_key] = mapping
    return normalized


def _validate_weekend_slot_students(
    patch: dict[str, dict[str, object]],
) -> None:
    students = load(STU_PATH)
    if not isinstance(students, list):
        raise RuntimeError("student roster unavailable")
    known_sids = {
        str(student.get("id") or "").strip()
        for student in students
        if isinstance(student, dict) and str(student.get("id") or "").strip()
    }
    for mapping in patch.values():
        for sid in mapping:
            if sid not in known_sids:
                raise _UnknownWeekendSlotStudentError(sid)


@bp_api_schedule_overrides.route("/api/weekend-slots", methods=["GET", "POST"])
def api_weekend_slots():
    if request.method == "GET":
        return jsonify(load(WEEKEND_SLOTS_PATH))

    try:
        body = _normalize_weekend_slots_patch(request.get_json(silent=True))
        _validate_weekend_slot_students(body)
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except _UnknownWeekendSlotStudentError as exc:
        return jsonify({"ok": False, "error": "unknown sid", "sid": exc.sid}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503

    initialize_today, reconcile = _assignment_hooks()
    with file_lock(WEEKEND_SLOTS_PATH):
        current = load(WEEKEND_SLOTS_PATH)
        if not isinstance(current, dict):
            current = {}
        for date_key, mapping in body.items():
            day = current.setdefault(date_key, {})
            for sid, value in mapping.items():
                if value is None or value is False or value == []:
                    day.pop(sid, None)
                    continue
                day[sid] = _normalize_weekend_slot_value(value)
            if not day:
                current.pop(date_key, None)
        save_atomic(WEEKEND_SLOTS_PATH, current)

    real_today = _today_kst_iso()
    if real_today in body:
        initialize_today(
            date_key=real_today,
            weekend_slots=current,
        )
    enqueue_current_schedule_changes(
        str(sid)
        for mapping in body.values()
        for sid in mapping
    )
    for date_key, mapping in body.items():
        for sid in mapping:
            reconcile(
                date_key,
                sid,
                weekend_slots=current,
            )
    return "", 204


__all__ = (
    "bp_api_schedule_overrides",
    "configure_schedule_override_assignment_hooks",
)
