from __future__ import annotations

from typing import Callable, Final, TypeAlias, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    read_json_object,
    require_int,
    require_int_value,
    require_object,
    require_text_value,
)
from verify_ocr_training_pack_intake_only_command_checklist import REPORT_JSON as INTAKE_COMMAND_CHECKLIST_JSON
from verify_ocr_training_pack_intake_only_command_checklist import main as verify_intake_only_command_checklist

Verifier: TypeAlias = Callable[[], int]
EXPECTED_COMMAND_COUNT: Final[int] = 8
BLANK_EVIDENCE_COMMAND_STEP: Final[int] = 2
BLANK_EVIDENCE_COMMAND_LABEL: Final[str] = "blank evidence rejection"
BLANK_EVIDENCE_COMMAND: Final[str] = (
    "python tools/subjective_sheet_lab/verify_ocr_training_pack_blank_evidence_rejection.py"
)


def intake_command_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack intake-only command checklist", verify_intake_only_command_checklist),)


def intake_command_reports() -> dict[str, JsonObject]:
    return {"training_pack_intake_only_command_checklist": read_json_object(INTAKE_COMMAND_CHECKLIST_JSON)}


def require_training_pack_intake_only_command_checklist(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_READY",
        "intake_command_checklist.status",
    )
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "intake_command_checklist.current_blocker",
    )
    require_text_value(
        report.get("stops_before"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "intake_command_checklist.stops_before",
    )
    require_text_value(report.get("production_default"), "NO_GO", "intake_command_checklist.production_default")
    for key, value in intake_command_integer_requirements():
        require_int_value(report.get(key), value, f"intake_command_checklist.{key}")
    require_blank_evidence_rejection_command(report)


def require_blank_evidence_rejection_command(report: JsonObject) -> None:
    commands = command_rows(report.get("commands"))
    if len(commands) != EXPECTED_COMMAND_COUNT:
        raise ExtendedGateError("intake_command_checklist.commands must contain eight commands")
    blank_command = command_at_step(commands, BLANK_EVIDENCE_COMMAND_STEP)
    require_text_value(
        blank_command.get("label"),
        BLANK_EVIDENCE_COMMAND_LABEL,
        "intake_command_checklist.commands[2].label",
    )
    require_text_value(
        blank_command.get("command"),
        BLANK_EVIDENCE_COMMAND,
        "intake_command_checklist.commands[2].command",
    )


def command_rows(value: JsonValue) -> tuple[JsonObject, ...]:
    match value:
        case list() as rows:
            return tuple(require_object(row, "intake_command_checklist.commands[]") for row in rows)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("intake_command_checklist.commands must be a list")
        case unreachable:
            assert_never(unreachable)


def command_at_step(commands: tuple[JsonObject, ...], step_no: int) -> JsonObject:
    for row in commands:
        if require_int(row.get("step_no"), "intake_command_checklist.commands[].step_no") == step_no:
            return row
    raise ExtendedGateError("blank evidence rejection command is missing from intake checklist")


def intake_command_integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("ordered_command_count", EXPECTED_COMMAND_COUNT),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def intake_command_checklist_summary_fields() -> JsonObject:
    return {
        "training_pack_intake_only_command_checklist_status": "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_READY",
        "training_pack_intake_only_command_checklist_blocker": "training_pack_recognized_evidence_files_missing",
        "training_pack_intake_only_command_count": EXPECTED_COMMAND_COUNT,
        "training_pack_intake_only_blank_evidence_command_step": BLANK_EVIDENCE_COMMAND_STEP,
        "training_pack_intake_only_command_stops_before": "promotion_replacement_accuracy_recompute_or_runtime_write",
    }
