# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by ocr_provider_free_extended_gate_summary.py

from __future__ import annotations

from ocr_provider_free_extended_gate_common import JsonObject, require_bool_value, require_int_value, require_text_value


def require_training_pack_post_dropbox_replay(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_POST_DROPBOX_INTAKE_REPLAY_READY_WAITING_FOR_EVIDENCE",
        "training_pack_post_dropbox.status",
    )
    for key, value in integer_expectations():
        require_int_value(report.get(key), value, f"training_pack_post_dropbox.{key}")
    require_bool_value(report.get("simulated_target_coverage_ready"), True, "training_pack_post_dropbox.coverage_ready")
    require_bool_value(report.get("simulated_replacement_input_ready"), True, "training_pack_post_dropbox.replacement_ready")
    require_bool_value(
        report.get("simulated_promotion_preconditions_ready"),
        True,
        "training_pack_post_dropbox.promotion_ready",
    )
    require_bool_value(
        report.get("promotion_allowed_without_user_approval"),
        False,
        "training_pack_post_dropbox.promotion_without_approval",
    )
    require_bool_value(
        report.get("replacement_payload_write_attempted"),
        False,
        "training_pack_post_dropbox.replacement_write_attempted",
    )
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_post_dropbox.next_status")


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("actual_evidence_file_count", 0),
        ("simulated_evidence_file_count", 4),
        ("simulated_contract_accepted_count", 4),
        ("simulated_contract_rejected_count", 0),
        ("simulated_recognized_value_count", 80),
        ("simulated_covered_target_count", 4),
        ("simulated_missing_target_count", 0),
    )


def training_pack_post_dropbox_summary_fields() -> JsonObject:
    return {
        "training_pack_post_dropbox_actual_evidence_file_count": 0,
        "training_pack_post_dropbox_simulated_evidence_file_count": 4,
        "training_pack_post_dropbox_simulated_recognized_value_count": 80,
        "training_pack_post_dropbox_simulated_coverage_ready": True,
        "training_pack_post_dropbox_simulated_promotion_ready": True,
        "training_pack_post_dropbox_promotion_without_approval": False,
        "training_pack_post_dropbox_replacement_write_attempted": False,
    }
