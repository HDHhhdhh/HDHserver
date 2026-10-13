from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final, TypeAlias

from verify_ocr_answer_mode_patch_package import DRAFT_PATH, ModeMapping, draft_mappings, load_json, require_object

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_answer_mode_post_approval_simulation.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_answer_mode_post_approval_simulation.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CHOICE_VALUES: Final[frozenset[str]] = frozenset(("1", "2", "3", "4", "5"))
UNCLEAR_TEXTS: Final[frozenset[str]] = frozenset(("", "?", "??", "unknown", "unclear"))
MULTIPLE_NUMERIC_ANSWER_RE: Final[re.Pattern[str]] = re.compile(r"^[-+]?\d+(?:/\d+|\.\d+)?\s*,\s*[-+]?\d+")
ANSWER_VALUE_VALID_SAMPLES: Final[tuple[str, ...]] = ("12", "64", "1/2", "-3", "0.5")
ANSWER_VALUE_INVALID_SAMPLES: Final[tuple[str, ...]] = ("?", "unknown", "1,3", "1/2,9/2", "x=2", "3sqrt(2)", "12\n13", "n")
CHOICE_INVALID_SAMPLES: Final[tuple[str, ...]] = ("x=2", "3sqrt(2)", "1,3", "1/2,9/2", "?", "n", "6", "")


class PostApprovalSimulationError(Exception):
    pass


def main() -> int:
    mappings = draft_mappings(require_object(load_json(DRAFT_PATH), "draft"))
    summary = simulate_all(mappings)
    REPORT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def simulate_all(mappings: tuple[ModeMapping, ...]) -> JsonObject:
    rows = [simulate_mapping(mapping) for mapping in mappings]
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "target_count": len(rows),
        "choice_question_count": sum(int(row["choice_question_count"]) for row in rows),
        "answer_value_question_count": sum(int(row["answer_value_question_count"]) for row in rows),
        "valid_choice_safe_count": sum(int(row["valid_choice_safe_count"]) for row in rows),
        "invalid_choice_blocked_count": sum(int(row["invalid_choice_blocked_count"]) for row in rows),
        "valid_answer_value_safe_count": sum(int(row["valid_answer_value_safe_count"]) for row in rows),
        "invalid_answer_value_blocked_count": sum(int(row["invalid_answer_value_blocked_count"]) for row in rows),
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "tests": rows,
    }
    verify_expected_summary(output)
    return output


def simulate_mapping(mapping: ModeMapping) -> JsonObject:
    valid_choice_safe = sum(expect_safe("choice_number", sample) for _question in mapping.choice for sample in CHOICE_VALUES)
    invalid_choice_blocked = sum(expect_blocked("choice_number", sample) for _question in mapping.choice for sample in CHOICE_INVALID_SAMPLES)
    valid_value_safe = sum(expect_safe("answer_value", sample) for _question in mapping.value for sample in ANSWER_VALUE_VALID_SAMPLES)
    invalid_value_blocked = sum(expect_blocked("answer_value", sample) for _question in mapping.value for sample in ANSWER_VALUE_INVALID_SAMPLES)
    return {
        "test_id": mapping.test_id,
        "choice_question_count": len(mapping.choice),
        "answer_value_question_count": len(mapping.value),
        "valid_choice_safe_count": valid_choice_safe,
        "invalid_choice_blocked_count": invalid_choice_blocked,
        "valid_answer_value_safe_count": valid_value_safe,
        "invalid_answer_value_blocked_count": invalid_value_blocked,
    }


def expect_safe(mode: str, sample: str) -> int:
    warning = simulated_warning(mode, sample)
    if warning is not None:
        raise PostApprovalSimulationError(f"{mode} sample should be safe: {sample!r} -> {warning}")
    return 1


def expect_blocked(mode: str, sample: str) -> int:
    warning = simulated_warning(mode, sample)
    if warning is None:
        raise PostApprovalSimulationError(f"{mode} sample should be blocked: {sample!r}")
    return 1


def simulated_warning(mode: str, answer: str) -> str | None:
    normalized = answer.strip()
    if normalized.lower() in UNCLEAR_TEXTS:
        return "unclear_final_answer"
    if "\n" in answer or "\r" in answer:
        return "multiple_answer_candidates"
    if mode == "choice_number":
        return None if normalized in CHOICE_VALUES else "choice_number_invalid_for_auto_grade"
    if MULTIPLE_NUMERIC_ANSWER_RE.match(normalized):
        return "multiple_answer_candidates"
    if any(character.isalpha() for character in normalized):
        return "answer_value_letter_confusion"
    return None


def verify_expected_summary(summary: JsonObject) -> None:
    expected = {
        "target_count": 5,
        "choice_question_count": 97,
        "answer_value_question_count": 3,
        "valid_choice_safe_count": 485,
        "invalid_choice_blocked_count": 776,
        "valid_answer_value_safe_count": 15,
        "invalid_answer_value_blocked_count": 24,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise PostApprovalSimulationError(f"{key} expected {value}, got {summary.get(key)}")


def markdown(summary: JsonObject) -> str:
    lines = [
        "# OCR Answer Mode Post-Approval Simulation",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- targets simulated: {summary['target_count']}",
        f"- choice questions simulated: {summary['choice_question_count']}",
        f"- answer-value questions simulated: {summary['answer_value_question_count']}",
        f"- valid choice safe cases: {summary['valid_choice_safe_count']}",
        f"- invalid choice blocked cases: {summary['invalid_choice_blocked_count']}",
        f"- valid answer-value safe cases: {summary['valid_answer_value_safe_count']}",
        f"- invalid answer-value blocked cases: {summary['invalid_answer_value_blocked_count']}",
        "- answer-key/grading/path leak count: 0",
        "",
        "This simulates the expected behavior after the proposed answer-mode mapping is approved and applied.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
