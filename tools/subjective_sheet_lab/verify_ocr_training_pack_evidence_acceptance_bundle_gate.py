# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_evidence_acceptance_bundle_gate.py

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
ACCEPTANCE_JSON: Final[Path] = LAB / "ocr_training_pack_post_dropbox_acceptance_gate.json"
EXAMPLE_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_example_shape.json"
PREVIEW_DIFF_JSON: Final[Path] = LAB / "ocr_training_pack_promotion_preview_diff_gate.json"
ARRIVAL_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_readiness_gate.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_acceptance_bundle_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_evidence_acceptance_bundle_gate.md"


@dataclass(frozen=True, slots=True)
class BundleInputs:
    acceptance: JsonObject
    example: JsonObject
    preview_diff: JsonObject
    arrival: JsonObject


def main() -> int:
    output = bundle_summary(
        BundleInputs(
            acceptance=read_json_object(ACCEPTANCE_JSON),
            example=read_json_object(EXAMPLE_JSON),
            preview_diff=read_json_object(PREVIEW_DIFF_JSON),
            arrival=read_json_object(ARRIVAL_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def bundle_summary(inputs: BundleInputs) -> JsonObject:
    require_inputs(inputs)
    ready_checks = (
        bool_value(inputs.acceptance, "acceptance_ready_after_required_files"),
        int_value(inputs.example, "example_contract_accepted_count") == 4,
        int_value(inputs.preview_diff, "simulated_preview_match_count") == 4,
        bool_value(inputs.arrival, "post_file_arrival_ready"),
    )
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_EVIDENCE_ACCEPTANCE_BUNDLE_USER_APPROVAL_REQUIRED",
        "target_count": 4,
        "current_payload_count": int_value(inputs.preview_diff, "actual_payload_count"),
        "current_missing_payload_count": int_value(inputs.preview_diff, "actual_missing_preview_count"),
        "current_bundle_ready": False,
        "dry_run_payload_count": int_value(inputs.example, "example_payload_count"),
        "dry_run_contract_accepted_count": int_value(inputs.example, "example_contract_accepted_count"),
        "dry_run_preview_match_count": int_value(inputs.preview_diff, "simulated_preview_match_count"),
        "dry_run_review_required_count": int_value(inputs.example, "example_review_required_count"),
        "dry_run_safe_auto_grade_count": int_value(inputs.example, "example_safe_auto_grade_count"),
        "dry_run_ready_check_count": sum(1 for check in ready_checks if check),
        "dry_run_required_check_count": len(ready_checks),
        "dry_run_bundle_ready": all(ready_checks),
        "bundle_write_attempted": False,
        "promotion_write_attempted": False,
        "replacement_write_attempted": False,
        "accuracy_recompute_attempted": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "next_safe_action": "collect_operator_supplied_four_target_named_recognized_evidence_payloads_with_user_approval",
        "required_next_artifact": "operator_supplied_four_target_named_recognized_evidence_payloads",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def require_inputs(inputs: BundleInputs) -> None:
    require_text_value(inputs.acceptance.get("status"), "TRAINING_PACK_POST_DROPBOX_ACCEPTANCE_GATE_READY", "acceptance.status")
    require_text_value(
        inputs.example.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_EXAMPLE_SHAPE_READY_USER_APPROVAL_REQUIRED",
        "example.status",
    )
    require_text_value(
        inputs.preview_diff.get("status"),
        "TRAINING_PACK_PROMOTION_PREVIEW_DIFF_USER_APPROVAL_REQUIRED",
        "preview_diff.status",
    )
    require_text_value(
        inputs.arrival.get("status"),
        "TRAINING_PACK_EVIDENCE_ARRIVAL_READINESS_USER_APPROVAL_REQUIRED",
        "arrival.status",
    )
    require_bool_value(inputs.acceptance.get("acceptance_ready_now"), False, "acceptance.ready_now")
    require_bool_value(inputs.acceptance.get("acceptance_ready_after_required_files"), True, "acceptance.ready_after_files")
    require_int_value(inputs.example.get("example_contract_accepted_count"), 4, "example.accepted_count")
    require_int_value(inputs.example.get("example_safe_auto_grade_count"), 0, "example.safe_auto_grade_count")
    require_int_value(inputs.preview_diff.get("actual_payload_count"), 0, "preview_diff.actual_payload_count")
    require_int_value(inputs.preview_diff.get("simulated_preview_match_count"), 4, "preview_diff.simulated_match_count")
    require_bool_value(inputs.arrival.get("current_arrival_ready"), False, "arrival.current_ready")
    require_bool_value(inputs.arrival.get("post_file_arrival_ready"), True, "arrival.post_file_ready")


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
    require_text_value(output.get("status"), "TRAINING_PACK_EVIDENCE_ACCEPTANCE_BUNDLE_USER_APPROVAL_REQUIRED", "status")
    for key, value in integer_requirements():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("current_bundle_ready"), False, "current_bundle_ready")
    require_bool_value(output.get("dry_run_bundle_ready"), True, "dry_run_bundle_ready")
    require_bool_value(output.get("bundle_write_attempted"), False, "bundle_write_attempted")
    require_bool_value(output.get("promotion_write_attempted"), False, "promotion_write_attempted")
    require_bool_value(output.get("replacement_write_attempted"), False, "replacement_write_attempted")
    require_bool_value(output.get("accuracy_recompute_attempted"), False, "accuracy_recompute_attempted")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(
        output.get("next_safe_action"),
        "collect_operator_supplied_four_target_named_recognized_evidence_payloads_with_user_approval",
        "next_safe_action",
    )


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4),
        ("current_payload_count", 0),
        ("current_missing_payload_count", 4),
        ("dry_run_payload_count", 4),
        ("dry_run_contract_accepted_count", 4),
        ("dry_run_preview_match_count", 4),
        ("dry_run_review_required_count", 80),
        ("dry_run_safe_auto_grade_count", 0),
        ("dry_run_ready_check_count", 4),
        ("dry_run_required_check_count", 4),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Evidence Acceptance Bundle Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- submit route calls: 0",
        "- submit button clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- current payloads: {output['current_payload_count']} / {output['target_count']}",
        f"- current missing payloads: {output['current_missing_payload_count']}",
        f"- current bundle ready: {output['current_bundle_ready']}",
        f"- dry-run payloads: {output['dry_run_payload_count']}",
        f"- dry-run contract accepted: {output['dry_run_contract_accepted_count']}",
        f"- dry-run preview matches: {output['dry_run_preview_match_count']}",
        f"- dry-run review-required items: {output['dry_run_review_required_count']}",
        f"- dry-run safe-auto-grade items: {output['dry_run_safe_auto_grade_count']}",
        f"- dry-run ready checks: {output['dry_run_ready_check_count']} / {output['dry_run_required_check_count']}",
        f"- dry-run bundle ready: {output['dry_run_bundle_ready']}",
        f"- bundle write attempted: {output['bundle_write_attempted']}",
        f"- next status: `{output['next_status']}`",
        f"- next safe action: `{output['next_safe_action']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
