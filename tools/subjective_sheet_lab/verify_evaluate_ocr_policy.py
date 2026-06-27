from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from evaluate_ocr_result import ExpectedItem, RecognizedItem, evaluate

OUT_DIR = Path("C:/server-ocr/gemini_outputs/evaluate_ocr_policy_regression")


@dataclass(frozen=True, slots=True)
class PolicyCase:
    name: str
    expected: ExpectedItem
    recognized: RecognizedItem
    required_policy: str
    required_warnings: tuple[str, ...]
    required_accepted: bool


@dataclass(frozen=True, slots=True)
class PolicyCaseResult:
    name: str
    recognized: str
    accepted_match: bool
    legacy_policy: str
    review_policy: str
    warnings: tuple[str, ...]
    passed: bool


class PolicyRegressionError(Exception):
    pass


def main() -> int:
    results = tuple(run_case(case) for case in cases())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(results)
    write_markdown(results)
    failed = tuple(result for result in results if not result.passed)
    if failed:
        names = ", ".join(result.name for result in failed)
        raise PolicyRegressionError(f"evaluate_ocr_result policy failed: {names}")
    print(json.dumps({"ok": True, "cases": len(results), "out_dir": str(OUT_DIR)}, ensure_ascii=False))
    return 0


def cases() -> tuple[PolicyCase, ...]:
    return (
        PolicyCase("exact_safe", expected_item(1, "1"), recognized_item(1, "1"), "safe_auto_grade", (), True),
        PolicyCase("normalized_safe", expected_item(17, "1/2,9/2"), recognized_item(17, "1/2, 9/2"), "safe_auto_grade", (), True),
        PolicyCase("accepted_alias_safe", ExpectedItem(4, "0.5", ("0.5", "1/2")), recognized_item(4, "1/2"), "safe_auto_grade", (), True),
        PolicyCase("variable_confusion_review", expected_item(8, "x"), recognized_item(8, "n"), "review_required", ("variable_confusion_x_n",), False),
        PolicyCase("q003_x_n_data_check", expected_item(3, "x=2"), recognized_item(3, "x→n"), "data_check_required", ("variable_confusion_x_n", "equation_part_missing", "possible_answer_key_or_crop_mismatch"), False),
        PolicyCase("q010_zero_six_review", expected_item(10, "0"), recognized_item(10, "6"), "review_required", ("digit_confusion_0_6",), False),
        PolicyCase("accepted_warning_blocks_safe", expected_item(6, "0"), recognized_item(6, "0", ("digit_confusion_0_6",)), "review_required", ("digit_confusion_0_6",), True),
        PolicyCase("possible_mismatch_blocks_safe", expected_item(3, "x=2"), recognized_item(3, "x=2", ("possible_answer_key_or_crop_mismatch",)), "data_check_required", ("possible_answer_key_or_crop_mismatch",), True),
        PolicyCase("jamo_confusion_review", expected_item(4, "ㄱ,ㄷ"), recognized_item(4, "7,C"), "review_required", ("jamo_choice_confusion",), False),
        PolicyCase("equation_part_missing_review", expected_item(16, "y=3"), recognized_item(16, "y"), "review_required", ("equation_part_missing",), False),
    )


def expected_item(question: int, expected: str) -> ExpectedItem:
    return ExpectedItem(question, expected, (expected,))


def recognized_item(question: int, recognized: str, warnings: tuple[str, ...] = ()) -> RecognizedItem:
    return RecognizedItem(question, recognized, warnings)


def run_case(case: PolicyCase) -> PolicyCaseResult:
    row = evaluate((case.expected,), (case.recognized,))[0]
    passed = row.review_policy == case.required_policy and row.accepted_match == case.required_accepted and all(warning in row.warnings for warning in case.required_warnings)
    return PolicyCaseResult(
        name=case.name,
        recognized=case.recognized.recognized,
        accepted_match=row.accepted_match,
        legacy_policy=row.legacy_policy,
        review_policy=row.review_policy,
        warnings=row.warnings,
        passed=passed,
    )


def write_json(results: tuple[PolicyCaseResult, ...]) -> None:
    payload = {
        "summary": {
            "total": len(results),
            "passed": sum(1 for result in results if result.passed),
            "failed": sum(1 for result in results if not result.passed),
        },
        "items": [asdict(result) for result in results],
    }
    (OUT_DIR / "evaluate_ocr_policy_regression.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(results: tuple[PolicyCaseResult, ...]) -> None:
    lines = [
        "# evaluate_ocr_result policy regression",
        "",
        "| case | recognized | accepted | before | after | warnings | passed |",
        "|---|---|---:|---|---|---|---:|",
    ]
    for result in results:
        lines.append(f"| {result.name} | `{result.recognized}` | {result.accepted_match} | {result.legacy_policy} | {result.review_policy} | {', '.join(result.warnings)} | {result.passed} |")
    (OUT_DIR / "evaluate_ocr_policy_regression.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
