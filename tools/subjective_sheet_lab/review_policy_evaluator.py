from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from human_transcription_eval import answers_match, normalize as normalize_answer

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

JAMO_CHOICES: Final[frozenset[str]] = frozenset({"ㄱ", "ㄴ", "ㄷ", "ㄹ"})
JAMO_CONFUSERS: Final[frozenset[str]] = frozenset({"7", "4", "C", "c", "2", "L", "l"})
ARROW_STROKES: Final[tuple[str, ...]] = ("→", "->", "=>", "↦")
REPORT_NAME: Final[str] = "same_contact_review_policy_eval"


@dataclass(frozen=True, slots=True)
class PolicyInput:
    expected_path: Path
    recognized_path: Path
    out_dir: Path


@dataclass(frozen=True, slots=True)
class AnswerItem:
    question: int
    text: str
    needs_review: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewResult:
    question: int
    expected: str
    recognized: str
    exact_match: bool
    status: str
    review_policy: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    total: int
    safe_auto_grade: int
    review_required: int
    data_check_required: int
    exact_match: int
    mismatch: int
    missing: int


class ReviewPolicyError(Exception):
    pass


def main() -> int:
    inputs = parse_args()
    expected = load_items(inputs.expected_path, "expected")
    recognized = load_items(inputs.recognized_path, "recognized")
    rows = evaluate_items(expected, recognized)
    write_reports(inputs.out_dir, rows)
    return 0 if len(rows) == 20 and not any(row.recognized.strip() in {"", "?"} for row in rows) else 1


def parse_args() -> PolicyInput:
    parser = argparse.ArgumentParser(
        description="Apply local review_required policy to existing OCR recognized.json without API calls.",
    )
    parser.add_argument("--expected", required=True, type=Path, help="expected.json path")
    parser.add_argument("--recognized", required=True, type=Path, help="recognized.json path")
    parser.add_argument("--out-dir", required=True, type=Path, help="output directory")
    args = parser.parse_args()
    return PolicyInput(expected_path=args.expected, recognized_path=args.recognized, out_dir=args.out_dir)


def load_items(path: Path, value_key: str, *, require_complete: bool = True) -> dict[int, AnswerItem]:
    payload = parse_json_file(path)
    items_value = payload.get("items")
    if not isinstance(items_value, list):
        raise ReviewPolicyError(f"{path} does not contain an items list")
    items: dict[int, AnswerItem] = {}
    for raw_item in items_value:
        if not isinstance(raw_item, dict):
            raise ReviewPolicyError(f"{path} contains a non-object item")
        question_value = raw_item.get("question")
        answer_value = raw_item.get(value_key)
        if type(question_value) is not int or not 1 <= question_value <= 20:
            raise ReviewPolicyError(f"{path} contains an item without integer question")
        if not isinstance(answer_value, str):
            raise ReviewPolicyError(f"{path} question {question_value} lacks {value_key}")
        if question_value in items:
            raise ReviewPolicyError(f"{path} contains duplicate question {question_value}")
        needs_review = raw_item.get("needs_review", False)
        uncertainty = raw_item.get("uncertainty", "clear")
        if not isinstance(uncertainty, str):
            raise ReviewPolicyError(f"{path} question {question_value} has invalid uncertainty")
        warnings = raw_item.get("warnings", [])
        if not isinstance(needs_review, bool) or not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
            raise ReviewPolicyError(f"{path} question {question_value} has invalid review metadata")
        items[question_value] = AnswerItem(question_value, answer_value.strip(), needs_review or uncertainty not in {"none", "clear"}, tuple(warnings))
    if require_complete and sorted(items) != list(range(1, 21)):
        raise ReviewPolicyError(f"{path} must contain exactly question 1..20 once")
    return items


def parse_json_file(path: Path) -> dict[str, JsonValue]:
    raw_payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw_payload, dict):
        raise ReviewPolicyError(f"{path} top-level JSON must be an object")
    return raw_payload


def evaluate_items(expected: dict[int, AnswerItem], recognized: dict[int, AnswerItem]) -> list[ReviewResult]:
    rows: list[ReviewResult] = []
    for question in sorted(expected):
        expected_text = expected[question].text
        hit = recognized.get(question, AnswerItem(question=question, text="?"))
        rows.append(evaluate_item(question, expected_text, hit.text, needs_review=hit.needs_review, model_warnings=hit.warnings))
    return rows


def evaluate_item(question: int, expected: str, recognized: str, *, needs_review: bool = False, model_warnings: tuple[str, ...] = ()) -> ReviewResult:
    exact_match = answers_match(expected, recognized)
    warnings = list(dict.fromkeys((*model_warnings, *(("model_needs_review",) if needs_review else ()), *warning_codes(expected, recognized, exact_match))))
    status = status_for(exact_match, warnings)
    review_policy = review_policy_for(warnings, status)
    return ReviewResult(
        question=question,
        expected=expected,
        recognized=recognized,
        exact_match=exact_match,
        status=status,
        review_policy=review_policy,
        warnings=tuple(warnings),
    )


