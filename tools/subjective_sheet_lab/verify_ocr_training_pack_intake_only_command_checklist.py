# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_intake_only_command_checklist.py

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
from ocr_training_pack_intake_only_command_markdown import markdown

LAB: Final[Path] = Path(__file__).resolve().parent
OPERATOR_SUMMARY_JSON: Final[Path] = LAB / "ocr_operator_next_action_summary.json"
INTAKE_ONLY_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_no_promotion_gate.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_command_checklist.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_intake_only_command_checklist.md"


@dataclass(frozen=True, slots=True)
class ChecklistInputs:
    operator_summary: JsonObject
    intake_only: JsonObject


@dataclass(frozen=True, slots=True)
class ChecklistCommand:
    step_no: int
    label: str
    command: str
    purpose: str


def main() -> int:
    output = write_report()
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def write_report() -> JsonObject:
    output = command_checklist(
        ChecklistInputs(
            operator_summary=read_json_object(OPERATOR_SUMMARY_JSON),
            intake_only=read_json_object(INTAKE_ONLY_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    return output


def command_checklist(inputs: ChecklistInputs) -> JsonObject:
    require_inputs(inputs)
    commands = checklist_commands()
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_READY",
        "current_blocker": text_value(inputs.operator_summary.get("current_blocker"), "current_blocker"),
        "required_file_count": 4,
        "present_file_count": 0,
        "missing_file_count": 4,
        "ordered_command_count": len(commands),
        "commands": [command_fields(command) for command in commands],
        "stops_before": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: ChecklistInputs) -> None:
    require_text_value(
        inputs.operator_summary.get("status"),
        "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED",
        "operator_summary.status",
    )
    require_text_value(
        inputs.intake_only.get("status"),
        "TRAINING_PACK_INTAKE_ONLY_NO_PROMOTION_USER_ACTION_REQUIRED",
        "intake_only.status",
    )
    require_int_value(inputs.operator_summary.get("required_file_count"), 4, "operator_summary.required_file_count")
    require_int_value(inputs.operator_summary.get("missing_file_count"), 4, "operator_summary.missing_file_count")
    require_int_value(inputs.intake_only.get("required_file_count"), 4, "intake_only.required_file_count")
    require_int_value(inputs.intake_only.get("missing_file_count"), 4, "intake_only.missing_file_count")
    require_bool_value(inputs.intake_only.get("promotion_write_attempted"), False, "intake_only.promotion_write")
    require_bool_value(inputs.intake_only.get("replacement_write_attempted"), False, "intake_only.replacement_write")
    require_bool_value(inputs.intake_only.get("runtime_write_attempted"), False, "intake_only.runtime_write")
    require_bool_value(
        inputs.operator_summary.get("provider_call_required_for_next_action"),
        False,
        "operator_summary.provider_call_required",
    )


def checklist_commands() -> tuple[ChecklistCommand, ...]:
    return (
        ChecklistCommand(
            1,
            "arrival smoke",
            "python tools/subjective_sheet_lab/verify_ocr_training_pack_evidence_arrival_smoke.py",
            "check target file names and byte sizes before payload parsing",
        ),
        ChecklistCommand(
            2,
            "blank evidence rejection",
            "python tools/subjective_sheet_lab/verify_ocr_training_pack_blank_evidence_rejection.py",
            "reject skeleton or blank recognized evidence before contract-valid payloads can replace benchmarks",
        ),
        ChecklistCommand(
            3,
            "contract check",
            "python tools/subjective_sheet_lab/verify_ocr_training_pack_recognized_evidence_contract.py",
            "validate recognized evidence payload shape only",
        ),
        ChecklistCommand(
            4,
            "target coverage",
            "python tools/subjective_sheet_lab/verify_ocr_training_pack_recognized_evidence_target_coverage.py",
            "confirm all four expected training-pack targets are present",
        ),
        ChecklistCommand(
            5,
            "target diff",
            "python tools/subjective_sheet_lab/verify_ocr_training_pack_recognized_evidence_target_diff.py",
            "check target-named evidence files match required test ids",
        ),
        ChecklistCommand(
            6,
            "intake replay",
            "python tools/subjective_sheet_lab/verify_ocr_training_pack_recognized_evidence_intake_replay.py",
            "replay accepted/rejected evidence files without promotion",
        ),
        ChecklistCommand(
            7,
            "real-file replay gate",
            "python tools/subjective_sheet_lab/verify_ocr_training_pack_post_dropbox_real_file_replay_gate.py",
            "summarize replay readiness while keeping writes disabled",
        ),
        ChecklistCommand(
            8,
            "intake-only stop gate",
            "python tools/subjective_sheet_lab/verify_ocr_training_pack_intake_only_no_promotion_gate.py",
            "verify promotion, replacement, accuracy recompute, and runtime writes remain blocked",
        ),
    )


def command_fields(command: ChecklistCommand) -> JsonObject:
    return {
        "step_no": command.step_no,
        "label": command.label,
        "command": command.command,
        "purpose": command.purpose,
    }


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_READY", "status")
    require_text_value(
        output.get("stops_before"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "stops_before",
    )
    for key, value in integer_requirements():
        require_int_value(output.get(key), value, key)


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("ordered_command_count", 8),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


if __name__ == "__main__":
    raise SystemExit(main())
