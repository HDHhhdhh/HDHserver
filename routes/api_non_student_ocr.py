from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Final

from flask import Blueprint, jsonify, request

from core.non_student_ocr_cache import CapturedCacheError, load_captured_review

bp_api_non_student_ocr = Blueprint("api_non_student_ocr", __name__)

ENABLED_ENV: Final = "NON_STUDENT_OCR_CAPTURED_CACHE_ROUTE_ENABLED"
TOKEN_ENV: Final = "NON_STUDENT_OCR_CAPTURED_CACHE_TOKEN"
ROOT_ENV: Final = "NON_STUDENT_OCR_CAPTURED_CACHE_ROOT"
RELATIVE_DIR_ENV: Final = "NON_STUDENT_OCR_CAPTURED_CACHE_RELATIVE_DIR"
CASE_ID_ENV: Final = "NON_STUDENT_OCR_CAPTURED_CACHE_CASE_ID"
TEST_ID_ENV: Final = "NON_STUDENT_OCR_CAPTURED_CACHE_TEST_ID"
ROUND_ENV: Final = "NON_STUDENT_OCR_CAPTURED_CACHE_ROUND"
TRUTHY: Final = frozenset({"1", "true", "yes", "on"})


def _error(status_code: int, code: str, message: str):
    return jsonify(
        {
            "ok": False,
            "code": code,
            "message": message,
            "provider_calls": 0,
            "fallback": "stop" if status_code != 503 else "manual_review",
        }
    ), status_code


def _enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "").strip().lower() in TRUTHY


def _configured(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CapturedCacheError("ROUTE_NOT_CONFIGURED", "internal OCR cache route is not configured", 503)
    return value


@bp_api_non_student_ocr.post("/api/internal/non-student-ocr/review-cache")
def non_student_ocr_review_cache():
    if not _enabled():
        return _error(503, "FEATURE_DISABLED", "internal OCR cache route is disabled")

    configured_token = os.environ.get(TOKEN_ENV, "").strip()
    provided_token = request.headers.get("X-Internal-OCR-Token", "").strip()
    if not configured_token or not hmac.compare_digest(configured_token, provided_token):
        return _error(403, "INTERNAL_TOKEN_REQUIRED", "internal OCR token is required")

    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"case_id"}:
        return _error(400, "INVALID_REQUEST", "request must contain case_id only")
    case_id = str(body.get("case_id") or "").strip()

    try:
        configured_case_id = _configured(CASE_ID_ENV)
        if not hmac.compare_digest(configured_case_id, case_id):
            return _error(404, "CACHE_NOT_FOUND", "captured cache was not found")
        response = load_captured_review(
            case_id=case_id,
            test_id=_configured(TEST_ID_ENV),
            round_no=_configured(ROUND_ENV),
            root=Path(_configured(ROOT_ENV)),
            relative_dir=Path(_configured(RELATIVE_DIR_ENV)),
        )
    except CapturedCacheError as error:
        return _error(error.status_code, error.code, error.message)

    return jsonify(response)
