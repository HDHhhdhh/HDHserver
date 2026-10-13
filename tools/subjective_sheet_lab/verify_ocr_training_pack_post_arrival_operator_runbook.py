# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_post_arrival_operator_runbook.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
CHECKLIST_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_command_checklist.json"
ACCEPTANCE_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_acceptance_summary.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_operator_runbook.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_post_arrival_operator_runbook.md"


@dataclass(frozen=True, slots=True)
class RunbookInputs:
    checklist: JsonObject
    acceptance: JsonObject


@dataclass(frozen=True, slots=True)
class RunbookCommand:
    step_no: int
    label: str
    command: str


def main() -> int:
    output = runbook(
        RunbookInputs(
            checklist=read_json_object(CHECKLIST_JSON),
            acceptance=read_json_object(ACCEPTANCE_JSON),
        ),
    )
    require_report(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def runbook(inputs: RunbookInputs) -> JsonObject:
    require_inputs(inputs)
    commands = checklist_commands(inputs.checklist)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_POST_ARRIVAL_OPERATOR_RUNBOOK_READY",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "user_action_required": "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "required_file_count": 4,
        "present_file_count": 0,
        "missing_file_count": 4,
        "runbook_step_count": len(commands),
        "validation_command_count": len(commands),
        "payload_parse_before_arrival_allowed": False,
        "payload_parse_after_arrival_allowed": True,
        "promotion_write_allowed": False,
        "replacement_write_allowed": False,
        "runtime_write_allowed": False,
        "accuracy_recompute_allowed": False,
        "provider_call_required": False,
        "allowed_after_files_arrive": "arrival_smoke_then_blank_rejection_then_contract_then_coverage_then_intake_replay",
        "stop_before": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: RunbookInputs) -> None:
    require_text_value(inputs.checklist.get("status"), "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_READY", "checklist.status")
    require_text_value(
        inputs.acceptance.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_ACCEPTANCE_SUMMARY_USER_ACTION_REQUIRED",
        "acceptance.status",
    )
    require_text_value(inputs.checklist.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "checklist.blocker")
    require_text_value(inputs.acceptance.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "acceptance.blocker")
    for key, value in input_counts():
        source, field = key.split(".", maxsplit=1)
        require_int_value(getattr(inputs, source).get(field), value, key)
    require_bool_value(inputs.acceptance.get("acceptance_ready_now"), False, "acceptance.ready_now")
    require_bool_value(inputs.acceptance.get("acceptance_ready_after_required_files"), True, "acceptance.ready_after_files")
    require_bool_value(
        inputs.acceptance.get("contract_payload_parse_allowed_now"),
        False,
        "acceptance.contract_payload_parse_allowed_now",
    )
    for label, payload in (("checklist", inputs.checklist), ("acceptance", inputs.acceptance)):
        require_safety_counters(label, payload)


def input_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("checklist.required_file_count", 4),
        ("checklist.present_file_count", 0),
        ("checklist.missing_file_count", 4),
        ("checklist.ordered_command_count", 8),
        ("acceptance.required_file_count", 4),
        ("acceptance.present_file_count", 0),
        ("acceptance.missing_file_count", 4),
        ("acceptance.pending_file_count", 4),
    )


def checklist_commands(checklist: JsonObject) -> tuple[RunbookCommand, ...]:
    match checklist.get("commands"):
        case list() as rows:
            result = tuple(command_from_row(row) for row in rows)
            if len(result) != 8:
                raise ExtendedGateError("operator runbook requires eight validation commands")
            return result
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("checklist commands must be a list")
        case unreachable:
            assert_never(unreachable)


def command_from_row(value: JsonValue) -> RunbookCommand:
    match value:
        case dict() as row:
            return RunbookCommand(
                step_no=int_field(row.get("step_no"), "command.step_no"),
                label=text_field(row.get("label"), "command.label"),
                command=text_field(row.get("command"), "command.command"),
            )
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("command row must be a mapping")
        case unreachable:
            assert_never(unreachable)


def require_report(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_POST_ARRIVAL_OPERATOR_RUNBOOK_READY", "status")
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_text_value(output.get("user_action_required"), "copy_four_contract_valid_training_pack_recognized_evidence_files", "user_action_required")
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
        ("runbook_step_count", 8),
        ("validation_command_count", 8),
    )


def output_booleans() -> tuple[tuple[str, bool], ...]:
    return (
        ("payload_parse_before_arrival_allowed", False),
        ("payload_parse_after_arrival_allowed", True),
        ("promotion_write_allowed", False),
        ("replacement_write_allowed", False),
        ("runtime_write_allowed", False),
        ("accuracy_recompute_allowed", False),
        ("provider_call_required", False),
    )


def require_safety_counters(label: str, payload: JsonObject) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_leak")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.path_leak")


def int_field(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise ExtendedGateError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def text_field(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Post-Arrival Operator Runbook",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- user action required: `{output['user_action_required']}`",
        f"- required files: {output['required_file_count']}",
        f"- present files: {output['present_file_count']}",
        f"- missing files: {output['missing_file_count']}",
        f"- validation commands after files arrive: {output['validation_command_count']}",
        f"- payload parse before arrival allowed: {output['payload_parse_before_arrival_allowed']}",
        f"- payload parse after arrival allowed: {output['payload_parse_after_arrival_allowed']}",
        f"- stop before: `{output['stop_before']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
