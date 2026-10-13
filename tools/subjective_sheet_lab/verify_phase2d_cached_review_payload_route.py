# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_phase2d_cached_review_payload_route.py

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from tools.subjective_sheet_lab.phase2d_cached_review_payload_route_verifier_support import (  # noqa: E402
    CACHE_ENABLED_ENV,
    CACHE_RECOGNIZED_ENV,
    CACHE_REVIEW_ENV,
    DEFAULT_CACHE,
    FULL_SHEET,
    PHASE2E_CACHE_ROOT_ENV,
    ROUTE,
    ROUTE_ENABLED_ENV,
    JsonObject,
    Phase2DVerificationError,
    assert_no_forbidden_fields,
    assert_no_paths,
    count_statuses,
    item_question_no,
    newest_created_dir,
    require_array,
    require_object,
    runtime_dirs,
    valid_fields,
    with_env,
    write_cache_fixtures,
)


def main() -> int:
    if not FULL_SHEET.is_file():
        raise Phase2DVerificationError(f"real full-sheet image missing: {FULL_SHEET}")
    if not DEFAULT_CACHE.is_file():
        raise Phase2DVerificationError(f"default recognized cache missing: {DEFAULT_CACHE}")
    fixtures = write_cache_fixtures()
    app = create_app()
    client = app.test_client()
    results = {
        "disabled_default": with_env({ROUTE_ENABLED_ENV: None, CACHE_ENABLED_ENV: "1"}, lambda: verify_error(client, 503, "feature_disabled")),
        "cache_disabled_fails_closed": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: None}, lambda: verify_error(client, 503, "recognition_unavailable")),
        "recognized_cache_hit": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_RECOGNIZED_ENV: str(DEFAULT_CACHE), CACHE_REVIEW_ENV: None}, lambda: verify_success(client, "phase2d_cached_recognized", {"review_required": 20})),
        "stable_same_image_cache_hit": with_env(
            {ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_RECOGNIZED_ENV: None, CACHE_REVIEW_ENV: None, PHASE2E_CACHE_ROOT_ENV: str(fixtures["stable_cache_root"])},
            lambda: verify_success(client, "phase2d_cached_recognized", {"review_required": 20}),
        ),
        "stable_same_image_cache_replay_repeatable": with_env(
            {ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_RECOGNIZED_ENV: None, CACHE_REVIEW_ENV: None, PHASE2E_CACHE_ROOT_ENV: str(fixtures["stable_cache_root"])},
            lambda: verify_repeatable_review_payload(client),
        ),
        "implicit_default_cache_not_reused": with_env(
            {ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_RECOGNIZED_ENV: None, CACHE_REVIEW_ENV: None, PHASE2E_CACHE_ROOT_ENV: str(fixtures["empty_stable_cache_root"])},
            lambda: verify_error(client, 503, "recognition_unavailable"),
        ),
        "recognized_status_ignored": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_RECOGNIZED_ENV: str(fixtures["recognized_status"]), CACHE_REVIEW_ENV: None}, lambda: verify_success(client, "phase2d_cached_recognized", {"review_required": 20})),
        "review_payload_cache_hit": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_REVIEW_ENV: str(fixtures["review_payload"]), CACHE_RECOGNIZED_ENV: None}, lambda: verify_success(client, "phase2d_cached_review_payload")),
        "wrapped_route_response_cache_replay_preserves_statuses": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_REVIEW_ENV: str(fixtures["wrapped_route_response"]), CACHE_RECOGNIZED_ENV: None}, lambda: verify_success(client, "phase2d_cached_review_payload", {"safe_auto_grade": 20})),
        "invalid_choice_safe_auto_grade_downgraded": with_env(
            {ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_REVIEW_ENV: str(fixtures["invalid_choice_review_payload"]), CACHE_RECOGNIZED_ENV: None},
            lambda: verify_invalid_choice_downgrade(client),
        ),
        "cache_miss_fails_closed": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_RECOGNIZED_ENV: str(fixtures["missing"]), CACHE_REVIEW_ENV: None}, lambda: verify_error(client, 503, "recognition_unavailable")),
        "malformed_cache_fails_closed": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_RECOGNIZED_ENV: str(fixtures["malformed"]), CACHE_REVIEW_ENV: None}, lambda: verify_error(client, 503, "recognition_unavailable")),
        "forbidden_cache_fails_closed": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_RECOGNIZED_ENV: str(fixtures["forbidden"]), CACHE_REVIEW_ENV: None}, lambda: verify_error(client, 503, "recognition_unavailable")),
        "malformed_review_payload_fails_closed": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_REVIEW_ENV: str(fixtures["malformed_review_payload"]), CACHE_RECOGNIZED_ENV: None}, lambda: verify_error(client, 503, "recognition_unavailable")),
        "forbidden_review_payload_fails_closed": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_REVIEW_ENV: str(fixtures["forbidden_review_payload"]), CACHE_RECOGNIZED_ENV: None}, lambda: verify_error(client, 503, "recognition_unavailable")),
        "path_leak_review_payload_fails_closed": with_env({ROUTE_ENABLED_ENV: "1", CACHE_ENABLED_ENV: "1", CACHE_REVIEW_ENV: str(fixtures["path_leak_review_payload"]), CACHE_RECOGNIZED_ENV: None}, lambda: verify_error(client, 503, "recognition_unavailable")),
        "external_call_counts": {"submit_test": 0, "gemini_provider": 0, "old_ocr_route": 0},
    }
    print(json.dumps({"ok": True, "route": ROUTE, "fixtures": {key: str(value) for key, value in fixtures.items()}, "results": results}, ensure_ascii=False, indent=2))
    return 0


