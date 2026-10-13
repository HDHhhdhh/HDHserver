from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    require_bool_value,
    require_int,
    require_int_value,
    require_text_value,
)


@dataclass(frozen=True, slots=True)
class SummaryInputs:
    extended_gate: JsonObject
    preflight: JsonObject
    root_cause: JsonObject
    operator_manifest: JsonObject


@dataclass(frozen=True, slots=True)
class RequiredEvidenceFile:
    test_id: str
    file_name: str
    status: str


def require_inputs(inputs: SummaryInputs) -> None:
    require_min_int(inputs.extended_gate.get("extended_gate_count"), 57, "extended_gate.extended_gate_count")
    require_min_int(
        inputs.preflight.get("provider_free_extended_gate_count"),
        57,
        "preflight.provider_free_extended_gate_count",
    )
    require_min_int(inputs.root_cause.get("extended_gate_count"), 57, "root_cause.extended_gate_count")
    require_int_value(inputs.root_cause.get("wrong_safe_auto_grade"), 0, "root_cause.wrong_safe_auto_grade")
    require_text_value(
        inputs.operator_manifest.get("status"),
        "TRAINING_PACK_OPERATOR_EVIDENCE_MANIFEST_USER_APPROVAL_REQUIRED",
        "operator_manifest.status",
    )
    require_int_value(inputs.operator_manifest.get("target_count"), 4, "operator_manifest.target_count")
    require_int_value(inputs.operator_manifest.get("missing_entry_count"), 4, "operator_manifest.missing_entry_count")
    require_bool_value(inputs.operator_manifest.get("manifest_ready_now"), False, "operator_manifest.ready_now")
    require_bool_value(
        inputs.operator_manifest.get("manifest_ready_after_files"),
        True,
        "operator_manifest.ready_after_files",
    )
    for label, payload in (
        ("extended_gate", inputs.extended_gate),
        ("preflight", inputs.preflight),
        ("root_cause", inputs.root_cause),
        ("operator_manifest", inputs.operator_manifest),
    ):
        require_safety_counters(label, payload)


def require_safety_counters(label: str, payload: JsonObject) -> None:
    require_int_value(payload.get("provider_call_count"), 0, f"{label}.provider_call_count")
    require_int_value(payload.get("external_ocr_api_call_count"), 0, f"{label}.external_ocr_api_call_count")
    require_int_value(payload.get("submit_test_call_count"), 0, f"{label}.submit_test_call_count")
    require_int_value(payload.get("ts_submit_click_count"), 0, f"{label}.ts_submit_click_count")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.filesystem_path_leak_count")


def require_min_int(value: JsonValue, minimum: int, label: str) -> None:
    actual = require_int(value, label)
    if actual < minimum:
        raise ExtendedGateError(f"{label} expected at least {minimum}, got {actual}")


def observed_extended_gate_count(inputs: SummaryInputs) -> int:
    return max(
        require_int(inputs.extended_gate.get("extended_gate_count"), "extended_gate.extended_gate_count"),
        require_int(inputs.preflight.get("provider_free_extended_gate_count"), "preflight.provider_free_extended_gate_count"),
        require_int(inputs.root_cause.get("extended_gate_count"), "root_cause.extended_gate_count"),
    )


def required_evidence_files(operator_manifest: JsonObject) -> tuple[RequiredEvidenceFile, ...]:
    match operator_manifest.get("entries"):
        case list() as rows:
            return tuple(required_evidence_file(row, index) for index, row in enumerate(rows, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("operator manifest entries must be a list")
        case unreachable:
            assert_never(unreachable)


def required_evidence_file(value: JsonValue, index: int) -> RequiredEvidenceFile:
    match value:
        case dict() as row:
            return RequiredEvidenceFile(
                test_id=text_value(row.get("test_id"), f"entries[{index}].test_id"),
                file_name=text_value(row.get("required_file_name"), f"entries[{index}].required_file_name"),
                status=text_value(row.get("action_status"), f"entries[{index}].action_status"),
            )
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError(f"entries[{index}] must be a mapping")
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


def evidence_file_fields(item: RequiredEvidenceFile) -> JsonObject:
    return {
        "test_id": item.test_id,
        "required_file_name": item.file_name,
        "status": item.status,
        "required_review_item_count": 20,
        "required_question_sequence": "1-20",
    }
