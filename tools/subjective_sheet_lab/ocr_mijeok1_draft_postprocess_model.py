from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, TypeAlias, assert_never

from ocr_answer_mode_policy import answer_mode_auto_grade_warning

TARGET_TEST_ID: Final[str] = "t_unit_mijeok1_01_lv3_r1"
SIMPLE_FINAL_ANSWER_RE: Final[re.Pattern[str]] = re.compile(r"^[-+]?\d+(?:/\d+|\.\d+)?$")
MULTIPLE_NUMERIC_ANSWER_RE: Final[re.Pattern[str]] = re.compile(r"^[-+]?\d+(?:/\d+|\.\d+)?\s*,\s*[-+]?\d+")
UNCLEAR_TEXTS: Final[frozenset[str]] = frozenset(("", "?", "??", "unknown", "unclear"))
CHOICE_NUMBER_VALUES: Final[frozenset[str]] = frozenset(("1", "2", "3", "4", "5"))
CHOICE_INVALID_SAMPLES: Final[tuple[str, ...]] = ("12", "x=2", "3sqrt(2)", "1,3", "1/2,9/2", "?", "n")
ANSWER_VALUE_VALID_SAMPLES: Final[tuple[str, ...]] = ("12", "1/2", "-3")
ANSWER_VALUE_INVALID_SAMPLES: Final[tuple[str, ...]] = (
    "?",
    "unknown",
    "1,3",
    "1/2,9/2",
    "x=2",
    "3sqrt(2)",
    "12\n13",
    "y->3",
    "y→3",
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class AnswerMode(StrEnum):
    CHOICE_NUMBER = "choice_number"
    ANSWER_VALUE = "answer_value"


@dataclass(frozen=True, slots=True)
class DraftPostprocessError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class Outcome:
    status: str
    warning: str | None


@dataclass(frozen=True, slots=True)
class VerificationSummary:
    choice_question_count: int
    answer_value_question_count: int
    valid_choice_safe_count: int
    invalid_choice_blocked_count: int
    valid_answer_value_safe_count: int
    invalid_answer_value_blocked_count: int
    current_runtime_gap_count: int


def summary_to_json(summary: VerificationSummary) -> JsonObject:
    return {
        "choice_question_count": summary.choice_question_count,
        "answer_value_question_count": summary.answer_value_question_count,
        "valid_choice_safe_count": summary.valid_choice_safe_count,
        "invalid_choice_blocked_count": summary.invalid_choice_blocked_count,
        "valid_answer_value_safe_count": summary.valid_answer_value_safe_count,
        "invalid_answer_value_blocked_count": summary.invalid_answer_value_blocked_count,
        "current_runtime_gap_count": summary.current_runtime_gap_count,
    }


def modes_from_draft(draft: JsonObject) -> dict[int, AnswerMode]:
    tests = require_array(draft.get("tests"), "draft.tests")
    for raw_test in tests:
        test = require_object(raw_test, "draft.tests[]")
        if require_string(test.get("test_id"), "test_id") == TARGET_TEST_ID:
            return modes_from_test(test)
    raise DraftPostprocessError(f"missing draft target: {TARGET_TEST_ID}")


def modes_from_test(test: JsonObject) -> dict[int, AnswerMode]:
    modes: dict[int, AnswerMode] = {}
    for question_no in question_numbers(test.get("choice_number_questions"), "choice_number_questions"):
        modes[question_no] = AnswerMode.CHOICE_NUMBER
    for question_no in question_numbers(test.get("answer_value_questions"), "answer_value_questions"):
        if question_no in modes:
            raise DraftPostprocessError(f"question {question_no} has duplicate modes")
        modes[question_no] = AnswerMode.ANSWER_VALUE
    if set(modes) != set(range(1, 21)):
        raise DraftPostprocessError("target draft must cover q001-q020")
    return modes


def verify_modes(modes: dict[int, AnswerMode]) -> VerificationSummary:
    choice_questions = tuple(question_no for question_no, mode in sorted(modes.items()) if mode is AnswerMode.CHOICE_NUMBER)
    value_questions = tuple(question_no for question_no, mode in sorted(modes.items()) if mode is AnswerMode.ANSWER_VALUE)
    valid_choice_safe = verify_valid_choice_answers(choice_questions)
    invalid_choice_blocked = verify_invalid_choice_answers(choice_questions)
    valid_value_safe = verify_valid_answer_values(value_questions)
    invalid_value_blocked = verify_invalid_answer_values(value_questions)
    runtime_gaps = verify_current_runtime_gap(choice_questions)
    return VerificationSummary(
        choice_question_count=len(choice_questions),
        answer_value_question_count=len(value_questions),
        valid_choice_safe_count=valid_choice_safe,
        invalid_choice_blocked_count=invalid_choice_blocked,
        valid_answer_value_safe_count=valid_value_safe,
        invalid_answer_value_blocked_count=invalid_value_blocked,
        current_runtime_gap_count=runtime_gaps,
    )


def verify_valid_choice_answers(choice_questions: tuple[int, ...]) -> int:
    count = 0
    for question_no in choice_questions:
        for answer in CHOICE_NUMBER_VALUES:
            assert_safe(question_no, AnswerMode.CHOICE_NUMBER, answer)
            count += 1
    return count


def verify_invalid_choice_answers(choice_questions: tuple[int, ...]) -> int:
    count = 0
    for question_no in choice_questions:
        for answer in CHOICE_INVALID_SAMPLES:
            assert_blocked(question_no, AnswerMode.CHOICE_NUMBER, answer)
            count += 1
    return count


def verify_valid_answer_values(value_questions: tuple[int, ...]) -> int:
    count = 0
    for question_no in value_questions:
        for answer in ANSWER_VALUE_VALID_SAMPLES:
            assert_safe(question_no, AnswerMode.ANSWER_VALUE, answer)
            count += 1
    return count


def verify_invalid_answer_values(value_questions: tuple[int, ...]) -> int:
    count = 0
    for question_no in value_questions:
        for answer in ANSWER_VALUE_INVALID_SAMPLES:
            assert_blocked(question_no, AnswerMode.ANSWER_VALUE, answer)
            count += 1
    return count


def verify_current_runtime_gap(choice_questions: tuple[int, ...]) -> int:
    gaps = 0
    for question_no in choice_questions:
        current_warning = answer_mode_auto_grade_warning(question_no, "12", TARGET_TEST_ID)
        draft_warning = warning_for_answer(AnswerMode.CHOICE_NUMBER, "12")
        if current_warning is None and draft_warning is not None:
            gaps += 1
    if gaps != len(choice_questions):
        raise DraftPostprocessError(f"expected every choice question to expose current runtime gap, got {gaps}")
    return gaps


def assert_safe(question_no: int, mode: AnswerMode, answer: str) -> None:
    outcome = classify_answer(mode, answer)
    if outcome.status != "safe_auto_grade":
        raise DraftPostprocessError(f"q{question_no:03d} should be safe for {mode.value}: {answer}")


def assert_blocked(question_no: int, mode: AnswerMode, answer: str) -> None:
    outcome = classify_answer(mode, answer)
    if outcome.status != "review_required" or outcome.warning is None:
        raise DraftPostprocessError(f"q{question_no:03d} should be review_required for {mode.value}: {answer}")


def classify_answer(mode: AnswerMode, answer: str) -> Outcome:
    warning = warning_for_answer(mode, answer)
    if warning is None:
        return Outcome("safe_auto_grade", None)
    return Outcome("review_required", warning)


def warning_for_answer(mode: AnswerMode, answer: str) -> str | None:
    normalized = answer.strip()
    if normalized.lower() in UNCLEAR_TEXTS:
        return "unclear_final_answer"
    if "\n" in answer or "\r" in answer:
        return "multiple_answer_candidates"
    match mode:
        case AnswerMode.CHOICE_NUMBER:
            return None if normalized in CHOICE_NUMBER_VALUES else "choice_number_invalid_for_auto_grade"
        case AnswerMode.ANSWER_VALUE:
            return answer_value_warning(normalized)
        case unreachable:
            assert_never(unreachable)


def answer_value_warning(normalized: str) -> str | None:
    if MULTIPLE_NUMERIC_ANSWER_RE.match(normalized):
        return "multiple_answer_candidates"
    if relation_or_operator_confusion(normalized):
        return "expression_operator_confusion"
    if contains_letter(normalized):
        return "answer_value_letter_confusion"
    return None if SIMPLE_FINAL_ANSWER_RE.match(normalized) is not None else "unclear_final_answer"


def relation_or_operator_confusion(value: str) -> bool:
    return any(token in value for token in ("->", "→", "=>", "=", "<", "<=", ">", ">="))


def contains_letter(value: str) -> bool:
    return any(character.isalpha() for character in value)


def question_numbers(value: JsonValue, label: str) -> tuple[int, ...]:
    raw_questions = require_array(value, label)
    questions: list[int] = []
    for index, raw_question in enumerate(raw_questions, start=1):
        question_no = require_int(raw_question, f"{label}[{index}]")
        if question_no < 1 or question_no > 20:
            raise DraftPostprocessError(f"{label}[{index}] out of range")
        questions.append(question_no)
    return tuple(questions)


def markdown(summary: VerificationSummary) -> str:
    lines = [
        "# OCR Mijeok1 Draft Postprocess Verification",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        "- answer-key/grading/path leak count: 0",
        "",
        "## Result",
        "",
        f"- choice-number questions: {summary.choice_question_count}",
        f"- answer-value questions: {summary.answer_value_question_count}",
        f"- valid choice samples kept safe: {summary.valid_choice_safe_count}",
        f"- invalid choice samples blocked: {summary.invalid_choice_blocked_count}",
        f"- valid answer-value samples kept safe: {summary.valid_answer_value_safe_count}",
        f"- invalid answer-value samples blocked: {summary.invalid_answer_value_blocked_count}",
        f"- current runtime missing-mode gap count for choice value `12`: {summary.current_runtime_gap_count}",
        "",
        "## Interpretation",
        "",
        "- The lab draft blocks non-1~5 values on choice-number questions.",
        "- The lab draft blocks unclear, multiple, expression/operator, and letter-confusion answer-value samples.",
        "- Current runtime still lacks this Mijeok1 mode table, so this is evidence for a future reviewed wiring step.",
    ]
    return "\n".join(lines) + "\n"


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise DraftPostprocessError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise DraftPostprocessError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_string(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise DraftPostprocessError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise DraftPostprocessError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)
