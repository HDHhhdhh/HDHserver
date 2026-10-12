from __future__ import annotations

import time
import datetime as dt
import os
from flask import Blueprint, g, jsonify, request

from core.date_rules import is_iso_date_key
from core.isolated_kollus_qa import ENV as KOLLUS_QA_ENV, isolated_kollus_qa_allowed
from core.ghost_student import GHOST_STUDENT_WRITE_ERROR, is_ghost_student_sid
from core.network_access import ACADEMY_ACCESS_MESSAGE, academy_network_allowed, ip_allowed
from core.paths import PRG_PATH, STU_PATH, VID_PATH, WATCH_PATH
from core.progress_rules import (
    VALID_VIDEO_PROGRESS_STATUSES,
    normalize_watch_entry,
    watch_auto_status,
    watch_rank,
)
from core.storage import nocache_resp
from core.watch_store import WatchStoreReadError, load_watch_strict
from core.progress_store import load_progress_strict
from core.video_watch_cycles import latest_watch_projection
from core.video_sources import is_youtube_mid
from core.watch_progress_writer import (
    get_watch_entry,
    save_progress_status,
    save_watch_entry,
    sid_keys,
    save_watch_observation_progress,
)

bp_api_watch = Blueprint("api_watch", __name__)


@bp_api_watch.errorhandler(WatchStoreReadError)
def _watch_store_unavailable(_error):
    return jsonify({"ok": False, "error": "watch_store_unavailable"}), 503


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

    data = load_watch_strict(WATCH_PATH)

    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    out = latest_watch_projection(data, load_progress_strict(PRG_PATH), sid, date or today, date=date)

    return jsonify({"ok": True, "sid": sid, "date": date, "watch": out})

@bp_api_watch.route("/api/watch", methods=["GET", "POST"])
def api_watch():
    if request.method == "GET":
        if getattr(g, "student_app_public_request", False) is True:
            return jsonify({"ok": False, "error": "not found"}), 404
        return nocache_resp(load_watch_strict(WATCH_PATH))
    academy_allowed = _academy_request_allowed()
    qa_body = request.get_json(silent=True) if not academy_allowed and os.environ.get(KOLLUS_QA_ENV) == "1" else None
    qa_allowed = isinstance(qa_body, dict) and isolated_kollus_qa_allowed(
        str(qa_body.get("sid") or "").strip(), str(qa_body.get("mid") or "").strip()
    )
    if not academy_allowed and not qa_allowed:
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
    if is_youtube_mid(mid):
        return jsonify({"ok": False, "error": "youtube watch tracking is disabled"}), 400
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
    progress, cycle_watch, stale = save_watch_observation_progress(
        PRG_PATH, STU_PATH, VID_PATH, date, sid, mid, status,
        observation=incoming, cycle_token=str(body.get("cycleToken") or ""),
    )
    if stale:
        return jsonify({"ok": False, "code": "watch_cycle_changed", "watch": cycle_watch}), 409

    return jsonify({"ok": True, "watch": cycle_watch or merged, "progress": progress})


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
    if is_youtube_mid(mid):
        return jsonify({"ok": False, "error": "youtube watch tracking is disabled"}), 400

    if status == "interrupted":
        watch = get_watch_entry(WATCH_PATH, date, sid, mid)
        if watch_auto_status(watch) == "done":
            status = "done"

    merged = save_progress_status(PRG_PATH, STU_PATH, VID_PATH, date, sid, mid, status)

    return jsonify({"ok": True, "progress": merged})
