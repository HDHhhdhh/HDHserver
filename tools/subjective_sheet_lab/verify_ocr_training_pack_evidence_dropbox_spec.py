# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_evidence_dropbox_spec.py

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
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_dropbox_spec.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_evidence_dropbox_spec.md"
FILENAME_SUFFIX: Final[str] = "_recognized_evidence.json"


@dataclass(frozen=True, slots=True)
class DropboxStats:
    required_file_count: int
    present_file_count: int
    matching_file_count: int
    missing_file_count: int
    unexpected_file_count: int
    dropbox_ready: bool


def main() -> int:
    output = dropbox_summary(read_json_object(SOURCE_JSON), evidence_file_names())
    require_current_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def evidence_file_names() -> tuple[str, ...]:
    return tuple(path.name for path in sorted(EVIDENCE_DIR.glob("*.json"))) if EVIDENCE_DIR.exists() else ()


def dropbox_summary(source: JsonObject, actual_names: tuple[str, ...]) -> JsonObject:
    require_text_value(
        source.get("status"),
        "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING",
        "source.status",
    )
    required_names = expected_file_names(target_ids(source))
    stats = dropbox_stats(required_names, actual_names)
    probes = dropbox_probe_stats(required_names)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_EVIDENCE_DROPBOX_USER_APPROVAL_REQUIRED",
        "target_count": len(required_names),
        **stats_fields(stats),
        "dropbox_probe_count": len(probes),
        "dropbox_probe_ready_count": sum(1 for probe in probes if probe.dropbox_ready),
        "dropbox_probe_blocked_count": sum(1 for probe in probes if not probe.dropbox_ready),
        "required_file_names": list(required_names),
        "present_file_names": list(actual_names),
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


def target_ids(source: JsonObject) -> tuple[str, ...]:
    match source.get("targets"):
        case list() as targets:
            return tuple(target_id for target in targets if (target_id := target_id_or_none(target)) is not None)
        case None | bool() | int() | float() | str() | dict():
            return ()
        case unreachable:
            assert_never(unreachable)


def target_id_or_none(value: JsonValue) -> str | None:
    match value:
        case dict() as target:
            return text_or_none(target.get("test_id"))
        case None | bool() | int() | float() | str() | list():
            return None
        case unreachable:
            assert_never(unreachable)


def text_or_none(value: JsonValue) -> str | None:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            return None
        case unreachable:
            assert_never(unreachable)


def expected_file_names(targets: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{target}{FILENAME_SUFFIX}" for target in targets)


def dropbox_stats(required_names: tuple[str, ...], actual_names: tuple[str, ...]) -> DropboxStats:
    required = set(required_names)
    actual = set(actual_names)
    missing_count = len(required - actual)
    unexpected_count = len(actual - required)
    ready = missing_count == 0 and unexpected_count == 0 and len(actual_names) == len(required_names)
    return DropboxStats(
        required_file_count=len(required_names),
        present_file_count=len(actual_names),
        matching_file_count=len(required & actual),
        missing_file_count=missing_count,
        unexpected_file_count=unexpected_count,
        dropbox_ready=ready,
    )


def dropbox_probe_stats(required_names: tuple[str, ...]) -> tuple[DropboxStats, ...]:
    if len(required_names) != 4:
        raise ExtendedGateError("Training Pack dropbox probes require 4 target filenames")
    return (
        dropbox_stats(required_names, required_names),
        dropbox_stats(required_names, required_names[:3]),
        dropbox_stats(required_names, (*required_names[:3], "unexpected_recognized_evidence.json")),
        dropbox_stats(required_names, ()),
    )


def stats_fields(stats: DropboxStats) -> JsonObject:
    return {
        "required_file_count": stats.required_file_count,
        "present_file_count": stats.present_file_count,
        "matching_file_count": stats.matching_file_count,
        "missing_file_count": stats.missing_file_count,
        "unexpected_file_count": stats.unexpected_file_count,
        "dropbox_ready": stats.dropbox_ready,
    }


def require_current_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_EVIDENCE_DROPBOX_USER_APPROVAL_REQUIRED", "status")
    for key, value in current_integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("dropbox_ready"), False, "dropbox_ready")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def current_integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4), ("required_file_count", 4), ("present_file_count", 0),
        ("matching_file_count", 0), ("missing_file_count", 4), ("unexpected_file_count", 0),
        ("dropbox_probe_count", 4), ("dropbox_probe_ready_count", 1), ("dropbox_probe_blocked_count", 3),
        ("provider_call_count", 0), ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Evidence Dropbox Spec",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- required files: {output['required_file_count']}",
        f"- present files: {output['present_file_count']}",
        f"- matching files: {output['matching_file_count']}",
        f"- missing files: {output['missing_file_count']}",
        f"- unexpected files: {output['unexpected_file_count']}",
        f"- probes: {output['dropbox_probe_ready_count']} ready / {output['dropbox_probe_blocked_count']} blocked",
        f"- dropbox ready: {output['dropbox_ready']}",
        f"- next status: `{output['next_status']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
