from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_provider_free_extended_gate_count import EXTENDED_GATE_COUNT
from verify_ocr_next_action_queue_state import REPORT_JSON_OUT as QUEUE_STATE_JSON
from verify_ocr_next_action_queue_state import main as verify_queue_state
from verify_ocr_next_action_queue_state_guard import REPORT_JSON_OUT as QUEUE_STATE_GUARD_JSON
from verify_ocr_next_action_queue_state_guard import main as verify_queue_state_guard

Verifier: TypeAlias = Callable[[], int]


def queue_state_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (
        ("OCR next-action queue state", verify_queue_state),
        ("OCR next-action queue state guard", verify_queue_state_guard),
    )


def queue_state_reports() -> dict[str, JsonObject]:
    return {
        "ocr_next_action_queue_state": read_json_object(QUEUE_STATE_JSON),
        "ocr_next_action_queue_state_guard": read_json_object(QUEUE_STATE_GUARD_JSON),
    }


def require_ocr_next_action_queue_state(report: JsonObject) -> None:
    require_bool_value(report.get("ok"), True, "queue_state.ok")
    require_bool_value(report.get("latest_heading_present"), True, "queue_state.latest_heading_present")
    require_bool_value(report.get("latest_heading_at_tail"), True, "queue_state.latest_heading_at_tail")
    require_int_value(report.get("required_snippet_count"), 105, "queue_state.required_snippet_count")
    require_int_value(report.get("missing_snippet_count"), 0, "queue_state.missing_snippet_count")
    require_int_value(report.get("latest_required_snippet_count"), 24, "queue_state.latest_required_snippet_count")
    require_int_value(report.get("latest_missing_snippet_count"), 0, "queue_state.latest_missing_snippet_count")
    require_int_value(
        report.get("expected_extended_gate_count"),
        EXTENDED_GATE_COUNT,
        "queue_state.expected_extended_gate_count",
    )
    require_text_value(report.get("classifier_status"), "environment_split_verified", "queue_state.classifier_status")
    require_text_value(report.get("freshness_status"), "fresh_and_consistent", "queue_state.freshness_status")
    require_int_value(report.get("provider_call_count"), 0, "queue_state.provider_call_count")
    require_int_value(report.get("external_ocr_api_call_count"), 0, "queue_state.external_ocr_api_call_count")
    require_int_value(report.get("submit_test_call_count"), 0, "queue_state.submit_test_call_count")
    require_int_value(report.get("ts_submit_click_count"), 0, "queue_state.ts_submit_click_count")
    require_int_value(
        report.get("answer_key_or_grading_field_leak_count"),
        0,
        "queue_state.answer_key_or_grading_field_leak_count",
    )
    require_int_value(report.get("filesystem_path_leak_count"), 0, "queue_state.filesystem_path_leak_count")
    require_text_value(report.get("production_default"), "NO_GO", "queue_state.production_default")
    require_int_value(report.get("issue_count"), 0, "queue_state.issue_count")


def require_ocr_next_action_queue_state_guard(report: JsonObject) -> None:
    require_bool_value(report.get("ok"), True, "queue_state_guard.ok")
    require_text_value(report.get("status"), "OCR_NEXT_ACTION_QUEUE_STATE_GUARD_VERIFIED", "queue_state_guard.status")
    require_int_value(report.get("probe_count"), 2, "queue_state_guard.probe_count")
    require_int_value(report.get("failed_probe_count"), 0, "queue_state_guard.failed_probe_count")
    require_bool_value(
        report.get("missing_latest_required_snippet_blocked"),
        True,
        "queue_state_guard.missing_latest_required_snippet_blocked",
    )
    require_int_value(
        report.get("latest_required_snippet_removed_count"),
        1,
        "queue_state_guard.latest_required_snippet_removed_count",
    )
    require_int_value(report.get("provider_call_count"), 0, "queue_state_guard.provider_call_count")
    require_int_value(report.get("external_ocr_api_call_count"), 0, "queue_state_guard.external_ocr_api_call_count")
    require_int_value(report.get("submit_test_call_count"), 0, "queue_state_guard.submit_test_call_count")
    require_int_value(report.get("ts_submit_click_count"), 0, "queue_state_guard.ts_submit_click_count")
    require_int_value(
        report.get("answer_key_or_grading_field_leak_count"),
        0,
        "queue_state_guard.answer_key_or_grading_field_leak_count",
    )
    require_int_value(report.get("filesystem_path_leak_count"), 0, "queue_state_guard.filesystem_path_leak_count")
    require_text_value(report.get("production_default"), "NO_GO", "queue_state_guard.production_default")


def queue_state_summary_fields() -> JsonObject:
    return {
        "queue_state_verified": True,
        "queue_state_required_snippet_count": 105,
        "queue_state_missing_snippet_count": 0,
        "queue_state_latest_required_snippet_count": 24,
        "queue_state_latest_missing_snippet_count": 0,
        "queue_state_expected_extended_gate_count": EXTENDED_GATE_COUNT,
        "queue_state_latest_heading_present": True,
        "queue_state_latest_heading_at_tail": True,
        "queue_state_classifier_status": "environment_split_verified",
        "queue_state_freshness_status": "fresh_and_consistent",
        "queue_state_guard_verified": True,
        "queue_state_guard_probe_count": 2,
        "queue_state_guard_missing_latest_required_snippet_blocked": True,
    }
