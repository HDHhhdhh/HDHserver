# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by human_transcription_eval.py; not intended as a direct CLI.

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Protocol, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class ConfigLike(Protocol):
    case_dir: Path


class SummaryLike(Protocol):
    total: int
    ocr_evaluated_total: int
    exact_or_normalized_match: int
    mismatch_vs_human: int
    mismatch_vs_expected: int
    missing: int
    ambiguous_human_label_count: int
    ocr_recognition_accuracy_against_human_transcription: float
    answer_key_grading_accuracy_recognized_vs_expected: float
    source_wrong_safe_auto_grade_against_human_transcription: int
    wrong_safe_auto_grade_against_human_transcription: int
    safe_auto_grade: int
    review_required: int
    data_check_required: int


class RowLike(Protocol):
    question_no: int
    human_answer: str
    human_confidence: str
    recognized: str
    expected: str
    match_to_human: bool
    match_to_expected: bool
    source_final_policy: str
    existing_final_policy: str
    policy_warnings: tuple[str, ...]
    crop_path: str
    notes: str


class SourceHashLike(Protocol):
    role: str
    path: str
    sha256: str


def write_outputs(
    config: ConfigLike,
    summary: SummaryLike,
    rows: tuple[RowLike, ...],
    source_hashes: tuple[SourceHashLike, ...],
) -> None:
    payload = {
        "audience": "developer_lab_only",
        "student_facing": False,
        "summary": summary_to_dict(summary),
        "source_hashes": [source_hash_to_dict(item) for item in source_hashes],
        "items": [row_to_dict(row) for row in rows],
    }
    (config.case_dir / "human_transcription_eval.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(config.case_dir / "human_transcription_eval.csv", rows)
    write_markdown(config.case_dir / "human_transcription_eval.md", summary, rows)
    write_interpretation(config.case_dir / "combined_case_interpretation.md", summary, rows)


def summary_to_dict(summary: SummaryLike) -> dict[str, JsonValue]:
    return {
        "total": summary.total,
        "ocr_evaluated_total": summary.ocr_evaluated_total,
        "exact_or_normalized_match": summary.exact_or_normalized_match,
        "mismatch_vs_human": summary.mismatch_vs_human,
        "mismatch_vs_expected": summary.mismatch_vs_expected,
        "missing": summary.missing,
        "ambiguous_human_label_count": summary.ambiguous_human_label_count,
        "ocr_recognition_accuracy_against_human_transcription": summary.ocr_recognition_accuracy_against_human_transcription,
        "answer_key_grading_accuracy_recognized_vs_expected": summary.answer_key_grading_accuracy_recognized_vs_expected,
        "source_wrong_safe_auto_grade_against_human_transcription": summary.source_wrong_safe_auto_grade_against_human_transcription,
        "wrong_safe_auto_grade_against_human_transcription": summary.wrong_safe_auto_grade_against_human_transcription,
        "safe_auto_grade": summary.safe_auto_grade,
        "review_required": summary.review_required,
        "data_check_required": summary.data_check_required,
    }


def row_to_dict(row: RowLike) -> dict[str, JsonValue]:
    return {
        "question_no": row.question_no,
        "human_answer": row.human_answer,
        "human_confidence": row.human_confidence,
        "recognized": row.recognized,
        "expected": row.expected,
        "match_to_human": row.match_to_human,
        "match_to_expected": row.match_to_expected,
        "source_final_policy": row.source_final_policy,
        "effective_policy": row.existing_final_policy,
        "existing_final_policy": row.existing_final_policy,
        "policy_warnings": list(row.policy_warnings),
        "crop_path": row.crop_path,
        "notes": row.notes,
    }


def source_hash_to_dict(source_hash: SourceHashLike) -> dict[str, JsonValue]:
    return {"role": source_hash.role, "path": source_hash.path, "sha256": source_hash.sha256}


def write_csv(path: Path, rows: tuple[RowLike, ...]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "question_no",
            "human_answer",
            "human_confidence",
            "recognized",
            "expected",
            "match_to_human",
            "match_to_expected",
            "source_final_policy",
            "effective_policy",
            "existing_final_policy",
            "policy_warnings",
            "crop_path",
            "notes",
        ])
        for row in rows:
            writer.writerow([
                row.question_no,
                row.human_answer,
                row.human_confidence,
                row.recognized,
                row.expected,
                row.match_to_human,
                row.match_to_expected,
                row.source_final_policy,
                row.existing_final_policy,
                row.existing_final_policy,
                ";".join(row.policy_warnings),
                row.crop_path,
                row.notes,
            ])


