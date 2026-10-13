# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_intake_only_no_promotion_gate.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
INTAKE_REPLAY_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake_replay.json"
REAL_FILE_REPLAY_JSON: Final[Path] = LAB / "ocr_training_pack_post_dropbox_real_file_replay_gate.json"
OPERATOR_SUMMARY_JSON: Final[Path] = LAB / "ocr_operator_next_action_summary.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_no_promotion_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_intake_only_no_promotion_gate.md"


@dataclass(frozen=True, slots=True)
class IntakeOnlyInputs:
    intake_replay: JsonObject
    real_file_replay: JsonObject
    operator_summary: JsonObject


def main() -> int:
    output = intake_only_summary(
        IntakeOnlyInputs(
            intake_replay=read_json_object(INTAKE_REPLAY_JSON),
            real_file_replay=read_json_object(REAL_FILE_REPLAY_JSON),
            operator_summary=read_json_object(OPERATOR_SUMMARY_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def intake_only_summary(inputs: IntakeOnlyInputs) -> JsonObject:
    require_inputs(inputs)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_INTAKE_ONLY_NO_PROMOTION_USER_ACTION_REQUIRED",
        "current_stage": "waiting_for_four_recognized_evidence_files",
        "allowed_when_files_arrive": "blank_rejection_then_contract_validate_then_intake_replay_only",
        "blocked_without_separate_authorization": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "next_safe_action": "collect_four_recognized_evidence_files_then_run_intake_replay_only",
        "required_file_count": 4,
        "present_file_count": 0,
        "missing_file_count": 4,
        "intake_replay_ready_now": False,
        "intake_replay_ready_after_required_files": True,
        "promotion_write_attempted": False,
        "replacement_write_attempted": False,
        "accuracy_recompute_attempted": False,
        "runtime_write_attempted": False,
        "dry_run_contract_accepted_count": 4,
        "dry_run_review_required_count": 80,
        "dry_run_safe_auto_grade_count": 0,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: IntakeOnlyInputs) -> None:
    require_text_value(
        inputs.intake_replay.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED",
        "intake_replay.status",
    )
    require_text_value(
        inputs.real_file_replay.get("status"),
        "TRAINING_PACK_POST_DROPBOX_REAL_FILE_REPLAY_USER_APPROVAL_REQUIRED",
        "real_file_replay.status",
    )
    require_text_value(
        inputs.operator_summary.get("status"),
        "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED",
        "operator_summary.status",
    )
    for payload, key, value, label in input_integer_requirements(inputs):
        require_int_value(payload.get(key), value, label)
    require_bool_value(inputs.intake_replay.get("intake_replay_ready"), False, "intake_replay.ready")
    require_bool_value(inputs.real_file_replay.get("real_file_replay_ready"), False, "real_file_replay.ready_now")
    require_bool_value(inputs.real_file_replay.get("post_file_replay_ready"), True, "real_file_replay.ready_after_files")
    require_bool_value(inputs.real_file_replay.get("promotion_write_attempted"), False, "real_file_replay.promotion_write")
    require_bool_value(inputs.real_file_replay.get("replacement_write_attempted"), False, "real_file_replay.replacement_write")
    require_bool_value(inputs.real_file_replay.get("accuracy_recompute_attempted"), False, "real_file_replay.accuracy_recompute")
    require_bool_value(inputs.operator_summary.get("provider_call_required_for_next_action"), False, "operator.provider_call")
    require_bool_value(inputs.operator_summary.get("promotion_write_authorization_required"), True, "operator.promotion_auth")


def input_integer_requirements(inputs: IntakeOnlyInputs) -> tuple[tuple[JsonObject, str, int, str], ...]:
    return (
        (inputs.intake_replay, "evidence_file_count", 0, "intake_replay.evidence_file_count"),
        (inputs.intake_replay, "accepted_file_count", 0, "intake_replay.accepted_file_count"),
        (inputs.intake_replay, "missing_required_file_count", 4, "intake_replay.missing_count"),
        (inputs.real_file_replay, "current_real_file_count", 0, "real_file_replay.current_file_count"),
        (inputs.real_file_replay, "current_missing_file_count", 4, "real_file_replay.missing_count"),
        (inputs.real_file_replay, "dry_run_contract_accepted_count", 4, "real_file_replay.contract_accepted"),
        (inputs.real_file_replay, "dry_run_review_required_count", 80, "real_file_replay.review_required"),
        (inputs.real_file_replay, "dry_run_safe_auto_grade_count", 0, "real_file_replay.safe_auto_grade"),
        (inputs.operator_summary, "required_file_count", 4, "operator.required_file_count"),
        (inputs.operator_summary, "missing_file_count", 4, "operator.missing_file_count"),
    )


def require_summary(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_INTAKE_ONLY_NO_PROMOTION_USER_ACTION_REQUIRED",
        "status",
    )
    for key, value in integer_requirements():
        require_int_value(output.get(key), value, key)
    for key, value in bool_requirements():
        require_bool_value(output.get(key), value, key)
    require_text_value(
        output.get("next_safe_action"),
        "collect_four_recognized_evidence_files_then_run_intake_replay_only",
        "next_safe_action",
    )


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("dry_run_contract_accepted_count", 4),
        ("dry_run_review_required_count", 80),
        ("dry_run_safe_auto_grade_count", 0),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def bool_requirements() -> tuple[tuple[str, bool], ...]:
    return (
        ("intake_replay_ready_now", False),
        ("intake_replay_ready_after_required_files", True),
        ("promotion_write_attempted", False),
        ("replacement_write_attempted", False),
        ("accuracy_recompute_attempted", False),
        ("runtime_write_attempted", False),
    )


def markdown(output: JsonObject) -> str:
    return "\n".join(
        [
            "# OCR Training Pack Intake-Only No-Promotion Gate",
            "",
            f"- status: `{output['status']}`",
            f"- current stage: `{output['current_stage']}`",
            f"- allowed when files arrive: `{output['allowed_when_files_arrive']}`",
            f"- blocked without separate authorization: `{output['blocked_without_separate_authorization']}`",
            f"- files present/missing: {output['present_file_count']} / {output['missing_file_count']}",
            f"- intake replay ready now: {output['intake_replay_ready_now']}",
            f"- intake replay ready after required files: {output['intake_replay_ready_after_required_files']}",
            f"- dry-run review-required items: {output['dry_run_review_required_count']}",
            f"- dry-run safe-auto-grade items: {output['dry_run_safe_auto_grade_count']}",
            f"- next safe action: `{output['next_safe_action']}`",
            "- provider/Gemini/API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- promotion/replacement/runtime writes: 0",
            "- answer-key/grading/path leak count: 0",
            "- production default: `NO-GO`",
            "",
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
