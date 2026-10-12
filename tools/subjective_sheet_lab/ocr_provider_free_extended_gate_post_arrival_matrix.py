from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_post_arrival_dry_run_readiness_matrix import REPORT_JSON as POST_ARRIVAL_MATRIX_JSON
from verify_ocr_training_pack_post_arrival_dry_run_readiness_matrix import main as verify_post_arrival_matrix

Verifier: TypeAlias = Callable[[], int]


def post_arrival_matrix_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack post-arrival dry-run readiness matrix", verify_post_arrival_matrix),)


def post_arrival_matrix_reports() -> dict[str, JsonObject]:
    return {"training_pack_post_arrival_dry_run_readiness_matrix": read_json_object(POST_ARRIVAL_MATRIX_JSON)}


def require_training_pack_post_arrival_readiness_matrix(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_READINESS_MATRIX_READY",
        "post_arrival_matrix.status",
    )
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "post_arrival_matrix.current_blocker",
    )
    for key, value in matrix_counts():
        require_int_value(report.get(key), value, f"post_arrival_matrix.{key}")


def matrix_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("ordered_command_count", 8),
        ("currently_runnable_command_count", 3),
        ("blocked_missing_evidence_count", 5),
        ("after_files_runnable_command_count", 8),
        ("payload_parse_allowed_now_count", 0),
        ("write_allowed_command_count", 0),
        ("stop_before_write_command_count", 1),
    )


def post_arrival_matrix_summary_fields() -> JsonObject:
    return {
        "training_pack_post_arrival_matrix_status": "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_READINESS_MATRIX_READY",
        "training_pack_post_arrival_matrix_command_count": 8,
        "training_pack_post_arrival_matrix_runnable_now_count": 3,
        "training_pack_post_arrival_matrix_blocked_missing_evidence_count": 5,
        "training_pack_post_arrival_matrix_after_files_runnable_count": 8,
        "training_pack_post_arrival_matrix_write_allowed_count": 0,
    }