def warning_codes(expected: str, recognized: str, exact_match: bool) -> list[str]:
    if recognized.strip() in {"", "?"}:
        return ["missing"]
    warnings: list[str] = []
    expected_compact = compact(expected)
    recognized_compact = compact(recognized)
    if has_x_n_confusion(expected_compact, recognized_compact):
        warnings.append("variable_confusion_x_n")
    if has_zero_six_confusion(expected_compact, recognized_compact):
        warnings.append("digit_confusion_0_6")
    if has_jamo_confusion(expected, recognized):
        warnings.append("jamo_choice_confusion")
    if "=" in expected_compact and "=" not in recognized_compact:
        warnings.append("equation_part_missing")
    if any(stroke in recognized for stroke in ARROW_STROKES) and "=" in expected_compact:
        warnings.append("possible_answer_key_or_crop_mismatch")
    if not exact_match and not warnings:
        warnings.append("mismatch")
    return warnings


def status_for(exact_match: bool, warnings: list[str]) -> str:
    if exact_match and not warnings:
        return "safe_auto_grade"
    return "review_required"


def review_policy_for(warnings: list[str], status: str) -> str:
    if "possible_answer_key_or_crop_mismatch" in warnings:
        return "data_check_required"
    if status == "safe_auto_grade":
        return "safe_auto_grade"
    return "review_required"


def has_x_n_confusion(expected: str, recognized: str) -> bool:
    return ("x" in expected and "n" in recognized) or ("n" in expected and "x" in recognized)


def has_zero_six_confusion(expected: str, recognized: str) -> bool:
    return {expected, recognized} == {"0", "6"}


def has_jamo_confusion(expected: str, recognized: str) -> bool:
    return bool(JAMO_CHOICES.intersection(expected)) and bool(JAMO_CONFUSERS.intersection(recognized))


def compact(value: str) -> str:
    return normalize_answer(value)


def write_reports(out_dir: Path, rows: list[ReviewResult]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    write_json(out_dir / f"{REPORT_NAME}.json", summary, rows)
    write_csv(out_dir / f"{REPORT_NAME}.csv", rows)
    write_markdown(out_dir / f"{REPORT_NAME}.md", summary, rows)


def summarize(rows: list[ReviewResult]) -> ReviewSummary:
    return ReviewSummary(
        total=len(rows),
        safe_auto_grade=sum(1 for row in rows if row.status == "safe_auto_grade"),
        review_required=sum(1 for row in rows if row.status == "review_required"),
        data_check_required=sum(1 for row in rows if row.review_policy == "data_check_required"),
        exact_match=sum(1 for row in rows if row.exact_match),
        mismatch=sum(1 for row in rows if row.recognized not in {"", "?"} and not row.exact_match),
        missing=sum(1 for row in rows if row.recognized in {"", "?"}),
    )


def write_json(path: Path, summary: ReviewSummary, rows: list[ReviewResult]) -> None:
    payload = {
        "summary": asdict(summary),
        "items": [
            {
                "question": row.question,
                "expected": row.expected,
                "recognized": row.recognized,
                "exact_match": row.exact_match,
                "status": row.status,
                "review_policy": row.review_policy,
                "warnings": list(row.warnings),
            }
            for row in rows
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[ReviewResult]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["question", "expected", "recognized", "exact_match", "status", "review_policy", "warnings"])
        for row in rows:
            writer.writerow(
                [row.question, row.expected, row.recognized, row.exact_match, row.status, row.review_policy, ";".join(row.warnings)],
            )


def write_markdown(path: Path, summary: ReviewSummary, rows: list[ReviewResult]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# Same-contact review policy eval\n\n")
        handle.write("This report is generated from existing local OCR results only. No API calls are made.\n\n")
        handle.write("## Summary\n\n")
        handle.write(f"- total: {summary.total}\n")
        handle.write(f"- safe_auto_grade: {summary.safe_auto_grade}\n")
        handle.write(f"- review_required: {summary.review_required}\n")
        handle.write(f"- data_check_required: {summary.data_check_required}\n")
        handle.write(f"- exact_match: {summary.exact_match}\n")
        handle.write(f"- mismatch: {summary.mismatch}\n")
        handle.write(f"- missing: {summary.missing}\n\n")
        handle.write("## Items\n\n")
        handle.write("| q | expected | recognized | status | policy | warnings |\n")
        handle.write("|---:|---|---|---|---|---|\n")
        for row in rows:
            handle.write(
                f"| {row.question} | `{row.expected}` | `{row.recognized}` | "
                f"{row.status} | {row.review_policy} | {', '.join(row.warnings)} |\n",
            )


if __name__ == "__main__":
    raise SystemExit(main())