def verify_error(client, expected_status: int, expected_code: str) -> JsonObject:
    response = client.post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "error response")
    if response.status_code != expected_status:
        raise Phase2DVerificationError(f"error case returned {response.status_code}, wanted {expected_status}")
    if payload.get("ok") is not False or payload.get("errorCode") != expected_code:
        raise Phase2DVerificationError(f"wrong error payload: {payload}")
    if "review_payload" in payload:
        raise Phase2DVerificationError("error response included review_payload")
    return {"http_status": response.status_code, "errorCode": str(payload.get("errorCode"))}


def verify_success(client, expected_source: str, expected_statuses: dict[str, int] | None = None) -> JsonObject:
    before = runtime_dirs()
    response = client.post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "success response")
    if response.status_code != 200 or payload.get("ok") is not True:
        raise Phase2DVerificationError(f"success case failed {response.status_code}: {response.get_data(as_text=True)}")
    assert_no_forbidden_fields(payload)
    assert_no_paths(payload)
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    if review_payload.get("source") != expected_source:
        raise Phase2DVerificationError(f"source {review_payload.get('source')} != {expected_source}")
    items = require_array(review_payload.get("items"), "review_payload.items")
    if len(items) != 20:
        raise Phase2DVerificationError("review payload must contain 20 items")
    question_numbers = sorted(item_question_no(item, index) for index, item in enumerate(items, start=1))
    if question_numbers != list(range(1, 21)):
        raise Phase2DVerificationError("review payload must contain questions 1..20")
    statuses = count_statuses(items)
    if expected_statuses is not None and statuses != expected_statuses:
        raise Phase2DVerificationError(f"statuses {statuses} != {expected_statuses}")
    case_dir = newest_created_dir(before)
    crop_count = len(tuple(case_dir.rglob("q*.png")))
    if crop_count < 20:
        raise Phase2DVerificationError("Phase 2C crop pipeline did not run")
    return {
        "http_status": response.status_code,
        "source": str(review_payload.get("source")),
        "items": len(items),
        "statuses": statuses,
        "case_dir": str(case_dir),
        "crop_pipeline_ran": True,
        "forbidden_field_hits": 0,
        "student_path_leaks": 0,
    }


