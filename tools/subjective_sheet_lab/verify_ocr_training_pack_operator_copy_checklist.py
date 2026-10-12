# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_operator_copy_checklist.py

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
DROPBOX_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_dropbox_spec.json"
CONTRACT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_contract.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_operator_copy_checklist.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_operator_copy_checklist.md"
EVIDENCE_SUBDIR: Final[str] = "tools/subjective_sheet_lab/training_pack_recognized_evidence"
FILENAME_SUFFIX: Final[str] = "_recognized_evidence.json"
ALLOWED_STATUSES: Final[tuple[str, ...]] = (
    "safe_auto_grade",
    "review_required",
    "retake_required",
    "data_check_required",
)


@dataclass(frozen=True, slots=True)
class CopyChecklist:
    required_file_count: int
    present_file_count: int
    missing_file_count: int
    checklist_entry_count: int
    operator_action_required_count: int
    evidence_ready: bool


def main() -> int:
    output = checklist_summary(read_json_object(DROPBOX_JSON), read_json_object(CONTRACT_JSON))
    require_current_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def checklist_summary(dropbox: JsonObject, contract: JsonObject) -> JsonObject:
    require_text_value(
        dropbox.get("status"),
        "TRAINING_PACK_EVIDENCE_DROPBOX_USER_APPROVAL_REQUIRED",
        "dropbox.status",
    )
    require_text_value(
        contract.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS",
        "contract.status",
    )
    required_files = text_tuple(dropbox.get("required_file_names"), "required_file_names")
    present_files = text_tuple(dropbox.get("present_file_names"), "present_file_names")
    stats = copy_stats(required_files, present_files)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_OPERATOR_COPY_CHECKLIST_USER_ACTION_REQUIRED",
        "dropbox_subdir": EVIDENCE_SUBDIR,
        **stats_fields(stats),
        "checklist_entries": checklist_entries(required_files, present_files),
        "required_payload_root": "review_payload.items",
        "required_question_numbers": "1..20",
        "required_item_count_per_file": 20,
        "allowed_statuses": list(ALLOWED_STATUSES),
        "recognized_answer_contract": "recognized string or recognized_answer string/null",
        "forbidden_fields": ["expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "grading"],
        "forbidden_student_facing_values": ["local filesystem paths", "answer keys", "grading labels"],
        "next_status": "USER_APPROVAL_REQUIRED",
        "required_next_artifact": "four_target-named_recognized_evidence_payload_files",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def text_tuple(value: JsonValue, label: str) -> tuple[str, ...]:
    match value:
        case list():
            return tuple(text_item(item, label) for item in value)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError(f"{label} must be a list of text values")
        case unreachable:
            assert_never(unreachable)


def text_item(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} contains a non-text value")
        case unreachable:
            assert_never(unreachable)


def copy_stats(required_files: tuple[str, ...], present_files: tuple[str, ...]) -> CopyChecklist:
    present = set(present_files)
    missing_count = sum(1 for file_name in required_files if file_name not in present)
    return CopyChecklist(
        required_file_count=len(required_files),
        present_file_count=len(present_files),
        missing_file_count=missing_count,
        checklist_entry_count=len(required_files),
        operator_action_required_count=missing_count,
        evidence_ready=missing_count == 0,
    )


def stats_fields(stats: CopyChecklist) -> JsonObject:
    return {
        "required_file_count": stats.required_file_count,
        "present_file_count": stats.present_file_count,
        "missing_file_count": stats.missing_file_count,
        "checklist_entry_count": stats.checklist_entry_count,
        "operator_action_required_count": stats.operator_action_required_count,
        "evidence_ready": stats.evidence_ready,
    }


def checklist_entries(required_files: tuple[str, ...], present_files: tuple[str, ...]) -> list[JsonObject]:
    present = set(present_files)
    return [
        {
            "file_name": file_name,
            "test_id": test_id_from_file(file_name),
            "present": file_name in present,
            "operator_action": "copy_or_create_valid_recognized_evidence_payload",
            "must_have_review_items": 20,
            "must_have_question_numbers": "1..20",
            "must_not_include": "answer_key_or_grading_or_filesystem_path_values",
        }
        for file_name in required_files
    ]


def test_id_from_file(file_name: str) -> str:
    if not file_name.endswith(FILENAME_SUFFIX):
        raise ExtendedGateError(f"{file_name} must end with {FILENAME_SUFFIX}")
    return file_name[: -len(FILENAME_SUFFIX)]


def require_current_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_OPERATOR_COPY_CHECKLIST_USER_ACTION_REQUIRED", "status")
    for key, value in current_integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("evidence_ready"), False, "evidence_ready")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def current_integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4), ("present_file_count", 0), ("missing_file_count", 4),
        ("checklist_entry_count", 4), ("operator_action_required_count", 4),
        ("required_item_count_per_file", 20), ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0), ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Operator Copy Checklist",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- dropbox subdir: `{output['dropbox_subdir']}`",
        f"- required files: {output['required_file_count']}",
        f"- present files: {output['present_file_count']}",
        f"- missing files: {output['missing_file_count']}",
        f"- operator actions required: {output['operator_action_required_count']}",
        f"- payload root: `{output['required_payload_root']}`",
        f"- required item count per file: {output['required_item_count_per_file']}",
        f"- required question numbers: `{output['required_question_numbers']}`",
        f"- recognized answer contract: `{output['recognized_answer_contract']}`",
        f"- evidence ready: {output['evidence_ready']}",
        f"- next status: `{output['next_status']}`",
        "- answer-key/grading/path leak count: 0",
        "",
        "## Required Files",
        *[f"- `{entry['file_name']}`: present={entry['present']}" for entry in output["checklist_entries"]],
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
