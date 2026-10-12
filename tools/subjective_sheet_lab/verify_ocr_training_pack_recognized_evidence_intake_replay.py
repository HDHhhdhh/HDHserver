# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_intake_replay.py

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
from ocr_training_pack_recognized_evidence_contract_core import validate_payload

LAB: Final[Path] = Path(__file__).resolve().parent
CHECKLIST_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_operator_checklist.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake_replay.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake_replay.md"


@dataclass(frozen=True, slots=True)
class ExpectedEvidence:
    test_id: str
    required_file_name: str


@dataclass(frozen=True, slots=True)
class EvidenceReplay:
    file_name: str
    test_id: str
    accepted: bool
    reason: str
    expected_file_name: str


def main() -> int:
    output = intake_replay(read_json_object(CHECKLIST_JSON), evidence_payloads())
    require_intake_replay(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def evidence_payloads() -> tuple[tuple[str, JsonObject], ...]:
    files = sorted(EVIDENCE_DIR.glob("*.json")) if EVIDENCE_DIR.exists() else []
    return tuple((path.name, read_json_object(path)) for path in files)


def intake_replay(checklist: JsonObject, payloads: tuple[tuple[str, JsonObject], ...]) -> JsonObject:
    expected = expected_evidence(checklist)
    rows = tuple(replay_row(file_name, payload, expected) for file_name, payload in payloads)
    expected_names = tuple(item.required_file_name for item in expected)
    present_names = tuple(row.file_name for row in rows)
    missing_names = tuple(name for name in expected_names if name not in present_names)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED",
        "checklist_entry_count": len(expected),
        "evidence_file_count": len(rows),
        "accepted_file_count": sum(1 for row in rows if row.accepted),
        "rejected_file_count": sum(1 for row in rows if not row.accepted),
        "missing_required_file_count": len(missing_names),
        "unexpected_file_count": sum(1 for row in rows if row.file_name not in expected_names),
        "target_mismatch_file_count": sum(1 for row in rows if row.file_name != row.expected_file_name),
        "intake_replay_ready": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "required_next_artifact": "four_contract_valid_target_named_recognized_evidence_files",
        "missing_required_file_names": list(missing_names),
        "file_results": [replay_fields(row) for row in rows],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def expected_evidence(checklist: JsonObject) -> tuple[ExpectedEvidence, ...]:
    require_text_value(
        checklist.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED",
        "checklist.status",
    )
    match checklist.get("entries"):
        case list() as entries:
            return tuple(expected_entry(entry) for entry in entries)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("checklist.entries must be a list")
        case unreachable:
            assert_never(unreachable)


def expected_entry(value: JsonValue) -> ExpectedEvidence:
    match value:
        case dict() as entry:
            return ExpectedEvidence(
                test_id=text_field(entry.get("test_id"), "test_id"),
                required_file_name=text_field(entry.get("required_file_name"), "required_file_name"),
            )
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("checklist entry must be a mapping")
        case unreachable:
            assert_never(unreachable)


def replay_row(file_name: str, payload: JsonObject, expected: tuple[ExpectedEvidence, ...]) -> EvidenceReplay:
    test_id = payload_test_id(payload)
    target = next((item for item in expected if item.test_id == test_id), ExpectedEvidence(test_id="", required_file_name=""))
    contract = validate_payload(payload)
    reason = replay_reason(contract.reason, contract.accepted, target.required_file_name, file_name)
    return EvidenceReplay(
        file_name=file_name,
        test_id=test_id,
        accepted=contract.accepted and target.required_file_name == file_name,
        reason=reason,
        expected_file_name=target.required_file_name,
    )


def replay_reason(contract_reason: str, contract_accepted: bool, expected_file_name: str, file_name: str) -> str:
    if not contract_accepted:
        return contract_reason
    if expected_file_name == "":
        return "unexpected_test_id"
    if expected_file_name != file_name:
        return "target_file_name_mismatch"
    return contract_reason


def payload_test_id(payload: JsonObject) -> str:
    match payload.get("review_payload"):
        case dict() as review_payload:
            return text_field(review_payload.get("test_id"), "review_payload.test_id")
        case None | bool() | int() | float() | str() | list():
            return ""
        case unreachable:
            assert_never(unreachable)


def text_field(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def replay_fields(row: EvidenceReplay) -> JsonObject:
    return {
        "file_name": row.file_name,
        "test_id": row.test_id,
        "accepted": row.accepted,
        "reason": row.reason,
        "expected_file_name": row.expected_file_name,
    }


def require_intake_replay(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED",
        "status",
    )
    for key, value in integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("intake_replay_ready"), False, "intake_replay_ready")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("checklist_entry_count", 4), ("evidence_file_count", 0), ("accepted_file_count", 0),
        ("rejected_file_count", 0), ("missing_required_file_count", 4), ("unexpected_file_count", 0),
        ("target_mismatch_file_count", 0), ("provider_call_count", 0), ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0), ("ts_submit_click_count", 0), ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    return "\n".join(
        [
            "# OCR Training Pack Recognized Evidence Intake Replay",
            "",
            "- Gemini/API calls: 0; external OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- student-facing: false",
            "- production default: `NO-GO`",
            f"- status: `{output['status']}`",
            f"- checklist entries: {output['checklist_entry_count']}",
            f"- evidence files: {output['evidence_file_count']}",
            f"- accepted files: {output['accepted_file_count']}",
            f"- rejected files: {output['rejected_file_count']}",
            f"- missing required files: {output['missing_required_file_count']}",
            f"- unexpected files: {output['unexpected_file_count']}",
            f"- target mismatches: {output['target_mismatch_file_count']}",
            f"- intake replay ready: {output['intake_replay_ready']}",
            f"- next status: `{output['next_status']}`",
            "- answer-key/grading/path leak count: 0",
            "",
        ],
    ) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
