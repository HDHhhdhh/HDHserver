"""Native student API: explicit projection, session authority, no content links."""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, urlparse

from flask import Blueprint, current_app, g, jsonify, request

from core.student_app_v2 import content, homework, projections, submissions
from core.student_app_v2.contracts import (
    ApiError, authority, date_key, error_payload, network, now, require_academy,
)
from core.student_app_v2.ledger import Ledger

bp_api_student_app_v2 = Blueprint("student_app_v2", __name__)
bp_api_student_submissions_admin = Blueprint("student_submissions_admin", __name__)
V2_ROUTES = frozenset({
    ("/api/mobile/student/today", "GET"),
    ("/api/mobile/student/assignments", "GET"),
    ("/api/mobile/network/status", "GET"),
    ("/api/mobile/student/tests/<assignment_id>", "GET"),
    ("/api/mobile/student/tests/<assignment_id>/problem", "GET"),
    ("/api/mobile/student/tests/<assignment_id>/submit", "POST"),
    ("/api/mobile/student/tests/<assignment_id>/result", "GET"),
    ("/api/mobile/student/tests/<assignment_id>/solution", "GET"),
    ("/api/mobile/student/homework/<assignment_id>/complete", "POST"),
    ("/api/mobile/app/release", "GET"),
})


@bp_api_student_app_v2.errorhandler(ApiError)
@bp_api_student_submissions_admin.errorhandler(ApiError)
def api_error(exc):
    return jsonify(error_payload(exc)), exc.status


@bp_api_student_app_v2.errorhandler(Exception)
@bp_api_student_submissions_admin.errorhandler(Exception)
def unavailable(exc):
    from core.student_homework_repository import HomeworkConflictError, HomeworkNotInitializedError
    if isinstance(exc, HomeworkConflictError):
        return jsonify(ok=False, code=exc.code), 409
    if isinstance(exc, HomeworkNotInitializedError):
        return jsonify(ok=False, code=exc.code), 503
    return jsonify(ok=False, code="temporarily_unavailable"), 503


@bp_api_student_app_v2.after_request
@bp_api_student_submissions_admin.after_request
def no_store(response):
    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "Referrer-Policy": "no-referrer"})
    return response


def _body(allowed: set[str]) -> dict:
    if request.content_length is not None and request.content_length > 512000:
        raise ApiError("invalid_payload")
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - allowed:
        raise ApiError("invalid_payload")
    return body


def _page() -> int:
    value = request.args.get("page", "1")
    if not re.fullmatch(r"[1-9][0-9]{0,3}", value):
        raise ApiError("invalid_page")
    return int(value)


@bp_api_student_submissions_admin.before_request
def operator_boundary():
    from core.admin_basic_auth import ADMIN_AUTH_CHALLENGE, admin_network_allowed, verify_admin_authorization
    from core.student_app_config import load_student_app_config
    from core.student_public_proxy import public_host_matches
    from routes.api_student_homework import _same_origin
    adapter = current_app.extensions.get("student_public_surface")
    config = adapter.config if adapter is not None else load_student_app_config()
    if public_host_matches(request.environ, config.public_host, config.trusted_proxy_networks):
        raise ApiError("not_found", 404)
    if not admin_network_allowed(request):
        raise ApiError("academy_network_required", 403)
    if not verify_admin_authorization(request.headers.get("Authorization")):
        response = jsonify(ok=False, code="admin_auth_required")
        response.status_code = 401
        response.headers["WWW-Authenticate"] = ADMIN_AUTH_CHALLENGE
        return response
    if request.method == "POST" and not _same_origin():
        raise ApiError("origin_required", 403)
    g.student_submission_operator = request.authorization.username


@bp_api_student_submissions_admin.get("/api/admin/student-test-submissions")
def inspect_submission():
    from core.student_app_v2.resets import inspect
    if set(request.args) != {"assignmentId"}:
        raise ApiError("invalid_payload")
    return jsonify(inspect(request.args["assignmentId"]))


@bp_api_student_submissions_admin.post("/api/admin/student-test-submissions/reset")
def reset_submission():
    from core.student_app_v2.resets import reset
    body = _body({"operationId", "assignmentId", "expectedClientSubmissionId", "reason"})
    return jsonify(reset(body, g.student_submission_operator))


@bp_api_student_app_v2.get("/api/mobile/network/status")
def network_status():
    authority()
    return jsonify(ok=True, **network(), serverTime=now().isoformat())


@bp_api_student_app_v2.get("/api/mobile/student/today")
def today():
    sid = authority()
    date = date_key(request.args.get("date", now().date().isoformat()))
    snapshot, items = projections.day_items(sid, date)
    return jsonify(ok=True, date=date, serverTime=now().isoformat(), network=network(),
                   profile=projections.profile(sid),
                   items=items, homeworkSummary=projections.homework_summary(sid, date),
                   notice=projections.notice(sid),
                   courseBlocked={"message": snapshot.get("blockMessage", "")} if snapshot.get("courseBlocked") else None)


