from __future__ import annotations

from typing import Literal, TypedDict, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    require_bool_value,
    require_int,
    require_int_value,
    require_text_value,
)

OperatorState = Literal["READY", "STALE", "BLOCKED"]


class OperatorSummaryReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    operator_state: OperatorState
    status_card_report_path: str
    status_card_status: str
    manual_qa_handoff_status: str
    manual_qa_ready: bool
    source_report_count: int
    stale_source_count: int
    failed_source_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    required_user_action: str
    operator_next_action_status: str
    operator_next_action: str
    current_blocker: str
    operator_required_file_count: int
    operator_present_file_count: int
    operator_missing_file_count: int
    operator_ready_now: bool
    operator_ready_after_required_files: bool
    promotion_write_authorization_required: bool
    next_safe_action: str


def build_report(status_card_payload: JsonObject, next_action_payload: JsonObject) -> OperatorSummaryReport:
    assert_status_card_safety(status_card_payload)
    assert_next_action_summary(next_action_payload)
    state = operator_state(status_card_payload)
    next_action = require_text(next_action_payload.get("operator_next_action"), "operator_next_action.operator_next_action")
    return {
        "ok": True,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_OPERATOR_SUMMARY_VERIFIED",
        "operator_state": state,
        "status_card_report_path": status_card_path(),
        "status_card_status": require_text(status_card_payload.get("status"), "status_card.status"),
        "manual_qa_handoff_status": require_text(
            status_card_payload.get("manual_qa_handoff_status"),
            "status_card.manual_qa_handoff_status",
        ),
        "manual_qa_ready": state == "READY",
        "source_report_count": require_int(status_card_payload.get("source_report_count"), "status_card.source_report_count"),
        "stale_source_count": require_int(status_card_payload.get("stale_source_count"), "status_card.stale_source_count"),
        "failed_source_count": require_int(status_card_payload.get("failed_source_count"), "status_card.failed_source_count"),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "required_user_action": next_action if state == "READY" else required_user_action(state),
        "operator_next_action_status": require_text(next_action_payload.get("status"), "operator_next_action.status"),
        "operator_next_action": next_action,
        "current_blocker": require_text(next_action_payload.get("current_blocker"), "operator_next_action.current_blocker"),
        "operator_required_file_count": require_int(next_action_payload.get("required_file_count"), "operator_next_action.required_file_count"),
        "operator_present_file_count": require_int(next_action_payload.get("present_file_count"), "operator_next_action.present_file_count"),
        "operator_missing_file_count": require_int(next_action_payload.get("missing_file_count"), "operator_next_action.missing_file_count"),
        "operator_ready_now": require_bool_return(next_action_payload.get("ready_now"), False, "operator_next_action.ready_now"),
        "operator_ready_after_required_files": require_bool_return(
            next_action_payload.get("ready_after_required_files"),
            True,
            "operator_next_action.ready_after_required_files",
        ),
        "promotion_write_authorization_required": require_bool_return(
            next_action_payload.get("promotion_write_authorization_required"),
            True,
            "operator_next_action.promotion_write_authorization_required",
        ),
        "next_safe_action": next_safe_action(state, next_action),
    }


def assert_status_card_safety(payload: JsonObject) -> None:
    require_bool(payload.get("student_facing"), False, "status_card.student_facing")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"status_card.{key}")
    require_int_value(
        payload.get("answer_key_or_grading_field_leak_count"),
        0,
        "status_card.answer_key_or_grading_field_leak_count",
    )
    require_int_value(payload.get("filesystem_path_leak_count"), 0, "status_card.filesystem_path_leak_count")
    require_text_value(payload.get("production_default"), "NO_GO", "status_card.production_default")


