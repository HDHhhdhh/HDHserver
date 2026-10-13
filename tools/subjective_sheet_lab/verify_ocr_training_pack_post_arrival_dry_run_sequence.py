# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_post_arrival_dry_run_sequence.py

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
ARRIVAL_SMOKE_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_smoke.json"
COMMAND_CHECKLIST_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_command_checklist.json"
INTAKE_ONLY_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_no_promotion_gate.json"
OPERATOR_SUMMARY_JSON: Final[Path] = LAB / "ocr_operator_next_action_summary.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_dry_run_sequence.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_post_arrival_dry_run_sequence.md"


@dataclass(frozen=True, slots=True)
class DryRunInputs:
    arrival_smoke: JsonObject
    command_checklist: JsonObject
    intake_only: JsonObject
    operator_summary: JsonObject


def main() -> int:
    output = dry_run_sequence(
        DryRunInputs(
            arrival_smoke=read_json_object(ARRIVAL_SMOKE_JSON),
            command_checklist=read_json_object(COMMAND_CHECKLIST_JSON),
            intake_only=read_json_object(INTAKE_ONLY_JSON),
            operator_summary=read_json_object(OPERATOR_SUMMARY_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def dry_run_sequence(inputs: DryRunInputs) -> JsonObject:
    require_inputs(inputs)
    commands = command_names(inputs.command_checklist)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_SEQUENCE_USER_APPROVAL_REQUIRED",
        "current_blocker": text_value(inputs.operator_summary.get("current_blocker"), "operator.current_blocker"),
        "planned_command_count": len(commands),
        "first_command": commands[0],
        "last_command": commands[-1],
        "payload_parse_after_smoke_only": True,
        "current_ready": False,
        "ready_after_required_files": True,
        "stops_before": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "promotion_write_attempted": False,
        "replacement_write_attempted": False,
        "accuracy_recompute_attempted": False,
        "runtime_write_attempted": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: DryRunInputs) -> None:
    require_text_value(
        inputs.arrival_smoke.get("status"),
        "TRAINING_PACK_EVIDENCE_ARRIVAL_SMOKE_READY",
        "arrival_smoke.status",
    )
    require_text_value(
        inputs.command_checklist.get("status"),
        "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_READY",
        "command_checklist.status",
    )
    require_text_value(
        inputs.intake_only.get("status"),
        "TRAINING_PACK_INTAKE_ONLY_NO_PROMOTION_USER_ACTION_REQUIRED",
        "intake_only.status",
    )
    require_text_value(
        inputs.operator_summary.get("status"),
        "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED",
        "operator.status",
    )
    require_bool_value(inputs.arrival_smoke.get("payload_parse_attempted"), False, "arrival_smoke.payload_parse")
    require_bool_value(inputs.arrival_smoke.get("ready_after_required_files"), True, "arrival_smoke.ready_after_files")
    require_int_value(inputs.command_checklist.get("ordered_command_count"), 8, "command_checklist.command_count")
    require_text_value(
        inputs.intake_only.get("blocked_without_separate_authorization"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "intake_only.blocked_without_authorization",
    )
    for label, payload in (
        ("arrival_smoke", inputs.arrival_smoke),
        ("command_checklist", inputs.command_checklist),
        ("intake_only", inputs.intake_only),
        ("operator", inputs.operator_summary),
    ):
        require_zero_counters(label, payload)


def command_names(command_checklist: JsonObject) -> tuple[str, ...]:
    match command_checklist.get("commands"):
        case list() as rows:
            commands = tuple(command_name(row) for row in rows)
            if len(commands) != 8:
                raise ExtendedGateError("command_checklist.commands must contain eight commands")
            return commands
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("command_checklist.commands must be a list")
        case unreachable:
            assert_never(unreachable)


def command_name(value: JsonValue) -> str:
    match value:
        case dict() as row:
            return text_value(row.get("command"), "commands[].command")
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("command row must be a mapping")
        case unreachable:
            assert_never(unreachable)


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def require_zero_counters(label: str, payload: JsonObject) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_or_grading_field_leak_count")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.filesystem_path_leak_count")


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_SEQUENCE_USER_APPROVAL_REQUIRED", "status")
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_text_value(output.get("first_command"), "python tools/subjective_sheet_lab/verify_ocr_training_pack_evidence_arrival_smoke.py", "first_command")
    require_text_value(output.get("last_command"), "python tools/subjective_sheet_lab/verify_ocr_training_pack_intake_only_no_promotion_gate.py", "last_command")
    require_text_value(output.get("stops_before"), "promotion_replacement_accuracy_recompute_or_runtime_write", "stops_before")
    for key, value in integer_expectations():
        require_int_value(output.get(key), value, key)
    for key, value in bool_expectations():
        require_bool_value(output.get(key), value, key)


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("planned_command_count", 8),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def bool_expectations() -> tuple[tuple[str, bool], ...]:
    return (
        ("payload_parse_after_smoke_only", True),
        ("current_ready", False),
        ("ready_after_required_files", True),
        ("promotion_write_attempted", False),
        ("replacement_write_attempted", False),
        ("accuracy_recompute_attempted", False),
        ("runtime_write_attempted", False),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Post-Arrival Dry-Run Sequence",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- command sequence: {output['planned_command_count']} steps, smoke first, no-promotion stop last",
        f"- readiness: current={output['current_ready']}, after files={output['ready_after_required_files']}",
        f"- stops before: `{output['stops_before']}`",
        "- promotion/replacement/accuracy/runtime writes attempted: false",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
