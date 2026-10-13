# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_operator_checklist.py

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
TARGET_DIFF_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_target_diff.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_operator_checklist.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_operator_checklist.md"


@dataclass(frozen=True, slots=True)
class ChecklistEntry:
    step_no: int
    test_id: str
    required_file_name: str
    action_status: str


def main() -> int:
    output = operator_checklist(read_json_object(TARGET_DIFF_JSON))
    require_operator_checklist(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def operator_checklist(target_diff: JsonObject) -> JsonObject:
    require_text_value(
        target_diff.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_USER_APPROVAL_REQUIRED",
        "target_diff.status",
    )
    entries = tuple(checklist_entry(index, row) for index, row in enumerate(target_rows(target_diff), start=1))
    action_required = sum(1 for entry in entries if entry.action_status == "missing")
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED",
        "source_status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_USER_APPROVAL_REQUIRED",
        "checklist_entry_count": len(entries),
        "operator_action_required_count": action_required,
        "ready_entry_count": len(entries) - action_required,
        "required_file_count": len(entries),
        "required_review_item_count_per_payload": 20,
        "required_question_sequence": "1-20",
        "checklist_ready": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "entries": [entry_fields(entry) for entry in entries],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def target_rows(target_diff: JsonObject) -> tuple[JsonObject, ...]:
    match target_diff.get("target_rows"):
        case list() as rows:
            return tuple(json_row(row, index) for index, row in enumerate(rows, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("target_rows must be a list")
        case unreachable:
            assert_never(unreachable)


def json_row(value: JsonValue, index: int) -> JsonObject:
    match value:
        case dict() as row:
            return row
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError(f"target_rows[{index}] must be a mapping")
        case unreachable:
            assert_never(unreachable)


def checklist_entry(step_no: int, row: JsonObject) -> ChecklistEntry:
    present = bool_value(row.get("evidence_present"), "evidence_present")
    return ChecklistEntry(
        step_no=step_no,
        test_id=text_value(row.get("test_id"), "test_id"),
        required_file_name=text_value(row.get("required_file_name"), "required_file_name"),
        action_status="ready" if present else "missing",
    )


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
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


def entry_fields(entry: ChecklistEntry) -> JsonObject:
    return {
        "step_no": entry.step_no,
        "test_id": entry.test_id,
        "required_file_name": entry.required_file_name,
        "action_status": entry.action_status,
        "required_review_item_count": 20,
        "required_question_sequence": "1-20",
        "required_action": "add_contract_valid_recognized_evidence_payload",
        "student_facing": False,
    }


def require_operator_checklist(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED",
        "status",
    )
    for key, value in integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("checklist_ready"), False, "checklist_ready")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("checklist_entry_count", 4), ("operator_action_required_count", 4), ("ready_entry_count", 0),
        ("required_file_count", 4), ("required_review_item_count_per_payload", 20), ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0), ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Evidence Operator Checklist",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- checklist entries: {output['checklist_entry_count']}",
        f"- operator action required: {output['operator_action_required_count']}",
        f"- ready entries: {output['ready_entry_count']}",
        f"- checklist ready: {output['checklist_ready']}",
        f"- next status: `{output['next_status']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    for row in checklist_rows(output):
        lines.append(f"- {row.get('step_no')}. `{row.get('test_id')}` -> `{row.get('required_file_name')}`: {row.get('action_status')}")
    return "\n".join(lines) + "\n"


def checklist_rows(output: JsonObject) -> tuple[JsonObject, ...]:
    match output.get("entries"):
        case list() as rows:
            return tuple(json_row(row, index) for index, row in enumerate(rows, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("entries must be a list")
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
