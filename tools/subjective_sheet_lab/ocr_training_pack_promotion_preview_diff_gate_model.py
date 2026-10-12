from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_recognized_evidence_example_shape import example_payload


@dataclass(frozen=True, slots=True)
class PreviewRow:
    test_id: str
    file_name: str
    question_count: int
    sequence: str
    row_hash: str


@dataclass(frozen=True, slots=True)
class PayloadDiff:
    test_id: str
    file_name: str
    question_count: int
    sequence: str
    preview_row_hash: str
    payload_hash: str
    matched: bool


def diff_summary(preview: JsonObject, replay: JsonObject) -> JsonObject:
    require_text_value(
        preview.get("status"),
        "TRAINING_PACK_PROMOTION_PREVIEW_USER_APPROVAL_REQUIRED",
        "preview.status",
    )
    require_text_value(
        replay.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED",
        "replay.status",
    )
    rows = preview_rows(preview)
    simulated = tuple(simulated_diff(row) for row in rows)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_PROMOTION_PREVIEW_DIFF_USER_APPROVAL_REQUIRED",
        "preview_row_count": len(rows),
        "actual_payload_count": replay.get("evidence_file_count"),
        "actual_preview_match_count": replay.get("accepted_file_count"),
        "actual_missing_preview_count": replay.get("missing_required_file_count"),
        "simulated_payload_count": len(simulated),
        "simulated_preview_match_count": sum(1 for row in simulated if row.matched),
        "simulated_preview_mismatch_count": sum(1 for row in simulated if not row.matched),
        "simulated_question_count_total": sum(row.question_count for row in simulated),
        "current_diff_ready": False,
        "post_file_diff_ready": True,
        "promotion_write_attempted": False,
        "preview_manifest_hash": preview.get("preview_manifest_hash"),
        "simulated_payload_manifest_hash": payload_manifest_hash(simulated),
        "diff_rows": [diff_fields(row) for row in simulated],
        "next_status": "USER_APPROVAL_REQUIRED",
        "next_safe_action": "collect_four_target_named_contract_valid_payload_files_with_user_approval",
        "required_next_artifact": "four_target_named_contract_valid_payload_files",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def preview_rows(preview: JsonObject) -> tuple[PreviewRow, ...]:
    match preview.get("preview_rows"):
        case list() as rows:
            return tuple(preview_row(row) for row in rows)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("preview.preview_rows must be a list")
        case unreachable:
            assert_never(unreachable)


def preview_row(value: JsonValue) -> PreviewRow:
    match value:
        case dict() as row:
            return PreviewRow(
                test_id=text_field(row.get("test_id"), "test_id"),
                file_name=text_field(row.get("file_name"), "file_name"),
                question_count=int_field(row.get("question_count"), "question_count"),
                sequence=text_field(row.get("sequence"), "sequence"),
                row_hash=text_field(row.get("row_hash"), "row_hash"),
            )
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("preview row must be a mapping")
        case unreachable:
            assert_never(unreachable)


def simulated_diff(row: PreviewRow) -> PayloadDiff:
    payload = example_payload(row.test_id)
    question_count = payload_question_count(payload)
    sequence = payload_sequence(payload)
    return PayloadDiff(
        test_id=row.test_id,
        file_name=row.file_name,
        question_count=question_count,
        sequence=sequence,
        preview_row_hash=row.row_hash,
        payload_hash=payload_hash(payload),
        matched=question_count == row.question_count and sequence == row.sequence,
    )


def payload_question_count(payload: JsonObject) -> int:
    review_payload = review_payload_object(payload)
    return int_field(review_payload.get("problem_count"), "review_payload.problem_count")


def payload_sequence(payload: JsonObject) -> str:
    items = review_items(payload)
    sequence = tuple(question_no(item) for item in items)
    if sequence == tuple(range(1, 21)):
        return "1..20"
    return "non_contiguous"


def review_payload_object(payload: JsonObject) -> JsonObject:
    match payload.get("review_payload"):
        case dict() as review_payload:
            return review_payload
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("review_payload must be a mapping")
        case unreachable:
            assert_never(unreachable)


def review_items(payload: JsonObject) -> tuple[JsonObject, ...]:
    match review_payload_object(payload).get("items"):
        case list() as items:
            return tuple(item for item in items if isinstance(item, dict))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("review_payload.items must be a list")
        case unreachable:
            assert_never(unreachable)


def question_no(item: JsonObject) -> int:
    return int_field(item.get("question_no"), "question_no")


def payload_hash(payload: JsonObject) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def payload_manifest_hash(rows: tuple[PayloadDiff, ...]) -> str:
    return hashlib.sha256(json.dumps([diff_fields(row) for row in rows], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def text_field(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def int_field(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise ExtendedGateError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def diff_fields(row: PayloadDiff) -> JsonObject:
    return {
        "test_id": row.test_id,
        "file_name": row.file_name,
        "question_count": row.question_count,
        "sequence": row.sequence,
        "preview_row_hash": row.preview_row_hash,
        "payload_hash": row.payload_hash,
        "matched": row.matched,
    }


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_PROMOTION_PREVIEW_DIFF_USER_APPROVAL_REQUIRED", "status")
    for key, value in integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("current_diff_ready"), False, "current_diff_ready")
    require_bool_value(output.get("post_file_diff_ready"), True, "post_file_diff_ready")
    require_bool_value(output.get("promotion_write_attempted"), False, "promotion_write_attempted")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(
        output.get("next_safe_action"),
        "collect_four_target_named_contract_valid_payload_files_with_user_approval",
        "next_safe_action",
    )


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("preview_row_count", 4),
        ("actual_payload_count", 0),
        ("actual_preview_match_count", 0),
        ("actual_missing_preview_count", 4),
        ("simulated_payload_count", 4),
        ("simulated_preview_match_count", 4),
        ("simulated_preview_mismatch_count", 0),
        ("simulated_question_count_total", 80),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Promotion Preview Diff Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- submit route calls: 0",
        "- submit button clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- preview rows: {output['preview_row_count']}",
        f"- actual payloads: {output['actual_payload_count']}",
        f"- actual preview matches: {output['actual_preview_match_count']}",
        f"- actual missing preview rows: {output['actual_missing_preview_count']}",
        f"- simulated preview matches: {output['simulated_preview_match_count']}",
        f"- simulated preview mismatches: {output['simulated_preview_mismatch_count']}",
        f"- current diff ready: {output['current_diff_ready']}",
        f"- post-file diff ready: {output['post_file_diff_ready']}",
        f"- promotion write attempted: {output['promotion_write_attempted']}",
        f"- preview manifest hash: `{output['preview_manifest_hash']}`",
        f"- simulated payload manifest hash: `{output['simulated_payload_manifest_hash']}`",
        f"- next status: `{output['next_status']}`",
        f"- next safe action: `{output['next_safe_action']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)
