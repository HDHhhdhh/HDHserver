# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_phase2a_internal_ocr_route_stub.py

from __future__ import annotations

import json
import io
import os
import sys
from pathlib import Path
from collections.abc import Callable
from typing import Final, TypeAlias

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
FormValue: TypeAlias = str | tuple[io.BytesIO, str, str]
FormFields: TypeAlias = dict[str, FormValue]

ROUTE: Final[str] = "/api/ocr-test-sheet-review"
ROUTE_ENABLED_ENV: Final[str] = "OCR_PHASE2_REVIEW_ROUTE_ENABLED"
ALLOWED_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
SECOND_ALLOWED_TEST_ID: Final[str] = "t_unit_daesu_02_lv3_r1"
FULL_RANGE_UNIT_TEST_ID: Final[str] = "t_unit_daesu_03_lv3_r1"
FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct"),
)
MAX_IMAGE_BYTES: Final[int] = 8 * 1024 * 1024
VALID_FULL_SHEET: Final[Path] = Path(r"C:\server-ocr\incoming_cases\person_03\full_sheet.jpg")


class Phase2AVerificationError(Exception):
    pass


def main() -> int:
    if not VALID_FULL_SHEET.is_file():
        raise Phase2AVerificationError(f"real full-sheet image missing: {VALID_FULL_SHEET}")
    app = create_app()
    client = app.test_client()
    results = {
        "disabled_default": with_route_flag(None, lambda: verify_error(
            client,
            {"sid": "990", "testId": ALLOWED_TEST_ID, "round": "1"},
            503,
            "feature_disabled",
        )),
        "method_guard": verify_method_guard(client),
        "missing_sid": with_route_flag("1", lambda: verify_error(client, {"testId": ALLOWED_TEST_ID, "round": "1"}, 400, "invalid_request")),
        "ghost_student": with_route_flag("1", lambda: verify_error(client, {"sid": "ghost-outside-test", "testId": ALLOWED_TEST_ID, "round": "1"}, 403, "forbidden_student")),
        "blocked_test": with_route_flag("1", lambda: verify_error(client, {"sid": "990", "testId": "blocked_test", "round": "1"}, 403, "test_not_allowlisted")),
        "blocked_round": with_route_flag("1", lambda: verify_error(client, {"sid": "990", "testId": ALLOWED_TEST_ID, "round": "2"}, 403, "round_not_allowlisted")),
        "second_allowed_test_reaches_image_guard": with_route_flag("1", lambda: verify_error(client, {"sid": "990", "testId": SECOND_ALLOWED_TEST_ID, "round": "1"}, 400, "missing_image")),
        "second_allowed_test_wrong_round": with_route_flag("1", lambda: verify_error(client, {"sid": "990", "testId": SECOND_ALLOWED_TEST_ID, "round": "2"}, 403, "round_not_allowlisted")),
        "full_range_unit_test_reaches_image_guard": with_route_flag("1", lambda: verify_error(client, {"sid": "990", "testId": FULL_RANGE_UNIT_TEST_ID, "round": "1"}, 400, "missing_image")),
        "full_range_unit_test_wrong_round": with_route_flag("1", lambda: verify_error(client, {"sid": "990", "testId": FULL_RANGE_UNIT_TEST_ID, "round": "2"}, 403, "round_not_allowlisted")),
        "missing_image": with_route_flag("1", lambda: verify_error(client, {"sid": "990", "testId": ALLOWED_TEST_ID, "round": "1"}, 400, "missing_image")),
        "invalid_image_type": with_route_flag("1", lambda: verify_error(client, invalid_image_fields(), 415, "unsupported_image_type")),
        "oversized_image": with_route_flag("1", lambda: verify_error(client, oversized_image_fields(), 413, "image_too_large")),
        "allowed_payload": with_route_flag("1", lambda: verify_allowed_payload(client)),
    }
    print(json.dumps({"ok": True, "route": ROUTE, "results": results}, ensure_ascii=False, indent=2))
    return 0


def verify_method_guard(client) -> JsonObject:
    response = client.get(ROUTE)
    if response.status_code not in {404, 405}:
        raise Phase2AVerificationError(f"GET {ROUTE} returned {response.status_code}, wanted 404 or 405")
    return {"http_status": response.status_code}


def with_route_flag(value: str | None, action: Callable[[], JsonObject]) -> JsonObject:
    previous = os.environ.get(ROUTE_ENABLED_ENV)
    if value is None:
        os.environ.pop(ROUTE_ENABLED_ENV, None)
    else:
        os.environ[ROUTE_ENABLED_ENV] = value
    try:
        return action()
    finally:
        if previous is None:
            os.environ.pop(ROUTE_ENABLED_ENV, None)
        else:
            os.environ[ROUTE_ENABLED_ENV] = previous


def verify_error(client, fields: FormFields, expected_status: int, expected_code: str) -> JsonObject:
    response = client.post(ROUTE, data=fields)
    payload = response.get_json(silent=True)
    if response.status_code != expected_status:
        raise Phase2AVerificationError(f"{fields} returned {response.status_code}, wanted {expected_status}")
    if not isinstance(payload, dict):
        raise Phase2AVerificationError("error response must be JSON object")
    if payload.get("ok") is not False or payload.get("errorCode") != expected_code:
        raise Phase2AVerificationError(f"wrong error payload for {fields}: {payload}")
    if "review_payload" in payload:
        raise Phase2AVerificationError("error response must not include review_payload")
    return {"http_status": response.status_code, "errorCode": str(payload.get("errorCode"))}


def valid_image_fields() -> FormFields:
    return {
        "sid": "990",
        "testId": ALLOWED_TEST_ID,
        "round": "1",
        "image": (io.BytesIO(VALID_FULL_SHEET.read_bytes()), "full_sheet.jpg", "image/jpeg"),
    }


def invalid_image_fields() -> FormFields:
    return {
        "sid": "990",
        "testId": ALLOWED_TEST_ID,
        "round": "1",
        "image": (io.BytesIO(b"not an image"), "answer-sheet.txt", "text/plain"),
    }


def oversized_image_fields() -> FormFields:
    return {
        "sid": "990",
        "testId": ALLOWED_TEST_ID,
        "round": "1",
        "image": (io.BytesIO(b"0" * (MAX_IMAGE_BYTES + 1)), "answer-sheet.png", "image/png"),
    }


def verify_allowed_payload(client) -> JsonObject:
    response = client.post(ROUTE, data=valid_image_fields())
    payload = response.get_json(silent=True)
    if response.status_code != 200:
        raise Phase2AVerificationError(f"allowed request returned {response.status_code}: {response.get_data(as_text=True)}")
    if not isinstance(payload, dict):
        raise Phase2AVerificationError("allowed response must be JSON object")
    if payload.get("ok") is not True:
        raise Phase2AVerificationError(f"allowed response did not return ok=true: {payload}")
    assert_no_forbidden_fields(payload)
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    if review_payload.get("test_id") != ALLOWED_TEST_ID:
        raise Phase2AVerificationError("review_payload.test_id mismatch")
    if str(review_payload.get("round")) != "1":
        raise Phase2AVerificationError("review_payload.round mismatch")
    if int(review_payload.get("problem_count") or 0) != 20:
        raise Phase2AVerificationError("review_payload.problem_count must be 20")
    items = require_array(review_payload.get("items"), "review_payload.items")
    if len(items) != 20:
        raise Phase2AVerificationError("review_payload.items must contain 20 items")
    question_numbers = sorted(int(require_object(item, "item").get("question_no") or 0) for item in items)
    if question_numbers != list(range(1, 21)):
        raise Phase2AVerificationError("review_payload must contain question_no 1..20 exactly")
    statuses = count_statuses(items)
    return {"http_status": response.status_code, "items": len(items), "statuses": statuses}


def assert_no_forbidden_fields(value: JsonValue, path: str = "$") -> None:
    match value:
        case dict():
            for key, child in value.items():
                if key in FORBIDDEN_FIELDS:
                    raise Phase2AVerificationError(f"student-facing payload leaked {path}.{key}")
                assert_no_forbidden_fields(child, f"{path}.{key}")
        case list():
            for index, child in enumerate(value):
                assert_no_forbidden_fields(child, f"{path}[{index}]")
        case None | bool() | int() | float() | str():
            return


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise Phase2AVerificationError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise Phase2AVerificationError(f"{label} must be a JSON array")
    return value


def count_statuses(items: list[JsonValue]) -> JsonObject:
    counts: dict[str, JsonValue] = {}
    for value in items:
        item = require_object(value, "item")
        status = str(item.get("status") or "")
        counts[status] = int(counts.get(status, 0) or 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
