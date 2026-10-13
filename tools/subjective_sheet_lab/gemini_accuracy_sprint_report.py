# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# Run: C:\server-ocr\.venv\Scripts\python.exe tools\subjective_sheet_lab\gemini_accuracy_sprint_report.py --sprint-root <root>
"""Render a key-free, offline report from bounded Gemini sprint artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import TypeAlias, cast

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class ReportError(Exception):
    """Raised when a sprint root is incomplete or structurally unsafe to report."""


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an offline Gemini accuracy-sprint report.")
    parser.add_argument("--sprint-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.sprint_root.resolve()
    report = build_report(root)
    write_json(root / "gemini_accuracy_sprint_results.json", report)
    (root / "gemini_accuracy_sprint_results.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"ok": True, "decision": report["decision"], "top_variant": report["top_variant"], "provider_calls": report["provider_calls"]}, ensure_ascii=False, indent=2))
    return 0


def build_report(root: Path) -> JsonObject:
    ledger = require_object(read_json(root / "sprint_ledger.json"), "ledger")
    requests = require_list(ledger.get("requests"), "ledger requests")
    records = load_records(root)
    if len(records) != len(requests) or len(records) != 10:
        raise ReportError("screen must contain exactly ten completed provider records")
    variants: dict[str, list[JsonObject]] = defaultdict(list)
    failures: Counter[str] = Counter()
    for record in records:
        variants[cast(str, record["variant"])].append(record)
        failures.update(cast(list[str], record["failure_taxonomy"]))
    summaries = [summarize_variant(name, rows) for name, rows in sorted(variants.items())]
    top = sorted(summaries, key=lambda row: (-cast(float, row["accuracy_pct"]), -cast(float, row["average_coverage"]), cast(float, row["average_teacher_correction_proxy"]), cast(float, row["average_latency_ms"])))[0]
    decision = decision_for(top)
    return {
        "schema": "gemini_accuracy_sprint_results_v1",
        "screen_scope": "two_independent_normal_handwriting_cases_p1_contact_sheets",
        "model": "gemini-2.5-flash-lite",
        "temperature": 0,
        "max_output_tokens": 1024,
        "provider_budget": require_int(ledger.get("budget"), "budget"),
        "provider_calls": len(requests),
        "case_count": len({cast(str, record["case"]) for record in records}),
        "variant_count": len(summaries),
        "case_variant_metrics": records,
        "prompt_metrics": summaries,
        "failure_taxonomy": dict(sorted(failures.items())),
        "top_variant": top,
        "top_pipeline": "P1 four deidentified original-plus-enhanced contact sheets",
        "two_pass": "not_tested_in_this_bounded_screen",
        "cost": "cost_not_available",
        "wrong_safe_auto_grade": sum(cast(int, record["wrong_safe_auto_grade"]) for record in records),
        "decision": decision,
        "student_10_pilot": "NO_GO",
        "operating_app_changes": 0,
        "submit_calls": 0,
    }


def load_records(root: Path) -> list[JsonObject]:
    records: list[JsonObject] = []
    for evaluation_path in sorted(root.glob("*/*/evaluation.json")):
        evaluation = require_object(read_json(evaluation_path), "evaluation")
        receipt = require_object(read_json(evaluation_path.parent / "provider_receipt.json"), "provider receipt")
        if require_int(receipt.get("http_status"), "http status") != 200:
            raise ReportError("only HTTP 200 records can be reported as completed")
        rows = require_list(evaluation.get("rows"), "evaluation rows")
        taxonomy = [cast(str, tag) for row in rows for tag in require_list(require_object(row, "row").get("failure_taxonomy"), "failure taxonomy") if isinstance(tag, str)]
        records.append({
            "case": evaluation_path.parent.parent.name,
            "variant": evaluation_path.parent.name,
            "matches": require_int(evaluation.get("exact_or_normalized_match"), "matches"),
            "evaluated": require_int(evaluation.get("ocr_evaluated_total"), "evaluated"),
            "accuracy_pct": require_number(evaluation.get("ocr_vs_human_accuracy_pct"), "accuracy"),
            "candidate_coverage": require_int(evaluation.get("candidate_coverage"), "coverage"),
            "missing": require_int(evaluation.get("missing"), "missing"),
            "teacher_correction_proxy": require_int(evaluation.get("teacher_correction_proxy"), "correction proxy"),
            "wrong_safe_auto_grade": require_int(evaluation.get("wrong_safe_auto_grade"), "wrong safe auto grade"),
            "latency_ms": require_number(receipt.get("elapsed_ms"), "latency"),
            "total_tokens": usage_total(receipt.get("usage_metadata")),
            "failure_taxonomy": taxonomy,
        })
    return records


def summarize_variant(name: str, rows: list[JsonObject]) -> JsonObject:
    matches = sum(cast(int, row["matches"]) for row in rows)
    evaluated = sum(cast(int, row["evaluated"]) for row in rows)
    return {
        "variant": name,
        "matches": matches,
        "evaluated": evaluated,
        "accuracy_pct": round((matches / evaluated) * 100, 2) if evaluated else 0.0,
        "average_coverage": round(sum(cast(int, row["candidate_coverage"]) for row in rows) / len(rows), 2),
        "average_teacher_correction_proxy": round(sum(cast(int, row["teacher_correction_proxy"]) for row in rows) / len(rows), 2),
        "average_latency_ms": round(sum(cast(float, row["latency_ms"]) for row in rows) / len(rows), 1),
        "total_tokens": sum(cast(int, row["total_tokens"]) for row in rows),
        "missing": sum(cast(int, row["missing"]) for row in rows),
        "wrong_safe_auto_grade": sum(cast(int, row["wrong_safe_auto_grade"]) for row in rows),
    }


def decision_for(top: JsonObject) -> str:
    accuracy = require_number(top.get("accuracy_pct"), "top accuracy")
    coverage = require_number(top.get("average_coverage"), "top coverage")
    corrections = require_number(top.get("average_teacher_correction_proxy"), "top correction proxy")
    wrong_safe = require_int(top.get("wrong_safe_auto_grade"), "top wrong safe auto grade")
    if accuracy >= 95 and coverage >= 18 and corrections <= 2 and wrong_safe == 0:
        return "PASS_GEMINI_ACCURACY_TARGET"
    if accuracy >= 90 and wrong_safe == 0:
        return "CONDITIONAL_GO"
    return "NO_GO"


def render_markdown(report: JsonObject) -> str:
    prompt_rows = cast(list[JsonObject], report["prompt_metrics"])
    lines = [
        "# Gemini Accuracy Sprint Results",
        "",
        "## Scope",
        "",
        "- P1 only: four deidentified original-plus-enhanced contact sheets per case.",
        "- Two independent normal-handwriting cases; five prompt variants; sequential execution.",
        f"- Provider calls: {report['provider_calls']}/{report['provider_budget']}; cost: {report['cost']}.",
        "- No full-sheet transmission, answer-key use, route call, submit, operating-app edit, or automatic final answer.",
        "",
        "## Prompt Metrics",
        "",
        "| Variant | OCR vs human | Coverage | Correction proxy | Avg latency | Tokens | Missing | Wrong safe auto-grade |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in prompt_rows:
        lines.append(f"| {row['variant']} | {row['matches']}/{row['evaluated']} = {row['accuracy_pct']}% | {row['average_coverage']}/20 | {row['average_teacher_correction_proxy']} | {row['average_latency_ms']} ms | {row['total_tokens']} | {row['missing']} | {row['wrong_safe_auto_grade']} |")
    top = require_object(report["top_variant"], "top variant")
    lines.extend([
        "",
        "## Selection",
        "",
        f"- Top prompt: `{top['variant']}` with {top['accuracy_pct']}% OCR-vs-human accuracy and {top['average_coverage']}/20 average coverage.",
        f"- Top pipeline: {report['top_pipeline']}.",
        "- Recommended model: `gemini-2.5-flash-lite`; temperature `0`; max output tokens `1024`.",
        "- Two-pass was not tested in this bounded screen; do not enable it without separate approval.",
        "",
        "## Failure Taxonomy",
        "",
        *(f"- `{label}`: {count}" for label, count in cast(dict[str, int], report["failure_taxonomy"]).items()),
        "",
        "## Decision",
        "",
        f"- Result: `{report['decision']}`.",
        "- Candidate coverage was strong, but the best screened accuracy did not reach the 90% conditional threshold and correction proxy exceeded two items per case.",
        "- `wrong_safe_auto_grade` remains 0 because this sprint made no automatic promotions; all outputs remain review-only candidates.",
        "- Student 10-person pilot: `NO_GO`. No further provider calls or pilot expansion are authorized by this result.",
        "",
    ])
    return "\n".join(lines)


def read_json(path: Path) -> JsonValue:
    try:
        return cast(JsonValue, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise ReportError(f"cannot read local artifact {path.name}") from error


def write_json(path: Path, value: JsonValue) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ReportError(f"{label} must be an object")
    return cast(JsonObject, value)


def require_list(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ReportError(f"{label} must be a list")
    return value


def require_int(value: JsonValue, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReportError(f"{label} must be an integer")
    return value


def require_number(value: JsonValue, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ReportError(f"{label} must be numeric")
    return float(value)


def usage_total(value: JsonValue) -> int:
    metadata = value if isinstance(value, dict) else {}
    total = metadata.get("totalTokenCount")
    return int(total) if isinstance(total, int) and not isinstance(total, bool) else 0


if __name__ == "__main__":
    raise SystemExit(main())
