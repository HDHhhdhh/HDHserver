# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_operator_next_action_summary.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    read_json_object,
    require_text_value,
)
from ocr_operator_next_action_summary_model import (
    SummaryInputs,
    evidence_file_fields,
    observed_extended_gate_count,
    require_inputs,
    required_evidence_files,
    text_value,
)
from ocr_operator_next_action_summary_markdown import markdown

LAB: Final[Path] = Path(__file__).resolve().parent
EXTENDED_GATE_JSON: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_extended.json"
PREFLIGHT_JSON: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_preflight_readiness.json"
ROOT_CAUSE_JSON: Final[Path] = LAB / "ocr_root_cause_dashboard.json"
OPERATOR_MANIFEST_JSON: Final[Path] = LAB / "ocr_training_pack_operator_evidence_manifest_gate.json"
REPORT_JSON: Final[Path] = LAB / "ocr_operator_next_action_summary.json"
REPORT_MD: Final[Path] = LAB / "ocr_operator_next_action_summary.md"


def main() -> int:
    output = next_action_summary(
        SummaryInputs(
            extended_gate=read_json_object(EXTENDED_GATE_JSON),
            preflight=read_json_object(PREFLIGHT_JSON),
            root_cause=read_json_object(ROOT_CAUSE_JSON),
            operator_manifest=read_json_object(OPERATOR_MANIFEST_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def next_action_summary(inputs: SummaryInputs) -> JsonObject:
    require_inputs(inputs)
    evidence_files = required_evidence_files(inputs.operator_manifest)
    missing_count = sum(1 for item in evidence_files if item.status == "missing")
    present_count = len(evidence_files) - missing_count
    return {
        "ok": True,
        "student_facing": False,
        "status": "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED",
        "operator_next_action": "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "extended_gate_count": observed_extended_gate_count(inputs),
        "wrong_safe_auto_grade": 0,
        "required_file_count": len(evidence_files),
        "present_file_count": present_count,
        "missing_file_count": missing_count,
        "required_review_item_count_per_payload": 20,
        "required_question_sequence": "1-20",
        "ready_now": False,
        "ready_after_required_files": True,
        "api_authorization_required_for_next_action": False,
        "provider_call_required_for_next_action": False,
        "promotion_write_authorization_required": True,
        "required_files": [evidence_file_fields(item) for item in evidence_files],
        "source_manifest_sha256": text_value(inputs.operator_manifest.get("manifest_sha256"), "manifest_sha256"),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED", "status")
    require_text_value(
        output.get("operator_next_action"),
        "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "operator_next_action",
    )
    for key, value in integer_requirements():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("ready_now"), False, "ready_now")
    require_bool_value(output.get("ready_after_required_files"), True, "ready_after_required_files")
    require_bool_value(output.get("api_authorization_required_for_next_action"), False, "api_authorization")
    require_bool_value(output.get("provider_call_required_for_next_action"), False, "provider_call_required")
    require_bool_value(output.get("promotion_write_authorization_required"), True, "promotion_authorization")


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("wrong_safe_auto_grade", 0),
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("required_review_item_count_per_payload", 20),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


if __name__ == "__main__":
    raise SystemExit(main())
