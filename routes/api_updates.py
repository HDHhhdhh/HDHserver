from __future__ import annotations

import datetime as dt

from flask import Blueprint, abort, current_app, jsonify, request

from core.date_rules import parse_iso_date_key
from core.ghost_student import (
    GHOST_STUDENT_WRITE_ERROR,
    is_ghost_student_sid,
)
from core.paths import UPD_PATH
from core.request_consistency import updates_get_initializes
from core.storage import nocache_resp
from core.update_assignment_rules import (
    StudentAssignmentNotFoundError,
    merge_update_assignment,
    normalize_video_assign_list,
    sid_lookup,
    write_sid_mapping,
)
from core.update_assignment_store import (
    UpdateAssignmentStoreError,
    load_updates_strict,
    save_updates_strict,
    updates_lock,
)


bp_api_updates = Blueprint("api_updates", __name__)

_ASSIGNMENT_HOOKS_EXTENSION = "updates_assignment_hooks"
KST = dt.timezone(dt.timedelta(hours=9))


def _today_kst_iso() -> str:
    return dt.datetime.now(KST).date().isoformat()


def configure_updates_assignment_hooks(
    app,
    *,
    initialize_today,
    reconcile_self_study,
) -> None:
    if not callable(initialize_today) or not callable(reconcile_self_study):
        raise TypeError("updates assignment hooks must be callable")
    app.extensions[_ASSIGNMENT_HOOKS_EXTENSION] = {
        "initialize_today": initialize_today,
        "reconcile_self_study": reconcile_self_study,
    }


def _assignment_hooks() -> tuple:
    hooks = current_app.extensions.get(_ASSIGNMENT_HOOKS_EXTENSION)
    if not isinstance(hooks, dict):
        raise RuntimeError("updates assignment hooks are not configured")
    initialize_today = hooks.get("initialize_today")
    reconcile_self_study = hooks.get("reconcile_self_study")
    if not callable(initialize_today) or not callable(reconcile_self_study):
        raise RuntimeError("updates assignment hooks are incomplete")
    return initialize_today, reconcile_self_study


def _updates_lock():
    return updates_lock(UPD_PATH)


@bp_api_updates.get("/api/updates")
def api_updates():
    try:
        if not updates_get_initializes(request.args):
            return nocache_resp(load_updates_strict(UPD_PATH))
        current_app.logger.warning("[updates] compatibility GET initialization requested")
        initialize_today, _reconcile_self_study = _assignment_hooks()
        return nocache_resp(initialize_today())
    except UpdateAssignmentStoreError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503


@bp_api_updates.post("/api/updates/ensure-today")
def api_updates_ensure_today():
    try:
        initialize_today, _reconcile_self_study = _assignment_hooks()
        return nocache_resp(initialize_today())
    except UpdateAssignmentStoreError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503


@bp_api_updates.post("/api/updates/patch")
def api_updates_patch():
    body = request.get_json(force=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if "remove" in body and not isinstance(body.get("remove"), bool):
        return jsonify({"ok": False, "error": "bad payload"}), 400

    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    remove = body.get("remove") is True

    parsed_date = parse_iso_date_key(date)
    if not date or not sid or parsed_date is None:
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

    if remove:
        incoming = {"remove": True}
    else:
        incoming = (
            dict(body.get("entry") or {})
            if isinstance(body.get("entry"), dict)
            else {}
        )
        if "videos" in body:
            incoming["videos"] = body.get("videos")
        if not incoming:
            incoming["videos"] = []

    try:
        with _updates_lock():
            current = load_updates_strict(UPD_PATH)
            day = current.setdefault(date, {})
            if not isinstance(day, dict):
                current[date] = {}
                day = current[date]

            if remove:
                write_sid_mapping(day, sid, None)
                assignment = []
            else:
                assignment = merge_update_assignment(
                    sid_lookup(day, sid),
                    incoming,
                )
                source = (
                    str(assignment.get("source") or "").strip().casefold()
                    if isinstance(assignment, dict)
                    else ""
                )
                if source == "auto" and parsed_date > dt.date.fromisoformat(
                    _today_kst_iso()
                ):
                    return jsonify({
                        "ok": False,
                        "error": "future automatic assignment is not allowed",
                    }), 409
                write_sid_mapping(day, sid, assignment)

            if not day:
                current.pop(date, None)

            save_updates_strict(UPD_PATH, current)
        return jsonify({"ok": True, "assignment": assignment})
    except TimeoutError:
        return jsonify({
            "ok": False,
            "code": "updates_lock_timeout",
            "retryable": True,
            "error": "영상 배정 저장 요청이 잠시 겹쳤습니다. 자동으로 다시 시도합니다.",
        }), 409
    except UpdateAssignmentStoreError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503


@bp_api_updates.post("/api/updates/self-study")
def api_updates_self_study():
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    has_requested_videos = "videos" in body
    append_requested_videos = body.get("append") is True

    if not date or not sid or parse_iso_date_key(date) is None:
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403
    if has_requested_videos and not isinstance(body.get("videos"), list):
        return jsonify({"ok": False, "error": "videos must be an array"}), 400

    _initialize_today, reconcile_self_study = _assignment_hooks()
    requested_videos = (
        normalize_video_assign_list(body.get("videos"))
        if has_requested_videos
        else []
    )
    try:
        payload, status = reconcile_self_study(
            date=date,
            sid=sid,
            has_requested_videos=has_requested_videos,
            requested_videos=requested_videos,
            append_requested_videos=append_requested_videos,
        )
    except StudentAssignmentNotFoundError:
        abort(404, description="학생을 찾을 수 없습니다.")
    except TimeoutError:
        return jsonify({
            "ok": False,
            "code": "updates_lock_timeout",
            "retryable": True,
            "error": "영상 배정 저장 요청이 잠시 겹쳤습니다. 자동으로 다시 시도합니다.",
        }), 409
    except UpdateAssignmentStoreError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503
    return jsonify(payload), status


__all__ = (
    "bp_api_updates",
    "configure_updates_assignment_hooks",
)
