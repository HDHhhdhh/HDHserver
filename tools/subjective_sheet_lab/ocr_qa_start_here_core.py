from __future__ import annotations

from dataclasses import dataclass
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    assert_common_safety,
    require_bool_value,
    require_int,
    require_int_value,
    require_text_value,
)
from ocr_provider_free_extended_gate_count import EXTENDED_GATE_COUNT

EXPECTED_CHAIN_STEP_COUNT: Final[int] = 29


@dataclass(frozen=True, slots=True)
class ReportModifiedTimes:
    command_checklist: int
    operator_summary: int
    count_consistency: int


@dataclass(frozen=True, slots=True)
class StartHereInputs:
    count: JsonObject
    operator: JsonObject
    freshness: JsonObject
    command_checklist: JsonObject
    modified_times: ReportModifiedTimes


def build_output(inputs: StartHereInputs) -> JsonObject:
    require_inputs(inputs)
    return {
        "ok": True,
        "student_facing": False,
        "status": "OCR_QA_START_HERE_READY_WITH_USER_ACTION_REQUIRED",
        "start_here_path": "tools/subjective_sheet_lab/OCR_QA_START_HERE.md",
        "chain_step_count": EXPECTED_CHAIN_STEP_COUNT,
        "failed_step_count": 0,
        "extended_gate_count": require_int(inputs.count.get("expected_extended_gate_count"), "expected_extended_gate_count"),
        "operator_summary_report_count": require_int(
            inputs.count.get("operator_summary_report_count"),
            "operator_summary_report_count",
        ),
        "operator_summary_newer_than_queue_state": True,
        "command_checklist_modified_ns": inputs.modified_times.command_checklist,
        "operator_summary_modified_ns": inputs.modified_times.operator_summary,
        "count_consistency_modified_ns": inputs.modified_times.count_consistency,
        "command_checklist_newer_than_operator_summary": command_checklist_newer_than_operator(inputs.modified_times),
        "command_checklist_newer_than_count_consistency": command_checklist_newer_than_count(inputs.modified_times),
        "command_checklist_fresh_for_start_here": command_checklist_fresh_for_start_here(inputs.modified_times),
        "operator_status": text_value(inputs.operator.get("status"), "operator.status"),
        "current_blocker": text_value(inputs.operator.get("current_blocker"), "operator.current_blocker"),
        "next_safe_action": text_value(inputs.operator.get("operator_next_action"), "operator.operator_next_action"),
        "user_action_required": True,
        "provider_call_required_for_next_action": False,
        "api_authorization_required_for_next_action": False,
        "promotion_write_authorization_required": True,
        "required_file_count": require_int(inputs.operator.get("required_file_count"), "operator.required_file_count"),
        "present_file_count": require_int(inputs.operator.get("present_file_count"), "operator.present_file_count"),
        "missing_file_count": require_int(inputs.operator.get("missing_file_count"), "operator.missing_file_count"),
        "required_files": required_files(inputs.operator),
        "intake_command_count": require_int(
            inputs.command_checklist.get("ordered_command_count"),
            "command_checklist.ordered_command_count",
        ),
        "intake_commands": intake_commands(inputs.command_checklist),
        "required_review_item_count_per_payload": require_int(
            inputs.operator.get("required_review_item_count_per_payload"),
            "operator.required_review_item_count_per_payload",
        ),
        "required_question_sequence": text_value(
            inputs.operator.get("required_question_sequence"),
            "operator.required_question_sequence",
        ),
        "ready_now": False,
        "ready_after_required_files": True,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": text_value(inputs.freshness.get("production_default"), "freshness.production_default"),
    }


