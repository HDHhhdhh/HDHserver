from __future__ import annotations

import re

from flask import Blueprint, current_app, jsonify, make_response, request

from core.paths import CAL_PATH
from core.school_calendar_store import (
    SchoolCalendarConflictError,
    SchoolCalendarUnavailableError,
    load_school_calendar_snapshot,
    replace_school_calendar,
)


bp_api_school_calendar = Blueprint("api_school_calendar", __name__)


def _normalize_school_calendar_revision(value: str | None) -> str:
    revision = str(value or "").strip()
    if revision.startswith("W/"):
        revision = revision[2:].strip()
    return revision.strip('"').lower()


def _school_calendar_response(payload: dict, revision: str, status: int = 200):
    response = make_response(jsonify(payload), status)
    response.headers["X-School-Calendar-Revision"] = revision
    response.headers["ETag"] = f'"{revision}"'
    response.headers["Cache-Control"] = "no-store"
    return response


@bp_api_school_calendar.route("/api/school-calendar", methods=["GET", "POST"])
def api_school_calendar():
    try:
        if request.method == "GET":
            document, revision = load_school_calendar_snapshot(CAL_PATH)
            return _school_calendar_response(document, revision)

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"ok": False, "code": "invalid_school_calendar"}), 400

        expected_revision = _normalize_school_calendar_revision(
            request.headers.get("If-Match")
        )
        if not re.fullmatch(r"[0-9a-f]{64}", expected_revision):
            _document, revision = load_school_calendar_snapshot(CAL_PATH)
            return _school_calendar_response(
                {"ok": False, "code": "school_calendar_revision_required"},
                revision,
                428,
            )

        try:
            revision = replace_school_calendar(
                CAL_PATH,
                data,
                expected_revision=expected_revision,
            )
        except SchoolCalendarConflictError as exc:
            return _school_calendar_response(
                {"ok": False, "code": "school_calendar_conflict"},
                exc.current_revision,
                409,
            )
        return _school_calendar_response(data, revision)
    except (SchoolCalendarUnavailableError, TimeoutError) as exc:
        current_app.logger.error("School calendar is unavailable: %s", exc)
        return jsonify({"ok": False, "code": "school_calendar_unavailable"}), 503
