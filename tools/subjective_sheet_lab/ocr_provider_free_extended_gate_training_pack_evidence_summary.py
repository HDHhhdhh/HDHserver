# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by ocr_provider_free_extended_gate_training_pack_evidence.py

from __future__ import annotations

from ocr_provider_free_extended_gate_common import JsonObject


def training_pack_evidence_intake_summary_fields() -> JsonObject:
    return {
        "training_pack_recognized_evidence_intake_target_count": 4,
        "training_pack_recognized_evidence_intake_file_count": 0,
        "training_pack_recognized_evidence_intake_value_count": 0,
        "training_pack_recognized_evidence_intake_readiness_probe_count": 3,
        "training_pack_recognized_evidence_intake_ready_probe_count": 1,
        "training_pack_recognized_evidence_intake_blocked_probe_count": 2,
    }


def training_pack_evidence_target_coverage_summary_fields() -> JsonObject:
    return {
        "training_pack_recognized_evidence_target_coverage_target_count": 4,
        "training_pack_recognized_evidence_target_coverage_file_count": 0,
        "training_pack_recognized_evidence_target_coverage_covered_count": 0,
        "training_pack_recognized_evidence_target_coverage_missing_count": 4,
        "training_pack_recognized_evidence_target_coverage_duplicate_count": 0,
        "training_pack_recognized_evidence_target_coverage_unexpected_count": 0,
        "training_pack_recognized_evidence_target_coverage_missing_test_id_count": 0,
        "training_pack_recognized_evidence_target_coverage_probe_count": 5,
        "training_pack_recognized_evidence_target_coverage_ready_probe_count": 1,
        "training_pack_recognized_evidence_target_coverage_blocked_probe_count": 4,
        "training_pack_recognized_evidence_target_coverage_ready": False,
    }


def training_pack_evidence_contract_summary_fields() -> JsonObject:
    return {
        "training_pack_recognized_evidence_contract_target_count": 4,
        "training_pack_recognized_evidence_contract_file_count": 0,
        "training_pack_recognized_evidence_contract_probe_count": 10,
        "training_pack_recognized_evidence_contract_rejected_probe_count": 9,
        "training_pack_recognized_evidence_contract_sensitive_probe_count": 1,
        "training_pack_recognized_evidence_contract_path_probe_count": 1,
        "training_pack_recognized_evidence_contract_schema_probe_count": 7,
        "training_pack_recognized_evidence_contract_item_count_schema_probe_count": 1,
        "training_pack_recognized_evidence_contract_question_sequence_schema_probe_count": 1,
        "training_pack_recognized_evidence_contract_status_schema_probe_count": 2,
        "training_pack_recognized_evidence_contract_safe_auto_grade_status_probe_count": 1,
        "training_pack_recognized_evidence_contract_recognized_answer_schema_probe_count": 1,
        "training_pack_recognized_evidence_contract_blank_recognized_answer_probe_count": 1,
        "training_pack_recognized_evidence_contract_ready": True,
    }


def training_pack_evidence_example_shape_summary_fields() -> JsonObject:
    return {
        "training_pack_recognized_evidence_example_shape_target_count": 4,
        "training_pack_recognized_evidence_example_shape_payload_count": 4,
        "training_pack_recognized_evidence_example_shape_accepted_count": 4,
        "training_pack_recognized_evidence_example_shape_rejected_count": 0,
        "training_pack_recognized_evidence_example_shape_item_count": 80,
        "training_pack_recognized_evidence_example_shape_review_required_count": 80,
        "training_pack_recognized_evidence_example_shape_safe_auto_grade_count": 0,
        "training_pack_recognized_evidence_example_shape_write_attempted": False,
        "training_pack_recognized_evidence_example_shape_evidence_write_attempted": False,
        "training_pack_recognized_evidence_example_shape_replacement_without_approval": False,
    }


def training_pack_blank_evidence_rejection_summary_fields() -> JsonObject:
    return {
        "training_pack_blank_evidence_rejection_target_count": 4,
        "training_pack_blank_evidence_rejection_skeleton_file_count": 4,
        "training_pack_blank_evidence_rejection_target_file_match_count": 4,
        "training_pack_blank_evidence_rejection_accepted_file_count": 0,
        "training_pack_blank_evidence_rejection_rejected_file_count": 4,
        "training_pack_blank_evidence_rejection_blank_rejection_count": 4,
        "training_pack_blank_evidence_rejection_review_item_count": 80,
        "training_pack_blank_evidence_rejection_blank_recognized_value_count": 80,
        "training_pack_blank_evidence_rejection_safe_auto_grade_count": 0,
        "training_pack_blank_evidence_rejection_evidence_promotion_allowed": False,
        "training_pack_blank_evidence_rejection_replacement_allowed_without_real_ocr": False,
    }