def write_markdown(path: Path, summary: SummaryLike, rows: tuple[RowLike, ...]) -> None:
    lines = summary_lines(summary) + ["", "## Mismatch vs Human Transcription", ""]
    human_mismatches = tuple(row for row in rows if row.human_confidence != "low" and not row.match_to_human)
    if human_mismatches:
        lines += ["| q | human | recognized | notes |", "|---:|---|---|---|"]
        lines += [f"| {row.question_no} | `{row.human_answer}` | `{row.recognized}` | {row.notes} |" for row in human_mismatches]
    else:
        lines.append("- none")
    lines += [
        "",
        "## Per-question Rows",
        "",
        "| q | human | recognized | expected | human match | expected match | policy | confidence | notes |",
        "|---:|---|---|---|---:|---:|---|---|---|",
    ]
    lines += [
        f"| {row.question_no} | `{row.human_answer}` | `{row.recognized}` | `{row.expected}` | {row.match_to_human} | {row.match_to_expected} | {row.existing_final_policy} | {row.human_confidence} | {row.notes} {format_warnings(row.policy_warnings)} |"
        for row in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_interpretation(path: Path, summary: SummaryLike, rows: tuple[RowLike, ...]) -> None:
    key_mismatches = tuple(row for row in rows if not row.match_to_expected)
    human_mismatches = tuple(row for row in rows if row.human_confidence != "low" and not row.match_to_human)
    lines = summary_lines(summary) + [
        "",
        "## Answer-key vs OCR Separation",
        "",
        "| q | expected | human transcription | recognized | match_to_human | notes |",
        "|---:|---|---|---|---:|---|",
    ]
    lines += [
        f"| {row.question_no} | `{row.expected}` | `{row.human_answer}` | `{row.recognized}` | {row.match_to_human} | {row.notes} |"
        for row in key_mismatches
    ]
    lines += [
        "",
        "## OCR vs Human Transcription Mismatches",
        "",
        "| q | source policy | effective policy | human transcription | recognized | warnings | notes |",
        "|---:|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {row.question_no} | {row.source_final_policy} | {row.existing_final_policy} | `{row.human_answer}` | `{row.recognized}` | {', '.join(row.policy_warnings)} | {row.notes} |"
        for row in human_mismatches
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summary_lines(summary: SummaryLike) -> list[str]:
    return [
        "# Human Transcription OCR Evaluation",
        "",
        "Developer/lab-only report. It may include expected answer-key values and must not be shown in student-facing UI.",
        "",
        f"- total: {summary.total}",
        f"- OCR transcription accuracy: {summary.exact_or_normalized_match}/{summary.ocr_evaluated_total} = {summary.ocr_recognition_accuracy_against_human_transcription}%",
        f"- answer-key grading accuracy: {summary.answer_key_grading_accuracy_recognized_vs_expected}%",
        f"- source wrong_safe_auto_grade against human transcription: {summary.source_wrong_safe_auto_grade_against_human_transcription}",
        f"- wrong_safe_auto_grade against human transcription: {summary.wrong_safe_auto_grade_against_human_transcription}",
        f"- safe_auto_grade: {summary.safe_auto_grade}",
        f"- review_required: {summary.review_required}",
        f"- data_check_required: {summary.data_check_required}",
        f"- missing: {summary.missing}",
        f"- ambiguous human labels: {summary.ambiguous_human_label_count}",
    ]


def format_warnings(warnings: tuple[str, ...]) -> str:
    return "" if not warnings else f"(warnings: {', '.join(warnings)})"
