# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_priority_target_regression_matrix.py

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from verify_ocr_postprocessing_gate_matrix import item_for, warning_tuple

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_priority_target_regression_matrix.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_priority_target_regression_matrix.md")
FORBIDDEN_OUTPUT_KEYS: Final[frozenset[str]] = frozenset(
    ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "grading", "score", "answer_key_used"),
)
PATH_TOKENS: Final[tuple[str, ...]] = ("C:\\", "C:/", "server-ocr", "crop_benchmark_inputs", "phase2c_route_uploads")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PriorityCase:
    name: str
    question_no: int
    recognized: str
    wanted_status: str
    wanted_final_answer: str | None
    wanted_warning: str | None
    priority_reason: str


@dataclass(frozen=True, slots=True)
class PriorityResult:
    name: str
    question_no: int
    recognized: str
    status: str
    final_answer: str | None
    warnings: tuple[str, ...]
    priority_reason: str


@dataclass(frozen=True, slots=True)
class PriorityMatrixError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    results = tuple(verify_case(case) for case in cases())
    output = summary(results)
    assert_no_output_leaks(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output, results), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cases() -> tuple[PriorityCase, ...]:
    return (
        PriorityCase("q003_n_blocks_choice_autofill", 3, "n", "review_required", None, "choice_number_invalid_for_auto_grade", "x/n or 3/n-like choice OCR must not fill"),
        PriorityCase("q003_digit_3_can_fill_choice", 3, "3", "safe_auto_grade", "3", None, "clear choice digit should remain fillable"),
        PriorityCase("q018_90_blocks_digit_shape_confusion", 18, "90", "review_required", None, "digit_shape_confusion", "3/9 digit-shape confusion must not fill"),
        PriorityCase("q018_30_can_fill_answer_value", 18, "30", "safe_auto_grade", "30", None, "clear numeric answer_value should remain fillable"),
        PriorityCase("q015_inclusive_relation_blocks", 15, "-1<=x<=5", "review_required", None, "relation_symbol_confusion", "inclusive-vs-strict relation ambiguity must review"),
        PriorityCase("q015_strict_relation_still_reviews", 15, "-1<x<5", "review_required", None, "relation_symbol_confusion", "relation expressions remain review-gated"),
        PriorityCase("q016_arrow_relation_blocks", 16, "y->3", "review_required", None, "arrow_equal_confusion", "arrow/equal ambiguity must review"),
        PriorityCase("q016_equal_relation_still_reviews", 16, "y=3", "review_required", None, "relation_symbol_confusion", "relation expressions remain review-gated"),
        PriorityCase("q016_visible_digit_5_can_fill", 16, "5", "safe_auto_grade", "5", None, "clear numeric answer_value should remain fillable"),
    )


def verify_case(case: PriorityCase) -> PriorityResult:
    item = item_for(case.question_no, case.recognized)
    status = text_value(item.get("status"))
    final_answer = optional_text(item.get("final_answer"))
    warnings = warning_tuple(item)
    if status != case.wanted_status:
        raise PriorityMatrixError(f"{case.name} status expected {case.wanted_status}, got {status}")
    if final_answer != case.wanted_final_answer:
        raise PriorityMatrixError(f"{case.name} final_answer expected {case.wanted_final_answer}, got {final_answer}")
    if case.wanted_warning is not None and case.wanted_warning not in warnings:
        raise PriorityMatrixError(f"{case.name} missing warning {case.wanted_warning}: {warnings}")
    return PriorityResult(case.name, case.question_no, case.recognized, status, final_answer, warnings, case.priority_reason)


def summary(results: tuple[PriorityResult, ...]) -> JsonObject:
    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    require_count(status_counts, "safe_auto_grade", 3)
    require_count(status_counts, "review_required", 6)
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "case_count": len(results),
        "status_counts": status_counts,
        "results": [asdict(result) for result in results],
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_count(counts: dict[str, int], key: str, wanted: int) -> None:
    actual = counts.get(key, 0)
    if actual != wanted:
        raise PriorityMatrixError(f"{key} expected {wanted}, got {actual}")


def assert_no_output_leaks(output: JsonObject) -> None:
    text = json.dumps(output, ensure_ascii=False)
    forbidden_hits = [key for key in FORBIDDEN_OUTPUT_KEYS if f'"{key}"' in text]
    if forbidden_hits:
        raise PriorityMatrixError(f"priority matrix contains forbidden fields: {', '.join(forbidden_hits)}")
    path_hits = [token for token in PATH_TOKENS if token in text]
    if path_hits:
        raise PriorityMatrixError(f"priority matrix contains path-like tokens: {', '.join(path_hits)}")


def optional_text(value: JsonValue) -> str | None:
    match value:
        case None:
            return None
        case str():
            return value.strip()
        case bool() | int() | float() | list() | dict():
            raise PriorityMatrixError("final_answer must be string or null")
        case unreachable:
            assert_never(unreachable)


def text_value(value: JsonValue) -> str:
    match value:
        case str():
            return value.strip()
        case None | bool() | int() | float() | list() | dict():
            return ""
        case unreachable:
            assert_never(unreachable)


def markdown(output: JsonObject, results: tuple[PriorityResult, ...]) -> str:
    lines = [
        "# OCR Priority Target Regression Matrix",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- production default: `NO-GO`",
        f"- cases: {output['case_count']}",
        f"- status counts: {output['status_counts']}",
        "",
        "| Case | q | OCR | Status | Final | Warnings | Reason |",
        "|---|---:|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {result.name} | {result.question_no} | {result.recognized} | {result.status} | "
            f"{result.final_answer} | {', '.join(result.warnings)} | {result.priority_reason} |",
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
