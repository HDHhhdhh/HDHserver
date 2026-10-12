# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by ocr_provider_free_extended_gate_summary.py

from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)


def require_training_pack_arrival_readiness(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_EVIDENCE_ARRIVAL_READINESS_USER_APPROVAL_REQUIRED",
        "training_pack_arrival_readiness.status",
    )
    require_int_value(report.get("target_count"), 4, "training_pack_arrival_readiness.target_count")
    require_int_value(
        report.get("current_evidence_payload_count"),
        0,
        "training_pack_arrival_readiness.current_evidence_payload_count",
    )
    require_int_value(
        report.get("current_missing_payload_count"),
        4,
        "training_pack_arrival_readiness.current_missing_payload_count",
    )
    require_int_value(
        report.get("current_blocked_check_count"),
        4,
        "training_pack_arrival_readiness.current_blocked_check_count",
    )
    require_int_value(
        report.get("post_file_ready_check_count"),
        4,
        "training_pack_arrival_readiness.post_file_ready_check_count",
    )
    require_int_value(
        report.get("post_file_required_check_count"),
        4,
        "training_pack_arrival_readiness.post_file_required_check_count",
    )
    require_bool_value(report.get("post_file_arrival_ready"), True, "training_pack_arrival_readiness.ready_after_files")
    require_bool_value(report.get("current_arrival_ready"), False, "training_pack_arrival_readiness.ready_now")
    require_bool_value(report.get("promotion_write_attempted"), False, "training_pack_arrival_readiness.promotion_write_attempted")
    require_bool_value(report.get("replacement_write_attempted"), False, "training_pack_arrival_readiness.replacement_write_attempted")
    require_bool_value(report.get("accuracy_recompute_attempted"), False, "training_pack_arrival_readiness.accuracy_recompute_attempted")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_arrival_readiness.next_status")


def training_pack_arrival_readiness_summary_fields() -> JsonObject:
    return {
        "training_pack_arrival_readiness_target_count": 4,
        "training_pack_arrival_readiness_current_payload_count": 0,
        "training_pack_arrival_readiness_missing_payload_count": 4,
        "training_pack_arrival_readiness_current_blocked_count": 4,
        "training_pack_arrival_readiness_ready_check_count": 4,
        "training_pack_arrival_readiness_required_check_count": 4,
        "training_pack_arrival_readiness_ready_after_files": True,
        "training_pack_arrival_readiness_ready_now": False,
        "training_pack_arrival_readiness_promotion_write_attempted": False,
        "training_pack_arrival_readiness_replacement_write_attempted": False,
        "training_pack_arrival_readiness_accuracy_recompute_attempted": False,
    }
