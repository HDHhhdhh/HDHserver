from __future__ import annotations

import datetime as dt
import hmac
import os
import uuid

from flask import current_app, g, request

from core.network_access import ip_allowed

KST = dt.timezone(dt.timedelta(hours=9))


class ApiError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


def now() -> dt.datetime:
    return dt.datetime.now(KST)


def date_key(value: object) -> str:
    if not isinstance(value, str):
        raise ApiError("invalid_date")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        raise ApiError("invalid_date") from None
    if parsed.isoformat() != value:
        raise ApiError("invalid_date")
    return value


def request_id(value: object) -> str:
    if not isinstance(value, str):
        raise ApiError("invalid_request_id")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ApiError("invalid_request_id") from None
    if parsed.version != 4 or str(parsed) != value:
        raise ApiError("invalid_request_id")
    return value


def authority() -> str:
    if getattr(g, "student_app_public_request", False) is not True:
        raise ApiError("not_found", 404)
    sid = getattr(g, "student_app_active_sid", None)
    if not isinstance(sid, str) or not sid:
        raise ApiError("unauthenticated", 401)
    return sid


def network() -> dict:
    academy = ip_allowed(getattr(g, "student_app_client_ip", ""))
    # No override branch on the production hostname, even with a leaked secret.
    if (current_app.config.get("STUDENT_APP_PUBLIC_HOST") == "dev-app.5a-math.com"
            and getattr(g, "student_app_public_request", False) is True):
        secret = os.environ.get("STUDENT_APP_DEBUG_ACADEMY_SECRET", "")
        supplied = request.headers.get("X-Debug-Secret", "")
        value = request.headers.get("X-Debug-Academy")
        if secret and hmac.compare_digest(secret, supplied) and value in {"0", "1"}:
            academy = value == "1"
    return {"academy": academy, "reason": "allowlist" if academy else "outside"}


def require_academy() -> None:
    if not network()["academy"]:
        raise ApiError("academy_required", 403)


def answers_text(body: dict, count: int) -> str:
    answers = body.get("answers")
    if not isinstance(answers, list) or len(answers) > count:
        raise ApiError("invalid_answers")
    seen, lines = set(), []
    for answer in answers:
        if not isinstance(answer, dict) or set(answer) != {"n", "value"}:
            raise ApiError("invalid_answers")
        number, value = answer["n"], answer["value"]
        if (type(number) is not int or not 1 <= number <= count or number in seen
                or not isinstance(value, str) or len(value) > 500
                or len(value.splitlines()) > 1
                or any(char in value for char in "\r\n\v\f\x85\u2028\u2029")):
            raise ApiError("invalid_answers")
        seen.add(number)
        if value.strip():
            lines.append((number, f"{number}. {value.strip()}"))
    return "\n".join(line for _, line in sorted(lines))
