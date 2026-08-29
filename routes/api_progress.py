from __future__ import annotations

from flask import Blueprint, jsonify, request

from core.date_rules import is_iso_date_key
from core.ghost_student import GHOST_STUDENT_WRITE_ERROR, is_ghost_student_sid
from core.paths import PRG_PATH, STU_PATH, VID_PATH
from core.progress_notifications import commit_progress_notifications, progress_notification_snapshot
from core.progress_rules import merge_progress_day_sid
from core.progress_store import load_progress_strict, progress_file_lock, save_progress_strict


bp_api_progress = Blueprint("api_progress", __name__)


def _load_progress_strict(path=None) -> dict:
    return load_progress_strict(path or PRG_PATH)


def _save_progress_strict(data: dict, path=None) -> None:
    save_progress_strict(path or PRG_PATH, data)


def _progress_lock():
    return progress_file_lock(PRG_PATH)


def _sid_lookup(mapping: dict, sid: str):
    if not isinstance(mapping, dict):
        return None
    keys = [str(sid or "").strip()]
    if keys[0].isdigit():
        numeric = str(int(keys[0]))
        if numeric not in keys:
            keys.append(numeric)
    for key in keys:
        if key and key in mapping:
            return mapping.get(key)
    return None


def _progress_sids_from_query() -> list[str]:
    sid_values = request.args.getlist("sid")
    raw_values = list(request.args.getlist("sids"))
    if raw_values:
        raw_values.extend(sid_values)
    elif len(sid_values) > 1:
        raw_values.extend(sid_values)

    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        for part in str(raw or "").split(","):
            sid = part.strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            out.append(sid)
    return out


def _progress_for_sids(data: dict, sids: list[str], date: str = "") -> dict:
    out = {}
    days = (
        [(date, data.get(date) if isinstance(data, dict) else {})]
        if date
        else (data.items() if isinstance(data, dict) else [])
    )
    for day_key, day in days:
        if not isinstance(day, dict):
            continue
        filtered = {}
        for sid in sids:
            entry = _sid_lookup(day, sid)
            if isinstance(entry, dict) and entry:
                filtered[str(sid)] = entry
        if filtered:
            out[str(day_key)] = filtered
    if date and date not in out:
        out[date] = {}
    return out


def _notification_progress_snapshot(progress: dict, sid: str):
    return progress_notification_snapshot(
        progress,
        sid,
        students_path=STU_PATH,
        videos_path=VID_PATH,
    )


def _notification_progress_commit(before, after, sid: str) -> int:
    return commit_progress_notifications(before, after, sid)


@bp_api_progress.route("/api/progress", methods=["GET"])
def api_progress():
    date = str(request.args.get("date") or "").strip()
    sid = str(request.args.get("sid") or "").strip()
    sids = _progress_sids_from_query()

    if date and not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400

    data = _load_progress_strict()
    if date:
        day = data.get(date) if isinstance(data, dict) else {}
        if sids:
            return jsonify(_progress_for_sids(data, sids, date=date))
        if sid:
            entry = _sid_lookup(day if isinstance(day, dict) else {}, sid) or {}
            return jsonify({date: {str(sid): entry}})
        return jsonify({date: day if isinstance(day, dict) else {}})

    if sids:
        return jsonify(_progress_for_sids(data, sids))

    if sid:
        out = {}
        for day_key, day in (data.items() if isinstance(data, dict) else []):
            if not isinstance(day, dict):
                continue
            entry = _sid_lookup(day, sid)
            if isinstance(entry, dict) and entry:
                out[day_key] = {str(sid): entry}
        return jsonify(out)

    return jsonify(data)


@bp_api_progress.post("/api/progress/patch")
def api_progress_patch():
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    progress_patch = body.get("progress") or {}
    source = str(body.get("source") or "").strip()

    if not date or not sid or not isinstance(progress_patch, dict):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

    try:
        with _progress_lock():
            current = dict(_load_progress_strict())
            notification_before = _notification_progress_snapshot(current, sid)

            current_day = current.get(date)
            day = dict(current_day) if isinstance(current_day, dict) else {}
            current[date] = day

            current_sid = day.get(sid, {})
            if not isinstance(current_sid, dict):
                current_sid = {}

            merged = merge_progress_day_sid(current_sid, progress_patch, source=source)

            if merged:
                day[sid] = merged
            else:
                day.pop(sid, None)

            if not day:
                current.pop(date, None)

            _save_progress_strict(current)
            notification_after = _notification_progress_snapshot(current, sid)

        _notification_progress_commit(notification_before, notification_after, sid)
        return jsonify({"ok": True, "progress": merged})
    except TimeoutError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
