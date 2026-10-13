from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    read_json_object,
    require_bool_value,
    require_int,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_intake_only_no_promotion_gate import REPORT_JSON as INTAKE_ONLY_NO_PROMOTION_JSON
from verify_ocr_training_pack_intake_only_no_promotion_gate import main as verify_intake_only_no_promotion
from verify_ocr_operator_next_action_summary import REPORT_JSON as OPERATOR_NEXT_ACTION_JSON
from verify_ocr_operator_next_action_summary import main as verify_operator_next_action

Verifier: TypeAlias = Callable[[], int]


def operator_action_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (
        ("operator next-action summary", verify_operator_next_action),
        ("training pack intake-only no-promotion gate", verify_intake_only_no_promotion),
    )


def operator_action_reports() -> dict[str, JsonObject]:
    return {
        "operator_next_action": read_json_object(OPERATOR_NEXT_ACTION_JSON),
        "training_pack_intake_only_no_promotion": read_json_object(INTAKE_ONLY_NO_PROMOTION_JSON),
    }


def require_operator_next_action_summary(report: JsonObject) -> None:
    require_text_value(report.get("status"), "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED", "operator_action.status")
    require_text_value(
        report.get("operator_next_action"),
        "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "operator_action.next_action",
    )
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "operator_action.current_blocker",
    )
    require_min_int(report.get("extended_gate_count"), 57, "operator_action.extended_gate_count")
    for key, value in integer_requirements():
        require_int_value(report.get(key), value, f"operator_action.{key}")
    require_bool_value(report.get("ready_now"), False, "operator_action.ready_now")
    require_bool_value(report.get("ready_after_required_files"), True, "operator_action.ready_after_required_files")
    require_bool_value(
        report.get("api_authorization_required_for_next_action"),
        False,
        "operator_action.api_authorization_required",
    )
    require_bool_value(
        report.get("provider_call_required_for_next_action"),
        False,
        "operator_action.provider_call_required",
    )
    require_bool_value(
        report.get("promotion_write_authorization_required"),
        True,
        "operator_action.promotion_write_authorization_required",
    )


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("wrong_safe_auto_grade", 0),
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("required_review_item_count_per_payload", 20),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def require_training_pack_intake_only_no_promotion(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_INTAKE_ONLY_NO_PROMOTION_USER_ACTION_REQUIRED",
        "intake_only.status",
    )
    require_text_value(
        report.get("allowed_when_files_arrive"),
        "blank_rejection_then_contract_validate_then_intake_replay_only",
        "intake_only.allowed_when_files_arrive",
    )
    require_text_value(
        report.get("blocked_without_separate_authorization"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "intake_only.blocked_without_authorization",
    )
    for key, value in intake_only_integer_requirements():
        require_int_value(report.get(key), value, f"intake_only.{key}")
    for key, value in intake_only_bool_requirements():
        require_bool_value(report.get(key), value, f"intake_only.{key}")


def intake_only_integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("dry_run_review_required_count", 80),
        ("dry_run_safe_auto_grade_count", 0),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def intake_only_bool_requirements() -> tuple[tuple[str, bool], ...]:
    return (
        ("intake_replay_ready_now", False),
        ("intake_replay_ready_after_required_files", True),
        ("promotion_write_attempted", False),
        ("replacement_write_attempted", False),
        ("accuracy_recompute_attempted", False),
        ("runtime_write_attempted", False),
    )


def require_min_int(value: JsonValue, minimum: int, label: str) -> None:
    actual = require_int(value, label)
    if actual < minimum:
        raise ExtendedGateError(f"{label} expected at least {minimum}, got {actual}")


def operator_next_action_summary_fields() -> JsonObject:
    return {
        "operator_next_action_status": "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED",
        "operator_next_action": "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "operator_current_blocker": "training_pack_recognized_evidence_files_missing",
        "operator_required_file_count": 4,
        "operator_present_file_count": 0,
        "operator_missing_file_count": 4,
        "operator_ready_now": False,
        "operator_ready_after_required_files": True,
        "operator_api_authorization_required_for_next_action": False,
        "operator_provider_call_required_for_next_action": False,
        "operator_promotion_write_authorization_required": True,
    }


def intake_only_no_promotion_summary_fields() -> JsonObject:
    return {
        "training_pack_intake_only_no_promotion_status": "TRAINING_PACK_INTAKE_ONLY_NO_PROMOTION_USER_ACTION_REQUIRED",
        "training_pack_intake_only_allowed_when_files_arrive": "blank_rejection_then_contract_validate_then_intake_replay_only",
        "training_pack_intake_only_blocked_without_authorization": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "training_pack_intake_only_required_file_count": 4,
        "training_pack_intake_only_present_file_count": 0,
        "training_pack_intake_only_missing_file_count": 4,
        "training_pack_intake_only_ready_now": False,
        "training_pack_intake_only_ready_after_required_files": True,
        "training_pack_intake_only_promotion_write_attempted": False,
        "training_pack_intake_only_replacement_write_attempted": False,
        "training_pack_intake_only_runtime_write_attempted": False,
    }
