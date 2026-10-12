from __future__ import annotations

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

SENSITIVE_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)


@dataclass(frozen=True, slots=True)
class EvidenceFile:
    name: str
    test_id: str | None


@dataclass(frozen=True, slots=True)
class TargetRow:
    test_id: str
    required_file_name: str
    evidence_present: bool


def evidence_files(evidence_dir: Path) -> tuple[EvidenceFile, ...]:
    files = sorted(evidence_dir.glob("*.json")) if evidence_dir.exists() else []
    return tuple(EvidenceFile(name=path.name, test_id=payload_test_id(read_json_object(path))) for path in files)


def target_diff_summary(source: JsonObject, evidence: tuple[EvidenceFile, ...]) -> JsonObject:
    require_text_value(
        source.get("status"),
        "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING",
        "source.status",
    )
    targets = target_test_ids(source)
    rows = tuple(target_row(test_id, evidence) for test_id in targets)
    present_ids = tuple(item.test_id for item in evidence if item.test_id is not None)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_USER_APPROVAL_REQUIRED",
        "target_count": len(targets),
        "target_row_count": len(rows),
        "evidence_file_count": len(evidence),
        "covered_target_count": sum(1 for row in rows if row.evidence_present),
        "missing_target_count": sum(1 for row in rows if not row.evidence_present),
        "duplicate_evidence_target_count": duplicate_count(present_ids),
        "unexpected_evidence_target_count": sum(1 for test_id in unique_values(present_ids) if test_id not in targets),
        "missing_test_id_file_count": sum(1 for item in evidence if item.test_id is None),
        "target_diff_ready": False,
        "target_rows": [target_row_fields(row) for row in rows],
        "next_status": "USER_APPROVAL_REQUIRED",
        "required_next_artifact": "four_target-named_recognized_evidence_payload_files",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "sensitive_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    output["sensitive_field_leak_count"] = sensitive_leak_count(output)
    output["filesystem_path_leak_count"] = filesystem_path_leak_count(output)
    return output


def target_test_ids(source: JsonObject) -> tuple[str, ...]:
    match source.get("targets"):
        case list() as targets:
            return tuple(target_test_id(target) for target in targets)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("source.targets must be a list")
        case unreachable:
            assert_never(unreachable)


def target_test_id(value: JsonValue) -> str:
    match value:
        case dict() as payload:
            test_id = payload.get("test_id")
            if isinstance(test_id, str):
                return test_id
            raise ExtendedGateError("target.test_id must be text")
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("target must be a mapping")
        case unreachable:
            assert_never(unreachable)


def payload_test_id(payload: JsonObject) -> str | None:
    review_payload = payload.get("review_payload")
    match review_payload:
        case dict() as nested:
            return text_or_none(nested.get("test_id"))
        case None | bool() | int() | float() | str() | list():
            return text_or_none(payload.get("test_id"))
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


def target_row(test_id: str, evidence: tuple[EvidenceFile, ...]) -> TargetRow:
    return TargetRow(
        test_id=test_id,
        required_file_name=f"{test_id}_recognized_evidence.json",
        evidence_present=any(item.test_id == test_id for item in evidence),
    )


def target_row_fields(row: TargetRow) -> JsonObject:
    return {
        "test_id": row.test_id,
        "required_file_name": row.required_file_name,
        "evidence_present": row.evidence_present,
        "coverage_status": "covered" if row.evidence_present else "missing",
        "next_action": "keep_payload" if row.evidence_present else "add_recognized_evidence_payload",
    }


def unique_values(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def duplicate_count(values: tuple[str, ...]) -> int:
    return sum(values.count(value) - 1 for value in unique_values(values))


def sensitive_leak_count(value: JsonValue) -> int:
    match value:
        case dict() as payload:
            key_count = sum(1 for key in payload if key in SENSITIVE_TOKENS)
            return key_count + sum(sensitive_leak_count(nested) for nested in payload.values())
        case list() as payload:
            return sum(sensitive_leak_count(nested) for nested in payload)
        case str() as text:
            return 1 if text in SENSITIVE_TOKENS else 0
        case None | bool() | int() | float():
            return 0
        case unreachable:
            assert_never(unreachable)


def filesystem_path_leak_count(value: JsonValue) -> int:
    match value:
        case dict() as payload:
            return sum(filesystem_path_leak_count(nested) for nested in payload.values())
        case list() as payload:
            return sum(filesystem_path_leak_count(nested) for nested in payload)
        case str() as text:
            return text.count("C:\\") + text.count("C:/") + text.count("/c/")
        case None | bool() | int() | float():
            return 0
        case unreachable:
            assert_never(unreachable)


def require_target_diff_summary(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_USER_APPROVAL_REQUIRED",
        "status",
    )
    for key, value in integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("target_diff_ready"), False, "target_diff_ready")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4), ("target_row_count", 4), ("evidence_file_count", 0),
        ("covered_target_count", 0), ("missing_target_count", 4), ("duplicate_evidence_target_count", 0),
        ("unexpected_evidence_target_count", 0), ("missing_test_id_file_count", 0), ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0), ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("sensitive_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )
