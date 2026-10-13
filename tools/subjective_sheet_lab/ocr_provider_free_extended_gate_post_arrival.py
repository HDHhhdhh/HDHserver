from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_post_arrival_dry_run_sequence import REPORT_JSON as POST_ARRIVAL_JSON
from verify_ocr_training_pack_post_arrival_dry_run_sequence import main as verify_post_arrival_sequence

Verifier: TypeAlias = Callable[[], int]


def post_arrival_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack post-arrival dry-run sequence", verify_post_arrival_sequence),)


def post_arrival_reports() -> dict[str, JsonObject]:
    return {"training_pack_post_arrival_dry_run_sequence": read_json_object(POST_ARRIVAL_JSON)}


def require_training_pack_post_arrival_sequence(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_SEQUENCE_USER_APPROVAL_REQUIRED",
        "post_arrival.status",
    )
    require_text_value(
        report.get("stops_before"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "post_arrival.stops_before",
    )
    require_int_value(report.get("planned_command_count"), 8, "post_arrival.planned_command_count")
    require_bool_value(report.get("payload_parse_after_smoke_only"), True, "post_arrival.payload_parse_after_smoke_only")
    require_bool_value(report.get("current_ready"), False, "post_arrival.current_ready")
    require_bool_value(report.get("ready_after_required_files"), True, "post_arrival.ready_after_required_files")
    for key in (
        "promotion_write_attempted",
        "replacement_write_attempted",
        "accuracy_recompute_attempted",
        "runtime_write_attempted",
    ):
        require_bool_value(report.get(key), False, f"post_arrival.{key}")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(report.get(key), 0, f"post_arrival.{key}")
    require_int_value(report.get("answer_key_or_grading_field_leak_count"), 0, "post_arrival.answer_key_leak")
    require_int_value(report.get("filesystem_path_leak_count"), 0, "post_arrival.path_leak")


def post_arrival_summary_fields() -> JsonObject:
    return {
        "training_pack_post_arrival_sequence_status": "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_SEQUENCE_USER_APPROVAL_REQUIRED",
        "training_pack_post_arrival_sequence_command_count": 8,
        "training_pack_post_arrival_sequence_ready_now": False,
        "training_pack_post_arrival_sequence_ready_after_required_files": True,
        "training_pack_post_arrival_sequence_stops_before": "promotion_replacement_accuracy_recompute_or_runtime_write",
    }
