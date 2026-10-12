# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_post_arrival_command_bundle.py

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
ARRIVAL_DIGEST_JSON: Final[Path] = LAB / "ocr_training_pack_arrival_smoke_operator_digest.json"
RUNBOOK_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_operator_runbook.json"
CHECKLIST_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_command_checklist.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_command_bundle.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_post_arrival_command_bundle.md"


@dataclass(frozen=True, slots=True)
class BundleInputs:
    arrival_digest: JsonObject
    runbook: JsonObject
    checklist: JsonObject


def main() -> int:
    output = command_bundle(
        BundleInputs(
            arrival_digest=read_json_object(ARRIVAL_DIGEST_JSON),
            runbook=read_json_object(RUNBOOK_JSON),
            checklist=read_json_object(CHECKLIST_JSON),
        ),
    )
    require_report(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def command_bundle(inputs: BundleInputs) -> JsonObject:
    require_inputs(inputs)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_POST_ARRIVAL_COMMAND_BUNDLE_USER_ACTION_REQUIRED",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "user_action_required": "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "required_file_count": 4,
        "present_file_count": 0,
        "missing_file_count": 4,
        "bundle_ready_now": False,
        "bundle_ready_after_required_files": True,
        "bundle_step_count": 8,
        "currently_executable_step_count": 3,
        "blocked_by_missing_evidence_step_count": 5,
        "after_files_executable_step_count": 8,
        "payload_parse_before_arrival_allowed": False,
        "payload_parse_after_arrival_allowed": True,
        "provider_call_required": False,
        "write_allowed": False,
        "stop_before": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: BundleInputs) -> None:
    require_text_value(
        inputs.arrival_digest.get("status"),
        "TRAINING_PACK_ARRIVAL_SMOKE_OPERATOR_DIGEST_READY",
        "arrival_digest.status",
    )
    require_text_value(
        inputs.runbook.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_OPERATOR_RUNBOOK_READY",
        "runbook.status",
    )
    require_text_value(
        inputs.checklist.get("status"),
        "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_READY",
        "checklist.status",
    )
    for source, payload in input_payloads(inputs):
        require_text_value(
            payload.get("current_blocker"),
            "training_pack_recognized_evidence_files_missing",
            f"{source}.current_blocker",
        )
        require_safety_counters(source, payload)
    for key, value in input_counts():
        source, field = key.split(".", maxsplit=1)
        require_int_value(getattr(inputs, source).get(field), value, key)
    require_bool_value(inputs.arrival_digest.get("payload_parse_attempted"), False, "arrival_digest.payload_parse_attempted")
    require_bool_value(inputs.arrival_digest.get("smoke_ready_now"), False, "arrival_digest.smoke_ready_now")
    require_bool_value(inputs.arrival_digest.get("ready_after_required_files"), True, "arrival_digest.ready_after_files")
    require_bool_value(inputs.runbook.get("payload_parse_before_arrival_allowed"), False, "runbook.parse_before_arrival")
    require_bool_value(inputs.runbook.get("payload_parse_after_arrival_allowed"), True, "runbook.parse_after_arrival")
    require_bool_value(inputs.runbook.get("provider_call_required"), False, "runbook.provider_call_required")


def input_payloads(inputs: BundleInputs) -> tuple[tuple[str, JsonObject], ...]:
    return (
        ("arrival_digest", inputs.arrival_digest),
        ("runbook", inputs.runbook),
        ("checklist", inputs.checklist),
    )


def input_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("arrival_digest.required_file_count", 4),
        ("arrival_digest.present_file_count", 0),
        ("arrival_digest.missing_file_count", 4),
        ("runbook.required_file_count", 4),
        ("runbook.present_file_count", 0),
        ("runbook.missing_file_count", 4),
        ("runbook.validation_command_count", 8),
        ("checklist.required_file_count", 4),
        ("checklist.present_file_count", 0),
        ("checklist.missing_file_count", 4),
        ("checklist.ordered_command_count", 8),
    )


def require_report(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_POST_ARRIVAL_COMMAND_BUNDLE_USER_ACTION_REQUIRED", "status")
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_text_value(output.get("production_default"), "NO_GO", "production_default")
    for key, value in output_counts():
        require_int_value(output.get(key), value, key)
    for key, value in output_booleans():
        require_bool_value(output.get(key), value, key)
    require_safety_counters("output", output)


def output_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("bundle_step_count", 8),
        ("currently_executable_step_count", 3),
        ("blocked_by_missing_evidence_step_count", 5),
        ("after_files_executable_step_count", 8),
    )


def output_booleans() -> tuple[tuple[str, bool], ...]:
    return (
        ("bundle_ready_now", False),
        ("bundle_ready_after_required_files", True),
        ("payload_parse_before_arrival_allowed", False),
        ("payload_parse_after_arrival_allowed", True),
        ("provider_call_required", False),
        ("write_allowed", False),
    )


def require_safety_counters(label: str, payload: JsonObject) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_leak")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.path_leak")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Post-Arrival Command Bundle",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- required files: {output['required_file_count']}",
        f"- present files: {output['present_file_count']}",
        f"- missing files: {output['missing_file_count']}",
        f"- bundle ready now: {output['bundle_ready_now']}",
        f"- bundle ready after files: {output['bundle_ready_after_required_files']}",
        f"- currently executable steps: {output['currently_executable_step_count']}",
        f"- blocked by missing evidence steps: {output['blocked_by_missing_evidence_step_count']}",
        f"- executable steps after files arrive: {output['after_files_executable_step_count']}",
        f"- stop before: `{output['stop_before']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