@bp_api_student_app_v2.get("/api/mobile/student/assignments")
def assignments():
    sid = authority()
    start = date_key(request.args.get("from", now().date().isoformat()))
    end = date_key(request.args.get("to", start))
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if not 0 <= (last - first).days <= 366:
        raise ApiError("invalid_date_range")
    kind = request.args.get("kind", "all")
    if kind not in {"all", "video", "review", "test"}:
        raise ApiError("invalid_kind")
    after = ""
    cursor = request.args.get("cursor")
    if cursor:
        try:
            fields = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if fields[:4] != [sid, start, end, kind] or len(fields) != 5 or not isinstance(fields[4], str):
                raise ValueError
            after = fields[4]
        except Exception:
            raise ApiError("invalid_cursor") from None
    items = []
    for offset in range((last - first).days + 1):
        _, rows = projections.day_items(sid, (first + dt.timedelta(days=offset)).isoformat())
        items.extend(row for row in rows if (kind == "all" or row["kind"] == kind) and row["assignmentId"] > after)
    items.sort(key=lambda row: row["assignmentId"])
    more = len(items) > 50
    items = items[:50]
    next_cursor = base64.urlsafe_b64encode(json.dumps([sid, start, end, kind, items[-1]["assignmentId"]]).encode()).decode().rstrip("=") if more else None
    return jsonify(ok=True, items=items, nextCursor=next_cursor)


@bp_api_student_app_v2.get("/api/mobile/student/tests/<assignment_id>")
def test(assignment_id):
    sid = authority()
    require_academy()
    assignment = projections.resolve_test(assignment_id, sid, allow_stored=False)
    definition, saved = assignment["definition"], Ledger().get(assignment_id)
    if saved and saved["state"] == "resetting":
        raise ApiError("submission_reset_pending", 503)
    count = definition.get("problems")
    if type(count) is not int or not 1 <= count <= 999:
        raise ApiError("test_unavailable", 503)
    types = definition.get("answerTypes")
    if not isinstance(types, list) or len(types) != count or any(item not in {"choice5", "short"} for item in types):
        # Explicit authored types take precedence. Unknown types are manual
        # short input, never infer and expose answer-key structure.
        types = ["short"] * count
    result = saved.get("response") if saved else projections.historical_result(assignment)
    return jsonify(ok=True, assignmentId=assignment_id, testId=assignment["testId"],
                   title=assignment["title"], round=assignment["round"], questionCount=count,
                   answerTypes=types, problem={"pages": content.document(assignment, "problem"),
                                              "url": f"/api/mobile/student/tests/{quote(assignment_id, safe='')}/problem?page=n"},
                   status="graded" if result else "submitted" if saved else "not_started",
                   submission={"clientSubmissionId": saved["client_id"] if saved else None, "submittedAt": result["submittedAt"],
                               "score": result["score"]} if result else None,
                   solutionAvailable=projections.solution_available(assignment, saved))


@bp_api_student_app_v2.get("/api/mobile/student/tests/<assignment_id>/problem")
def problem(assignment_id):
    sid = authority()
    require_academy()
    return content.document(projections.resolve_test(assignment_id, sid, allow_stored=False), "problem", _page())


@bp_api_student_app_v2.post("/api/mobile/student/tests/<assignment_id>/submit")
def submit(assignment_id):
    sid = authority()
    require_academy()
    body = _body({"clientSubmissionId", "round", "answers", "memo", "acknowledgeOffsetWarning"})
    assignment = projections.resolve_test(assignment_id, sid)
    return jsonify(submissions.submit(assignment, body))


@bp_api_student_app_v2.get("/api/mobile/student/tests/<assignment_id>/result")
def result(assignment_id):
    sid = authority()
    projections.parse_assignment(assignment_id, sid)
    ledger = Ledger()
    if ledger.get(assignment_id):
        value, assignment = submissions.replay(ledger, assignment_id)
    else:
        assignment = projections.resolve_test(assignment_id, sid)
        value = projections.historical_result(assignment)
        if value is None:
            raise ApiError("not_submitted", 404)
    return jsonify(ok=True, **{key: value[key] for key in (
        "submittedAt", "score", "pct", "wrong", "wrongDetails", "solutionAvailable")},
        solutionPolicy="teacher_open" if assignment["metadata"].get("solutionOpen") is True else "after_submit")


@bp_api_student_app_v2.get("/api/mobile/student/tests/<assignment_id>/solution")
def solution(assignment_id):
    sid = authority()
    require_academy()
    ledger = Ledger()
    with ledger.lock():
        assignment = projections.resolve_test(assignment_id, sid, allow_stored=False)
        if not projections.solution_available(assignment, ledger.get(assignment_id)):
            raise ApiError("solution_locked", 403)
        ticket = request.args.get("ticket")
        if ticket or not content.can_proxy():
            return content.solution_redirect(assignment, sid, ticket)
        return content.document(assignment, "solution", _page())


@bp_api_student_app_v2.post("/api/mobile/student/homework/<assignment_id>/complete")
def complete_homework(assignment_id):
    sid = authority()
    body = _body({"clientRequestId"})
    return jsonify(homework.complete(sid, assignment_id, body.get("clientRequestId")))


@bp_api_student_app_v2.get("/api/mobile/app/release")
def release():
    from flask import g
    if getattr(g, "student_app_public_request", False) is not True:
        raise ApiError("not_found", 404)
    path = os.environ.get("STUDENT_APP_RELEASE_METADATA")
    if not path:
        raise ApiError("release_unavailable", 503)
    data = json.loads(Path(path).read_text("utf-8"))
    fields = {"versionCode", "versionName", "minSupportedVersionCode", "apkUrl", "sha256", "notes", "publishedAt"}
    if not isinstance(data, dict) or set(data) != fields:
        raise ApiError("release_unavailable", 503)
    if (any(type(data[key]) is not int or data[key] < 1 for key in ("versionCode", "minSupportedVersionCode"))
            or data["minSupportedVersionCode"] > data["versionCode"]
            or any(not isinstance(data[key], str) for key in fields - {"versionCode", "minSupportedVersionCode"})
            or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"])
            or urlparse(data["apkUrl"]).scheme != "https"):
        raise ApiError("release_unavailable", 503)
    return jsonify(data)
