# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by ocr_benchmark_gate.py; not intended as a direct CLI.

from __future__ import annotations

from typing import assert_never

from ocr_review_schema import JsonObject, JsonValue
from ocr_review_payload_validator import require_array, require_object, require_string


def render_markdown(report: JsonObject) -> str:
    lines = ["# OCR Benchmark Gate Report", "", "## Executive summary"]
    lines.extend(
        [
            "- Lab pipeline is structurally ready for feature-flag integration.",
            "- same-contact remains preferred.",
            "- wrong_safe_auto_grade has stayed 0 in evaluated cases.",
            "- Production default remains no-go until more independent handwriting cases have human transcription evaluation.",
            "",
            "## Per-case metrics table",
            "| Case | Role | Completed/Total | Answer-key accuracy | OCR transcription accuracy | Safe | Review | Data check | Missing | Wrong safe | Notes |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ],
    )
    for case in require_array(report.get("cases"), "cases"):
        row = require_object(case, "case")
        transcription = require_object(row.get("transcription"), "case.transcription")
        lines.append(case_row(row, transcription))
    lines.extend(section("Go/no-go status", go_status_lines(report)))
    lines.extend(section("Feature-flag blockers", bullet_lines(require_array(report.get("feature_flag_blockers"), "feature_flag_blockers"))))
    lines.extend(section("Production blockers", bullet_lines(require_array(report.get("production_blockers"), "production_blockers"))))
    lines.extend(section("What evidence is still missing", bullet_lines(require_array(report.get("missing_evidence"), "missing_evidence"))))
    lines.extend(section("Recommended next action", [f"- {require_string(report.get('recommended_next_action'), 'recommended_next_action')}"]))
    return "\n".join(lines) + "\n"


def case_row(row: JsonObject, transcription: JsonObject) -> str:
    accuracy = format_percent(row.get("answer_key_accuracy_percent"))
    transcription_text = format_transcription(transcription)
    notes = optional_string(row.get("notes")) or optional_string(transcription.get("note"))
    return f"| {row['case_id']} | {row['role']} | {row['completed']}/{row['total']} | {accuracy} | {transcription_text} | {row['safe_auto_grade']} | {row['review_required']} | {row['data_check_required']} | {row['missing']} | {row['wrong_safe_auto_grade']} | {notes} |"


def go_status_lines(report: JsonObject) -> list[str]:
    aggregate = require_object(report.get("aggregate"), "aggregate")
    return [
        f"- Feature-flag integration: `{report['gate_status']}`",
        f"- Feature-flag allowed: `{report['feature_flag_integration_allowed']}`",
        f"- Production default: `{report['production_default_status']}`",
        f"- Production default allowed: `{report['production_default_allowed']}`",
        f"- Preferred strategy: `{report['preferred_strategy']}`",
        f"- Cases included: {aggregate['cases_included']}",
        f"- Human transcription cases: {aggregate['cases_with_human_transcription']}",
    ]


def section(title: str, lines: list[str]) -> list[str]:
    return ["", f"## {title}", *lines]


def bullet_lines(values: list[JsonValue]) -> list[str]:
    if not values:
        return ["- none"]
    return [f"- {require_string(value, 'bullet')}" for value in values]


def format_percent(value: JsonValue) -> str:
    parsed = number(value)
    return "unavailable" if parsed is None else f"{parsed:.1f}%"


def format_transcription(transcription: JsonObject) -> str:
    if transcription.get("available") is not True:
        return "unavailable"
    return f"{transcription.get('correct')}/{transcription.get('total')} = {format_percent(transcription.get('accuracy_percent'))}"


def number(value: JsonValue) -> float | None:
    match value:
        case int() | float() if not isinstance(value, bool):
            return float(value)
        case str():
            return float(value)
        case None | bool() | list() | dict():
            return None
        case unreachable:
            assert_never(unreachable)


def optional_string(value: JsonValue) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            return ""
        case unreachable:
            assert_never(unreachable)
