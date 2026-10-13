# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by ocr_provider_free_extended_gate_training_pack.py

from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)


def require_training_pack_promotion_gate(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_EVIDENCE_PROMOTION_USER_APPROVAL_REQUIRED",
        "training_pack_evidence_promotion.status",
    )
    require_int_value(report.get("target_count"), 4, "training_pack_evidence_promotion.target_count")
    require_int_value(report.get("evidence_file_count"), 0, "training_pack_evidence_promotion.evidence_file_count")
    require_int_value(report.get("recognized_value_count"), 0, "training_pack_evidence_promotion.recognized_value_count")
    require_int_value(
        report.get("target_coverage_missing_count"),
        4,
        "training_pack_evidence_promotion.target_coverage_missing_count",
    )
    require_int_value(report.get("promotion_probe_count"), 5, "training_pack_evidence_promotion.promotion_probe_count")
    require_int_value(
        report.get("promotion_probe_ready_count"),
        1,
        "training_pack_evidence_promotion.promotion_probe_ready_count",
    )
    require_int_value(
        report.get("promotion_probe_blocked_count"),
        4,
        "training_pack_evidence_promotion.promotion_probe_blocked_count",
    )
    require_bool_value(report.get("contract_ready"), True, "training_pack_evidence_promotion.contract_ready")
    require_bool_value(
        report.get("target_coverage_ready"),
        False,
        "training_pack_evidence_promotion.target_coverage_ready",
    )
    require_bool_value(
        report.get("replacement_input_ready"),
        False,
        "training_pack_evidence_promotion.replacement_input_ready",
    )
    require_bool_value(report.get("replacement_allowed"), False, "training_pack_evidence_promotion.replacement_allowed")
    require_bool_value(report.get("promotion_ready"), False, "training_pack_evidence_promotion.promotion_ready")
    require_bool_value(report.get("promotion_allowed"), False, "training_pack_evidence_promotion.promotion_allowed")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_evidence_promotion.next_status")


def training_pack_promotion_summary_fields() -> JsonObject:
    return {
        "training_pack_evidence_promotion_file_count": 0,
        "training_pack_evidence_promotion_recognized_value_count": 0,
        "training_pack_evidence_promotion_missing_target_count": 4,
        "training_pack_evidence_promotion_ready_probe_count": 1,
        "training_pack_evidence_promotion_blocked_probe_count": 4,
        "training_pack_evidence_promotion_ready": False,
        "training_pack_evidence_promotion_allowed": False,
    }
