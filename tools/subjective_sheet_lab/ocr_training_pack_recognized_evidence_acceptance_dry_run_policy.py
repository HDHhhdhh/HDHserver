from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)


def require_acceptance_dry_run(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_RECOGNIZED_EVIDENCE_ACCEPTANCE_DRY_RUN_VERIFIED", "status")
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(output.get("next_action"), "copy_four_contract_valid_training_pack_recognized_evidence_files", "next_action")
    require_bool_value(output.get("complete_candidate_ready"), True, "complete_candidate_ready")
    for key, value in integer_expectations():
        require_int_value(output.get(key), value, key)


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4),
        ("required_file_count", 4),
        ("required_review_item_count_per_payload", 20),
        ("complete_candidate_count", 4),
        ("complete_candidate_accepted_payload_count", 4),
        ("complete_candidate_filename_match_count", 4),
        ("complete_candidate_covered_target_count", 4),
        ("complete_candidate_missing_target_count", 0),
        ("complete_candidate_duplicate_target_count", 0),
        ("complete_candidate_unexpected_target_count", 0),
        ("invalid_probe_count", 6),
        ("invalid_probe_blocked_count", 6),
        ("failed_probe_count", 0),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )
