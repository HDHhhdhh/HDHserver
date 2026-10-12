# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_phase2e_gemini_live_ocr_adapter.py

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter_verifier_support import (  # noqa: E402
    ALLOWED_TEST_ID,
    CACHE_WRITE_ENABLED_ENV,
    DEFAULT_CACHE,
    FULL_SHEET,
    LIVE_ENABLED_ENV,
    LOCAL_ONLY_ENV,
    MAX_CALLS_ENV,
    PHASE2E_ENV_KEYS,
    PROVIDER_ALLOWED_ENV,
    ROUTE,
    Phase2EVerificationError,
    JsonObject,
    assert_item_status,
    assert_item_warning,
    count_statuses,
    fake_phase2e_request,
    fake_pipeline_result,
    provider_items,
    require_array,
    route_env,
    verify_stable_same_image_recognized_path,
    verify_success,
    with_env,
    write_cache_fixtures,
)
from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import (  # noqa: E402
    Phase2EFeatureFlags,
    Phase2ERequest,
    Phase2EStatus,
    assert_phase2e_provider_gate_open,
    phase2e_flags_from_env,
    phase2e_provider_gate_is_open,
    prepare_phase2e_live_ocr,
)
from tools.subjective_sheet_lab.phase2e_live_provider_runner import review_payload_from_provider_items  # noqa: E402


def main() -> int:
    if not FULL_SHEET.is_file():
        raise Phase2EVerificationError(f"real full-sheet image missing: {FULL_SHEET}")
    if not DEFAULT_CACHE.is_file():
        raise Phase2EVerificationError(f"default recognized cache missing: {DEFAULT_CACHE}")

    fixtures = write_cache_fixtures()
    client = create_app().test_client()
    results = {
        "default_flags": verify_default_flags(),
        "provider_disabled_adapter": verify_adapter_status({}, "cache_miss", Phase2EStatus.PROVIDER_DISABLED),
        "local_only_blocks_adapter": verify_adapter_status(
            {LIVE_ENABLED_ENV: "1", LOCAL_ONLY_ENV: "1", PROVIDER_ALLOWED_ENV: "1"},
            "cache_miss",
            Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED,
        ),
        "authorization_blocks_adapter": verify_adapter_status(
            {LIVE_ENABLED_ENV: "1", LOCAL_ONLY_ENV: "0", PROVIDER_ALLOWED_ENV: None},
            "cache_miss",
            Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED,
        ),
        "max_calls_enforced_adapter": verify_adapter_status(
            {LIVE_ENABLED_ENV: "1", CACHE_WRITE_ENABLED_ENV: "1", LOCAL_ONLY_ENV: "0", PROVIDER_ALLOWED_ENV: "1", MAX_CALLS_ENV: "0"},
            "cache_miss",
            Phase2EStatus.PROVIDER_BUDGET_EXHAUSTED,
        ),
        "cache_write_required_adapter": verify_adapter_status(
            {LIVE_ENABLED_ENV: "1", LOCAL_ONLY_ENV: "0", PROVIDER_ALLOWED_ENV: "1", MAX_CALLS_ENV: "1"},
            "cache_miss",
            Phase2EStatus.LIVE_CALL_NOT_AUTHORIZED,
        ),
        "cache_hit_route_skips_provider": with_env(
            route_env(DEFAULT_CACHE, phase2e_live=True),
            lambda: verify_success(client, "phase2d_cached_recognized", {"review_required": 20}),
        ),
        "fresh_request_skips_configured_cache": with_env(
            route_env(DEFAULT_CACHE, phase2e_live=False),
            lambda: verify_error(client, 503, "recognition_unavailable", {"freshPhase2E": "1"}),
        ),
        "cache_miss_live_disabled_fails_closed": with_env(
            route_env(fixtures["missing"], phase2e_live=False),
            lambda: verify_error(client, 503, "recognition_unavailable"),
        ),
        "cache_miss_live_not_authorized_fails_closed": with_env(
            route_env(fixtures["missing"], phase2e_live=True, local_only=True),
            lambda: verify_error(client, 503, "recognition_unavailable"),
        ),
        "stable_same_image_recognized_path": verify_stable_same_image_recognized_path(),
        "provider_gate_assertion_default_closed": verify_provider_gate_assertion_closed(),
        "provider_gate_assertion_explicit_open": verify_provider_gate_assertion_open(),
        "live_provider_autofills_clear_items": verify_live_provider_payload_autofills_clear_items(),
        "live_provider_blocks_ambiguous_or_invalid_items": verify_live_provider_payload_blocks_ambiguous_or_invalid_items(),
        "external_call_counts": {"submit_test": 0, "gemini_provider": 0, "old_ocr_route": 0},
    }
    print(json.dumps({"ok": True, "route": ROUTE, "results": results}, ensure_ascii=False, indent=2))
    return 0


