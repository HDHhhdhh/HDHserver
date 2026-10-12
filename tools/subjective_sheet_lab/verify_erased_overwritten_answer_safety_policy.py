from __future__ import annotations

from copy import deepcopy
from typing import Final

from ocr_answers_text_bridge import BridgeError, convert_json_payload
from ocr_erased_overwritten_policy import RETAKE_WARNING_CODES, SAFETY_WARNING_CODES, normalize_review_item_for_safety
from ocr_review_payload_validator import ContractError, validate_payload
from ocr_review_schema import JsonObject, PayloadMode

TEST_ID: Final = "t_unit_daesu_01_lv3_r1"


def final_item(question_no: int) -> JsonObject:
    answer = str((question_no % 5) + 1)
    return {
        "question_no": question_no,
        "status": "safe_auto_grade",
        "recognized": answer,
        "warnings": [],
        "candidates": [],
        "final_answer": answer,
        "source": "safe_auto_grade",
    }


def final_payload() -> JsonObject:
    return {
        "test_id": TEST_ID,
        "round": "1",
        "problem_count": 20,
        "items": [final_item(question_no) for question_no in range(1, 21)],
    }


def assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_contract_rejects(payload: JsonObject, expected: str) -> None:
    try:
        validate_payload(payload, PayloadMode.REVIEW, "erased_policy")
    except ContractError as exc:
        if expected not in str(exc):
            raise AssertionError(f"expected {expected!r}, got {exc!s}") from exc
        return
    raise AssertionError("contract accepted unsafe auto-grade payload")


def assert_bridge_rejects(payload: JsonObject, expected: str) -> None:
    try:
        convert_json_payload(payload)
    except BridgeError as exc:
        if expected not in str(exc):
            raise AssertionError(f"expected {expected!r}, got {exc!s}") from exc
        return
    raise AssertionError("bridge accepted unsafe auto-grade payload")


def assert_warning_downgrades(warning_code: str) -> None:
    item = final_item(1)
    item["warnings"] = [warning_code]
    normalized = normalize_review_item_for_safety(item)
    expected_status = "retake_required" if warning_code in RETAKE_WARNING_CODES else "review_required"
    assert_equal(normalized["status"], expected_status, f"{warning_code} status")
    assert_equal(normalized["source"], None, f"{warning_code} source")
    assert_equal(normalized["final_answer"], None, f"{warning_code} final_answer")


def assert_unclear_without_candidate_requires_retake() -> None:
    item = final_item(1)
    item["warnings"] = ["unclear_final_answer"]
    item["recognized"] = "?"
    item["final_answer"] = "?"
    item["candidates"] = []
    normalized = normalize_review_item_for_safety(item)
    assert_equal(normalized["status"], "retake_required", "no-candidate unclear status")


def assert_unclear_with_candidate_stays_reviewable() -> None:
    item = final_item(1)
    item["warnings"] = ["unclear_final_answer"]
    item["recognized"] = "?"
    item["final_answer"] = "?"
    item["candidates"] = ["2"]
    normalized = normalize_review_item_for_safety(item)
    assert_equal(normalized["status"], "review_required", "candidate unclear status")


def assert_clean_auto_grade_still_passes() -> None:
    payload = final_payload()
    answers_text = convert_json_payload(payload).answers_text
    lines = answers_text.splitlines()
    assert_equal(len(lines), 20, "answersText line count")
    if not all(line.strip() for line in lines):
        raise AssertionError("answersText contains empty lines")
    validate_payload(payload, PayloadMode.FINAL, "clean_auto_grade")


def assert_contract_and_bridge_reject_warning(warning_code: str) -> None:
    payload = final_payload()
    unsafe = deepcopy(payload)
    first = unsafe["items"][0]
    if not isinstance(first, dict):
        raise AssertionError("fixture item must be an object")
    first["warnings"] = [warning_code]
    assert_contract_rejects(unsafe, "blocked by erased/overwritten warning")
    assert_bridge_rejects(unsafe, "blocked by erased/overwritten warning")


def main() -> int:
    for warning_code in sorted(SAFETY_WARNING_CODES):
        assert_warning_downgrades(warning_code)
        assert_contract_and_bridge_reject_warning(warning_code)
    assert_unclear_without_candidate_requires_retake()
    assert_unclear_with_candidate_stays_reviewable()
    assert_clean_auto_grade_still_passes()
    print("ok: erased/overwritten warnings downgrade safe auto-grade")
    print("ok: unsafe auto-grade is rejected by contract and answersText bridge")
    print("ok: clean safe auto-grade still produces 20 non-empty answersText lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
