from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from ocr_relation_ambiguity import ARROW_TOKENS, RELATION_OPERATOR_WARNING_NAMES, relation_ambiguity_warnings

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

JAMO_CHOICES: Final[frozenset[str]] = frozenset({"ㄱ", "ㄴ", "ㄷ", "ㄹ"})
JAMO_CONFUSERS: Final[frozenset[str]] = frozenset({"7", "4", "C", "c", "2", "L", "l"})
DATA_CHECK_WARNINGS: Final[frozenset[str]] = frozenset({"possible_answer_key_or_crop_mismatch"})
REVIEW_WARNINGS: Final[frozenset[str]] = frozenset(
    {
        *RELATION_OPERATOR_WARNING_NAMES,
        "digit_confusion_0_6",
        "variable_confusion_x_n",
        "jamo_choice_confusion",
        "equation_part_missing",
        "missing",
        "mismatch",
    },
)


@dataclass(frozen=True, slots=True)
class EvalConfig:
    expected_path: Path
    recognized_path: Path
    out_dir: Path


@dataclass(frozen=True, slots=True)
class ExpectedItem:
    question: int
    expected: str
    accepted: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecognizedItem:
    question: int
    recognized: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvalItem:
    question: int
    expected: str
    recognized: str
    exact_match: bool
    normalized_match: bool
    accepted_match: bool
    legacy_policy: str
    review_policy: str
    status: str
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvalSummary:
    total: int
    exact_match: int
    normalized_match: int
    accepted_match: int
    safe_auto_grade: int
    review_required: int
    data_check_required: int
    missing: int
    mismatch: int
    accuracy: float


class EvaluateOcrError(Exception):
    pass


def main() -> int:
    config = parse_args()
    expected = load_expected(config.expected_path)
    recognized = load_recognized(config.recognized_path)
    rows = evaluate(expected, recognized)
    write_reports(config.out_dir, rows)
    print(json.dumps({"ok": True, "items": len(rows), "out_dir": str(config.out_dir)}, ensure_ascii=False))
    return 0


def parse_args() -> EvalConfig:
    parser = argparse.ArgumentParser(description="Evaluate OCR output with ambiguity review policy.")
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--recognized", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    return EvalConfig(args.expected, args.recognized, args.out_dir)


def load_expected(path: Path) -> tuple[ExpectedItem, ...]:
    payload = read_json_object(path)
    items = json_items(payload, path)
    parsed: list[ExpectedItem] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise EvaluateOcrError(f"{path} item {index} must be an object")
        question = int(item.get("question", item.get("no", index)))
        expected = str(item.get("expected", item.get("answer", item.get("canonical_answer", "")))).strip()
        accepted = accepted_answers(item, expected)
        parsed.append(ExpectedItem(question, expected, accepted))
    return tuple(sorted(parsed, key=lambda item: item.question))


def load_recognized(path: Path) -> tuple[RecognizedItem, ...]:
    payload = read_json_object(path)
    parsed: list[RecognizedItem] = []
    for index, item in enumerate(json_items(payload, path), start=1):
        if not isinstance(item, dict):
            raise EvaluateOcrError(f"{path} item {index} must be an object")
        question = int(item.get("question", item.get("no", index)))
        recognized = str(item.get("recognized", item.get("answer", ""))).strip()
        parsed.append(RecognizedItem(question, recognized, warning_tuple(item.get("warnings", ()))))
    return tuple(sorted(parsed, key=lambda item: item.question))


def accepted_answers(item: dict[str, JsonValue], expected: str) -> tuple[str, ...]:
    raw = item.get("accepted_answers", item.get("accepted", ()))
    values = [expected]
    if isinstance(raw, list):
        values.extend(str(value).strip() for value in raw if str(value).strip())
    return tuple(dict.fromkeys(values))


def warning_tuple(value: JsonValue) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item))


def read_json_object(path: Path) -> dict[str, JsonValue]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise EvaluateOcrError(f"{path} must contain a JSON object")
    return payload


def json_items(payload: dict[str, JsonValue], path: Path) -> list[JsonValue]:
    value = payload.get("items")
    if not isinstance(value, list):
        raise EvaluateOcrError(f"{path} must contain an items list")
    return value


def evaluate(expected: tuple[ExpectedItem, ...], recognized: tuple[RecognizedItem, ...]) -> tuple[EvalItem, ...]:
    recognized_by_question = {item.question: item for item in recognized}
    rows: list[EvalItem] = []
    for item in expected:
        hit = recognized_by_question.get(item.question, RecognizedItem(item.question, "?", ()))
        rows.append(evaluate_item(item, hit))
    return tuple(rows)


def evaluate_item(expected: ExpectedItem, recognized: RecognizedItem) -> EvalItem:
    exact_match = expected.expected.strip() == recognized.recognized.strip()
    normalized_match = normalize(expected.expected) == normalize(recognized.recognized)
    accepted_match = any(normalize(answer) == normalize(recognized.recognized) for answer in expected.accepted)
    warnings = merge_warnings(recognized.warnings, derived_warnings(expected.expected, recognized.recognized, accepted_match))
    review_policy = policy_for(warnings, accepted_match)
    status = status_for(recognized.recognized, accepted_match)
    return EvalItem(
        question=expected.question,
        expected=expected.expected,
        recognized=recognized.recognized,
        exact_match=exact_match,
        normalized_match=normalized_match,
        accepted_match=accepted_match,
        legacy_policy="safe_auto_grade" if accepted_match else "review_required",
        review_policy=review_policy,
        status=status,
        warnings=warnings,
    )


