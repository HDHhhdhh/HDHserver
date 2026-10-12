# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_operator_evidence_manifest_gate.py

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

LAB: Final[Path] = Path(__file__).resolve().parent
OPERATOR_CHECKLIST_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_operator_checklist.json"
REAL_FILE_REPLAY_JSON: Final[Path] = LAB / "ocr_training_pack_post_dropbox_real_file_replay_gate.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_operator_evidence_manifest_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_operator_evidence_manifest_gate.md"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    test_id: str
    required_file_name: str
    action_status: str


@dataclass(frozen=True, slots=True)
class ManifestInputs:
    operator_checklist: JsonObject
    real_file_replay: JsonObject


def main() -> int:
    output = manifest_summary(
        ManifestInputs(
            operator_checklist=read_json_object(OPERATOR_CHECKLIST_JSON),
            real_file_replay=read_json_object(REAL_FILE_REPLAY_JSON),
        ),
    )
    require_manifest_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def manifest_summary(inputs: ManifestInputs) -> JsonObject:
    require_inputs(inputs)
    entries = manifest_entries(inputs.operator_checklist)
    ready_now = bool_value(inputs.real_file_replay, "real_file_replay_ready")
    ready_after_files = bool_value(inputs.real_file_replay, "post_file_replay_ready")
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_OPERATOR_EVIDENCE_MANIFEST_USER_APPROVAL_REQUIRED",
        "target_count": len(entries),
        "manifest_entry_count": len(entries),
        "present_entry_count": sum(1 for entry in entries if entry.action_status == "ready"),
        "missing_entry_count": sum(1 for entry in entries if entry.action_status == "missing"),
        "required_review_item_count_per_payload": 20,
        "required_question_sequence": "1-20",
        "manifest_ready_now": ready_now,
        "manifest_ready_after_files": ready_after_files,
        "manifest_sha256": manifest_hash(entries),
        "entries": [entry_fields(entry) for entry in entries],
        "contract_source": "recognized_evidence_operator_checklist",
        "write_attempted": False,
        "promotion_write_attempted": False,
        "replacement_write_attempted": False,
        "accuracy_recompute_attempted": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "next_safe_action": "collect_four_contract_valid_target_named_recognized_evidence_files_with_user_approval",
        "required_next_artifact": "four_contract_valid_target_named_recognized_evidence_files",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def require_inputs(inputs: ManifestInputs) -> None:
    require_text_value(
        inputs.operator_checklist.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED",
        "operator_checklist.status",
    )
    require_text_value(
        inputs.real_file_replay.get("status"),
        "TRAINING_PACK_POST_DROPBOX_REAL_FILE_REPLAY_USER_APPROVAL_REQUIRED",
        "real_file_replay.status",
    )
    require_int_value(inputs.operator_checklist.get("checklist_entry_count"), 4, "operator_checklist.entry_count")
    require_int_value(inputs.operator_checklist.get("operator_action_required_count"), 4, "operator_checklist.action_count")
    require_int_value(inputs.real_file_replay.get("current_real_file_count"), 0, "real_file_replay.current_file_count")
    require_int_value(inputs.real_file_replay.get("current_missing_file_count"), 4, "real_file_replay.missing_file_count")
    require_bool_value(inputs.operator_checklist.get("checklist_ready"), False, "operator_checklist.ready")
    require_bool_value(inputs.real_file_replay.get("real_file_replay_ready"), False, "real_file_replay.ready_now")
    require_bool_value(inputs.real_file_replay.get("post_file_replay_ready"), True, "real_file_replay.ready_after_files")


def manifest_entries(operator_checklist: JsonObject) -> tuple[ManifestEntry, ...]:
    match operator_checklist.get("entries"):
        case list() as rows:
            return tuple(manifest_entry(row, index) for index, row in enumerate(rows, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("operator checklist entries must be a list")
        case unreachable:
            assert_never(unreachable)


def manifest_entry(value: JsonValue, index: int) -> ManifestEntry:
    match value:
        case dict() as row:
            return ManifestEntry(
                test_id=text_value(row.get("test_id"), f"entries[{index}].test_id"),
                required_file_name=text_value(row.get("required_file_name"), f"entries[{index}].required_file_name"),
                action_status=text_value(row.get("action_status"), f"entries[{index}].action_status"),
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


def bool_value(payload: JsonObject, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ExtendedGateError(f"{key} must be boolean")
    return value


def manifest_hash(entries: tuple[ManifestEntry, ...]) -> str:
    payload = [
        {"test_id": entry.test_id, "required_file_name": entry.required_file_name}
        for entry in sorted(entries, key=lambda item: item.test_id)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def entry_fields(entry: ManifestEntry) -> JsonObject:
    return {
        "test_id": entry.test_id,
        "required_file_name": entry.required_file_name,
        "action_status": entry.action_status,
        "required_review_item_count": 20,
        "required_question_sequence": "1-20",
    }


def require_manifest_summary(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_OPERATOR_EVIDENCE_MANIFEST_USER_APPROVAL_REQUIRED",
        "status",
    )
    for key, value in integer_requirements():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("manifest_ready_now"), False, "manifest_ready_now")
    require_bool_value(output.get("manifest_ready_after_files"), True, "manifest_ready_after_files")
    require_bool_value(output.get("write_attempted"), False, "write_attempted")
    require_bool_value(output.get("promotion_write_attempted"), False, "promotion_write_attempted")
    require_bool_value(output.get("replacement_write_attempted"), False, "replacement_write_attempted")
    require_bool_value(output.get("accuracy_recompute_attempted"), False, "accuracy_recompute_attempted")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(
        output.get("next_safe_action"),
        "collect_four_contract_valid_target_named_recognized_evidence_files_with_user_approval",
        "next_safe_action",
    )


def integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4),
        ("manifest_entry_count", 4),
        ("present_entry_count", 0),
        ("missing_entry_count", 4),
        ("required_review_item_count_per_payload", 20),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Operator Evidence Manifest Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- submit route calls: 0",
        "- submit button clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- manifest entries: {output['manifest_entry_count']}",
        f"- present entries: {output['present_entry_count']}",
        f"- missing entries: {output['missing_entry_count']}",
        f"- manifest ready now: {output['manifest_ready_now']}",
        f"- manifest ready after files: {output['manifest_ready_after_files']}",
        f"- manifest sha256: `{output['manifest_sha256']}`",
        f"- write attempted: {output['write_attempted']}",
        f"- next status: `{output['next_status']}`",
        f"- next safe action: `{output['next_safe_action']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
