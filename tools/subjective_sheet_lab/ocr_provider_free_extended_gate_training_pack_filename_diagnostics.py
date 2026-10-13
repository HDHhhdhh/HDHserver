from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)


def require_training_pack_filename_diagnostics(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_FILENAME_DIAGNOSTICS_USER_ACTION_REQUIRED",
        "training_pack_filename_diagnostics.status",
    )
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "training_pack_filename_diagnostics.blocker",
    )
    for key, value in filename_diagnostic_counts():
        require_int_value(report.get(key), value, f"training_pack_filename_diagnostics.{key}")
    require_bool_value(report.get("diagnostics_ready"), False, "training_pack_filename_diagnostics.ready")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_filename_diagnostics.next")


def filename_diagnostic_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("target_file_count", 4),
        ("expected_file_name_count", 4),
        ("evidence_file_count", 0),
        ("matching_file_name_count", 0),
        ("filename_mismatch_count", 0),
        ("unknown_test_id_file_count", 0),
        ("missing_test_id_file_count", 0),
    )


def training_pack_filename_diagnostics_summary_fields() -> JsonObject:
    return {
        "training_pack_recognized_evidence_filename_target_count": 4,
        "training_pack_recognized_evidence_filename_expected_count": 4,
        "training_pack_recognized_evidence_filename_file_count": 0,
        "training_pack_recognized_evidence_filename_match_count": 0,
        "training_pack_recognized_evidence_filename_mismatch_count": 0,
        "training_pack_recognized_evidence_filename_unknown_test_id_count": 0,
        "training_pack_recognized_evidence_filename_missing_test_id_count": 0,
        "training_pack_recognized_evidence_filename_diagnostics_ready": False,
    }
