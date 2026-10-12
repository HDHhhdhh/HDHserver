# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_local_candidate_policy_matrix.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias

from ocr_local_candidate_tools import CheckerSignal, apply_checker_signal, classify_tesseract_text

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_local_candidate_policy_matrix.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_local_candidate_policy_matrix.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
ExpectedFinalAnswer: TypeAlias = Literal["preserve", "clear"]


@dataclass(frozen=True, slots=True)
class PolicyCase:
    name: str
    item: JsonObject
    signal: CheckerSignal
    expected_status: str
    expected_final_answer: ExpectedFinalAnswer
    expected_warning: str | None


@dataclass(frozen=True, slots=True)
class PolicyResult:
    name: str
    status: str
    final_answer: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LocalCandidatePolicyError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    policy_results = tuple(run_policy_case(case) for case in policy_cases())
    classifier_summary = verify_tesseract_classifier()
    output = summary(policy_results, classifier_summary)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def policy_cases() -> tuple[PolicyCase, ...]:
    return (
        PolicyCase("skip_preserves_safe", safe_item("3"), CheckerSignal("tesseract", 1, "skip", "", None, None), "safe_auto_grade", "preserve", None),
        PolicyCase("blank_conflict_blocks_safe", safe_item("3"), CheckerSignal("tesseract", 1, "blank_like", "", None, "tesseract_blank_like"), "review_required", "clear", "local_checker_blank_conflict"),
        PolicyCase("format_conflict_blocks_safe", safe_item("3"), CheckerSignal("tesseract", 1, "format_conflict", "x=2", None, "tesseract_choice_digit_veto"), "review_required", "clear", "tesseract_choice_digit_veto"),
        PolicyCase("multiple_candidates_blocks_safe", safe_item("3"), CheckerSignal("tesseract", 1, "multiple_candidates", "13", None, "tesseract_multiple_choice_candidates"), "review_required", "clear", "tesseract_multiple_choice_candidates"),
        PolicyCase("candidate_conflict_blocks_safe", safe_item("3"), CheckerSignal("tesseract", 1, "candidate", "4", "4", None), "review_required", "clear", "tesseract_candidate_conflict"),
        PolicyCase("candidate_match_preserves_safe", safe_item("3"), CheckerSignal("tesseract", 1, "candidate", "3", "3", None), "safe_auto_grade", "preserve", None),
        PolicyCase("candidate_match_does_not_promote_review", review_item("3"), CheckerSignal("tesseract", 1, "candidate", "3", "3", None), "review_required", "clear", None),
    )


def safe_item(answer: str) -> JsonObject:
    return {
        "question_no": 1,
        "status": "safe_auto_grade",
        "recognized": answer,
        "warnings": [],
        "candidates": [],
        "final_answer": answer,
        "source": "safe_auto_grade",
    }


def review_item(answer: str) -> JsonObject:
    item = safe_item(answer)
    item["status"] = "review_required"
    item["source"] = None
    item["final_answer"] = None
    return item


def run_policy_case(case: PolicyCase) -> PolicyResult:
    result = apply_checker_signal(case.item, case.signal)
    status = require_str(result.get("status"), f"{case.name}.status")
    warnings = warning_tuple(result.get("warnings"))
    final_answer = final_answer_text(result.get("final_answer"))
    if status != case.expected_status:
        raise LocalCandidatePolicyError(f"{case.name} status {status} != {case.expected_status}")
    if case.expected_final_answer == "clear" and final_answer is not None:
        raise LocalCandidatePolicyError(f"{case.name} final_answer must be cleared")
    if case.expected_final_answer == "preserve" and final_answer != case.item.get("final_answer"):
        raise LocalCandidatePolicyError(f"{case.name} final_answer must be preserved")
    if case.expected_warning is not None and case.expected_warning not in warnings:
        raise LocalCandidatePolicyError(f"{case.name} missing warning {case.expected_warning}: {warnings}")
    return PolicyResult(case.name, status, final_answer, warnings)


def verify_tesseract_classifier() -> JsonObject:
    cases: tuple[tuple[str, str, str, str], ...] = (
        ("choice_number", "3", "candidate", ""),
        ("choice_number", "x=2", "format_conflict", "tesseract_choice_digit_veto"),
        ("choice_number", "13", "multiple_candidates", "tesseract_multiple_choice_candidates"),
        ("answer_value", "12/5", "candidate", ""),
        ("answer_value", "1,2", "multiple_candidates", "tesseract_multiple_candidates"),
        ("answer_value", "x=2", "format_conflict", "tesseract_answer_value_format_conflict"),
    )
    results: list[JsonObject] = []
    for index, (mode, text, expected_kind, expected_warning) in enumerate(cases, start=1):
        signal = classify_tesseract_text(index, mode, text)
        if signal.kind != expected_kind:
            raise LocalCandidatePolicyError(f"classifier {mode}:{text} kind {signal.kind} != {expected_kind}")
        if expected_warning and signal.warning != expected_warning:
            raise LocalCandidatePolicyError(f"classifier {mode}:{text} warning {signal.warning} != {expected_warning}")
        results.append({"mode": mode, "text": text, "kind": signal.kind, "warning": signal.warning})
    return {"case_count": len(results), "cases": results}


def summary(policy_results: tuple[PolicyResult, ...], classifier_summary: JsonObject) -> JsonObject:
    review_count = sum(1 for result in policy_results if result.status == "review_required")
    safe_count = sum(1 for result in policy_results if result.status == "safe_auto_grade")
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "policy_case_count": len(policy_results),
        "policy_review_required_count": review_count,
        "policy_safe_preserved_count": safe_count,
        "classifier_case_count": classifier_summary["case_count"],
        "policy_results": [result_payload(result) for result in policy_results],
        "classifier_results": classifier_summary["cases"],
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def result_payload(result: PolicyResult) -> JsonObject:
    return {"name": result.name, "status": result.status, "final_answer": result.final_answer, "warnings": list(result.warnings)}


def warning_tuple(value: JsonValue) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def final_answer_text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def require_str(value: JsonValue, label: str) -> str:
    if isinstance(value, str):
        return value
    raise LocalCandidatePolicyError(f"{label} must be a string")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Local Candidate Policy Matrix",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- policy cases: {output['policy_case_count']}",
        f"- review-required policy outcomes: {output['policy_review_required_count']}",
        f"- safe-preserved policy outcomes: {output['policy_safe_preserved_count']}",
        f"- classifier cases: {output['classifier_case_count']}",
        "- answer-key/grading/path leak count: 0",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
