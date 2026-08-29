from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from core import log_rules
from core.date_rules import is_iso_date_key
from core.ghost_student import GHOST_STUDENT_WRITE_ERROR, is_ghost_student_sid
from core.storage import nocache_resp
from routes.log_repository_provider import get_log_repository, repair_log_entry_placeholders


bp_api_logs = Blueprint("api_logs", __name__)


def _sids_from_query() -> list[str]:
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


def _log_export_targets_from_query() -> dict[str, str] | None:
    raw = request.args.get("exportTargets")
    if raw is None:
        return None
    if len(raw) > 65536:
        raise ValueError("too many export targets")
    try:
        rows = json.loads(raw)
    except Exception as exc:
        raise ValueError("invalid export targets") from exc
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("invalid export targets")

    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("invalid export target")
        sid = str(row[0] or "").strip()
        date = str(row[1] or "").strip()
        if not sid or not is_iso_date_key(date):
            raise ValueError("invalid export target")
        previous = out.get(sid, "")
        if date > previous:
            out[sid] = date
    return out


@bp_api_logs.get("/api/logs/entry")
def api_logs_entry():
    date = str(request.args.get("date") or "").strip()
    sid = str(request.args.get("sid") or "").strip()
    if not date or not sid or not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad query"}), 400

    result = get_log_repository().read_entry(date, sid)
    return jsonify({"ok": True, "source": result.source, "entry": result.entry})


@bp_api_logs.get("/api/logs/unarchived-summary")
def api_logs_unarchived_summary():
    exclude_date = str(
        request.args.get("exclude_date")
        or request.args.get("excludeDate")
        or ""
    ).strip()
    if exclude_date and not is_iso_date_key(exclude_date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    return nocache_resp(get_log_repository().summarize_unarchived_done(exclude_date))


@bp_api_logs.get("/api/homework-books")
def api_homework_books():
    logs = get_log_repository().read_logs()
    return nocache_resp(log_rules.latest_homework_books_by_student(logs))


@bp_api_logs.get("/api/logs")
def api_logs():
    date_filter = str(request.args.get("date") or "").strip()
    sid_filter = str(request.args.get("sid") or "").strip()
    sid_filters = _sids_from_query()
    if date_filter and not is_iso_date_key(date_filter):
        return jsonify({"ok": False, "error": "bad date"}), 400
    try:
        export_targets = _log_export_targets_from_query()
    except ValueError:
        return jsonify({"ok": False, "error": "bad exportTargets"}), 400

    repository = get_log_repository()
    if export_targets is not None:
        return nocache_resp(repository.read_export_history(export_targets))
    return nocache_resp(
        repository.read_logs(
            date_filter,
            sid_filter,
            sid_filters=sid_filters,
        )
    )


@bp_api_logs.post("/api/logs/patch")
def api_logs_patch():
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    entry = body.get("entry") or {}
    base = body.get("base") if isinstance(body.get("base"), dict) else {}

    top_clear = body.get("__clear")
    if isinstance(top_clear, list) and isinstance(entry, dict):
        entry = dict(entry)
        entry["__clear"] = top_clear

    if not date or not sid or not isinstance(entry, dict):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if not is_iso_date_key(date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

    entry = repair_log_entry_placeholders(entry, sid)
    base = repair_log_entry_placeholders(base, sid)
    result = get_log_repository().patch_entry(date, sid, entry, base)

    if result.json_conflict_entry is not None:
        return jsonify({
            "ok": False,
            "retryable": False,
            "error": "다른 화면에서 특이사항/숙제가 먼저 변경되었습니다. 새로고침 후 다시 저장해 주세요.",
            "entry": result.json_conflict_entry,
        }), 409

    if not result.sqlite_ok:
        if result.sqlite_base_conflict:
            if not result.json_ok:
                return jsonify({
                    "ok": False,
                    "sqlite": False,
                    "json": False,
                    "error": "sqlite out-of-sync and legacy logs.json save failed",
                }), 409
            return jsonify({
                "ok": True,
                "sqlite": False,
                "json": result.json_ok,
                "entry": result.merged,
                "warning": "sqlite out-of-sync",
            })
        return jsonify({
            "ok": False,
            "sqlite": False,
            "error": str(result.sqlite_error) if result.sqlite_error else "sqlite failed",
        }), 409

    if not result.json_ok:
        return jsonify({
            "ok": True,
            "sqlite": True,
            "json": False,
            "entry": result.merged,
            "warning": "SQLite save succeeded, but legacy JSON log storage is out of sync.",
        })

    return jsonify({"ok": True, "sqlite": True, "json": True, "entry": result.merged})


@bp_api_logs.post("/api/logs/patch-batch")
def api_logs_patch_batch():
    body = request.get_json(force=True) or {}
    patches = body.get("patches")
    if not isinstance(patches, list) or not 1 <= len(patches) <= 100:
        return jsonify({"ok": False, "error": "patches must contain 1 to 100 items"}), 400

    incoming = {}
    seen = set()
    for raw in patches:
        if not isinstance(raw, dict):
            return jsonify({"ok": False, "error": "bad patch item"}), 400

        date = str(raw.get("date") or "").strip()
        sid = str(raw.get("sid") or "").strip()
        entry = raw.get("entry") or {}
        clear = raw.get("__clear")

        if (
            not date
            or not sid
            or not is_iso_date_key(date)
            or not isinstance(entry, dict)
        ):
            return jsonify({"ok": False, "error": "bad patch item"}), 400
        if clear is not None and not isinstance(clear, list):
            return jsonify({"ok": False, "error": "bad clear list"}), 400
        if is_ghost_student_sid(sid):
            return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

        target_key = (date, sid)
        if target_key in seen:
            return jsonify({"ok": False, "error": "duplicate patch target"}), 400
        seen.add(target_key)

        safe_entry = dict(entry)
        if isinstance(clear, list) and clear:
            safe_entry["__clear"] = clear
        incoming.setdefault(date, {})[sid] = repair_log_entry_placeholders(safe_entry, sid)

    result = get_log_repository().legacy_post(incoming)
    if not result.sqlite_ok:
        return jsonify({
            "ok": False,
            "sqlite": False,
            "error": "batch sqlite save failed",
        }), 409

    return jsonify({"ok": True, "sqlite": True, "json": True, "count": len(seen)})


__all__ = ("bp_api_logs",)
