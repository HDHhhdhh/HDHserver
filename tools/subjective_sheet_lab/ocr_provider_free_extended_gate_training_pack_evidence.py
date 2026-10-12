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
    training_pack_blank_evidence_rejection_summary_fields,
    training_pack_evidence_contract_summary_fields,
    training_pack_evidence_intake_summary_fields,
    training_pack_evidence_target_coverage_summary_fields,
)


def require_training_pack_evidence_contract(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS",
        "training_pack_recognized_evidence_contract.status",
    )
    require_int_value(report.get("target_count"), 4, "training_pack_recognized_evidence_contract.target_count")
    require_int_value(
        report.get("evidence_file_count"),
        0,
        "training_pack_recognized_evidence_contract.evidence_file_count",
    )
    require_int_value(
        report.get("contract_probe_count"),
        10,
        "training_pack_recognized_evidence_contract.contract_probe_count",
    )
    require_int_value(
        report.get("contract_probe_rejected_count"),
        9,
        "training_pack_recognized_evidence_contract.contract_probe_rejected_count",
    )
    require_int_value(
        report.get("forbidden_field_probe_rejected_count"),
        1,
        "training_pack_recognized_evidence_contract.forbidden_field_probe_rejected_count",
    )
    require_int_value(
        report.get("filesystem_path_probe_rejected_count"),
        1,
        "training_pack_recognized_evidence_contract.filesystem_path_probe_rejected_count",
    )
    require_int_value(
        report.get("schema_probe_rejected_count"),
        7,
        "training_pack_recognized_evidence_contract.schema_probe_rejected_count",
    )
    require_int_value(
        report.get("item_count_schema_probe_rejected_count"),
        1,
        "training_pack_recognized_evidence_contract.item_count_schema_probe_rejected_count",
    )
    require_int_value(
        report.get("question_sequence_schema_probe_rejected_count"),
        1,
        "training_pack_recognized_evidence_contract.question_sequence_schema_probe_rejected_count",
    )
    require_int_value(
        report.get("status_schema_probe_rejected_count"),
        2,
        "training_pack_recognized_evidence_contract.status_schema_probe_rejected_count",
    )
    require_int_value(
        report.get("safe_auto_grade_status_probe_rejected_count"),
        1,
        "training_pack_recognized_evidence_contract.safe_auto_grade_status_probe_rejected_count",
    )
    require_int_value(
        report.get("recognized_answer_schema_probe_rejected_count"),
        1,
        "training_pack_recognized_evidence_contract.recognized_answer_schema_probe_rejected_count",
    )
    require_int_value(
        report.get("blank_recognized_answer_probe_rejected_count"),
        1,
        "training_pack_recognized_evidence_contract.blank_recognized_answer_probe_rejected_count",
    )
    require_bool_value(report.get("contract_ready"), True, "training_pack_recognized_evidence_contract.contract_ready")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_recognized_evidence_contract.next_status")


def require_training_pack_evidence_intake(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_USER_APPROVAL_REQUIRED",
        "training_pack_recognized_evidence_intake.status",
    )
    require_int_value(report.get("target_count"), 4, "training_pack_recognized_evidence_intake.target_count")
    require_int_value(report.get("evidence_file_count"), 0, "training_pack_recognized_evidence_intake.evidence_file_count")
    require_int_value(report.get("recognized_value_count"), 0, "training_pack_recognized_evidence_intake.recognized_value_count")
    require_int_value(
        report.get("replacement_readiness_probe_count"),
        3,
        "training_pack_recognized_evidence_intake.replacement_readiness_probe_count",
    )
    require_int_value(
        report.get("replacement_readiness_probe_ready_count"),
        1,
        "training_pack_recognized_evidence_intake.replacement_readiness_probe_ready_count",
    )
    require_int_value(
        report.get("replacement_readiness_probe_blocked_count"),
        2,
        "training_pack_recognized_evidence_intake.replacement_readiness_probe_blocked_count",
    )


def require_training_pack_evidence_target_coverage(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_USER_APPROVAL_REQUIRED",
        "training_pack_recognized_evidence_target_coverage.status",
    )
    require_int_value(report.get("target_count"), 4, "training_pack_recognized_evidence_target_coverage.target_count")
    require_int_value(
        report.get("evidence_file_count"),
        0,
        "training_pack_recognized_evidence_target_coverage.evidence_file_count",
    )
    require_int_value(
        report.get("covered_target_count"),
        0,
        "training_pack_recognized_evidence_target_coverage.covered_target_count",
    )
    require_int_value(
        report.get("missing_target_count"),
        4,
        "training_pack_recognized_evidence_target_coverage.missing_target_count",
    )
    require_int_value(
        report.get("duplicate_target_count"),
        0,
        "training_pack_recognized_evidence_target_coverage.duplicate_target_count",
    )
    require_int_value(
        report.get("unexpected_target_count"),
        0,
        "training_pack_recognized_evidence_target_coverage.unexpected_target_count",
    )
    require_int_value(
        report.get("missing_test_id_count"),
        0,
        "training_pack_recognized_evidence_target_coverage.missing_test_id_count",
    )
    require_bool_value(
        report.get("target_coverage_ready"),
        False,
        "training_pack_recognized_evidence_target_coverage.target_coverage_ready",
    )
    require_int_value(
        report.get("coverage_probe_count"),
        5,
        "training_pack_recognized_evidence_target_coverage.coverage_probe_count",
    )
    require_int_value(
        report.get("coverage_probe_ready_count"),
        1,
        "training_pack_recognized_evidence_target_coverage.coverage_probe_ready_count",
    )
    require_int_value(
        report.get("coverage_probe_blocked_count"),
        4,
        "training_pack_recognized_evidence_target_coverage.coverage_probe_blocked_count",
    )
    require_text_value(
        report.get("next_status"),
        "USER_APPROVAL_REQUIRED",
        "training_pack_recognized_evidence_target_coverage.next_status",
    )


def require_training_pack_blank_evidence_rejection(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_BLANK_EVIDENCE_REJECTION_VERIFIED",
        "training_pack_blank_evidence_rejection.status",
    )
    require_int_value(report.get("target_count"), 4, "training_pack_blank_evidence_rejection.target_count")
    require_int_value(report.get("skeleton_file_count"), 4, "training_pack_blank_evidence_rejection.skeleton_file_count")
    require_int_value(
        report.get("target_file_match_count"),
        4,
        "training_pack_blank_evidence_rejection.target_file_match_count",
    )
    require_int_value(report.get("accepted_file_count"), 0, "training_pack_blank_evidence_rejection.accepted_file_count")
    require_int_value(report.get("rejected_file_count"), 4, "training_pack_blank_evidence_rejection.rejected_file_count")
    require_int_value(report.get("blank_rejection_count"), 4, "training_pack_blank_evidence_rejection.blank_rejection_count")
    require_int_value(report.get("review_item_count"), 80, "training_pack_blank_evidence_rejection.review_item_count")
    require_int_value(
        report.get("blank_recognized_value_count"),
        80,
        "training_pack_blank_evidence_rejection.blank_recognized_value_count",
    )
    require_int_value(report.get("safe_auto_grade_count"), 0, "training_pack_blank_evidence_rejection.safe_auto_grade_count")
    require_bool_value(
        report.get("evidence_promotion_allowed"),
        False,
        "training_pack_blank_evidence_rejection.evidence_promotion_allowed",
    )
    require_bool_value(
        report.get("replacement_allowed_without_real_ocr"),
        False,
        "training_pack_blank_evidence_rejection.replacement_allowed_without_real_ocr",
    )
