from __future__ import annotations

import time

from flask import Blueprint, jsonify, request

from core.date_rules import is_iso_date_key
from core.ghost_student import GHOST_STUDENT_WRITE_ERROR, is_ghost_student_sid
from core.paths import PRG_PATH, STU_PATH, VID_PATH
from core.progress_notifications import commit_progress_notifications, progress_notification_snapshot
from core.progress_rules import merge_progress_day_sid
from core.progress_store import load_progress_scope, load_progress_strict, progress_file_lock, save_progress_strict
from core.video_watch_cycles import WatchCycleConflict, latest_watch_cycles, rearm_watch_cycles, validate_watch_rearms
from core.video_sources import is_youtube_mid, youtube_record_cleanup_patch


bp_api_progress = Blueprint("api_progress", __name__)


class RecordCleanupConflict(ValueError):
    pass


@bp_api_progress.after_request
def advertise_watch_cycle_support(response):
    response.headers["X-Video-Watch-Cycles"] = "1"
    response.headers["X-YouTube-Record-Cleanup"] = "1"
    return response


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


def _youtube_cleanup_inputs(date: str, sid: str):
    # The request-level exclusive absence barrier covers these related reads.
    # Resolve only for the explicit command; ordinary PATCH keeps its old I/O.
    import json
    from core.paths import ABS_PATH, UPD_PATH
    from core.log_rules import truthy
    from core.student_schedule_rules import student_absent_on_date
    from core.update_assignment_store import load_updates_strict
    from routes.log_repository_provider import get_log_repository

    logs = get_log_repository().read_logs(date, sid)
    entry = _sid_lookup(logs.get(date, {}), sid) if isinstance(logs, dict) else None
    if not isinstance(entry, dict) or not truthy(entry.get("done")) or truthy(entry.get("archived")):
        raise RecordCleanupConflict("최신 하원 기록을 확인하세요. 기록정리 대상이 변경되었습니다.")
    absent = json.loads(ABS_PATH.read_text("utf-8-sig"))
    if not isinstance(absent, dict):
        raise ValueError("invalid absence store")
    if student_absent_on_date(absent, date, sid):
        raise RecordCleanupConflict("결석 학생은 영상 완료 처리할 수 없습니다.")
    videos = json.loads(VID_PATH.read_text("utf-8-sig"))
    if not isinstance(videos, list) or any(not isinstance(row, dict) for row in videos):
        raise ValueError("invalid video catalog")
    updates = load_updates_strict(UPD_PATH)
    return _sid_lookup(updates.get(date, {}), sid), videos


def read_progress_projection(*, date="", sid="", sids=(), since=""):
    data = load_progress_scope(PRG_PATH, date=date, sids=sids or ([sid] if sid else []), since=since)
    if date:
        day = data.get(date) if isinstance(data, dict) else {}
        if sids:
            return _progress_for_sids(data, sids, date=date)
        if sid:
            entry = _sid_lookup(day if isinstance(day, dict) else {}, sid) or {}
            return {date: {str(sid): entry}}
        return {date: day if isinstance(day, dict) else {}}

    if sids:
        return _progress_for_sids(data, sids)

    if sid:
        out = {}
        for day_key, day in (data.items() if isinstance(data, dict) else []):
            if not isinstance(day, dict):
                continue
            entry = _sid_lookup(day, sid)
            if isinstance(entry, dict) and entry:
                out[day_key] = {str(sid): entry}
        return out

    return data


@bp_api_progress.route("/api/progress", methods=["GET"])
def api_progress():
    date = str(request.args.get("date") or "").strip()
    sid = str(request.args.get("sid") or "").strip()
    sids = _progress_sids_from_query()
    since = str(request.args.get("since") or "").strip()
    if (date and not is_iso_date_key(date)) or (since and not is_iso_date_key(since)):
        return jsonify({"ok": False, "error": "bad date"}), 400
    if not date and not sid and not sids:
        return jsonify({"ok": False, "error": "filter_required"}), 400

    return jsonify(read_progress_projection(date=date, sid=sid, sids=sids, since=since))


@bp_api_progress.post("/api/progress/patch")
def api_progress_patch():
    body = request.get_json(force=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    progress_patch = body.get("progress") or {}
    source = str(body.get("source") or "").strip()
    complete_youtube = body.get("completeAssignedYouTube", False)

    if not date or not sid or not isinstance(progress_patch, dict):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403
    if type(complete_youtube) is not bool or (complete_youtube and (source == "auto" or body.get("resumeAutoWatch"))):
        return jsonify({"ok": False, "error": "invalid YouTube cleanup command"}), 400

    try:
        rearms = validate_watch_rearms(body.get("resumeAutoWatch", {}), source)
        if any(is_youtube_mid(mid) for mid in rearms) or (source == "auto" and any(is_youtube_mid(mid) for mid in progress_patch)):
            raise ValueError("youtube watch tracking is disabled")
        if any(mid in progress_patch and progress_patch[mid] != "none" for mid in rearms):
            raise ValueError("conflicting resumeAutoWatch status")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        youtube_inputs = _youtube_cleanup_inputs(date, sid) if complete_youtube else None
        with _progress_lock():
            current = dict(_load_progress_strict())
            if source == "auto" and any(mid in latest_watch_cycles(current, sid, date) for mid in progress_patch):
                raise WatchCycleConflict("새 시청 진도는 해당 세대의 시청 기록으로만 갱신할 수 있습니다.")
            notification_before = _notification_progress_snapshot(current, sid)

            current_day = current.get(date)
            day = dict(current_day) if isinstance(current_day, dict) else {}
            current[date] = day

            progress_sid = sid
            if complete_youtube and sid not in day and sid.isdigit() and str(int(sid)) in day:
                progress_sid = str(int(sid))
            current_sid = day.get(progress_sid, {})
            if not isinstance(current_sid, dict):
                if complete_youtube:
                    raise RecordCleanupConflict("최신 진행 기록 형식을 확인할 수 없습니다.")
                current_sid = {}

            # Replayed rearm commands cannot rewrite a newer watch/manual state.
            changes = {key: value for key, value in progress_patch.items() if key not in rearms}
            if youtube_inputs is not None:
                assignment, videos = youtube_inputs
                changes.update(youtube_record_cleanup_patch(assignment, current_sid, videos))
            merged = merge_progress_day_sid(current_sid, changes, source=source)
            if rearms:
                merged = rearm_watch_cycles(merged, rearms, int(time.time() * 1000))

            if merged:
                day[progress_sid] = merged
            else:
                day.pop(progress_sid, None)

            if not day:
                current.pop(date, None)

            if not complete_youtube or merged != current_sid:
                _save_progress_strict(current)
            notification_after = _notification_progress_snapshot(current, sid)

        _notification_progress_commit(notification_before, notification_after, sid)
        return jsonify({"ok": True, "progress": merged})
    except RecordCleanupConflict as exc:
        return jsonify({"ok": False, "code": "record_cleanup_conflict", "error": str(exc)}), 409
    except WatchCycleConflict as exc:
        return jsonify({"ok": False, "code": "watch_cycle_conflict", "error": str(exc)}), 409
    except TimeoutError:
        return jsonify({
            "ok": False,
            "code": "progress_lock_timeout",
            "retryable": True,
            "error": "진도 저장 요청이 잠시 겹쳤습니다. 자동으로 다시 시도합니다.",
        }), 409
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
