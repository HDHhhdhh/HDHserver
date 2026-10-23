"""Administrator-only tuition ledger; reads never initialize financial state."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3

from flask import Blueprint, current_app, g, jsonify, request

from core.admin_basic_auth import ADMIN_AUTH_CHALLENGE, verify_admin_authorization
from core.json_store import JsonStore, StoreError
from core.paths import ABS_PATH, ARRIVE_TIME_PATH, ATTENDANCE_PATH, BASE, EXTRA_PATH
from core.payment_evidence import month_window, project_evidence
from core.payment_repository import PaymentRepository
from core.payment_rules import PLANS, PaymentError, account_summary, empty_account, package_balance, line_balance, text
from core.person_identity_store import PersonIdentityUnavailableError
from routes.api_students import read_admin_students

bp_api_payments = Blueprint("api_payments", __name__)
KST = dt.timezone(dt.timedelta(hours=9))
EVIDENCE_STORES = {key: JsonStore(path, dict, dict) for key, path in {
    "attendance": ATTENDANCE_PATH, "arrivals": ARRIVE_TIME_PATH, "absence": ABS_PATH,
    "makeup": BASE / "makeup_carryover.json", "extra": EXTRA_PATH,
}.items()}


def repository():
    return PaymentRepository(os.environ.get("DB_PATH") or BASE / "app.sqlite")


@bp_api_payments.before_request
def require_admin():
    if getattr(g, "student_app_public_request", False):
        return jsonify(ok=False, code="not_found", message="찾을 수 없습니다."), 404
    verifier = current_app.config.get("ACADEMY_ADMIN_AUTHORIZER")
    if not callable(verifier):
        verifier = verify_admin_authorization
    if not verifier(request.headers.get("Authorization")):
        return jsonify(ok=False, code="admin_required", message="관리자 로그인이 필요합니다."), 401, {
            "WWW-Authenticate": ADMIN_AUTH_CHALLENGE}
    if request.method == "POST":
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify(ok=False, code="cross_site", message="관리자 화면에서 다시 저장해 주세요."), 403
        if not request.is_json or request.content_length is not None and request.content_length > 32_768:
            return jsonify(ok=False, code="invalid_body", message="저장 내용의 형식 또는 크기를 확인해 주세요."), 400


@bp_api_payments.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp_api_payments.errorhandler(PaymentError)
def payment_error(exc):
    return jsonify(ok=False, code=exc.code, message=str(exc)), exc.status


def unavailable(exc):
    current_app.logger.error("Payment store unavailable: %s", type(exc).__name__)
    return jsonify(ok=False, code="payment_store_unavailable", message="결제 또는 출결 자료를 읽지 못했습니다. 저장하지 않았습니다."), 503


for error_type in (StoreError, sqlite3.Error, PersonIdentityUnavailableError):
    bp_api_payments.register_error_handler(error_type, unavailable)


def students():
    raw = read_admin_students()
    if not isinstance(raw, list):
        raise PaymentError("students_unavailable", "학생 목록을 읽지 못했습니다.", 503)
    result = {}
    for row in raw:
        if not isinstance(row, dict) or not row.get("id"):
            raise PaymentError("students_unavailable", "학생 식별 정보를 확인해 주세요.", 503)
        sid = str(row["id"])
        if sid in result:
            raise PaymentError("students_unavailable", "중복 학생 식별 정보가 있습니다.", 503)
        result[sid] = {key: str(row.get(key) or "") for key in ("name", "school", "grade", "curriculum", "personId")}
    return result


def valid_sid(value):
    return text(value, "학생 식별 번호", 120, required=True)


@bp_api_payments.get("/api/payments/overview")
def overview():
    roster = students()
    stored = {row["sid"]: row for row in repository().overview()}
    rows = []
    for sid in roster.keys() | stored.keys():
        record = stored.get(sid, {"sid": sid, "revision": 0, **account_summary(empty_account(sid))})
        rows.append({**record, "student": roster.get(sid, record.get("student", {})), "archived": sid not in roster})
    rows.sort(key=lambda row: (row["archived"], row["student"].get("name", ""), row["sid"]))
    return jsonify(students=rows, plans=PLANS, today=dt.datetime.now(KST).date().isoformat())


@bp_api_payments.get("/api/payments/account")
def account():
    sid = valid_sid(request.args.get("sid"))
    result = repository().get(sid)
    if sid not in students() and result["revision"] == 0:
        raise PaymentError("student_not_found", "학생을 찾지 못했습니다.", 404)
    result["balances"] = {row["id"]: package_balance(result["account"], row) for row in result["account"]["packages"]}
    result["lineBalances"] = {row["id"]: [line_balance(result["account"], row, i) for i in range(len(row["lines"]))]
        for row in result["account"]["packages"]}
    return jsonify(result)


@bp_api_payments.get("/api/payments/evidence")
def evidence():
    sid = valid_sid(request.args.get("sid"))
    month = request.args.get("month")
    month_window(month)
    if sid not in students():
        # Archived accounts retain their confirmed ledger; evidence is roster-scoped.
        return jsonify(events=[], archived=True)
    snapshots = {key: store.read()[0] for key, store in EVIDENCE_STORES.items()}
    return jsonify(events=project_evidence(sid, month, **snapshots))


@bp_api_payments.post("/api/payments/command")
def command():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise PaymentError("invalid_body", "저장 내용은 JSON 객체여야 합니다.")
    sid = valid_sid(payload.get("sid"))
    roster = students()
    if sid not in roster:
        replay = repository().replay(sid, payload)
        if replay:
            return jsonify(replay)
        previous = next((row for row in repository().overview() if row["sid"] == sid), None)
        if previous is None or payload.get("action") not in ("payment", "refund", "void"):
            raise PaymentError("student_archived", "현재 수강 중인 학생을 선택해 주세요.", 409)
        student = previous["student"]
    else:
        student = roster[sid]
    now = dt.datetime.now(KST)
    actor = (request.authorization.username if request.authorization else None) or "administrator"
    return jsonify(repository().execute(sid, payload, student=student, today=now.date().isoformat(),
        now=now.isoformat(), actor=actor))
