# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_arrival_smoke_operator_digest.py

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

LAB: Final[Path] = Path(__file__).resolve().parent
ARRIVAL_SMOKE_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_smoke.json"
RUNBOOK_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_operator_runbook.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_arrival_smoke_operator_digest.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_arrival_smoke_operator_digest.md"


@dataclass(frozen=True, slots=True)
class DigestInputs:
    arrival_smoke: JsonObject
    runbook: JsonObject


def main() -> int:
    output = digest(
        DigestInputs(
            arrival_smoke=read_json_object(ARRIVAL_SMOKE_JSON),
            runbook=read_json_object(RUNBOOK_JSON),
        ),
    )
    require_report(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def digest(inputs: DigestInputs) -> JsonObject:
    require_inputs(inputs)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_ARRIVAL_SMOKE_OPERATOR_DIGEST_READY",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "smoke_scope": "file_name_and_size_only",
        "required_file_count": 4,
        "present_file_count": 0,
        "matching_file_count": 0,
        "missing_file_count": 4,
        "unexpected_file_count": 0,
        "zero_byte_file_count": 0,
        "positive_size_file_count": 0,
        "payload_parse_attempted": False,
        "smoke_ready_now": False,
        "ready_after_required_files": True,
        "next_safe_stage": "blank_rejection_then_contract_validate_then_target_coverage_then_intake_replay",
        "provider_call_required": False,
        "write_allowed": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: DigestInputs) -> None:
    require_text_value(
        inputs.arrival_smoke.get("status"),
        "TRAINING_PACK_EVIDENCE_ARRIVAL_SMOKE_READY",
        "arrival_smoke.status",
    )
    require_text_value(
        inputs.runbook.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_OPERATOR_RUNBOOK_READY",
        "runbook.status",
    )
    require_text_value(inputs.arrival_smoke.get("scope"), "file_name_and_size_only", "arrival_smoke.scope")
    require_text_value(
        inputs.runbook.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "runbook.current_blocker",
    )
    for key, value in input_counts():
        source, field = key.split(".", maxsplit=1)
        require_int_value(getattr(inputs, source).get(field), value, key)
    require_bool_value(inputs.arrival_smoke.get("payload_parse_attempted"), False, "arrival_smoke.payload_parse_attempted")
    require_bool_value(inputs.arrival_smoke.get("smoke_ready_now"), False, "arrival_smoke.smoke_ready_now")
    require_bool_value(inputs.arrival_smoke.get("ready_after_required_files"), True, "arrival_smoke.ready_after_files")
    require_bool_value(inputs.runbook.get("payload_parse_before_arrival_allowed"), False, "runbook.parse_before_arrival")
    require_bool_value(inputs.runbook.get("payload_parse_after_arrival_allowed"), True, "runbook.parse_after_arrival")
    require_bool_value(inputs.runbook.get("provider_call_required"), False, "runbook.provider_call_required")
    for label, payload in (("arrival_smoke", inputs.arrival_smoke), ("runbook", inputs.runbook)):
        require_safety_counters(label, payload)


def input_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("arrival_smoke.required_file_count", 4),
        ("arrival_smoke.present_file_count", 0),
        ("arrival_smoke.matching_file_count", 0),
        ("arrival_smoke.missing_file_count", 4),
        ("arrival_smoke.unexpected_file_count", 0),
        ("arrival_smoke.zero_byte_file_count", 0),
        ("arrival_smoke.positive_size_file_count", 0),
        ("runbook.required_file_count", 4),
        ("runbook.present_file_count", 0),
        ("runbook.missing_file_count", 4),
        ("runbook.validation_command_count", 8),
    )


def require_report(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_ARRIVAL_SMOKE_OPERATOR_DIGEST_READY", "status")
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_text_value(output.get("smoke_scope"), "file_name_and_size_only", "smoke_scope")
    require_text_value(
        output.get("next_safe_stage"),
        "blank_rejection_then_contract_validate_then_target_coverage_then_intake_replay",
        "next_safe_stage",
    )
    require_text_value(output.get("production_default"), "NO_GO", "production_default")
    for key, value in output_counts():
        require_int_value(output.get(key), value, key)
    for key, value in output_booleans():
        require_bool_value(output.get(key), value, key)
    require_safety_counters("output", output)


def output_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("matching_file_count", 0),
        ("missing_file_count", 4),
        ("unexpected_file_count", 0),
        ("zero_byte_file_count", 0),
        ("positive_size_file_count", 0),
    )


def output_booleans() -> tuple[tuple[str, bool], ...]:
    return (
        ("payload_parse_attempted", False),
        ("smoke_ready_now", False),
        ("ready_after_required_files", True),
        ("provider_call_required", False),
        ("write_allowed", False),
    )


def require_safety_counters(label: str, payload: JsonObject) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_leak")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.path_leak")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Arrival Smoke Operator Digest",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- scope: `{output['smoke_scope']}`",
        f"- required files: {output['required_file_count']}",
        f"- present files: {output['present_file_count']}",
        f"- missing files: {output['missing_file_count']}",
        f"- unexpected files: {output['unexpected_file_count']}",
        f"- zero-byte files: {output['zero_byte_file_count']}",
        f"- payload parse attempted: {output['payload_parse_attempted']}",
        f"- smoke ready now: {output['smoke_ready_now']}",
        f"- ready after files: {output['ready_after_required_files']}",
        f"- next safe stage: `{output['next_safe_stage']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
