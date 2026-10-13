from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_post_arrival_command_bundle import REPORT_JSON as COMMAND_BUNDLE_JSON
from verify_ocr_training_pack_post_arrival_command_bundle import main as verify_command_bundle

Verifier: TypeAlias = Callable[[], int]


def post_arrival_bundle_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack post-arrival command bundle", verify_command_bundle),)


def post_arrival_bundle_reports() -> dict[str, JsonObject]:
    return {"training_pack_post_arrival_command_bundle": read_json_object(COMMAND_BUNDLE_JSON)}


def require_training_pack_post_arrival_command_bundle(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_COMMAND_BUNDLE_USER_ACTION_REQUIRED",
        "post_arrival_bundle.status",
    )
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "post_arrival_bundle.current_blocker",
    )
    require_text_value(report.get("production_default"), "NO_GO", "post_arrival_bundle.production_default")
    for key, value in bundle_counts():
        require_int_value(report.get(key), value, f"post_arrival_bundle.{key}")
    for key, value in bundle_booleans():
        require_bool_value(report.get(key), value, f"post_arrival_bundle.{key}")


def bundle_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("bundle_step_count", 8),
        ("currently_executable_step_count", 3),
        ("blocked_by_missing_evidence_step_count", 5),
        ("after_files_executable_step_count", 8),
    )


def bundle_booleans() -> tuple[tuple[str, bool], ...]:
    return (
        ("bundle_ready_now", False),
        ("bundle_ready_after_required_files", True),
        ("payload_parse_before_arrival_allowed", False),
        ("payload_parse_after_arrival_allowed", True),
        ("provider_call_required", False),
        ("write_allowed", False),
    )


def post_arrival_bundle_summary_fields() -> JsonObject:
    return {
        "training_pack_post_arrival_bundle_status": "TRAINING_PACK_POST_ARRIVAL_COMMAND_BUNDLE_USER_ACTION_REQUIRED",
        "training_pack_post_arrival_bundle_ready_now": False,
        "training_pack_post_arrival_bundle_ready_after_files": True,
        "training_pack_post_arrival_bundle_step_count": 8,
        "training_pack_post_arrival_bundle_runnable_now_count": 3,
        "training_pack_post_arrival_bundle_blocked_missing_evidence_count": 5,
        "training_pack_post_arrival_bundle_after_files_count": 8,
        "training_pack_post_arrival_bundle_payload_parse_before_arrival_allowed": False,
        "training_pack_post_arrival_bundle_payload_parse_after_arrival_allowed": True,
        "training_pack_post_arrival_bundle_write_allowed": False,
        "training_pack_post_arrival_bundle_provider_call_required": False,
    }
