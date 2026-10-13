from __future__ import annotations

from typing import Final

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue

TEST_ID: Final[str] = "t_training_pack_mijeok1_non_frequent_r1"


def synthetic_probe_payloads() -> list[JsonObject]:
    return [
        valid_payload(),
        with_forbidden_field(),
        with_filesystem_path(),
        short_payload(),
        duplicate_question_payload(),
        with_missing_status(),
        with_invalid_status(),
        with_safe_auto_grade_status(),
        with_non_text_recognized_answer(),
        with_blank_recognized_answer(),
    ]


def valid_payload() -> JsonObject:
    return payload_with_items(base_items())


def with_forbidden_field() -> JsonObject:
    items = base_items()
    items[0]["canonical_answer"] = "1"
    return payload_with_items(items)


def with_filesystem_path() -> JsonObject:
    items = base_items()
    items[0]["note"] = "C:/server/internal-artifact.png"
    return payload_with_items(items)


def short_payload() -> JsonObject:
    return payload_with_items(base_items()[:19])


def duplicate_question_payload() -> JsonObject:
    items = base_items()
    items[19]["question_no"] = 1
    return payload_with_items(items)


def with_missing_status() -> JsonObject:
    items = base_items()
    del items[0]["status"]
    return payload_with_items(items)


def with_invalid_status() -> JsonObject:
    items = base_items()
    items[0]["status"] = "completed_recognized"
    return payload_with_items(items)


def with_safe_auto_grade_status() -> JsonObject:
    items = base_items()
    items[0]["status"] = "safe_auto_grade"
    return payload_with_items(items)


def with_non_text_recognized_answer() -> JsonObject:
    items = base_items()
    items[0]["recognized"] = 1
    return payload_with_items(items)


def with_blank_recognized_answer() -> JsonObject:
    items = base_items()
    items[0]["recognized"] = ""
    return payload_with_items(items)


def base_items() -> list[JsonObject]:
    return [
        {
            "question_no": question_no,
            "status": "review_required",
            "recognized": "1",
        }
        for question_no in range(1, 21)
    ]


def payload_with_items(items: list[JsonObject]) -> JsonObject:
    payload_items: JsonValue = items
    return {
        "review_payload": {
            "test_id": TEST_ID,
            "round": "1",
            "problem_count": 20,
            "items": payload_items,
        }
    }