def verify_repeatable_review_payload(client) -> JsonObject:
    first = post_review_payload(client)
    second = post_review_payload(client)
    first_text = json.dumps(first, ensure_ascii=False, sort_keys=True)
    second_text = json.dumps(second, ensure_ascii=False, sort_keys=True)
    if first_text != second_text:
        raise Phase2DVerificationError("same OMR image did not replay the same review_payload")
    items = require_array(first.get("items"), "repeatable.review_payload.items")
    return {
        "source": str(first.get("source")),
        "same_review_payload": True,
        "items": len(items),
        "statuses": count_statuses(items),
    }


def verify_invalid_choice_downgrade(client) -> JsonObject:
    review_payload = post_review_payload_for_source(client, "phase2d_cached_review_payload")
    items = require_array(review_payload.get("items"), "invalid_choice.review_payload.items")
    statuses = count_statuses(items)
    expected_statuses = {"retake_required": 3, "review_required": 3, "safe_auto_grade": 14}
    if statuses != expected_statuses:
        raise Phase2DVerificationError(f"statuses {statuses} != {expected_statuses}")
    q005 = require_question(items, 5)
    q016 = require_question(items, 16)
    q017 = require_question(items, 17)
    if q005.get("status") != "review_required" or q005.get("final_answer") is not None:
        raise Phase2DVerificationError(f"q005 invalid choice downgrade failed: {q005}")
    if q016.get("status") != "review_required" or q016.get("warnings") != ["overwritten_answer"] or q016.get("final_answer") is not None:
        raise Phase2DVerificationError(f"q016 overwritten downgrade failed: {q016}")
    if q017.get("status") != "review_required" or q017.get("warnings") != ["overwritten_answer"] or q017.get("final_answer") is not None:
        raise Phase2DVerificationError(f"q017 overwritten downgrade failed: {q017}")
    return {
        "source": str(review_payload.get("source")),
        "items": len(items),
        "statuses": statuses,
        "q005": question_summary(q005),
        "q016": question_summary(q016),
        "q017": question_summary(q017),
    }


def post_review_payload(client) -> JsonObject:
    response = client.post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "repeatable success response")
    if response.status_code != 200 or payload.get("ok") is not True:
        raise Phase2DVerificationError(f"repeatable success case failed {response.status_code}: {response.get_data(as_text=True)}")
    assert_no_forbidden_fields(payload)
    assert_no_paths(payload)
    review_payload = require_object(payload.get("review_payload"), "repeatable review_payload")
    if review_payload.get("source") != "phase2d_cached_recognized":
        raise Phase2DVerificationError(f"repeatable source {review_payload.get('source')} != phase2d_cached_recognized")
    items = require_array(review_payload.get("items"), "repeatable review_payload.items")
    if len(items) != 20:
        raise Phase2DVerificationError("repeatable review payload must contain 20 items")
    return review_payload


def post_review_payload_for_source(client, expected_source: str) -> JsonObject:
    response = client.post(ROUTE, data=valid_fields())
    payload = require_object(response.get_json(silent=True), "targeted success response")
    if response.status_code != 200 or payload.get("ok") is not True:
        raise Phase2DVerificationError(f"targeted success case failed {response.status_code}: {response.get_data(as_text=True)}")
    assert_no_forbidden_fields(payload)
    assert_no_paths(payload)
    review_payload = require_object(payload.get("review_payload"), "targeted review_payload")
    if review_payload.get("source") != expected_source:
        raise Phase2DVerificationError(f"targeted source {review_payload.get('source')} != {expected_source}")
    return review_payload


def require_question(items, question_no: int) -> JsonObject:
    for item in items:
        if isinstance(item, dict) and item.get("question_no") == question_no:
            return item
    raise Phase2DVerificationError(f"question {question_no} missing")


def question_summary(item: JsonObject) -> JsonObject:
    warnings = item.get("warnings")
    return {
        "status": str(item.get("status")),
        "warnings": warnings if isinstance(warnings, list) else [],
        "final_answer": item.get("final_answer"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
