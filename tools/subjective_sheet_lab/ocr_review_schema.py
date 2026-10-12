from __future__ import annotations

from enum import StrEnum
from typing import Final, NewType, TypeAlias, assert_never

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]
QuestionNo = NewType("QuestionNo", int)

DEFAULT_PROBLEM_COUNT: Final = 20
ANSWER_KEY_ONLY_FIELDS: Final = frozenset(
    {"expected", "expected_answer", "canonical", "canonical_answer", "canonical_answers", "accepted_answers", "answer_key", "answer_keys", "answerkeys", "grading", "correct_answer", "is_correct", "correct", "incorrect", "score", "wrong", "pct"},
)
FINAL_SOURCES: Final = frozenset(
    {
        "safe_auto_grade",
        "student_selected_candidate",
        "student_direct_input",
        "safe_auto_grade_after_retake",
        "student_selected_candidate_after_retake",
        "student_direct_input_after_retake",
    },
)


class ReviewStatus(StrEnum):
    SAFE_AUTO_GRADE = "safe_auto_grade"
    REVIEW_REQUIRED = "review_required"
    RETAKE_REQUIRED = "retake_required"
    RETAKE_UPLOADED = "retake_uploaded"
    DATA_CHECK_REQUIRED = "data_check_required"
    CONFIRMED = "confirmed"
    STUDENT_SELECTED_CANDIDATE = "student_selected_candidate"
    STUDENT_DIRECT_INPUT = "student_direct_input"
    SAFE_AUTO_GRADE_AFTER_RETAKE = "safe_auto_grade_after_retake"
    STUDENT_SELECTED_CANDIDATE_AFTER_RETAKE = "student_selected_candidate_after_retake"
    STUDENT_DIRECT_INPUT_AFTER_RETAKE = "student_direct_input_after_retake"


class AnswerSource(StrEnum):
    SAFE_AUTO_GRADE = "safe_auto_grade"
    STUDENT_SELECTED_CANDIDATE = "student_selected_candidate"
    STUDENT_DIRECT_INPUT = "student_direct_input"
    RETAKE_UPLOADED = "retake_uploaded"
    SAFE_AUTO_GRADE_AFTER_RETAKE = "safe_auto_grade_after_retake"
    STUDENT_SELECTED_CANDIDATE_AFTER_RETAKE = "student_selected_candidate_after_retake"
    STUDENT_DIRECT_INPUT_AFTER_RETAKE = "student_direct_input_after_retake"


class PayloadMode(StrEnum):
    REVIEW = "review"
    FINAL = "final"


FINAL_STATUSES: Final = frozenset({ReviewStatus.SAFE_AUTO_GRADE, ReviewStatus.CONFIRMED, ReviewStatus.STUDENT_SELECTED_CANDIDATE, ReviewStatus.STUDENT_DIRECT_INPUT, ReviewStatus.SAFE_AUTO_GRADE_AFTER_RETAKE, ReviewStatus.STUDENT_SELECTED_CANDIDATE_AFTER_RETAKE, ReviewStatus.STUDENT_DIRECT_INPUT_AFTER_RETAKE})
UNRESOLVED_STATUSES: Final = frozenset({ReviewStatus.REVIEW_REQUIRED, ReviewStatus.RETAKE_REQUIRED, ReviewStatus.DATA_CHECK_REQUIRED})
RETAKE_FINAL_STATUSES: Final = frozenset({ReviewStatus.SAFE_AUTO_GRADE_AFTER_RETAKE, ReviewStatus.STUDENT_SELECTED_CANDIDATE_AFTER_RETAKE, ReviewStatus.STUDENT_DIRECT_INPUT_AFTER_RETAKE})
EXACT_SOURCE_BY_STATUS: Final = {
    ReviewStatus.SAFE_AUTO_GRADE: AnswerSource.SAFE_AUTO_GRADE,
    ReviewStatus.RETAKE_UPLOADED: AnswerSource.RETAKE_UPLOADED,
    ReviewStatus.STUDENT_SELECTED_CANDIDATE: AnswerSource.STUDENT_SELECTED_CANDIDATE,
    ReviewStatus.STUDENT_DIRECT_INPUT: AnswerSource.STUDENT_DIRECT_INPUT,
    ReviewStatus.SAFE_AUTO_GRADE_AFTER_RETAKE: AnswerSource.SAFE_AUTO_GRADE_AFTER_RETAKE,
    ReviewStatus.STUDENT_SELECTED_CANDIDATE_AFTER_RETAKE: AnswerSource.STUDENT_SELECTED_CANDIDATE_AFTER_RETAKE,
    ReviewStatus.STUDENT_DIRECT_INPUT_AFTER_RETAKE: AnswerSource.STUDENT_DIRECT_INPUT_AFTER_RETAKE,
}


def find_forbidden_answer_key_paths(value: JsonValue) -> list[str]:
    found: list[str] = []

    def walk(current: JsonValue, path: str) -> None:
        match current:
            case dict():
                for key, child in current.items():
                    child_path = f"{path}.{key}"
                    if str(key).casefold() in ANSWER_KEY_ONLY_FIELDS:
                        found.append(child_path)
                    walk(child, child_path)
            case list():
                for index, child in enumerate(current):
                    walk(child, f"{path}[{index}]")
            case None | bool() | int() | float() | str():
                return
            case unreachable:
                assert_never(unreachable)

    walk(value, "$")
    return found
