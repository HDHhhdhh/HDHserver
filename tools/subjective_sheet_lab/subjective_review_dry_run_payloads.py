from __future__ import annotations

import json
from typing import assert_never

from evaluate_ocr_result import ExpectedItem, RecognizedItem, evaluate
from ocr_review_schema import JsonValue
from subjective_review_dry_run_types import DryRunError, JsonObject


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise DryRunError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise DryRunError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_string(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise DryRunError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise DryRunError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def build_review_payload(payload: JsonObject) -> JsonObject:
    rows = evaluate(read_expected_items(payload), read_recognized_items(payload))
    retake_questions = frozenset(require_int(value, "retake_required_questions[]") for value in require_array(payload.get("retake_required_questions"), "retake_required_questions"))
    items: list[JsonValue] = []
    for row in rows:
        status = "retake_required" if row.question in retake_questions else row.review_policy
        items.append({
            "question_no": row.question,
            "status": status,
            "recognized": row.recognized,
            "warnings": list(row.warnings),
            "candidates": [],
            "final_answer": row.recognized if status == "safe_auto_grade" else None,
            "source": "safe_auto_grade" if status == "safe_auto_grade" else None,
        })
    return {
        "source": "local_dry_run_review_payload",
        "test_id": require_string(payload.get("test_id"), "test_id"),
        "round": require_string(payload.get("round"), "round"),
        "problem_count": require_int(payload.get("problem_count"), "problem_count"),
        "items": items,
    }


def read_expected_items(payload: JsonObject) -> tuple[ExpectedItem, ...]:
    rows: list[ExpectedItem] = []
    for index, value in enumerate(require_array(payload.get("expected_items"), "expected_items"), start=1):
        item = require_object(value, f"expected_items[{index}]")
        expected = require_string(item.get("expected"), f"expected_items[{index}].expected")
        question = require_int(item.get("question"), f"expected_items[{index}].question")
        rows.append(ExpectedItem(question, expected, (expected,)))
    return tuple(rows)


def read_recognized_items(payload: JsonObject) -> tuple[RecognizedItem, ...]:
    rows: list[RecognizedItem] = []
    for index, value in enumerate(require_array(payload.get("recognized_items"), "recognized_items"), start=1):
        item = require_object(value, f"recognized_items[{index}]")
        rows.append(
            RecognizedItem(
                require_int(item.get("question"), f"recognized_items[{index}].question"),
                require_string(item.get("recognized"), f"recognized_items[{index}].recognized"),
                read_warnings(item),
            ),
        )
    return tuple(rows)


def read_warnings(item: JsonObject) -> tuple[str, ...]:
    raw = item.get("warnings")
    if raw is None:
        return ()
    return tuple(require_string(value, "warning") for value in require_array(raw, "warnings"))


def clone_json_object(payload: JsonObject) -> JsonObject:
    return require_object(json.loads(json.dumps(payload, ensure_ascii=False)), "cloned payload")


def item_objects(payload: JsonObject) -> tuple[JsonObject, ...]:
    return tuple(require_object(value, "payload item") for value in require_array(payload.get("items"), "payload.items"))
