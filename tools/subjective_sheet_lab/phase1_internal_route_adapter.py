# /// script
# requires-python = ">=3.11"
# ///
#
# --- How to run ---
# python tools/subjective_sheet_lab/verify_phase1_internal_route_adapter.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from final_review_payload_bridge import JsonValue
from phase1_internal_contract_harness import (
    FIXTURE_PATH,
    build_phase1_response,
    ensure_phase1_contract,
    read_json,
    resolve_review_fixture_path,
)
from subjective_review_dry_run_core import DryRunError, JsonObject, run_dry_flow

INTERNAL_MODE: Final = "phase1_internal_only"
FEATURE_DISABLED_STATUS: Final = 404
INVALID_REQUEST_STATUS: Final = 400
SUCCESS_STATUS: Final = 200


@dataclass(frozen=True, slots=True)
class RouteAdapterError(Exception):
    http_status: int
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class RouteAdapterResult:
    http_status: int
    payload: JsonObject


@dataclass(frozen=True, slots=True)
class InternalReviewRequest:
    sid: str
    test_id: str
    round_name: str
    input_kind: str
    image_path: str

    def as_contract_request(self) -> JsonObject:
        return {
            "sid": self.sid,
            "testId": self.test_id,
            "round": self.round_name,
            "inputKind": self.input_kind,
            "imagePath": self.image_path,
        }


def handle_internal_review_request(raw_request: JsonObject) -> RouteAdapterResult:
    try:
        request = parse_internal_request(raw_request)
    except RouteAdapterError as exc:
        return RouteAdapterResult(exc.http_status, error_payload(exc))

    try:
        response = build_internal_response(request)
    except (DryRunError, RouteAdapterError) as exc:
        return RouteAdapterResult(INVALID_REQUEST_STATUS, adapter_failure_payload(str(exc)))

    return RouteAdapterResult(SUCCESS_STATUS, response)


def parse_internal_request(raw_request: JsonObject) -> InternalReviewRequest:
    ensure_feature_enabled(raw_request.get("featureEnabled"))
    mode = require_string(raw_request.get("mode"), "mode")
    if mode != INTERNAL_MODE:
        raise RouteAdapterError(INVALID_REQUEST_STATUS, "invalid_mode", "Phase 1 adapter only accepts internal mode")
    return InternalReviewRequest(
        require_string(raw_request.get("sid"), "sid"),
        require_string(raw_request.get("testId"), "testId"),
        require_string(raw_request.get("round"), "round"),
        require_string(raw_request.get("inputKind"), "inputKind"),
        require_string(raw_request.get("imagePath"), "imagePath"),
    )


def ensure_feature_enabled(value: JsonValue) -> None:
    match value:
        case True:
            return
        case False | None:
            raise RouteAdapterError(FEATURE_DISABLED_STATUS, "feature_disabled", "Phase 1 internal OCR review is disabled")
        case int() | float() | str() | list() | dict():
            raise RouteAdapterError(INVALID_REQUEST_STATUS, "invalid_feature_flag", "featureEnabled must be true or false")
        case unreachable:
            assert_never(unreachable)


def build_internal_response(request: InternalReviewRequest) -> JsonObject:
    contract_fixture = read_json(FIXTURE_PATH)
    review_fixture_path = resolve_review_fixture_path(contract_fixture)
    dry_result = run_dry_flow(read_json(review_fixture_path))
    response = build_phase1_response(
        replace_contract_request(contract_fixture, request),
        dry_result,
    )
    ensure_phase1_contract(response)
    return response


def replace_contract_request(
    contract_fixture: JsonObject,
    request: InternalReviewRequest,
) -> JsonObject:
    copy = require_object(json.loads(json.dumps(contract_fixture, ensure_ascii=False)), "contract_fixture")
    copy["request"] = request.as_contract_request()
    return copy


def error_payload(exc: RouteAdapterError) -> JsonObject:
    return {
        "ok": False,
        "code": exc.code,
        "error": exc.message,
        "submit_test_called": False,
        "student_record_write_allowed": False,
        "gemini_api_called": False,
    }


def adapter_failure_payload(message: str) -> JsonObject:
    return {
        "ok": False,
        "code": "contract_adapter_failed",
        "error": message,
        "submit_test_called": False,
        "student_record_write_allowed": False,
        "gemini_api_called": False,
    }


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise RouteAdapterError(INVALID_REQUEST_STATUS, "invalid_request", f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_string(value: JsonValue, label: str) -> str:
    match value:
        case str() if value.strip():
            return value.strip()
        case None | bool() | int() | float() | str() | list() | dict():
            raise RouteAdapterError(INVALID_REQUEST_STATUS, "invalid_request", f"{label} must be a non-empty string")
        case unreachable:
            assert_never(unreachable)


def write_json(path: Path, payload: JsonObject) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
