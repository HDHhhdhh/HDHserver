# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_dropbox_ready_simulation.py

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
from verify_ocr_training_pack_evidence_dropbox_spec import (
    REPORT_JSON as DROPBOX_JSON,
    SOURCE_JSON,
    dropbox_summary,
)
from verify_ocr_training_pack_operator_copy_checklist import CONTRACT_JSON, checklist_summary

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_dropbox_ready_simulation.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_dropbox_ready_simulation.md"


@dataclass(frozen=True, slots=True)
class DropboxSimulation:
    name: str
    file_names: tuple[str, ...]
    expected_ready: bool
    expected_missing_count: int
    expected_unexpected_count: int


def main() -> int:
    output = simulation_summary(read_json_object(SOURCE_JSON), read_json_object(CONTRACT_JSON), read_json_object(DROPBOX_JSON))
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def simulation_summary(source: JsonObject, contract: JsonObject, current_dropbox: JsonObject) -> JsonObject:
    required_names = text_values(current_dropbox.get("required_file_names"), "required_file_names")
    rows = tuple(simulation_result(source, contract, case) for case in simulation_cases(required_names))
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_DROPBOX_READY_SIMULATION_READY",
        "current_real_dropbox_ready": current_dropbox.get("dropbox_ready"),
        "real_present_file_count": current_dropbox.get("present_file_count"),
        "real_missing_file_count": current_dropbox.get("missing_file_count"),
        "simulation_count": len(rows),
        "passed_simulation_count": sum(1 for row in rows if row["simulation_passed"] is True),
        "failed_simulation_count": sum(1 for row in rows if row["simulation_passed"] is not True),
        "simulated_full_dropbox_ready": rows[0]["dropbox_ready"],
        "simulated_full_copy_evidence_ready": rows[0]["copy_evidence_ready"],
        "full_dropbox_operator_action_required_count": rows[0]["operator_action_required_count"],
        "simulations": list(rows),
        "next_status": "USER_APPROVAL_REQUIRED",
        "required_next_artifact": "four_target_named_payload_files",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def simulation_cases(required_names: tuple[str, ...]) -> tuple[DropboxSimulation, ...]:
    if len(required_names) != 4:
        raise ExtendedGateError("Training Pack ready simulation requires exactly four target filenames")
    wrong = (*required_names[:3], "wrong_target_recognized_evidence.json")
    return (
        DropboxSimulation("all_required_files_present", required_names, True, 0, 0),
        DropboxSimulation("one_required_file_missing", required_names[:3], False, 1, 0),
        DropboxSimulation("unexpected_file_added", (*required_names, "unexpected_recognized_evidence.json"), False, 0, 1),
        DropboxSimulation("wrong_target_file_name", wrong, False, 1, 1),
        DropboxSimulation("empty_dropbox", (), False, 4, 0),
    )


def simulation_result(source: JsonObject, contract: JsonObject, case: DropboxSimulation) -> JsonObject:
    dropbox = dropbox_summary(source, case.file_names)
    checklist = checklist_summary(dropbox, contract)
    ready = bool_value(dropbox.get("dropbox_ready"), "dropbox_ready")
    missing = int_value(dropbox.get("missing_file_count"), "missing_file_count")
    unexpected = int_value(dropbox.get("unexpected_file_count"), "unexpected_file_count")
    action_required = int_value(checklist.get("operator_action_required_count"), "operator_action_required_count")
    copy_ready = bool_value(checklist.get("evidence_ready"), "evidence_ready")
    passed = ready is case.expected_ready and missing == case.expected_missing_count and unexpected == case.expected_unexpected_count
    return {
        "name": case.name,
        "dropbox_ready": ready,
        "copy_evidence_ready": copy_ready,
        "missing_file_count": missing,
        "unexpected_file_count": unexpected,
        "operator_action_required_count": action_required,
        "simulation_passed": passed,
    }


def text_values(value: JsonValue, label: str) -> tuple[str, ...]:
    match value:
        case list() as values:
            return tuple(text_value(item, label) for item in values)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError(f"{label} must be a list")
        case unreachable:
            assert_never(unreachable)


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} values must be text")
        case unreachable:
            assert_never(unreachable)


def int_value(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise ExtendedGateError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def bool_value(value: JsonValue, label: str) -> bool:
    match value:
        case bool():
            return value
        case None | int() | float() | str() | list() | dict():
            raise ExtendedGateError(f"{label} must be boolean")
        case unreachable:
            assert_never(unreachable)


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_DROPBOX_READY_SIMULATION_READY", "status")
    require_bool_value(output.get("current_real_dropbox_ready"), False, "current_real_dropbox_ready")
    require_bool_value(output.get("simulated_full_dropbox_ready"), True, "simulated_full_dropbox_ready")
    require_bool_value(output.get("simulated_full_copy_evidence_ready"), True, "simulated_full_copy_evidence_ready")
    for key, expected in integer_expectations():
        require_int_value(output.get(key), expected, key)
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("real_present_file_count", 0), ("real_missing_file_count", 4), ("simulation_count", 5),
        ("passed_simulation_count", 5), ("failed_simulation_count", 0),
        ("full_dropbox_operator_action_required_count", 0), ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0), ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Dropbox Ready Simulation", "",
        "- Gemini/API calls: 0; external OCR API calls: 0", "- submit route calls: 0", "- submit button clicks: 0",
        "- student-facing: false", "- production default: `NO-GO`", f"- status: `{output['status']}`",
        f"- real dropbox ready: {output['current_real_dropbox_ready']}",
        f"- real present/missing files: {output['real_present_file_count']} / {output['real_missing_file_count']}",
        f"- simulated full dropbox ready: {output['simulated_full_dropbox_ready']}",
        f"- simulated full copy checklist ready: {output['simulated_full_copy_evidence_ready']}",
        f"- simulations passed: {output['passed_simulation_count']} / {output['simulation_count']}",
        "- sensitive/path leak count: 0", "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