def require_inputs(inputs: StartHereInputs) -> None:
    assert_common_safety("count", inputs.count)
    assert_common_safety("operator", inputs.operator)
    assert_common_safety("freshness", inputs.freshness)
    assert_common_safety("command_checklist", inputs.command_checklist)
    require_fresh_command_checklist(inputs.modified_times)
    require_int_value(inputs.count.get("issue_count"), 0, "count.issue_count")
    require_bool_value(inputs.count.get("operator_summary_newer_than_queue_state"), True, "count.operator_summary_newer")
    require_text_value(inputs.freshness.get("production_default"), "NO_GO", "freshness.production_default")
    require_text_value(inputs.operator.get("status"), "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED", "operator.status")
    require_text_value(
        inputs.operator.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "operator.current_blocker",
    )
    require_text_value(
        inputs.operator.get("operator_next_action"),
        "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "operator.operator_next_action",
    )
    require_bool_value(inputs.operator.get("ready_now"), False, "operator.ready_now")
    require_bool_value(inputs.operator.get("ready_after_required_files"), True, "operator.ready_after_required_files")
    require_bool_value(inputs.operator.get("provider_call_required_for_next_action"), False, "operator.provider_call_required")
    require_bool_value(inputs.operator.get("api_authorization_required_for_next_action"), False, "operator.api_authorization_required")
    require_bool_value(inputs.operator.get("promotion_write_authorization_required"), True, "operator.promotion_write_authorization_required")
    require_int_value(inputs.operator.get("required_file_count"), 4, "operator.required_file_count")
    require_int_value(inputs.operator.get("present_file_count"), 0, "operator.present_file_count")
    require_int_value(inputs.operator.get("missing_file_count"), 4, "operator.missing_file_count")
    require_int_value(inputs.operator.get("required_review_item_count_per_payload"), 20, "operator.required_review_item_count_per_payload")
    require_text_value(inputs.operator.get("required_question_sequence"), "1-20", "operator.required_question_sequence")
    require_text_value(
        inputs.command_checklist.get("status"),
        "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_READY",
        "command_checklist.status",
    )
    require_text_value(
        inputs.command_checklist.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "command_checklist.current_blocker",
    )
    require_int_value(inputs.command_checklist.get("ordered_command_count"), 8, "command_checklist.command_count")
    require_int_value(inputs.count.get("expected_extended_gate_count"), EXTENDED_GATE_COUNT, "count.expected_extended_gate_count")
    require_int_value(inputs.count.get("operator_summary_report_count"), EXTENDED_GATE_COUNT, "count.operator_summary_report_count")


def require_fresh_command_checklist(times: ReportModifiedTimes) -> None:
    if not command_checklist_fresh_for_start_here(times):
        raise ExtendedGateError("command checklist is older than operator summary or count consistency evidence")


def command_checklist_fresh_for_start_here(times: ReportModifiedTimes) -> bool:
    return command_checklist_newer_than_operator(times) and command_checklist_newer_than_count(times)


def command_checklist_newer_than_operator(times: ReportModifiedTimes) -> bool:
    return times.command_checklist >= times.operator_summary


def command_checklist_newer_than_count(times: ReportModifiedTimes) -> bool:
    return times.command_checklist >= times.count_consistency


def required_files(operator: JsonObject) -> list[JsonObject]:
    return [
        {
            "test_id": text_value(row.get("test_id"), "required_file.test_id"),
            "required_file_name": text_value(row.get("required_file_name"), "required_file.required_file_name"),
        }
        for row in rows(operator, "required_files")
    ]


def intake_commands(command_checklist: JsonObject) -> list[JsonObject]:
    return [
        {
            "step_no": require_int(row.get("step_no"), "command.step_no"),
            "label": text_value(row.get("label"), "command.label"),
            "command": text_value(row.get("command"), "command.command"),
            "purpose": purpose_text(row.get("purpose")),
        }
        for row in rows(command_checklist, "commands")
    ]


def rows(payload: JsonObject, key: str) -> tuple[JsonObject, ...]:
    match payload.get(key):
        case list() as values:
            return tuple(json_row(value, index, key) for index, value in enumerate(values, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError(f"{key} must be a list")
        case unreachable:
            assert_never(unreachable)


def json_row(value: JsonValue, index: int, key: str) -> JsonObject:
    match value:
        case dict() as row:
            return row
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError(f"{key}[{index}] must be a mapping")
        case unreachable:
            assert_never(unreachable)


def purpose_text(value: JsonValue) -> str:
    return text_value(value, "command.purpose").replace("expected training-pack targets", "required training-pack targets")


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)
