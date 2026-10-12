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
from ocr_provider_free_extended_gate_training_pack_evidence_summary import (
    training_pack_evidence_example_shape_summary_fields,
)


def require_training_pack_evidence_example_shape(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_EXAMPLE_SHAPE_READY_USER_APPROVAL_REQUIRED",
        "training_pack_recognized_evidence_example_shape.status",
    )
    require_int_value(report.get("target_count"), 4, "training_pack_recognized_evidence_example_shape.target_count")
    require_int_value(
        report.get("example_payload_count"),
        4,
        "training_pack_recognized_evidence_example_shape.example_payload_count",
    )
    require_int_value(
        report.get("example_contract_accepted_count"),
        4,
        "training_pack_recognized_evidence_example_shape.example_contract_accepted_count",
    )
    require_int_value(
        report.get("example_contract_rejected_count"),
        0,
        "training_pack_recognized_evidence_example_shape.example_contract_rejected_count",
    )
    require_int_value(
        report.get("example_item_count"),
        80,
        "training_pack_recognized_evidence_example_shape.example_item_count",
    )
    require_int_value(
        report.get("example_review_required_count"),
        80,
        "training_pack_recognized_evidence_example_shape.example_review_required_count",
    )
    require_int_value(
        report.get("example_safe_auto_grade_count"),
        0,
        "training_pack_recognized_evidence_example_shape.example_safe_auto_grade_count",
    )
    require_bool_value(
        report.get("example_payload_write_attempted"),
        False,
        "training_pack_recognized_evidence_example_shape.example_payload_write_attempted",
    )
    require_bool_value(
        report.get("evidence_file_write_attempted"),
        False,
        "training_pack_recognized_evidence_example_shape.evidence_file_write_attempted",
    )
    require_bool_value(
        report.get("replacement_allowed_without_user_approval"),
        False,
        "training_pack_recognized_evidence_example_shape.replacement_allowed_without_user_approval",
    )
    require_text_value(
        report.get("next_status"),
        "USER_APPROVAL_REQUIRED",
        "training_pack_recognized_evidence_example_shape.next_status",
    )
