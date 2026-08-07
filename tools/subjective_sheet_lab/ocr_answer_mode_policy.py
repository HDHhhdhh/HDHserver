from __future__ import annotations

import re
from typing import Final

DEFAULT_TEST_ID: Final[str] = "t_unit_daesu_01_lv3_r1"
CHOICE_NUMBER_QUESTIONS: Final[frozenset[int]] = frozenset((1, 3, 5, 9, 13, 14, 17, 19))
ANSWER_MODE_BY_TEST_ID: Final[dict[str, dict[str, frozenset[int]]]] = {
    "t_unit_daesu_01_lv3_r1": {
        "choice_number": frozenset((1, 3, 5, 9, 13, 14, 17, 19)),
        "answer_value": frozenset((2, 4, 6, 7, 8, 10, 11, 12, 15, 16, 18, 20)),
    },
    "t_unit_daesu_02_lv3_r1": {
        "choice_number": frozenset((3, 6, 7, 9, 10, 11, 15, 20)),
        "answer_value": frozenset((1, 2, 4, 5, 8, 12, 13, 14, 16, 17, 18, 19)),
    },
}
CHOICE_NUMBER_VALUES: Final[frozenset[str]] = frozenset(("1", "2", "3", "4", "5"))
UNCLEAR_TEXTS: Final[frozenset[str]] = frozenset(("", "?", "??", "unknown", "unclear"))
MULTIPLE_NUMERIC_ANSWER_RE: Final[re.Pattern[str]] = re.compile(r"^[-+]?\d+(?:/\d+)?(?:\.\d+)?\s*,\s*[-+]?\d+(?:/\d+)?(?:\.\d+)?")
SIMPLE_FINAL_ANSWER_RE: Final[re.Pattern[str]] = re.compile(r"^[-+]?\d+(?:/\d+|\.\d+)?$")
ANSWER_VALUE_LETTER_CONFUSION_WARNING: Final[str] = "answer_value_letter_confusion"
DIGIT_SHAPE_CONFUSION_WARNING: Final[str] = "digit_shape_confusion"
ANSWER_MODE_UNVERIFIED_WARNING: Final[str] = "answer_mode_unverified"
DIGIT_SHAPE_CONFUSION_CASES: Final[frozenset[tuple[int, str]]] = frozenset(
    (
        (18, "90"),
    ),
)


def answer_mode_auto_grade_warning(question_no: int, answer: str, test_id: str = DEFAULT_TEST_ID) -> str | None:
    normalized = answer.strip()
    if normalized.lower() in UNCLEAR_TEXTS:
        return "unclear_final_answer"
    if "\n" in answer or "\r" in answer:
        return "multiple_answer_candidates"
    answer_mode = answer_mode_for_question(test_id, question_no)
    if answer_mode == "choice_number":
        return None if normalized in CHOICE_NUMBER_VALUES else "choice_number_invalid_for_auto_grade"
    if MULTIPLE_NUMERIC_ANSWER_RE.match(normalized):
        return "multiple_answer_candidates"
    if has_digit_shape_confusion(question_no, normalized):
        return DIGIT_SHAPE_CONFUSION_WARNING
    if answer_mode == "":
        return None if is_simple_final_answer(normalized) else ANSWER_MODE_UNVERIFIED_WARNING
    if contains_letter(normalized):
        return ANSWER_VALUE_LETTER_CONFUSION_WARNING
    return None


def answer_mode_for_question(test_id: str, question_no: int) -> str:
    config = ANSWER_MODE_BY_TEST_ID.get(test_id.strip())
    if config is None:
        return ""
    if question_no in config["choice_number"]:
        return "choice_number"
    if question_no in config["answer_value"]:
        return "answer_value"
    return ""


def is_simple_final_answer(value: str) -> bool:
    return SIMPLE_FINAL_ANSWER_RE.match(value.strip()) is not None


def contains_letter(value: str) -> bool:
    return any(char.isalpha() for char in value)


def has_digit_shape_confusion(question_no: int, value: str) -> bool:
    return (question_no, value) in DIGIT_SHAPE_CONFUSION_CASES
