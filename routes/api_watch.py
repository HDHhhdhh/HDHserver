from __future__ import annotations

import time
from flask import Blueprint, jsonify, request

from core.ghost_student import GHOST_STUDENT_WRITE_ERROR, is_ghost_student_sid
from core.network_access import ACADEMY_ACCESS_MESSAGE, academy_network_allowed
from core.paths import WATCH_PATH, PRG_PATH
from core.progress_rules import (
    PROGRESS_MANUAL_META_KEY,
    VALID_VIDEO_PROGRESS_STATUSES,
    WATCH_AUTO_PROGRESS_META_KEY,
    merge_progress_day_sid,
    merge_watch_entry,
    has_completed_video_before_date,
    normalize_watch_entry,
    watch_auto_status,
    watch_rank,
)
from core.storage import load, save_atomic, nocache_resp

bp_api_watch = Blueprint("api_watch", __name__)

AUTO_PROGRESS_META_KEY = WATCH_AUTO_PROGRESS_META_KEY
MANUAL_PROGRESS_META_KEY = PROGRESS_MANUAL_META_KEY


def _watch_lock():
    from routes.api_basic import _InterProcessFileLock

    wp = str(getattr(WATCH_PATH, "__fspath__", lambda: str(WATCH_PATH))())
    return _InterProcessFileLock(wp + ".lock", timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0)


def _sid_keys(sid: str) -> list[str]:
    keys = [str(sid or "").strip()]
    if keys[0].isdigit():
        alt = str(int(keys[0]))
        if alt not in keys:
            keys.append(alt)
    return [k for k in keys if k]


def _save_watch_entry(date: str, sid: str, mid: str, incoming) -> dict:
    date = str(date or "").strip()
    sid = str(sid or "").strip()
    mid = str(mid or "").strip()
    if not date or not sid or not mid:
        raise ValueError("missing date/sid/mid")

    merged_incoming = normalize_watch_entry(incoming)
    if not merged_incoming["updatedAt"]:
        merged_incoming["updatedAt"] = int(time.time() * 1000)

    with _watch_lock():
        data = load(WATCH_PATH)
        if not isinstance(data, dict):
            data = {}

        by_date = data.setdefault(date, {})
        if not isinstance(by_date, dict):
            by_date = {}
            data[date] = by_date

        by_sid = None
        sid_key = sid
        for key in _sid_keys(sid):
            cand = by_date.get(key)
            if isinstance(cand, dict):
                by_sid = cand
                sid_key = key
                break

        if by_sid is None:
            by_sid = {}
            by_date[sid_key] = by_sid

        prev = by_sid.get(mid, {})
        merged = merge_watch_entry(prev, merged_incoming)
        by_sid[mid] = merged

        save_atomic(WATCH_PATH, data)

    return merged


def _get_watch_entry(date: str, sid: str, mid: str) -> dict:
    data = load(WATCH_PATH)
    if not isinstance(data, dict):
        return {}
    by_date = data.get(str(date or "").strip())
    if not isinstance(by_date, dict):
        return {}
    for key in _sid_keys(sid):
        by_sid = by_date.get(key)
        if isinstance(by_sid, dict):
            return normalize_watch_entry(by_sid.get(str(mid or "").strip()))
    return {}


def _save_progress_status(date: str, sid: str, mid: str, status: str) -> dict:
    date = str(date or "").strip()
    sid = str(sid or "").strip()
    mid = str(mid or "").strip()
    status = str(status or "").strip()

    if not date or not sid or not mid:
        raise ValueError("missing date/sid/mid")
    if status not in VALID_VIDEO_PROGRESS_STATUSES:
        raise ValueError("bad status")

    from routes.api_basic import (
        _load_progress_strict,
        _progress_lock,
        _save_progress_strict,
        _reconcile_auto_assignment_after_progress,
    )

    with _progress_lock():
        current = dict(_load_progress_strict(PRG_PATH))

        if status == "interrupted" and has_completed_video_before_date(
            current,
            load(WATCH_PATH),
            sid_keys=_sid_keys(sid),
            mid=mid,
            before_date=date,
        ):
            status = "done"

        current_day = current.get(date)
        day = dict(current_day) if isinstance(current_day, dict) else {}
        current[date] = day

        sid_key = sid
        cur_sid = None
        for key in _sid_keys(sid):
            cand = day.get(key)
            if isinstance(cand, dict):
                sid_key = key
                cur_sid = cand
                break
        if cur_sid is None:
            cur_sid = {}

        merged = merge_progress_day_sid(cur_sid, {mid: status}, source="auto")

        if merged:
            day[sid_key] = merged
        else:
            day.pop(sid_key, None)

        if not day:
            current.pop(date, None)

        _save_progress_strict(current, PRG_PATH)

    try:
        _reconcile_auto_assignment_after_progress(
            date,
            sid,
            progress=current,
            watch=load(WATCH_PATH) or {},
        )
    except Exception as exc:
        # Playback progress must not fail because assignment cleanup is
        # temporarily unavailable.
        print("[watch] auto-assignment reconcile failed:", exc, flush=True)

    return merged


@bp_api_watch.get("/api/watch/latest")
def api_watch_latest():
    sid = str(request.args.get("sid") or "").strip()
    date = str(request.args.get("date") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "missing sid"}), 400

    data = load(WATCH_PATH)
    if not isinstance(data, dict):
        data = {}

    out = {}
    keys = _sid_keys(sid)
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
        return nocache_resp(load(WATCH_PATH))
    if not academy_network_allowed():
        return jsonify({
            "ok": False,
            "error": "academy_network_required",
            "message": ACADEMY_ACCESS_MESSAGE,
        }), 403

    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid  = str(body.get("sid")  or "").strip()
    mid  = str(body.get("mid")  or "").strip()
    if not date or not sid or not mid:
        return jsonify({"ok": False, "error": "missing date/sid/mid"}), 400
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

    merged = _save_watch_entry(date, sid, mid, incoming)
    status = watch_auto_status(merged)
    progress = _save_progress_status(date, sid, mid, status) if status else {}
    if status:
        try:
            from routes.api_basic import record_review_video_watch

            record_review_video_watch(date, sid, mid)
        except Exception as exc:
            # A counseling-note side effect must never make a valid watch save fail.
            print("[watch] review counseling sync failed:", exc, flush=True)

    return jsonify({"ok": True, "watch": merged, "progress": progress})


@bp_api_watch.post("/api/watch-status")
def api_watch_status():
    if not academy_network_allowed():
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

    if not date or not sid or not mid:
        return jsonify({"ok": False, "error": "missing date/sid/mid"}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403
    if status not in VALID_VIDEO_PROGRESS_STATUSES:
        return jsonify({"ok": False, "error": "bad status"}), 400

    if status == "interrupted":
        try:
            watch = _get_watch_entry(date, sid, mid)
            if watch_auto_status(watch) == "done":
                status = "done"
        except Exception:
            pass

    merged = _save_progress_status(date, sid, mid, status)
    if status in {"interrupted", "done"}:
        try:
            from routes.api_basic import record_review_video_watch

            record_review_video_watch(date, sid, mid)
        except Exception as exc:
            print("[watch-status] review counseling sync failed:", exc, flush=True)

    return jsonify({"ok": True, "progress": merged})
