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


def require_training_pack_post_dropbox_real_file_replay(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_POST_DROPBOX_REAL_FILE_REPLAY_USER_APPROVAL_REQUIRED",
        "training_pack_post_dropbox_real_file.status",
    )
    for key, value in integer_requirements():
        require_int_value(report.get(key), value, f"training_pack_post_dropbox_real_file.{key}")
    for key, value in bool_requirements():
        require_bool_value(report.get(key), value, f"training_pack_post_dropbox_real_file.{key}")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_post_dropbox_real_file.next_status")


def training_pack_post_dropbox_real_file_summary_fields() -> JsonObject:
    return {
        "training_pack_post_dropbox_real_file_count": 0,
        "training_pack_post_dropbox_real_file_accepted_count": 0,
        "training_pack_post_dropbox_real_file_missing_count": 4,
        "training_pack_post_dropbox_real_file_ready_now": False,
        "training_pack_post_dropbox_real_file_ready_after_files": True,
        "training_pack_post_dropbox_real_file_dry_run_review_required_count": 80,
        "training_pack_post_dropbox_real_file_dry_run_safe_auto_grade_count": 0,
        "training_pack_post_dropbox_real_file_write_attempted": False,
        "training_pack_post_dropbox_real_file_promotion_write_attempted": False,
        "training_pack_post_dropbox_real_file_replacement_write_attempted": False,
        "training_pack_post_dropbox_real_file_accuracy_recompute_attempted": False,
    }


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4),
        ("current_real_file_count", 0),
        ("current_accepted_file_count", 0),
        ("current_missing_file_count", 4),
        ("current_ready_check_count", 0),
        ("current_required_check_count", 4),
        ("dry_run_contract_accepted_count", 4),
        ("dry_run_preview_match_count", 4),
        ("dry_run_review_required_count", 80),
        ("dry_run_safe_auto_grade_count", 0),
        ("post_file_ready_check_count", 4),
        ("post_file_required_check_count", 4),
    )


def bool_requirements() -> tuple[tuple[str, bool], ...]:
    return (
        ("current_intake_replay_ready", False),
        ("current_target_diff_ready", False),
        ("current_post_dropbox_ready", False),
        ("current_bundle_ready", False),
        ("real_file_replay_ready", False),
        ("post_file_replay_ready", True),
        ("real_file_replay_write_attempted", False),
        ("promotion_write_attempted", False),
        ("replacement_write_attempted", False),
        ("accuracy_recompute_attempted", False),
    )
