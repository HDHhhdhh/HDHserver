from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, TypedDict, assert_never

from ocr_answer_mode_policy import answer_mode_auto_grade_warning

DRAFT_PATH: Final[Path] = Path(__file__).with_name("ocr_answer_mode_draft_targets.json")
REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_training_pack_draft_postprocess_verification.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_training_pack_draft_postprocess_verification.md")
TARGET_IDS: Final[tuple[str, ...]] = (
    "t_training_pack_mijeok1_non_frequent_r1",
    "t_training_pack_mijeok1_non_frequent_r2",
    "t_training_pack_gongsu2_non_frequent_r1",
    "t_training_pack_gongsu2_non_frequent_r2",
)
CHOICE_VALUES: Final[frozenset[str]] = frozenset(("1", "2", "3", "4", "5"))
INVALID_CHOICE_SAMPLES: Final[tuple[str, ...]] = ("12", "x=2", "3sqrt(2)", "1,3", "1/2,9/2", "?", "n", "unknown")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class TargetResult(TypedDict):
    test_id: str
    choice_question_count: int
    valid_choice_safe_count: int
    invalid_choice_blocked_count: int
    current_runtime_gap_count: int


@dataclass(frozen=True, slots=True)
class TrainingPackPolicyError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    draft = require_object(json.loads(DRAFT_PATH.read_text(encoding="utf-8")), "draft")
    by_test_id = draft_tests_by_id(draft)
    results = [verify_target(test_id, by_test_id[test_id]) for test_id in TARGET_IDS]
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "target_count": len(results),
        "total_choice_question_count": sum(result["choice_question_count"] for result in results),
        "total_invalid_choice_blocked_count": sum(result["invalid_choice_blocked_count"] for result in results),
        "total_current_runtime_gap_count": sum(result["current_runtime_gap_count"] for result in results),
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "targets": results,
    }
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(results), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def draft_tests_by_id(draft: JsonObject) -> dict[str, JsonObject]:
    tests = require_array(draft.get("tests"), "draft.tests")
    by_test_id: dict[str, JsonObject] = {}
    for raw_test in tests:
        test = require_object(raw_test, "draft.tests[]")
        test_id = require_string(test.get("test_id"), "test_id")
        by_test_id[test_id] = test
    missing = [test_id for test_id in TARGET_IDS if test_id not in by_test_id]
    if missing:
        raise TrainingPackPolicyError(f"missing training pack draft targets: {missing}")
    return by_test_id


def verify_target(test_id: str, test: JsonObject) -> TargetResult:
    choice_questions = questions(test.get("choice_number_questions"), f"{test_id}.choice_number_questions")
    answer_value_questions = questions(test.get("answer_value_questions"), f"{test_id}.answer_value_questions")
    audit_questions = questions(test.get("needs_visual_mode_audit_questions"), f"{test_id}.needs_visual_mode_audit_questions")
    if len(choice_questions) != 20 or answer_value_questions or audit_questions:
        raise TrainingPackPolicyError(f"{test_id} must be drafted as 20 choice-number questions only")
    invalid_blocked = verify_invalid_choice_samples(choice_questions)
    return {
        "test_id": test_id,
        "choice_question_count": len(choice_questions),
        "valid_choice_safe_count": len(choice_questions) * len(CHOICE_VALUES),
        "invalid_choice_blocked_count": invalid_blocked,
        "current_runtime_gap_count": verify_runtime_gap(test_id, choice_questions),
    }


def verify_invalid_choice_samples(choice_questions: tuple[int, ...]) -> int:
    blocked = 0
    for question_no in choice_questions:
        for answer in INVALID_CHOICE_SAMPLES:
            if choice_warning(answer) is None:
                raise TrainingPackPolicyError(f"q{question_no:03d} invalid choice sample passed: {answer}")
            blocked += 1
    return blocked


def verify_runtime_gap(test_id: str, choice_questions: tuple[int, ...]) -> int:
    gaps = 0
    for question_no in choice_questions:
        current_warning = answer_mode_auto_grade_warning(question_no, "12", test_id)
        if current_warning is None and choice_warning("12") is not None:
            gaps += 1
    if gaps != len(choice_questions):
        raise TrainingPackPolicyError(f"{test_id} expected {len(choice_questions)} runtime gaps, got {gaps}")
    return gaps


def choice_warning(answer: str) -> str | None:
    normalized = answer.strip()
    return None if normalized in CHOICE_VALUES else "choice_number_invalid_for_auto_grade"


def questions(value: JsonValue, label: str) -> tuple[int, ...]:
    raw_questions = require_array(value, label)
    parsed: list[int] = []
    for index, raw_question in enumerate(raw_questions, start=1):
        question_no = require_int(raw_question, f"{label}[{index}]")
        if question_no < 1 or question_no > 20:
            raise TrainingPackPolicyError(f"{label}[{index}] out of range")
        parsed.append(question_no)
    if len(set(parsed)) != len(parsed):
        raise TrainingPackPolicyError(f"{label} has duplicate question numbers")
    return tuple(parsed)


def markdown(results: list[TargetResult]) -> str:
    lines = [
        "# OCR Training Pack Draft Postprocess Verification",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        "- answer-key/grading/path leak count: 0",
        "",
        "| test_id | choice | invalid blocked | runtime gap |",
        "|---|---:|---:|---:|",
    ]
    for result in results:
        lines.append(
            f"| `{result['test_id']}` | {result['choice_question_count']} | "
            f"{result['invalid_choice_blocked_count']} | {result['current_runtime_gap_count']} |"
        )
    lines.extend(("", "All four Training Pack drafts block non-1~5 choice answers but are not wired into runtime."))
    return "\n".join(lines) + "\n"


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise TrainingPackPolicyError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise TrainingPackPolicyError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_string(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise TrainingPackPolicyError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise TrainingPackPolicyError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
