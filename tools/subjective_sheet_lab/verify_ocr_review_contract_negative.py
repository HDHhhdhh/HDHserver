# /// script
# requires-python = ">=3.11"
# ///
#
# --- How to run ---
# python tools/subjective_sheet_lab/verify_ocr_review_contract_negative.py

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

from validate_ocr_review_contract import (
    ContractError,
    JsonObject,
    JsonValue,
    PayloadMode,
    ROOT,
    require_array,
    require_object,
    require_string,
    validate_payload,
)
from ocr_erased_overwritten_policy import SAFETY_WARNING_CODES


@dataclass(frozen=True, slots=True)
class NegativeCase:
    name: str
    payload: JsonObject
    mode: PayloadMode
    expected_error: str


def clone(value: JsonValue) -> JsonValue:
    return json.loads(json.dumps(value, ensure_ascii=False))


def load_base_payload() -> JsonObject:
    raw = require_object(read_json_file("final_review_payload_bridge_fixture.json"), "fixture")
    return require_object(clone(raw.get("valid_payload")), "fixture.valid_payload")


def read_json_file(name: str) -> JsonValue:
    return json.loads((ROOT / name).read_text(encoding="utf-8-sig"))


def items(payload: JsonObject) -> list[JsonObject]:
    value = payload.get("items")
    if not isinstance(value, list):
        raise AssertionError("base payload items must be a list")
    return [require_object(item, "base item") for item in value]


def item_by_question(payload: JsonObject, question_no: int) -> JsonObject:
    for item in items(payload):
        if item.get("question_no") == question_no:
            return item
    raise AssertionError(f"question {question_no} not found in base payload")


def mutate_item(question_no: int, updates: JsonObject) -> JsonObject:
    payload = load_base_payload()
    item_by_question(payload, question_no).update(updates)
    return payload


def without_question(question_no: int) -> JsonObject:
    payload = load_base_payload()
    payload["items"] = [item for item in items(payload) if item.get("question_no") != question_no]
    return payload


def with_extra_question() -> JsonObject:
    payload = load_base_payload()
    extra = require_object(clone(item_by_question(payload, 20)), "extra")
    extra["question_no"] = 21
    require_array(payload.get("items"), "payload.items").append(extra)
    return payload


def with_problem_count(problem_count: int) -> JsonObject:
    payload = load_base_payload()
    payload["problem_count"] = problem_count
    return payload


def with_duplicate_question() -> JsonObject:
    payload = load_base_payload()
    duplicate = require_object(clone(item_by_question(payload, 1)), "duplicate")
    require_array(payload.get("items"), "payload.items").append(duplicate)
    return payload


def with_leak(field_name: str) -> JsonObject:
    payload = load_base_payload()
    item_by_question(payload, 1)[field_name] = "leaked"
    return payload


def with_safe_auto_warning(warning_code: str) -> JsonObject:
    return mutate_item(
        1,
        {
            "status": "safe_auto_grade",
            "source": "safe_auto_grade",
            "final_answer": "1",
            "warnings": [warning_code],
        },
    )


def with_warning_newline() -> JsonObject:
    return mutate_item(1, {"warnings": ["erased_trace_detected\nsecond line"]})


def with_candidate_newline() -> JsonObject:
    return mutate_item(1, {"candidates": ["1\n2"]})


def negative_cases() -> tuple[NegativeCase, ...]:
    cases = [
        NegativeCase("fewer_than_20_questions", without_question(20), PayloadMode.FINAL, "missing questions"),
        NegativeCase("more_than_20_questions", with_extra_question(), PayloadMode.FINAL, "outside 1..20"),
        NegativeCase("problem_count_less_than_20", with_problem_count(19), PayloadMode.FINAL, "problem_count must be 20"),
        NegativeCase("problem_count_more_than_20", with_problem_count(21), PayloadMode.FINAL, "problem_count must be 20"),
        NegativeCase("duplicate_question_no", with_duplicate_question(), PayloadMode.FINAL, "duplicated"),
        NegativeCase("missing_question_no", mutate_item(1, {"question_no": None}), PayloadMode.FINAL, "question_no must be"),
        NegativeCase("question_no_outside_1_20", mutate_item(1, {"question_no": 21}), PayloadMode.FINAL, "outside 1..20"),
        NegativeCase("invalid_status", mutate_item(1, {"status": "bogus_status"}), PayloadMode.FINAL, "unknown status"),
        NegativeCase("invalid_source", mutate_item(1, {"source": "bogus_source"}), PayloadMode.FINAL, "unknown source"),
        NegativeCase("safe_auto_grade_without_final_answer", mutate_item(1, {"final_answer": None}), PayloadMode.FINAL, "final_answer is required"),
        NegativeCase("confirmed_student_source_without_final_answer", mutate_item(4, {"final_answer": None}), PayloadMode.FINAL, "final_answer is required"),
        NegativeCase("review_required_reaches_final_bridge", unresolved("review_required"), PayloadMode.FINAL, "unresolved status review_required"),
        NegativeCase("retake_required_reaches_final_bridge", unresolved("retake_required"), PayloadMode.FINAL, "unresolved status retake_required"),
        NegativeCase("retake_uploaded_reaches_final_bridge", retake_uploaded(), PayloadMode.FINAL, "unresolved status retake_uploaded"),
        NegativeCase("data_check_required_reaches_final_bridge", unresolved("data_check_required"), PayloadMode.FINAL, "unresolved status data_check_required"),
        NegativeCase("warning_newline_blocked", with_warning_newline(), PayloadMode.REVIEW, "single line"),
        NegativeCase("candidate_newline_blocked", with_candidate_newline(), PayloadMode.REVIEW, "single line"),
    ]
    cases.extend(
        NegativeCase(
            f"{warning_code}_blocks_safe_auto_grade",
            with_safe_auto_warning(warning_code),
            PayloadMode.REVIEW,
            "blocked by erased/overwritten warning",
        )
        for warning_code in sorted(SAFETY_WARNING_CODES)
    )
    cases.extend(
        NegativeCase(f"{field_name}_leakage", with_leak(field_name), PayloadMode.REVIEW, "leaks answer-key fields")
        for field_name in ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct")
    )
    return tuple(cases)


def unresolved(status: str) -> JsonObject:
    return mutate_item(1, {"status": status, "source": None, "final_answer": None})


def retake_uploaded() -> JsonObject:
    return mutate_item(1, {"status": "retake_uploaded", "source": "retake_uploaded", "final_answer": None})


def assert_rejected(case: NegativeCase) -> None:
    try:
        validate_payload(case.payload, case.mode, case.name)
    except ContractError as exc:
        if case.expected_error not in str(exc):
            raise AssertionError(f"{case.name}: expected {case.expected_error!r}, got {exc!s}") from exc
        return
    raise AssertionError(f"{case.name}: payload was accepted")


def assert_shuffled_order() -> None:
    raw = require_object(read_json_file("final_review_payload_bridge_fixture.json"), "fixture")
    payload = require_object(clone(raw.get("valid_payload")), "fixture.valid_payload")
    answers_text = validate_payload(payload, PayloadMode.FINAL, "shuffled_order")
    expected = require_string(raw.get("golden_answers_text"), "fixture.golden_answers_text")
    if answers_text != expected:
        raise AssertionError("shuffled input order did not produce 1..20 answersText")


def main() -> int:
    passed: list[str] = []
    for case in negative_cases():
        assert_rejected(case)
        passed.append(case.name)
    assert_shuffled_order()
    print(f"ok: rejected {len(passed)} malformed OCR review payloads")
    print("ok: shuffled final payload still emits answersText in 1..20 order")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
