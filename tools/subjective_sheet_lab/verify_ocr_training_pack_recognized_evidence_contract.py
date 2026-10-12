# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_contract.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_training_pack_recognized_evidence_contract_core import contract_summary
from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_contract.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_contract.md"


def main() -> int:
    output = contract_summary(read_json_object(SOURCE_JSON), evidence_payloads())
    require_current_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def evidence_payloads() -> list[JsonObject]:
    files = sorted(EVIDENCE_DIR.glob("*.json")) if EVIDENCE_DIR.exists() else []
    return [read_json_object(path) for path in files]


def require_current_summary(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS",
        "status",
    )
    for key, value in current_integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("contract_ready"), True, "contract_ready")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def current_integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4),
        ("evidence_file_count", 0),
        ("live_evidence_accepted_count", 0),
        ("live_evidence_rejected_count", 0),
        ("contract_probe_count", 10),
        ("contract_probe_accepted_count", 1),
        ("contract_probe_rejected_count", 9),
        ("forbidden_field_probe_rejected_count", 1),
        ("filesystem_path_probe_rejected_count", 1),
        ("schema_probe_rejected_count", 7),
        ("item_count_schema_probe_rejected_count", 1),
        ("question_sequence_schema_probe_rejected_count", 1),
        ("status_schema_probe_rejected_count", 2),
        ("safe_auto_grade_status_probe_rejected_count", 1),
        ("recognized_answer_schema_probe_rejected_count", 1),
        ("blank_recognized_answer_probe_rejected_count", 1),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Evidence Contract",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- targets: {output['target_count']}",
        f"- evidence files: {output['evidence_file_count']}",
        f"- live evidence accepted: {output['live_evidence_accepted_count']}",
        f"- live evidence rejected: {output['live_evidence_rejected_count']}",
        f"- contract probes: {output['contract_probe_count']}",
        f"- contract probes accepted: {output['contract_probe_accepted_count']}",
        f"- contract probes rejected: {output['contract_probe_rejected_count']}",
        f"- forbidden-field probes rejected: {output['forbidden_field_probe_rejected_count']}",
        f"- filesystem-path probes rejected: {output['filesystem_path_probe_rejected_count']}",
        f"- schema probes rejected: {output['schema_probe_rejected_count']}",
        f"- item-count schema probes rejected: {output['item_count_schema_probe_rejected_count']}",
        f"- question-sequence schema probes rejected: {output['question_sequence_schema_probe_rejected_count']}",
        f"- status schema probes rejected: {output['status_schema_probe_rejected_count']}",
        f"- safe-auto-grade status probes rejected: {output['safe_auto_grade_status_probe_rejected_count']}",
        f"- recognized-answer schema probes rejected: {output['recognized_answer_schema_probe_rejected_count']}",
        f"- blank recognized-answer probes rejected: {output['blank_recognized_answer_probe_rejected_count']}",
        f"- contract ready: {output['contract_ready']}",
        f"- next status: `{output['next_status']}`",
        "- sensitive/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