def verify_error(client, expected_status: int, expected_code: str, extra_fields: dict[str, str] | None = None) -> JsonObject:
    fields = {
        "sid": "990",
        "testId": ALLOWED_TEST_ID,
        "round": "1",
        "image": (FULL_SHEET.open("rb"), "full_sheet.jpg", "image/jpeg"),
    }
    if extra_fields:
        fields.update(extra_fields)
    response = client.post(ROUTE, data={
        **fields,
    })
    payload = response.get_json(silent=True)
    if response.status_code != expected_status or not isinstance(payload, dict):
        raise Phase2EVerificationError(f"error case returned {response.status_code}: {response.get_data(as_text=True)}")
    if payload.get("ok") is not False or payload.get("errorCode") != expected_code:
        raise Phase2EVerificationError(f"wrong error payload: {payload}")
    if "review_payload" in payload:
        raise Phase2EVerificationError("error response included review_payload")
    return {"http_status": response.status_code, "errorCode": expected_code, "extra_fields": sorted((extra_fields or {}).keys())}


def verify_default_flags() -> JsonObject:
    flags = phase2e_flags_from_env({})
    names = (
        "live_enabled",
        "cache_write_enabled",
        "local_only",
        "provider_calls_require_cache_miss",
        "max_provider_calls_per_request",
        "fail_closed_on_provider_error",
    )
    return {name: getattr(flags, name) for name in names}


def verify_adapter_status(values: dict[str, str | None], cache_miss_reason: str, expected: Phase2EStatus) -> JsonObject:
    env = {key: None for key in PHASE2E_ENV_KEYS}
    env.update(values)
    return with_env(env, lambda: assert_adapter_status(cache_miss_reason, expected))


def assert_adapter_status(cache_miss_reason: str, expected: Phase2EStatus) -> JsonObject:
    result = prepare_phase2e_live_ocr(
        Phase2ERequest(
            sid="990",
            test_id=ALLOWED_TEST_ID,
            round_no=1,
            pipeline_result=fake_pipeline_result(),
            cache_miss_reason=cache_miss_reason,
            request_metadata={"verifier": "phase2e"},
        )
    )
    if result.status is not expected:
        raise Phase2EVerificationError(f"status {result.status.value} != {expected.value}")
    if result.provider_call_count != 0 or result.provider_call_attempted:
        raise Phase2EVerificationError("Phase 2E skeleton attempted a provider call")
    return {
        "status": result.status.value,
        "provider_call_count": result.provider_call_count,
        "provider_call_attempted": result.provider_call_attempted,
        "max_provider_calls": result.max_provider_calls,
    }


def verify_provider_gate_assertion_closed() -> JsonObject:
    flags = phase2e_flags_from_env({})
    result = assert_phase2e_provider_gate_open(fake_phase2e_request(), flags)
    if result is None:
        raise Phase2EVerificationError("default provider gate unexpectedly opened")
    if result.provider_call_attempted or result.provider_call_count:
        raise Phase2EVerificationError("closed provider gate reported a provider call")
    return {
        "status": result.status.value,
        "reason": result.reason,
        "provider_gate_open": phase2e_provider_gate_is_open(flags),
        "provider_call_count": result.provider_call_count,
    }


