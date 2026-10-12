# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_post_dropbox_real_file_replay_gate.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
INTAKE_REPLAY_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake_replay.json"
TARGET_DIFF_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_target_diff.json"
POST_DROPBOX_ACCEPTANCE_JSON: Final[Path] = LAB / "ocr_training_pack_post_dropbox_acceptance_gate.json"
ACCEPTANCE_BUNDLE_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_acceptance_bundle_gate.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_post_dropbox_real_file_replay_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_post_dropbox_real_file_replay_gate.md"


@dataclass(frozen=True, slots=True)
class ReplayInputs:
    intake_replay: JsonObject
    target_diff: JsonObject
    post_dropbox_acceptance: JsonObject
    acceptance_bundle: JsonObject


def main() -> int:
    output = real_file_replay_summary(
        ReplayInputs(
            intake_replay=read_json_object(INTAKE_REPLAY_JSON),
            target_diff=read_json_object(TARGET_DIFF_JSON),
            post_dropbox_acceptance=read_json_object(POST_DROPBOX_ACCEPTANCE_JSON),
            acceptance_bundle=read_json_object(ACCEPTANCE_BUNDLE_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def real_file_replay_summary(inputs: ReplayInputs) -> JsonObject:
    require_inputs(inputs)
    current_checks = (
        bool_value(inputs.intake_replay, "intake_replay_ready"),
        bool_value(inputs.target_diff, "target_diff_ready"),
        bool_value(inputs.post_dropbox_acceptance, "acceptance_ready_now"),
        bool_value(inputs.acceptance_bundle, "current_bundle_ready"),
    )
    post_file_checks = (
        bool_value(inputs.post_dropbox_acceptance, "acceptance_ready_after_required_files"),
        bool_value(inputs.acceptance_bundle, "dry_run_bundle_ready"),
        int_value(inputs.acceptance_bundle, "dry_run_contract_accepted_count") == 4,
        int_value(inputs.acceptance_bundle, "dry_run_preview_match_count") == 4,
    )
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_POST_DROPBOX_REAL_FILE_REPLAY_USER_APPROVAL_REQUIRED",
        "target_count": 4,
        "current_real_file_count": int_value(inputs.target_diff, "evidence_file_count"),
        "current_accepted_file_count": int_value(inputs.intake_replay, "accepted_file_count"),
        "current_missing_file_count": int_value(inputs.target_diff, "missing_target_count"),
        "current_intake_replay_ready": current_checks[0],
        "current_target_diff_ready": current_checks[1],
        "current_post_dropbox_ready": current_checks[2],
        "current_bundle_ready": current_checks[3],
        "current_ready_check_count": sum(1 for check in current_checks if check),
        "current_required_check_count": len(current_checks),
        "real_file_replay_ready": all(current_checks),
        "dry_run_contract_accepted_count": int_value(inputs.acceptance_bundle, "dry_run_contract_accepted_count"),
        "dry_run_preview_match_count": int_value(inputs.acceptance_bundle, "dry_run_preview_match_count"),
        "dry_run_review_required_count": int_value(inputs.acceptance_bundle, "dry_run_review_required_count"),
        "dry_run_safe_auto_grade_count": int_value(inputs.acceptance_bundle, "dry_run_safe_auto_grade_count"),
        "post_file_ready_check_count": sum(1 for check in post_file_checks if check),
        "post_file_required_check_count": len(post_file_checks),
        "post_file_replay_ready": all(post_file_checks),
        "real_file_replay_write_attempted": False,
        "promotion_write_attempted": False,
        "replacement_write_attempted": False,
        "accuracy_recompute_attempted": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "next_safe_action": "collect_four_target_named_real_evidence_files_with_user_approval",
        "required_next_artifact": "four_target_named_real_evidence_files",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def require_inputs(inputs: ReplayInputs) -> None:
    require_text_value(
        inputs.intake_replay.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED",
        "intake_replay.status",
    )
    require_text_value(
        inputs.target_diff.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_USER_APPROVAL_REQUIRED",
        "target_diff.status",
    )
    require_text_value(
        inputs.post_dropbox_acceptance.get("status"),
        "TRAINING_PACK_POST_DROPBOX_ACCEPTANCE_GATE_READY",
        "post_dropbox_acceptance.status",
    )
    require_text_value(
        inputs.acceptance_bundle.get("status"),
        "TRAINING_PACK_EVIDENCE_ACCEPTANCE_BUNDLE_USER_APPROVAL_REQUIRED",
        "acceptance_bundle.status",
    )
    for payload, key, expected, label in input_integer_requirements(inputs):
        require_int_value(payload.get(key), expected, label)
    require_bool_value(inputs.intake_replay.get("intake_replay_ready"), False, "intake_replay.ready")
    require_bool_value(inputs.target_diff.get("target_diff_ready"), False, "target_diff.ready")
    require_bool_value(inputs.post_dropbox_acceptance.get("acceptance_ready_now"), False, "post_dropbox.ready_now")
    require_bool_value(
        inputs.post_dropbox_acceptance.get("acceptance_ready_after_required_files"),
        True,
        "post_dropbox.ready_after_files",
    )
    require_bool_value(inputs.acceptance_bundle.get("current_bundle_ready"), False, "acceptance_bundle.current_ready")
    require_bool_value(inputs.acceptance_bundle.get("dry_run_bundle_ready"), True, "acceptance_bundle.dry_run_ready")


def input_integer_requirements(inputs: ReplayInputs) -> tuple[tuple[JsonObject, str, int, str], ...]:
    return (
        (inputs.intake_replay, "evidence_file_count", 0, "intake_replay.evidence_file_count"),
        (inputs.intake_replay, "accepted_file_count", 0, "intake_replay.accepted_file_count"),
        (inputs.intake_replay, "missing_required_file_count", 4, "intake_replay.missing_required_file_count"),
        (inputs.target_diff, "evidence_file_count", 0, "target_diff.evidence_file_count"),
        (inputs.target_diff, "covered_target_count", 0, "target_diff.covered_target_count"),
        (inputs.target_diff, "missing_target_count", 4, "target_diff.missing_target_count"),
        (inputs.acceptance_bundle, "current_missing_payload_count", 4, "acceptance_bundle.current_missing_count"),
        (inputs.acceptance_bundle, "dry_run_contract_accepted_count", 4, "acceptance_bundle.contract_accepted"),
        (inputs.acceptance_bundle, "dry_run_preview_match_count", 4, "acceptance_bundle.preview_match"),
        (inputs.acceptance_bundle, "dry_run_review_required_count", 80, "acceptance_bundle.review_required"),
        (inputs.acceptance_bundle, "dry_run_safe_auto_grade_count", 0, "acceptance_bundle.safe_auto_grade"),
    )


def int_value(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ExtendedGateError(f"{key} must be an integer")
    return value


def bool_value(payload: JsonObject, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ExtendedGateError(f"{key} must be boolean")
    return value


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_POST_DROPBOX_REAL_FILE_REPLAY_USER_APPROVAL_REQUIRED", "status")
    for key, value in integer_requirements():
        require_int_value(output.get(key), value, key)
    for key, value in bool_requirements():
        require_bool_value(output.get(key), value, key)
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(
        output.get("next_safe_action"),
        "collect_four_target_named_real_evidence_files_with_user_approval",
        "next_safe_action",
    )


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
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
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


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Post-Dropbox Real-File Replay Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- submit route calls: 0",
        "- submit button clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- current real files: {output['current_real_file_count']} / {output['target_count']}",
        f"- current accepted files: {output['current_accepted_file_count']}",
        f"- current missing files: {output['current_missing_file_count']}",
        f"- current replay ready: {output['real_file_replay_ready']}",
        f"- post-file replay ready: {output['post_file_replay_ready']}",
        f"- dry-run review-required items: {output['dry_run_review_required_count']}",
        f"- dry-run safe-auto-grade items: {output['dry_run_safe_auto_grade_count']}",
        f"- real-file replay write attempted: {output['real_file_replay_write_attempted']}",
        f"- next status: `{output['next_status']}`",
        f"- next safe action: `{output['next_safe_action']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
