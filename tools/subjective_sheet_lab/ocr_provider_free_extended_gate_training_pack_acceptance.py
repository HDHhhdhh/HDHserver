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


def require_training_pack_acceptance_bundle(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_EVIDENCE_ACCEPTANCE_BUNDLE_USER_APPROVAL_REQUIRED",
        "training_pack_acceptance_bundle.status",
    )
    for key, value in integer_requirements():
        require_int_value(report.get(key), value, f"training_pack_acceptance_bundle.{key}")
    require_bool_value(report.get("current_bundle_ready"), False, "training_pack_acceptance_bundle.current_ready")
    require_bool_value(report.get("dry_run_bundle_ready"), True, "training_pack_acceptance_bundle.dry_run_ready")
    require_bool_value(report.get("bundle_write_attempted"), False, "training_pack_acceptance_bundle.bundle_write_attempted")
    require_bool_value(report.get("promotion_write_attempted"), False, "training_pack_acceptance_bundle.promotion_write_attempted")
    require_bool_value(report.get("replacement_write_attempted"), False, "training_pack_acceptance_bundle.replacement_write_attempted")
    require_bool_value(report.get("accuracy_recompute_attempted"), False, "training_pack_acceptance_bundle.accuracy_recompute_attempted")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_acceptance_bundle.next_status")


def training_pack_acceptance_bundle_summary_fields() -> JsonObject:
    return {
        "training_pack_acceptance_bundle_current_payload_count": 0,
        "training_pack_acceptance_bundle_missing_payload_count": 4,
        "training_pack_acceptance_bundle_current_ready": False,
        "training_pack_acceptance_bundle_dry_run_payload_count": 4,
        "training_pack_acceptance_bundle_dry_run_contract_accepted_count": 4,
        "training_pack_acceptance_bundle_dry_run_preview_match_count": 4,
        "training_pack_acceptance_bundle_dry_run_review_required_count": 80,
        "training_pack_acceptance_bundle_dry_run_safe_auto_grade_count": 0,
        "training_pack_acceptance_bundle_dry_run_ready_check_count": 4,
        "training_pack_acceptance_bundle_dry_run_required_check_count": 4,
        "training_pack_acceptance_bundle_dry_run_ready": True,
        "training_pack_acceptance_bundle_write_attempted": False,
        "training_pack_acceptance_bundle_promotion_write_attempted": False,
        "training_pack_acceptance_bundle_replacement_write_attempted": False,
        "training_pack_acceptance_bundle_accuracy_recompute_attempted": False,
    }


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4),
        ("current_payload_count", 0),
        ("current_missing_payload_count", 4),
        ("dry_run_payload_count", 4),
        ("dry_run_contract_accepted_count", 4),
        ("dry_run_preview_match_count", 4),
        ("dry_run_review_required_count", 80),
        ("dry_run_safe_auto_grade_count", 0),
        ("dry_run_ready_check_count", 4),
        ("dry_run_required_check_count", 4),
    )
