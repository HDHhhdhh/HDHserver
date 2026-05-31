from __future__ import annotations

import time
from flask import Blueprint, jsonify, request

from core.paths import WATCH_PATH, PRG_PATH
from core.progress_rules import (
    PROGRESS_MANUAL_META_KEY,
    VALID_VIDEO_PROGRESS_STATUSES,
    WATCH_AUTO_PROGRESS_META_KEY,
    WATCH_DONE_RATIO,
    WATCH_INTERRUPTED_RATIO,
    merge_auto_watch_progress_status,
    merge_watch_entry as _merge_watch_entry,
    normalize_watch_entry as _norm_watch_entry,
    watch_auto_status as _watch_auto_status,
    watch_rank as _watch_rank,
    watch_ratio as _watch_ratio,
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

    merged_incoming = _norm_watch_entry(incoming)
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
        merged = _merge_watch_entry(prev, merged_incoming)
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
            return _norm_watch_entry(by_sid.get(str(mid or "").strip()))
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

    from routes.api_basic import _load_progress_strict, _progress_lock

    with _progress_lock():
        current = _load_progress_strict()

        day = current.setdefault(date, {})
        if not isinstance(day, dict):
            day = {}
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

        merged = merge_auto_watch_progress_status(cur_sid, mid, status)

        if merged:
            day[sid_key] = merged
        else:
            day.pop(sid_key, None)

        if not day:
            current.pop(date, None)

        save_atomic(PRG_PATH, current)

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
            normalized = _norm_watch_entry(entry)
            if current is None or _watch_rank(normalized) > _watch_rank(current):
                out[mid_s] = normalized

    return jsonify({"ok": True, "sid": sid, "date": date, "watch": out})

@bp_api_watch.route("/api/watch", methods=["GET", "POST"])
def api_watch():
    if request.method == "GET":
        return nocache_resp(load(WATCH_PATH))

    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid  = str(body.get("sid")  or "").strip()
    mid  = str(body.get("mid")  or "").strip()
    if not date or not sid or not mid:
        return jsonify({"ok": False, "error": "missing date/sid/mid"}), 400

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
    status = _watch_auto_status(merged)
    progress = _save_progress_status(date, sid, mid, status) if status else {}

    return jsonify({"ok": True, "watch": merged, "progress": progress})


@bp_api_watch.post("/api/watch-status")
def api_watch_status():
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    mid = str(body.get("mid") or "").strip()
    status = str(body.get("status") or "").strip()

    if not date or not sid or not mid:
        return jsonify({"ok": False, "error": "missing date/sid/mid"}), 400
    if status not in VALID_VIDEO_PROGRESS_STATUSES:
        return jsonify({"ok": False, "error": "bad status"}), 400

    if status == "interrupted":
        try:
            watch = _get_watch_entry(date, sid, mid)
            if _watch_auto_status(watch) == "done":
                status = "done"
        except Exception:
            pass

    merged = _save_progress_status(date, sid, mid, status)

    return jsonify({"ok": True, "progress": merged})
