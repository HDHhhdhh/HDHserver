from __future__ import annotations

import sys
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dataclasses import dataclass
from typing import Final, assert_never

from tools.subjective_sheet_lab.ocr_review_schema import (
    DEFAULT_PROBLEM_COUNT,
    FINAL_SOURCES,
    JsonObject,
    JsonValue,
    QuestionNo,
    ReviewStatus,
    find_forbidden_answer_key_paths,
)
from tools.subjective_sheet_lab.ocr_erased_overwritten_policy import blocks_auto_grade_for_safety


@dataclass(frozen=True, slots=True)
class BridgeError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class FinalAnswerItem:
    question_no: QuestionNo
    final_answer: str
    source: str
    status: ReviewStatus


@dataclass(frozen=True, slots=True)
class BridgeResult:
    problem_count: int
    answers_text: str
    items: tuple[FinalAnswerItem, ...]


FINAL_BRIDGE_STATUSES: Final = frozenset(
    {
        ReviewStatus.SAFE_AUTO_GRADE,
        ReviewStatus.CONFIRMED,
        ReviewStatus.STUDENT_SELECTED_CANDIDATE,
        ReviewStatus.STUDENT_DIRECT_INPUT,
        ReviewStatus.SAFE_AUTO_GRADE_AFTER_RETAKE,
        ReviewStatus.STUDENT_SELECTED_CANDIDATE_AFTER_RETAKE,
        ReviewStatus.STUDENT_DIRECT_INPUT_AFTER_RETAKE,
    },
)


def convert_json_payload(raw: JsonValue) -> BridgeResult:
    if isinstance(raw, dict) and raw.get("schema") is not None:
        from tools.subjective_sheet_lab.ocr_review_payload_validator import validate_payload
        from tools.subjective_sheet_lab.ocr_review_schema import PayloadMode
        try:
            validate_payload(raw, PayloadMode.FINAL, "final_run")
        except Exception as exc:
            raise BridgeError(str(exc)) from exc
    leak_paths = find_forbidden_answer_key_paths(raw)
    if leak_paths:
        joined = ", ".join(leak_paths)
        raise BridgeError(f"payload contains student-forbidden answer key fields: {joined}")
    payload = require_object(raw, "payload")
    item_values = require_array(payload.get("items"), "payload.items")
    parsed_items = tuple(parse_item(item_value) for item_value in item_values)
    return convert_items(parsed_items, parse_problem_count(payload))


def convert_items(items: tuple[FinalAnswerItem, ...], problem_count: int) -> BridgeResult:
    if problem_count <= 0:
        raise BridgeError("problem_count must be positive")
    by_question: dict[int, FinalAnswerItem] = {}
    for item in items:
        question_no = int(item.question_no)
        if question_no < 1 or question_no > problem_count:
            raise BridgeError(f"question {question_no} is outside 1..{problem_count}")
        if question_no in by_question:
            raise BridgeError(f"question {question_no} is duplicated")
        by_question[question_no] = item
    missing = [str(no) for no in range(1, problem_count + 1) if no not in by_question]
    if missing:
        raise BridgeError(f"missing questions: {', '.join(missing)}")
    ordered = tuple(by_question[no] for no in range(1, problem_count + 1))
    return BridgeResult(problem_count, "\n".join(item.final_answer for item in ordered), ordered)


def parse_problem_count(payload: JsonObject) -> int:
    for key in ("problem_count", "problems"):
        value = payload.get(key)
        if value is not None:
            return parse_positive_int(value, key)
    return DEFAULT_PROBLEM_COUNT


def parse_item(value: JsonValue) -> FinalAnswerItem:
    item = require_object(value, "payload.items[]")
    question_no = QuestionNo(parse_positive_int(item.get("question_no"), "question_no"))
    status = parse_status(item.get("status"), question_no)
    ensure_status_is_final(status, question_no)
    warnings = parse_string_array(item.get("warnings"), question_no)
    if blocks_auto_grade_for_safety(status.value, warnings):
        raise BridgeError(f"question {int(question_no)} safe_auto_grade is blocked by erased/overwritten warning")
    return FinalAnswerItem(
        question_no,
        parse_final_answer(item.get("final_answer"), question_no),
        parse_source(item.get("source"), status, question_no),
        status,
    )


def ensure_status_is_final(status: ReviewStatus, question_no: QuestionNo) -> None:
    if status in FINAL_BRIDGE_STATUSES:
        return
    match status:
        case ReviewStatus.REVIEW_REQUIRED | ReviewStatus.RETAKE_REQUIRED | ReviewStatus.RETAKE_UPLOADED | ReviewStatus.DATA_CHECK_REQUIRED:
            raise BridgeError(f"question {int(question_no)} has unresolved status {status.value}")
        case unreachable:
            assert_never(unreachable)


def parse_status(value: JsonValue, question_no: QuestionNo) -> ReviewStatus:
    raw = require_string(value, f"question {int(question_no)} status")
    try:
        return ReviewStatus(raw)
    except ValueError as exc:
        raise BridgeError(f"question {int(question_no)} has unknown status {raw}") from exc


def parse_final_answer(value: JsonValue, question_no: QuestionNo) -> str:
    answer = require_string(value, f"question {int(question_no)} final_answer").strip()
    if not answer or "?" in answer:
        raise BridgeError(f"question {int(question_no)} final_answer is empty")
    if "\n" in answer or "\r" in answer:
        raise BridgeError(f"question {int(question_no)} final_answer contains a newline")
    return answer


def parse_string_array(value: JsonValue, question_no: QuestionNo) -> tuple[str, ...]:
    if value is None:
        return ()
    values = require_array(value, f"question {int(question_no)} warnings")
    out: list[str] = []
    for index, item in enumerate(values, start=1):
        text = require_string(item, f"question {int(question_no)} warnings[{index}]")
        if "\n" in text or "\r" in text:
            raise BridgeError(f"question {int(question_no)} warnings[{index}] contains a newline")
        out.append(text)
    return tuple(out)


def parse_source(value: JsonValue, status: ReviewStatus, question_no: QuestionNo) -> str:
    source = require_string(value, f"question {int(question_no)} source").strip()
    if source not in FINAL_SOURCES:
        raise BridgeError(f"question {int(question_no)} source {source} is not final")
    if status is ReviewStatus.SAFE_AUTO_GRADE and source != ReviewStatus.SAFE_AUTO_GRADE:
        raise BridgeError(f"question {int(question_no)} safe answer has mismatched source")
    return source


def parse_positive_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            parsed = value
        case str():
            try:
                parsed = int(value)
            except ValueError as exc:
                raise BridgeError(f"{label} must be an integer") from exc
        case None | bool() | float() | list() | dict():
            raise BridgeError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)
    if parsed <= 0:
        raise BridgeError(f"{label} must be positive")
    return parsed


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise BridgeError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise BridgeError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_string(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise BridgeError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)