def derived_warnings(expected: str, recognized: str, accepted_match: bool) -> tuple[str, ...]:
    if recognized.strip() in {"", "?"}:
        return ("missing",)
    expected_compact = normalize(expected)
    recognized_compact = normalize(recognized)
    warnings: list[str] = []
    if has_x_n_confusion(expected_compact, recognized_compact):
        warnings.append("variable_confusion_x_n")
    if {expected_compact, recognized_compact} == {"0", "6"}:
        warnings.append("digit_confusion_0_6")
    if bool(JAMO_CHOICES.intersection(expected)) and bool(JAMO_CONFUSERS.intersection(recognized)):
        warnings.append("jamo_choice_confusion")
    if "=" in expected_compact and "=" not in recognized_compact:
        warnings.append("equation_part_missing")
    warnings.extend(relation_ambiguity_warnings(expected, recognized))
    if has_x_n_confusion(expected_compact, recognized_compact) and any(stroke in recognized for stroke in ARROW_TOKENS) and "=" in expected_compact:
        warnings.append("possible_answer_key_or_crop_mismatch")
    if not accepted_match and not warnings:
        warnings.append("mismatch")
    return tuple(warnings)


def has_x_n_confusion(expected: str, recognized: str) -> bool:
    return ("x" in expected and "n" in recognized) or ("n" in expected and "x" in recognized)


def merge_warnings(primary: tuple[str, ...], secondary: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*primary, *secondary)))


def policy_for(warnings: tuple[str, ...], accepted_match: bool) -> str:
    warning_set = frozenset(warnings)
    if warning_set & DATA_CHECK_WARNINGS:
        return "data_check_required"
    if warning_set & REVIEW_WARNINGS:
        return "review_required"
    return "safe_auto_grade" if accepted_match else "review_required"


def status_for(recognized: str, accepted_match: bool) -> str:
    if recognized.strip() in {"", "?"}:
        return "missing"
    return "accepted" if accepted_match else "mismatch"


def normalize(value: str) -> str:
    return "".join(value.split()).lower()


def write_reports(out_dir: Path, rows: tuple[EvalItem, ...]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    (out_dir / "eval.json").write_text(json.dumps({"summary": asdict(summary), "items": [asdict(row) for row in rows]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(out_dir / "eval.csv", rows)
    write_markdown(out_dir / "eval.md", summary, rows)
    write_before_after(out_dir / "before_after_policy.md", rows)


def summarize(rows: tuple[EvalItem, ...]) -> EvalSummary:
    total = len(rows)
    accepted = sum(1 for row in rows if row.accepted_match)
    return EvalSummary(
        total=total,
        exact_match=sum(1 for row in rows if row.exact_match),
        normalized_match=sum(1 for row in rows if row.normalized_match),
        accepted_match=accepted,
        safe_auto_grade=sum(1 for row in rows if row.review_policy == "safe_auto_grade"),
        review_required=sum(1 for row in rows if row.review_policy == "review_required"),
        data_check_required=sum(1 for row in rows if row.review_policy == "data_check_required"),
        missing=sum(1 for row in rows if row.status == "missing"),
        mismatch=sum(1 for row in rows if row.status == "mismatch"),
        accuracy=round((accepted / total) * 100, 2) if total else 0.0,
    )


def write_csv(path: Path, rows: tuple[EvalItem, ...]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["question", "expected", "recognized", "exact_match", "normalized_match", "accepted_match", "legacy_policy", "review_policy", "status", "warnings"])
        for row in rows:
            writer.writerow([row.question, row.expected, row.recognized, row.exact_match, row.normalized_match, row.accepted_match, row.legacy_policy, row.review_policy, row.status, ";".join(row.warnings)])


def write_markdown(path: Path, summary: EvalSummary, rows: tuple[EvalItem, ...]) -> None:
    lines = ["# OCR evaluation", "", "This report is generated locally from existing OCR JSON. No API calls are made.", "", "## Summary", ""]
    for key, value in asdict(summary).items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## Items", "", "| q | expected | recognized | exact | normalized | accepted | policy | status | warnings |", "|---:|---|---|---:|---:|---:|---|---|---|"]
    for row in rows:
        lines.append(f"| {row.question} | `{safe_cell(row.expected)}` | `{safe_cell(row.recognized)}` | {row.exact_match} | {row.normalized_match} | {row.accepted_match} | {row.review_policy} | {row.status} | {safe_cell(', '.join(row.warnings))} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_before_after(path: Path, rows: tuple[EvalItem, ...]) -> None:
    changed = tuple(row for row in rows if row.legacy_policy != row.review_policy)
    lines = ["# Before/after policy classification", "", "Before uses accepted_match-only auto grading. After applies ambiguity warnings before safe_auto_grade.", "", "| q | recognized | accepted | before | after | warnings |", "|---:|---|---:|---|---|---|"]
    for row in changed:
        lines.append(f"| {row.question} | `{safe_cell(row.recognized)}` | {row.accepted_match} | {row.legacy_policy} | {row.review_policy} | {safe_cell(', '.join(row.warnings))} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def safe_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
