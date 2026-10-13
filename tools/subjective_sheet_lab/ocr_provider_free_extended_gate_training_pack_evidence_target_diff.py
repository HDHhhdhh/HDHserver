from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)


def require_training_pack_evidence_target_diff(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_USER_APPROVAL_REQUIRED",
        "training_pack_recognized_evidence_target_diff.status",
    )
    require_int_value(report.get("target_count"), 4, "training_pack_recognized_evidence_target_diff.target_count")
    require_int_value(report.get("target_row_count"), 4, "training_pack_recognized_evidence_target_diff.target_row_count")
    require_int_value(report.get("evidence_file_count"), 0, "training_pack_recognized_evidence_target_diff.file_count")
    require_int_value(report.get("covered_target_count"), 0, "training_pack_recognized_evidence_target_diff.covered_count")
    require_int_value(report.get("missing_target_count"), 4, "training_pack_recognized_evidence_target_diff.missing_count")
    require_int_value(
        report.get("duplicate_evidence_target_count"),
        0,
        "training_pack_recognized_evidence_target_diff.duplicate_count",
    )
    require_int_value(
        report.get("unexpected_evidence_target_count"),
        0,
        "training_pack_recognized_evidence_target_diff.unexpected_count",
    )
    require_int_value(
        report.get("missing_test_id_file_count"),
        0,
        "training_pack_recognized_evidence_target_diff.missing_test_id_count",
    )
    require_bool_value(report.get("target_diff_ready"), False, "training_pack_recognized_evidence_target_diff.ready")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_recognized_evidence_target_diff.next")


def training_pack_evidence_target_diff_summary_fields() -> JsonObject:
    return {
        "training_pack_recognized_evidence_target_diff_row_count": 4,
        "training_pack_recognized_evidence_target_diff_file_count": 0,
        "training_pack_recognized_evidence_target_diff_covered_count": 0,
        "training_pack_recognized_evidence_target_diff_missing_count": 4,
        "training_pack_recognized_evidence_target_diff_duplicate_count": 0,
        "training_pack_recognized_evidence_target_diff_unexpected_count": 0,
        "training_pack_recognized_evidence_target_diff_missing_test_id_count": 0,
        "training_pack_recognized_evidence_target_diff_ready": False,
    }
