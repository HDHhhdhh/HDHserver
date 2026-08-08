from __future__ import annotations

import datetime as dt
import re
from typing import Final
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from core.student_logs import StudentOperationLogRepository


bp_api_student_logs = Blueprint("api_student_logs", __name__)
ADMIN_REFERER_PATHS: Final = frozenset({"/admin", "/dh1130"})
MAX_SID_LENGTH: Final = 120
MAX_NAME_LENGTH: Final = 120
MAX_COMMENT_LENGTH: Final = 300
ALLOWED_KINDS: Final = frozenset({"homework_insufficient"})
DATE_PATTERN: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KST: Final = dt.timezone(dt.timedelta(hours=9))


def get_repository() -> StudentOperationLogRepository:
    return StudentOperationLogRepository()


def _admin_surface_allowed() -> bool:
    raw = (request.headers.get("Referer") or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    host = (request.host or "").lower()
    if parsed.netloc and parsed.netloc.lower() != host:
        return False
    return (parsed.path.rstrip("/") or "/") in ADMIN_REFERER_PATHS


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


@bp_api_student_logs.before_request
def require_admin_surface():
    if not _admin_surface_allowed():
        return jsonify({"ok": False, "error": "student logs are only available from the admin page"}), 403


@bp_api_student_logs.get("/api/student-logs")
def list_student_logs():
    return jsonify({"ok": True, "logs": get_repository().list_all()})


@bp_api_student_logs.post("/api/student-logs")
def create_student_log():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "JSON object is required"}), 400

    sid = _clean_text(payload.get("sid"))
    student_name = _clean_text(payload.get("studentName"))
    kind = _clean_text(payload.get("kind"))
    comment = _clean_text(payload.get("comment"))
    date = _clean_text(payload.get("date"))

    if not sid or len(sid) > MAX_SID_LENGTH:
        return jsonify({"ok": False, "error": "sid is required"}), 400
    if not student_name or len(student_name) > MAX_NAME_LENGTH:
        return jsonify({"ok": False, "error": "studentName is required"}), 400
    if kind not in ALLOWED_KINDS:
        return jsonify({"ok": False, "error": "unsupported log kind"}), 400
    if not comment:
        return jsonify({"ok": False, "error": "comment is required"}), 400
    if len(comment) > MAX_COMMENT_LENGTH:
        return jsonify({"ok": False, "error": "comment too long"}), 400

    if not date:
        date = dt.datetime.now(KST).date().isoformat()
    if not DATE_PATTERN.fullmatch(date):
        return jsonify({"ok": False, "error": "date must be YYYY-MM-DD"}), 400

    log = get_repository().create(
        sid=sid,
        student_name=student_name,
        kind=kind,
        comment=comment,
        date=date,
    )
    return jsonify({"ok": True, "log": log}), 201


@bp_api_student_logs.delete("/api/student-logs")
def clear_student_logs():
    deleted = get_repository().clear_all()
    return jsonify({"ok": True, "deleted": deleted})


__all__ = ["bp_api_student_logs", "get_repository"]
