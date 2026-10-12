# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_evidence_arrival_smoke.py

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
    require_int,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
DROPBOX_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_dropbox_spec.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_smoke.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_smoke.md"


@dataclass(frozen=True, slots=True)
class FileProbe:
    file_name: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class SmokeStats:
    required_file_count: int
    present_file_count: int
    matching_file_count: int
    missing_file_count: int
    unexpected_file_count: int
    zero_byte_file_count: int
    positive_size_file_count: int

    @property
    def smoke_ready(self) -> bool:
        return (
            self.present_file_count == self.required_file_count
            and self.missing_file_count == 0
            and self.unexpected_file_count == 0
            and self.zero_byte_file_count == 0
        )


def main() -> int:
    output = arrival_smoke(read_json_object(DROPBOX_JSON), file_probes())
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def file_probes() -> tuple[FileProbe, ...]:
    files = sorted(EVIDENCE_DIR.glob("*.json")) if EVIDENCE_DIR.exists() else []
    return tuple(FileProbe(file_name=path.name, byte_size=path.stat().st_size) for path in files)


def arrival_smoke(dropbox: JsonObject, probes: tuple[FileProbe, ...]) -> JsonObject:
    required_names = required_file_names(dropbox)
    stats = smoke_stats(required_names, probes)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_EVIDENCE_ARRIVAL_SMOKE_READY",
        "scope": "file_name_and_size_only",
        "payload_parse_attempted": False,
        "required_file_count": stats.required_file_count,
        "present_file_count": stats.present_file_count,
        "matching_file_count": stats.matching_file_count,
        "missing_file_count": stats.missing_file_count,
        "unexpected_file_count": stats.unexpected_file_count,
        "zero_byte_file_count": stats.zero_byte_file_count,
        "positive_size_file_count": stats.positive_size_file_count,
        "smoke_ready_now": stats.smoke_ready,
        "ready_after_required_files": True,
        "next_safe_command": "verify_ocr_training_pack_recognized_evidence_contract.py",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def required_file_names(dropbox: JsonObject) -> tuple[str, ...]:
    require_text_value(
        dropbox.get("status"),
        "TRAINING_PACK_EVIDENCE_DROPBOX_USER_APPROVAL_REQUIRED",
        "dropbox.status",
    )
    match dropbox.get("required_file_names"):
        case list() as names:
            return tuple(text_field(name, "required_file_names[]") for name in names)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("required_file_names must be a list")
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


def smoke_stats(required_names: tuple[str, ...], probes: tuple[FileProbe, ...]) -> SmokeStats:
    required = set(required_names)
    present = {probe.file_name for probe in probes}
    matching = required & present
    unexpected = present - required
    zero_byte = sum(1 for probe in probes if probe.byte_size <= 0)
    return SmokeStats(
        required_file_count=len(required_names),
        present_file_count=len(probes),
        matching_file_count=len(matching),
        missing_file_count=len(required - present),
        unexpected_file_count=len(unexpected),
        zero_byte_file_count=zero_byte,
        positive_size_file_count=len(probes) - zero_byte,
    )


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_EVIDENCE_ARRIVAL_SMOKE_READY", "status")
    require_text_value(output.get("scope"), "file_name_and_size_only", "scope")
    require_bool_value(output.get("payload_parse_attempted"), False, "payload_parse_attempted")
    require_int_value(output.get("required_file_count"), 4, "required_file_count")
    require_int_value(output.get("unexpected_file_count"), 0, "unexpected_file_count")
    require_int_value(output.get("zero_byte_file_count"), 0, "zero_byte_file_count")
    require_bool_value(output.get("ready_after_required_files"), True, "ready_after_required_files")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(output.get(key), 0, key)
    require_int_value(output.get("answer_key_or_grading_field_leak_count"), 0, "answer_key_or_grading_field_leak_count")
    require_int_value(output.get("filesystem_path_leak_count"), 0, "filesystem_path_leak_count")
    present = require_int(output.get("present_file_count"), "present_file_count")
    matching = require_int(output.get("matching_file_count"), "matching_file_count")
    if matching != present:
        raise ExtendedGateError("all present files must match required names")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Evidence Arrival Smoke",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- payload parsing attempted: false",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- scope: `{output['scope']}`",
        f"- required files: {output['required_file_count']}",
        f"- present files: {output['present_file_count']}",
        f"- matching files: {output['matching_file_count']}",
        f"- missing files: {output['missing_file_count']}",
        f"- unexpected files: {output['unexpected_file_count']}",
        f"- zero-byte files: {output['zero_byte_file_count']}",
        f"- smoke ready now: {output['smoke_ready_now']}",
        f"- next safe command: `{output['next_safe_command']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
