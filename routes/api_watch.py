from __future__ import annotations

import time
from flask import Blueprint, jsonify, request

from core.paths import WATCH_PATH, PRG_PATH
from core.storage import load, save_atomic, nocache_resp

bp_api_watch = Blueprint("api_watch", __name__)


def _watch_lock():
    from routes.api_basic import _InterProcessFileLock

    wp = str(getattr(WATCH_PATH, "__fspath__", lambda: str(WATCH_PATH))())
    return _InterProcessFileLock(wp + ".lock", timeout_sec=6.0, poll_sec=0.05)


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
    if dur > 0 and last >= max(dur - 1, int(dur * 0.95)):
        completed = True

    return {
        "last": last,
        "dur": dur,
        "completed": completed,
        "updatedAt": updated_at,
    }


def _merge_watch_entry(prev, incoming) -> dict:
    a = _norm_watch_entry(prev)
    b = _norm_watch_entry(incoming)

    last = max(a["last"], b["last"])
    dur = max(a["dur"], b["dur"])
    completed = a["completed"] or b["completed"]
    if dur > 0 and last >= max(dur - 1, int(dur * 0.95)):
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

        # watch-status는 "자동 반영" 경로이므로 수동으로 지정된 상태를 우선한다.
        # "none"은 관리자가 수동으로 흰색 처리한 명시 상태이므로 자동값으로 덮지 않는다.
        # - interrupted 자동값은 기존 상태가 없을 때만 세팅
        # - done 자동값은 interrupted를 done으로 올리는 것만 허용
        # - skip/done은 자동값으로 덮어쓰지 않음
        if status in ("", "none"):
            if prev not in ("done", "interrupted", "skip", "none"):
                merged.pop(mid, None)
        elif status == "interrupted":
            if prev in ("done", "interrupted", "skip", "none"):
                pass
            else:
                merged[mid] = "interrupted"
        elif status == "done":
            if prev == "none":
                merged[mid] = "none"
            elif prev == "skip":
                merged[mid] = "skip"
            else:
                merged[mid] = "done"
        elif status == "skip":
            if prev in ("done", "none"):
                pass
            else:
                merged[mid] = "skip"
        else:
            merged[mid] = status

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
    if not sid:
        return jsonify({"ok": False, "error": "missing sid"}), 400

    data = load(WATCH_PATH)
    if not isinstance(data, dict):
        data = {}

    out = {}
    keys = _sid_keys(sid)
    for by_date in data.values():
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

    return jsonify({"ok": True, "sid": sid, "watch": out})

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

    return jsonify({"ok": True, "watch": merged})


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

    merged = _save_progress_status(date, sid, mid, status)

    return jsonify({"ok": True, "progress": merged})
