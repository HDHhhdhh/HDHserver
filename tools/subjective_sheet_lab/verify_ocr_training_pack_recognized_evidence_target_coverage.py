# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_target_coverage.py

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
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_target_coverage.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_target_coverage.md"


@dataclass(frozen=True, slots=True)
class CoverageStats:
    target_count: int
    evidence_file_count: int
    covered_target_count: int
    missing_target_count: int
    duplicate_target_count: int
    unexpected_target_count: int
    missing_test_id_count: int
    target_coverage_ready: bool


def main() -> int:
    output = target_coverage_summary(read_json_object(SOURCE_JSON), evidence_payloads())
    require_current_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def evidence_payloads() -> tuple[JsonObject, ...]:
    files = sorted(EVIDENCE_DIR.glob("*.json")) if EVIDENCE_DIR.exists() else []
    return tuple(read_json_object(path) for path in files)


def target_coverage_summary(source: JsonObject, payloads: tuple[JsonObject, ...]) -> JsonObject:
    require_text_value(source.get("status"), "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING", "source.status")
    targets = target_ids(source)
    stats = coverage_stats(targets, payloads)
    probes = coverage_probe_stats(targets)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_USER_APPROVAL_REQUIRED",
        **stats_fields(stats),
        "coverage_probe_count": len(probes),
        "coverage_probe_ready_count": sum(1 for probe in probes if probe.target_coverage_ready),
        "coverage_probe_blocked_count": sum(1 for probe in probes if not probe.target_coverage_ready),
        "next_status": "USER_APPROVAL_REQUIRED",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def target_ids(source: JsonObject) -> tuple[str, ...]:
    match source.get("targets"):
        case list() as targets:
            return tuple(target_id for target in targets if (target_id := test_id_from_json(target)) is not None)
        case None | bool() | int() | float() | str() | dict():
            return ()
        case unreachable:
            assert_never(unreachable)


def test_id_from_json(value: JsonValue) -> str | None:
    match value:
        case dict() as payload:
            return text_or_none(payload.get("test_id"))
        case None | bool() | int() | float() | str() | list():
            return None
        case unreachable:
            assert_never(unreachable)


def payload_test_id(payload: JsonObject) -> str | None:
    review_payload = review_payload_object(payload)
    nested_test_id = text_or_none(review_payload.get("test_id")) if review_payload is not None else None
    return nested_test_id if nested_test_id is not None else text_or_none(payload.get("test_id"))


def review_payload_object(payload: JsonObject) -> JsonObject | None:
    match payload.get("review_payload"):
        case dict() as review_payload:
            return review_payload
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


def coverage_stats(targets: tuple[str, ...], payloads: tuple[JsonObject, ...]) -> CoverageStats:
    payload_ids = tuple(payload_test_id(payload) for payload in payloads)
    valid_ids = tuple(test_id for test_id in payload_ids if test_id is not None)
    unique_ids = unique_values(valid_ids)
    duplicate_count = sum(valid_ids.count(test_id) - 1 for test_id in unique_ids)
    missing_count = sum(1 for target in targets if target not in valid_ids)
    unexpected_count = sum(1 for test_id in unique_ids if test_id not in targets)
    missing_id_count = len(payload_ids) - len(valid_ids)
    ready = (
        len(payloads) == len(targets)
        and missing_count == 0
        and duplicate_count == 0
        and unexpected_count == 0
        and missing_id_count == 0
    )
    return CoverageStats(
        target_count=len(targets),
        evidence_file_count=len(payloads),
        covered_target_count=sum(1 for target in targets if target in valid_ids),
        missing_target_count=missing_count,
        duplicate_target_count=duplicate_count,
        unexpected_target_count=unexpected_count,
        missing_test_id_count=missing_id_count,
        target_coverage_ready=ready,
    )


def unique_values(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def coverage_probe_stats(targets: tuple[str, ...]) -> tuple[CoverageStats, ...]:
    if len(targets) != 4:
        raise ExtendedGateError("training pack target coverage probes require 4 targets")
    return (
        coverage_stats(targets, payloads_for_ids(targets)),
        coverage_stats(targets, payloads_for_ids((targets[0], targets[0], targets[1], targets[2]))),
        coverage_stats(targets, payloads_for_ids((targets[0], targets[1], targets[2], "unexpected_training_pack"))),
        coverage_stats(targets, payloads_for_ids(targets[:3])),
        coverage_stats(targets, (*payloads_for_ids(targets[:3]), {})),
    )


def payloads_for_ids(test_ids: tuple[str, ...]) -> tuple[JsonObject, ...]:
    return tuple({"review_payload": {"test_id": test_id}} for test_id in test_ids)


def stats_fields(stats: CoverageStats) -> JsonObject:
    return {
        "target_count": stats.target_count,
        "evidence_file_count": stats.evidence_file_count,
        "covered_target_count": stats.covered_target_count,
        "missing_target_count": stats.missing_target_count,
        "duplicate_target_count": stats.duplicate_target_count,
        "unexpected_target_count": stats.unexpected_target_count,
        "missing_test_id_count": stats.missing_test_id_count,
        "target_coverage_ready": stats.target_coverage_ready,
    }


def require_current_summary(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_USER_APPROVAL_REQUIRED",
        "status",
    )
    for key, value in current_integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("target_coverage_ready"), False, "target_coverage_ready")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def current_integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4), ("evidence_file_count", 0), ("covered_target_count", 0), ("missing_target_count", 4),
        ("duplicate_target_count", 0), ("unexpected_target_count", 0), ("missing_test_id_count", 0),
        ("coverage_probe_count", 5), ("coverage_probe_ready_count", 1), ("coverage_probe_blocked_count", 4),
        ("provider_call_count", 0), ("external_ocr_api_call_count", 0), ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0), ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Evidence Target Coverage",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- coverage: targets {output['target_count']}, files {output['evidence_file_count']}, covered {output['covered_target_count']}, missing {output['missing_target_count']}",
        f"- blocked inputs: duplicates {output['duplicate_target_count']}, unexpected {output['unexpected_target_count']}, missing test_id {output['missing_test_id_count']}",
        f"- probes: {output['coverage_probe_count']} total, {output['coverage_probe_ready_count']} ready, {output['coverage_probe_blocked_count']} blocked",
        f"- target coverage ready: {output['target_coverage_ready']}",
        f"- next status: `{output['next_status']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
