from __future__ import annotations

import time
from flask import Blueprint, jsonify, request

from core.paths import WATCH_PATH, PRG_PATH
from core.storage import load, save_atomic, nocache_resp

bp_api_watch = Blueprint("api_watch", __name__)

WATCH_INTERRUPTED_RATIO = 0.05
WATCH_DONE_RATIO = 0.90
AUTO_PROGRESS_META_KEY = "__autoWatchProgressMids"
MANUAL_PROGRESS_META_KEY = "__manualProgressMids"


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


def _norm_watch_entry(entry) -> dict:
    if not isinstance(entry, dict):
        entry = {}

    try:
        last = max(0, int(float(entry.get("last", 0) or 0)))
    except Exception:
        last = 0
    try:
        dur = max(0, int(float(entry.get("dur", 0) or 0)))
    except Exception:
        dur = 0
    try:
        updated_at = int(entry.get("updatedAt") or 0)
    except Exception:
        updated_at = 0

    completed = bool(entry.get("completed", False))
    if _watch_ratio({"last": last, "dur": dur}) >= WATCH_DONE_RATIO:
        completed = True

    return {
        "last": last,
        "dur": dur,
        "completed": completed,
        "updatedAt": updated_at,
    }


def _watch_ratio(entry) -> float:
    if not isinstance(entry, dict):
        return 0.0
    try:
        last = max(0, float(entry.get("last", 0) or 0))
        dur = max(0, float(entry.get("dur", 0) or 0))
    except Exception:
        return 0.0
    return last / dur if dur > 0 else 0.0


def _watch_auto_status(entry) -> str:
    e = _norm_watch_entry(entry)
    pct = _watch_ratio(e)
    if e["completed"] or pct >= WATCH_DONE_RATIO:
        return "done"
    if pct >= WATCH_INTERRUPTED_RATIO or (e["dur"] <= 0 and e["last"] > 0):
        return "interrupted"
    return ""


def _merge_watch_entry(prev, incoming) -> dict:
    a = _norm_watch_entry(prev)
    b = _norm_watch_entry(incoming)

    last = max(a["last"], b["last"])
    dur = max(a["dur"], b["dur"])
    completed = a["completed"] or b["completed"]
    if _watch_ratio({"last": last, "dur": dur}) >= WATCH_DONE_RATIO:
        completed = True

    return {
        "last": last,
        "dur": dur,
        "completed": completed,
        "updatedAt": max(a["updatedAt"], b["updatedAt"]),
    }


def _watch_rank(entry: dict) -> tuple:
    e = _norm_watch_entry(entry)
    pct = (e["last"] / e["dur"]) if e["dur"] > 0 else (1.0 if e["completed"] else 0.0)
    return (
        1 if e["completed"] else 0,
        pct,
        e["last"],
        e["updatedAt"],
    )


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
    if status not in ("done", "interrupted", "skip", "none", ""):
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

        merged = dict(cur_sid)
        prev = str(cur_sid.get(mid) or "").strip()
        auto_meta = cur_sid.get(AUTO_PROGRESS_META_KEY)
        if not isinstance(auto_meta, dict):
            auto_meta = {}
        else:
            auto_meta = dict(auto_meta)
        prev_auto = prev in ("done", "interrupted") and str(auto_meta.get(mid) or "").strip() == prev
        manual_meta = cur_sid.get(MANUAL_PROGRESS_META_KEY)
        manual_override = isinstance(manual_meta, dict) and bool(manual_meta.get(mid))

        def set_auto(value: str) -> None:
            merged[mid] = value
            auto_meta[mid] = value

        # Automatic watch progress may advance only values it wrote before.
        # Manual progress patches remove this marker in routes.api_basic.
        if status in ("", "none"):
            if prev_auto and prev != "done":
                merged.pop(mid, None)
                auto_meta.pop(mid, None)
            elif prev_auto and prev == "done":
                pass
            elif prev not in ("done", "interrupted", "skip", "none"):
                merged.pop(mid, None)
        elif status == "interrupted":
            if prev == "":
                set_auto("interrupted")
            elif prev_auto and prev != "done":
                set_auto("interrupted")
        elif status == "done":
            # Legacy auto-interrupted records predate AUTO_PROGRESS_META_KEY, so
            # allow a done upgrade unless a newer manual patch marked the mid.
            if prev == "" or prev_auto or (prev == "interrupted" and not manual_override):
                set_auto("done")
        elif status == "skip":
            if prev == "":
                set_auto("skip")
        else:
            merged[mid] = status

        if auto_meta:
            merged[AUTO_PROGRESS_META_KEY] = auto_meta
        else:
            merged.pop(AUTO_PROGRESS_META_KEY, None)

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
    if status not in ("done", "interrupted", "skip", "none", ""):
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
