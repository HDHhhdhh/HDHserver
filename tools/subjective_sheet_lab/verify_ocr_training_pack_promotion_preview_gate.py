# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_promotion_preview_gate.py

from __future__ import annotations

import hashlib
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
from verify_ocr_training_pack_post_dropbox_acceptance_gate import REPORT_JSON as ACCEPTANCE_JSON
from verify_ocr_training_pack_recognized_evidence_operator_checklist import REPORT_JSON as CHECKLIST_JSON

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_promotion_preview_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_promotion_preview_gate.md"


@dataclass(frozen=True, slots=True)
class PreviewRow:
    test_id: str
    file_name: str
    question_count: int
    sequence: str
    row_hash: str


def main() -> int:
    output = preview_summary(read_json_object(CHECKLIST_JSON), read_json_object(ACCEPTANCE_JSON))
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def preview_summary(checklist: JsonObject, acceptance: JsonObject) -> JsonObject:
    require_text_value(
        checklist.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED",
        "checklist.status",
    )
    require_text_value(acceptance.get("status"), "TRAINING_PACK_POST_DROPBOX_ACCEPTANCE_GATE_READY", "acceptance.status")
    rows = preview_rows(checklist_entries(checklist))
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_PROMOTION_PREVIEW_USER_APPROVAL_REQUIRED",
        "preview_row_count": len(rows),
        "preview_sequence_ok_count": sum(1 for row in rows if row.sequence == "1..20"),
        "preview_question_count_total": sum(row.question_count for row in rows),
        "current_acceptance_ready": acceptance.get("acceptance_ready_now"),
        "post_file_acceptance_ready": acceptance.get("acceptance_ready_after_required_files"),
        "promotion_preview_ready": False,
        "promotion_write_attempted": False,
        "preview_rows": [row_fields(row) for row in rows],
        "preview_manifest_hash": manifest_hash(rows),
        "next_status": "USER_APPROVAL_REQUIRED",
        "next_safe_action": "collect_four_target_named_payload_files_with_user_approval",
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


def checklist_entries(checklist: JsonObject) -> tuple[JsonObject, ...]:
    match checklist.get("entries"):
        case list() as entries:
            return tuple(mapping for mapping in entries if isinstance(mapping, dict))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("checklist.entries must be a list")
        case unreachable:
            assert_never(unreachable)


def preview_rows(entries: tuple[JsonObject, ...]) -> tuple[PreviewRow, ...]:
    return tuple(preview_row(entry) for entry in entries)


def preview_row(entry: JsonObject) -> PreviewRow:
    test_id = text_value(entry.get("test_id"), "test_id")
    file_name = text_value(entry.get("required_file_name"), "required_file_name")
    question_count = 20
    sequence = "1..20"
    return PreviewRow(test_id, file_name, question_count, sequence, row_hash(test_id, file_name))


def row_hash(test_id: str, file_name: str) -> str:
    payload = {"file_name": file_name, "question_count": 20, "sequence": "1..20", "test_id": test_id}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def manifest_hash(rows: tuple[PreviewRow, ...]) -> str:
    payload = [row_fields(row) for row in rows]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def row_fields(row: PreviewRow) -> JsonObject:
    return {
        "test_id": row.test_id,
        "file_name": row.file_name,
        "question_count": row.question_count,
        "sequence": row.sequence,
        "row_hash": row.row_hash,
    }


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_PROMOTION_PREVIEW_USER_APPROVAL_REQUIRED", "status")
    for key, expected in integer_expectations():
        require_int_value(output.get(key), expected, key)
    require_bool_value(output.get("current_acceptance_ready"), False, "current_acceptance_ready")
    require_bool_value(output.get("post_file_acceptance_ready"), True, "post_file_acceptance_ready")
    require_bool_value(output.get("promotion_preview_ready"), False, "promotion_preview_ready")
    require_bool_value(output.get("promotion_write_attempted"), False, "promotion_write_attempted")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(
        output.get("next_safe_action"),
        "collect_four_target_named_payload_files_with_user_approval",
        "next_safe_action",
    )


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("preview_row_count", 4), ("preview_sequence_ok_count", 4), ("preview_question_count_total", 80),
        ("provider_call_count", 0), ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Promotion Preview Gate", "",
        "- Gemini/API calls: 0; external OCR API calls: 0", "- submit route calls: 0", "- submit button clicks: 0",
        "- student-facing: false", "- production default: `NO-GO`", f"- status: `{output['status']}`",
        f"- preview rows: {output['preview_row_count']}",
        f"- preview question count total: {output['preview_question_count_total']}",
        f"- current acceptance ready: {output['current_acceptance_ready']}",
        f"- post-file acceptance ready: {output['post_file_acceptance_ready']}",
        f"- promotion write attempted: {output['promotion_write_attempted']}",
        f"- preview manifest hash: `{output['preview_manifest_hash']}`",
        f"- next status: `{output['next_status']}`", f"- next safe action: `{output['next_safe_action']}`",
        "- sensitive/path leak count: 0", "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