def assert_next_action_summary(payload: JsonObject) -> None:
    require_text_value(payload.get("status"), "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED", "operator_next_action.status")
    require_text_value(
        payload.get("operator_next_action"),
        "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "operator_next_action.operator_next_action",
    )
    require_text_value(
        payload.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "operator_next_action.current_blocker",
    )
    require_int_value(payload.get("required_file_count"), 4, "operator_next_action.required_file_count")
    require_int_value(payload.get("present_file_count"), 0, "operator_next_action.present_file_count")
    require_int_value(payload.get("missing_file_count"), 4, "operator_next_action.missing_file_count")
    require_bool_value(payload.get("ready_now"), False, "operator_next_action.ready_now")
    require_bool_value(payload.get("ready_after_required_files"), True, "operator_next_action.ready_after_required_files")
    require_bool_value(
        payload.get("api_authorization_required_for_next_action"),
        False,
        "operator_next_action.api_authorization_required_for_next_action",
    )
    require_bool_value(
        payload.get("provider_call_required_for_next_action"),
        False,
        "operator_next_action.provider_call_required_for_next_action",
    )
    require_bool_value(
        payload.get("promotion_write_authorization_required"),
        True,
        "operator_next_action.promotion_write_authorization_required",
    )
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"operator_next_action.{key}")
    require_int_value(
        payload.get("answer_key_or_grading_field_leak_count"),
        0,
        "operator_next_action.answer_key_or_grading_field_leak_count",
    )
    require_int_value(payload.get("filesystem_path_leak_count"), 0, "operator_next_action.filesystem_path_leak_count")
    require_text_value(payload.get("production_default"), "NO_GO", "operator_next_action.production_default")


def operator_state(payload: JsonObject) -> OperatorState:
    status = require_text(payload.get("status"), "status_card.status")
    stale_count = require_int(payload.get("stale_source_count"), "status_card.stale_source_count")
    failed_count = require_int(payload.get("failed_source_count"), "status_card.failed_source_count")
    match status:
        case "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_READY":
            require_bool(payload.get("ok"), True, "status_card.ok")
            require_text_value(payload.get("manual_qa_handoff_status"), "READY", "status_card.manual_qa_handoff_status")
            require_int_value(payload.get("source_report_count"), 2, "status_card.source_report_count")
            require_int_value(payload.get("stale_source_count"), 0, "status_card.stale_source_count")
            require_int_value(payload.get("failed_source_count"), 0, "status_card.failed_source_count")
            return "READY"
        case "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_BLOCKED":
            require_bool(payload.get("ok"), False, "status_card.ok")
            require_text_value(payload.get("manual_qa_handoff_status"), "BLOCKED", "status_card.manual_qa_handoff_status")
            if stale_count > 0:
                return "STALE"
            if failed_count > 0:
                return "BLOCKED"
            raise ExtendedGateError("status_card blocked without stale or failed source count")
        case str():
            raise ExtendedGateError(f"status_card.status unsupported: {status}")
        case unreachable:
            assert_never(unreachable)


def require_text(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def require_bool(value: JsonValue, expected: bool, label: str) -> None:
    require_bool_value(value, expected, label)


def require_bool_return(value: JsonValue, expected: bool, label: str) -> bool:
    require_bool_value(value, expected, label)
    return expected


def required_user_action(state: OperatorState) -> str:
    match state:
        case "READY":
            return "manual_qa_can_start"
        case "STALE":
            return "rerun_provider_free_handoff_status_card_chain"
        case "BLOCKED":
            return "inspect_handoff_status_card_source_reports"
        case unreachable:
            assert_never(unreachable)


def next_safe_action(state: OperatorState, operator_action: str) -> str:
    match state:
        case "READY":
            return f"{operator_action}; provider-free handoff is ready and live OCR remains approval gated."
        case "STALE":
            return "Refresh the final handoff/status-card chain before manual QA."
        case "BLOCKED":
            return "Open the status-card source reports and resolve the first failed metric."
        case unreachable:
            assert_never(unreachable)


def status_card_path() -> str:
    return "tools/subjective_sheet_lab/ocr_provider_free_handoff_status_card.json"
