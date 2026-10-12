from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_post_arrival_operator_runbook import REPORT_JSON as POST_ARRIVAL_RUNBOOK_JSON
from verify_ocr_training_pack_post_arrival_operator_runbook import main as verify_post_arrival_runbook

Verifier: TypeAlias = Callable[[], int]


def post_arrival_runbook_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack post-arrival operator runbook", verify_post_arrival_runbook),)


def post_arrival_runbook_reports() -> dict[str, JsonObject]:
    return {"training_pack_post_arrival_operator_runbook": read_json_object(POST_ARRIVAL_RUNBOOK_JSON)}


def require_training_pack_post_arrival_operator_runbook(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_OPERATOR_RUNBOOK_READY",
        "post_arrival_runbook.status",
    )
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "post_arrival_runbook.current_blocker",
    )
    require_text_value(
        report.get("user_action_required"),
        "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "post_arrival_runbook.user_action_required",
    )
    for key, value in runbook_counts():
        require_int_value(report.get(key), value, f"post_arrival_runbook.{key}")
    for key, value in runbook_booleans():
        require_bool_value(report.get(key), value, f"post_arrival_runbook.{key}")


def runbook_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("runbook_step_count", 8),
        ("validation_command_count", 8),
    )


def runbook_booleans() -> tuple[tuple[str, bool], ...]:
    return (
        ("payload_parse_before_arrival_allowed", False),
        ("payload_parse_after_arrival_allowed", True),
        ("promotion_write_allowed", False),
        ("replacement_write_allowed", False),
        ("runtime_write_allowed", False),
        ("accuracy_recompute_allowed", False),
        ("provider_call_required", False),
    )


def post_arrival_runbook_summary_fields() -> JsonObject:
    return {
        "training_pack_post_arrival_runbook_status": "TRAINING_PACK_POST_ARRIVAL_OPERATOR_RUNBOOK_READY",
        "training_pack_post_arrival_runbook_step_count": 8,
        "training_pack_post_arrival_runbook_validation_command_count": 8,
        "training_pack_post_arrival_runbook_missing_file_count": 4,
        "training_pack_post_arrival_runbook_payload_parse_before_arrival_allowed": False,
        "training_pack_post_arrival_runbook_payload_parse_after_arrival_allowed": True,
        "training_pack_post_arrival_runbook_provider_call_required": False,
        "training_pack_post_arrival_runbook_write_allowed": False,
    }