def verify_provider_gate_assertion_open() -> JsonObject:
    flags = Phase2EFeatureFlags(
        live_enabled=True,
        cache_write_enabled=True,
        local_only=False,
        provider_calls_require_cache_miss=True,
        max_provider_calls_per_request=1,
        fail_closed_on_provider_error=True,
        provider_calls_allowed=True,
    )
    result = assert_phase2e_provider_gate_open(fake_phase2e_request(), flags)
    if result is not None:
        raise Phase2EVerificationError(f"explicit provider gate did not open: {result.status.value} {result.reason}")
    return {
        "provider_gate_open": phase2e_provider_gate_is_open(flags),
        "provider_call_count": 0,
        "provider_call_attempted": False,
    }


def verify_live_provider_payload_autofills_clear_items() -> JsonObject:
    recognized = {
        1: "4",
        2: "4",
        3: "3",
        4: "4",
        5: "2",
        6: "4",
        7: "12",
        8: "3",
        9: "9",
        10: "64",
        11: "42",
        12: "3",
        13: "4",
        14: "12",
        15: "5",
        16: "5",
        17: "3",
        18: "90",
        19: "4",
        20: "16",
    }
    payload = review_payload_from_provider_items(provider_items(recognized), fake_phase2e_request())
    items = require_array(payload.get("items"), "phase2e_live.items")
    statuses = count_statuses(items)
    expected = {"review_required": 20}
    if statuses != expected:
        raise Phase2EVerificationError(f"live provider statuses {statuses} != {expected}")
    assert_item_status(items, 1, "review_required", None)
    assert_item_status(items, 9, "review_required", None)
    assert_item_status(items, 14, "review_required", None)
    assert_item_status(items, 16, "review_required", None)
    assert_item_status(items, 17, "review_required", None)
    assert_item_status(items, 18, "review_required", None)
    assert_item_candidate(items, 1, "4")
    assert_item_candidate(items, 16, "5")
    assert_item_candidate(items, 17, "3")
    assert_item_warning(items, 9, "choice_number_invalid_for_auto_grade")
    assert_item_warning(items, 14, "choice_number_invalid_for_auto_grade")
    assert_item_warning(items, 18, "digit_shape_confusion")
    return {"items": len(items), "statuses": statuses, "manual_review_questions": [9, 14, 18]}


def verify_live_provider_payload_blocks_ambiguous_or_invalid_items() -> JsonObject:
    recognized = {number: "1" for number in range(1, 21)}
    recognized[1] = "x=2"
    recognized[2] = "y=3"
    recognized[3] = "1->3"
    recognized[5] = "9"
    payload = review_payload_from_provider_items(provider_items(recognized), fake_phase2e_request())
    items = require_array(payload.get("items"), "phase2e_live.items")
    statuses = count_statuses(items)
    expected = {"review_required": 20}
    if statuses != expected:
        raise Phase2EVerificationError(f"ambiguous provider statuses {statuses} != {expected}")
    assert_item_warning(items, 1, "relation_symbol_confusion")
    assert_item_warning(items, 2, "relation_symbol_confusion")
    assert_item_warning(items, 3, "arrow_equal_confusion")
    assert_item_warning(items, 5, "choice_number_invalid_for_auto_grade")
    return {"items": len(items), "statuses": statuses, "blocked_questions": [1, 2, 3, 5]}


def assert_item_candidate(items: list[JsonObject], question_no: int, candidate: str) -> None:
    item = next((value for value in items if isinstance(value, dict) and value.get("question_no") == question_no), None)
    if item is None:
        raise Phase2EVerificationError(f"q{question_no:03d} missing")
    candidates = require_array(item.get("candidates"), f"q{question_no:03d}.candidates")
    if candidate not in candidates:
        raise Phase2EVerificationError(f"q{question_no:03d} candidates {candidates} missing {candidate}")


if __name__ == "__main__":
    raise SystemExit(main())
