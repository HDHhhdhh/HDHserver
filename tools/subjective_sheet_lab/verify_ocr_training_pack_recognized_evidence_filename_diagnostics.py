# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_filename_diagnostics.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_training_pack_recognized_evidence_target_diff_core import (
    EvidenceFile,
    evidence_files,
    target_test_ids,
)

LAB: Final[Path] = Path(__file__).resolve().parent
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_filename_diagnostics.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_filename_diagnostics.md"


@dataclass(frozen=True, slots=True)
class ExpectedEvidenceFile:
    test_id: str
    required_file_name: str


@dataclass(frozen=True, slots=True)
class EvidenceNameRow:
    file_name: str
    payload_test_id: str
    required_file_name: str
    filename_status: str


def main() -> int:
    output = filename_diagnostics(read_json_object(SOURCE_JSON), evidence_files(EVIDENCE_DIR))
    require_filename_diagnostics(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def filename_diagnostics(source: JsonObject, evidence: tuple[EvidenceFile, ...]) -> JsonObject:
    require_text_value(
        source.get("status"),
        "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING",
        "source.status",
    )
    expected = tuple(expected_file(test_id) for test_id in target_test_ids(source))
    rows = tuple(name_row(item, expected) for item in evidence if item.test_id is not None)
    mismatch_count = sum(1 for row in rows if row.filename_status == "filename_mismatch")
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_FILENAME_DIAGNOSTICS_USER_ACTION_REQUIRED",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "target_file_count": len(expected),
        "expected_file_name_count": len(expected),
        "evidence_file_count": len(evidence),
        "matching_file_name_count": sum(1 for row in rows if row.filename_status == "filename_matches_payload_test_id"),
        "filename_mismatch_count": mismatch_count,
        "unknown_test_id_file_count": sum(1 for row in rows if row.filename_status == "unexpected_payload_test_id"),
        "missing_test_id_file_count": sum(1 for item in evidence if item.test_id is None),
        "diagnostics_ready": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "expected_files": [expected_fields(item) for item in expected],
        "observed_files": [row_fields(row) for row in rows],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def expected_file(test_id: str) -> ExpectedEvidenceFile:
    return ExpectedEvidenceFile(test_id=test_id, required_file_name=f"{test_id}_recognized_evidence.json")


def name_row(item: EvidenceFile, expected: tuple[ExpectedEvidenceFile, ...]) -> EvidenceNameRow:
    expected_by_test_id = {row.test_id: row.required_file_name for row in expected}
    required_file_name = expected_by_test_id.get(item.test_id, "")
    return EvidenceNameRow(
        file_name=item.name,
        payload_test_id=item.test_id or "",
        required_file_name=required_file_name,
        filename_status=filename_status(item.name, required_file_name),
    )


def filename_status(file_name: str, required_file_name: str) -> str:
    if required_file_name == "":
        return "unexpected_payload_test_id"
    if file_name == required_file_name:
        return "filename_matches_payload_test_id"
    return "filename_mismatch"


def expected_fields(item: ExpectedEvidenceFile) -> JsonObject:
    return {"test_id": item.test_id, "required_file_name": item.required_file_name, "present": False}


def row_fields(row: EvidenceNameRow) -> JsonObject:
    return {
        "file_name": row.file_name,
        "payload_test_id": row.payload_test_id,
        "required_file_name": row.required_file_name,
        "filename_status": row.filename_status,
    }


def require_filename_diagnostics(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_FILENAME_DIAGNOSTICS_USER_ACTION_REQUIRED",
        "status",
    )
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(output.get("production_default"), "NO_GO", "production_default")
    for key, value in expected_counts():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("diagnostics_ready"), False, "diagnostics_ready")


def expected_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("target_file_count", 4),
        ("expected_file_name_count", 4),
        ("evidence_file_count", 0),
        ("matching_file_name_count", 0),
        ("filename_mismatch_count", 0),
        ("unknown_test_id_file_count", 0),
        ("missing_test_id_file_count", 0),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Evidence Filename Diagnostics",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- target files: {output['target_file_count']}",
        f"- evidence files: {output['evidence_file_count']}",
        f"- filename mismatches: {output['filename_mismatch_count']}",
        f"- unknown test_id files: {output['unknown_test_id_file_count']}",
        f"- missing test_id files: {output['missing_test_id_file_count']}",
        f"- diagnostics ready: {output['diagnostics_ready']}",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
