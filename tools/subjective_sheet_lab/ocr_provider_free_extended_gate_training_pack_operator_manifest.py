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


def require_training_pack_operator_evidence_manifest(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_OPERATOR_EVIDENCE_MANIFEST_USER_APPROVAL_REQUIRED",
        "training_pack_operator_manifest.status",
    )
    for key, value in integer_requirements():
        require_int_value(report.get(key), value, f"training_pack_operator_manifest.{key}")
    require_bool_value(report.get("manifest_ready_now"), False, "training_pack_operator_manifest.ready_now")
    require_bool_value(report.get("manifest_ready_after_files"), True, "training_pack_operator_manifest.ready_after_files")
    require_bool_value(report.get("write_attempted"), False, "training_pack_operator_manifest.write_attempted")
    require_bool_value(report.get("promotion_write_attempted"), False, "training_pack_operator_manifest.promotion_write_attempted")
    require_bool_value(report.get("replacement_write_attempted"), False, "training_pack_operator_manifest.replacement_write_attempted")
    require_bool_value(report.get("accuracy_recompute_attempted"), False, "training_pack_operator_manifest.accuracy_recompute_attempted")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_operator_manifest.next_status")


def training_pack_operator_evidence_manifest_summary_fields() -> JsonObject:
    return {
        "training_pack_operator_manifest_entry_count": 4,
        "training_pack_operator_manifest_present_count": 0,
        "training_pack_operator_manifest_missing_count": 4,
        "training_pack_operator_manifest_ready_now": False,
        "training_pack_operator_manifest_ready_after_files": True,
        "training_pack_operator_manifest_write_attempted": False,
        "training_pack_operator_manifest_promotion_write_attempted": False,
        "training_pack_operator_manifest_replacement_write_attempted": False,
        "training_pack_operator_manifest_accuracy_recompute_attempted": False,
    }


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4),
        ("manifest_entry_count", 4),
        ("present_entry_count", 0),
        ("missing_entry_count", 4),
        ("required_review_item_count_per_payload", 20),
    )
