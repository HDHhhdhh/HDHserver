from __future__ import annotations

import time
from flask import Blueprint, g, jsonify, request

from core.date_rules import is_iso_date_key
from core.ghost_student import GHOST_STUDENT_WRITE_ERROR, is_ghost_student_sid
from core.network_access import ACADEMY_ACCESS_MESSAGE, academy_network_allowed, ip_allowed
from core.paths import PRG_PATH, STU_PATH, VID_PATH, WATCH_PATH
from core.progress_rules import (
    VALID_VIDEO_PROGRESS_STATUSES,
    normalize_watch_entry,
    watch_auto_status,
    watch_rank,
)
from core.storage import load, nocache_resp
from core.watch_progress_writer import (
    get_watch_entry,
    save_progress_status,
    save_watch_entry,
    sid_keys,
)

bp_api_watch = Blueprint("api_watch", __name__)


def _academy_request_allowed() -> bool:
    if getattr(g, "student_app_public_request", False) is True:
        client_ip = getattr(g, "student_app_client_ip", None)
        return isinstance(client_ip, str) and ip_allowed(client_ip)
    return academy_network_allowed()


def _public_sid_matches(sid: str) -> bool:
    if getattr(g, "student_app_public_request", False) is not True:
        return True
    active_sid = getattr(g, "student_app_active_sid", None)
    return isinstance(active_sid, str) and bool(sid) and sid == active_sid


@bp_api_watch.get("/api/watch/latest")
def api_watch_latest():
    sid = str(request.args.get("sid") or "").strip()
    date = str(request.args.get("date") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "missing sid"}), 400
    if date and not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400

    data = load(WATCH_PATH)
    if not isinstance(data, dict):
        data = {}

    out = {}
    keys = sid_keys(sid)
    date_items = [(date, data.get(date))] if date else data.items()
    for _, by_date in date_items:
        if not isinstance(by_date, dict):
            continue

        watched = None
        for key in keys:
            cand = by_date.get(key)
            if isinstance(cand, dict):
                watched = cand
                break
        if not isinstance(watched, dict):
            continue

        for mid, entry in watched.items():
            mid_s = str(mid or "").strip()
            if not mid_s:
                continue

            current = out.get(mid_s)
            normalized = normalize_watch_entry(entry)
            if current is None or watch_rank(normalized) > watch_rank(current):
                out[mid_s] = normalized

    return jsonify({"ok": True, "sid": sid, "date": date, "watch": out})

@bp_api_watch.route("/api/watch", methods=["GET", "POST"])
def api_watch():
    if request.method == "GET":
        if getattr(g, "student_app_public_request", False) is True:
            return jsonify({"ok": False, "error": "not found"}), 404
        return nocache_resp(load(WATCH_PATH))
    if not _academy_request_allowed():
        return jsonify({
            "ok": False,
            "error": "academy_network_required",
            "message": ACADEMY_ACCESS_MESSAGE,
        }), 403

    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid  = str(body.get("sid")  or "").strip()
    mid  = str(body.get("mid")  or "").strip()
    if not _public_sid_matches(sid):
        return jsonify({"ok": False, "code": "sid_mismatch", "error": "sid_mismatch"}), 403
    if not date or not sid or not mid:
        return jsonify({"ok": False, "error": "missing date/sid/mid"}), 400
    if not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

    try:
        last = max(0, int(float(body.get("last", 0))))
        dur  = max(0, int(float(body.get("dur", 0))))
        completed = bool(body.get("completed", False))
        updated_at = int(body.get("updatedAt") or int(time.time() * 1000))
    except Exception:
        return jsonify({"ok": False, "error": "invalid numeric fields"}), 400

    incoming = {
        "last": last,
        "dur": dur,
        "completed": completed,
        "updatedAt": updated_at,
    }

    merged = save_watch_entry(WATCH_PATH, date, sid, mid, incoming)
    status = watch_auto_status(merged)
    progress = (
        save_progress_status(PRG_PATH, STU_PATH, VID_PATH, date, sid, mid, status)
        if status
        else {}
    )

    return jsonify({"ok": True, "watch": merged, "progress": progress})


@bp_api_watch.post("/api/watch-status")
def api_watch_status():
    if not _academy_request_allowed():
        return jsonify({
            "ok": False,
            "error": "academy_network_required",
            "message": ACADEMY_ACCESS_MESSAGE,
        }), 403

    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    mid = str(body.get("mid") or "").strip()
    status = str(body.get("status") or "").strip()
    if not _public_sid_matches(sid):
        return jsonify({"ok": False, "code": "sid_mismatch", "error": "sid_mismatch"}), 403

    if not date or not sid or not mid:
        return jsonify({"ok": False, "error": "missing date/sid/mid"}), 400
    if not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403
    if status not in VALID_VIDEO_PROGRESS_STATUSES:
        return jsonify({"ok": False, "error": "bad status"}), 400

    if status == "interrupted":
        try:
            watch = get_watch_entry(WATCH_PATH, date, sid, mid)
            if watch_auto_status(watch) == "done":
                status = "done"
        except Exception:
            pass

    merged = save_progress_status(PRG_PATH, STU_PATH, VID_PATH, date, sid, mid, status)

    return jsonify({"ok": True, "progress": merged})
