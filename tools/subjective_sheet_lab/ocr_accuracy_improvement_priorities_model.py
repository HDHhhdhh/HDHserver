from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue

FORBIDDEN_OUTPUT_KEYS: Final[frozenset[str]] = frozenset(
    ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "grading", "score", "answer_key_used"),
)
PATH_TOKENS: Final[tuple[str, ...]] = ("C:\\", "C:/", "server-ocr", "crop_benchmark_inputs", "phase2c_route_uploads")


@dataclass(frozen=True, slots=True)
class RowPriority:
    case_id: str
    question_no: int
    priority: int
    issue_type: str
    confidence: str
    recognized: str
    human_answer: str
    policy_status: str
    reason: str


@dataclass(frozen=True, slots=True)
class CasePriority:
    case_id: str
    priority: int
    issue_type: str
    review_required: int
    safe_auto_grade: int
    missing: int
    accuracy: float | None
    reason: str


@dataclass(frozen=True, slots=True)
class PriorityError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def report(rows: tuple[RowPriority, ...], cases: tuple[CasePriority, ...], dashboard: JsonObject) -> JsonObject:
    wrong_safe = require_int(dashboard.get("wrong_safe_auto_grade"), "wrong_safe_auto_grade")
    if wrong_safe != 0:
        raise PriorityError("wrong_safe_auto_grade must remain zero before prioritizing accuracy work")
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "dashboard_weighted_accuracy": dashboard.get("weighted_ocr_vs_human_accuracy"),
        "dashboard_weighted_high_confidence_accuracy": dashboard.get("weighted_high_confidence_ocr_vs_human_accuracy"),
        "wrong_safe_auto_grade": wrong_safe,
        "row_priority_count": len(rows),
        "case_priority_count": len(cases),
        "top_row_priorities": [asdict(item) for item in rows[:12]],
        "case_priorities": [asdict(item) for item in cases],
        "next_actions": [
            "target high-confidence mismatches before low-confidence handwriting ambiguity",
            "reduce missing/unresolved rows only when safe review routing stays intact",
            "keep wrong_safe_auto_grade at zero as the non-negotiable gate",
        ],
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_dashboard(dashboard: JsonObject) -> None:
    for key in (
        "provider_call_count",
        "external_ocr_api_call_count",
        "submit_test_call_count",
        "ts_submit_click_count",
        "wrong_safe_auto_grade",
    ):
        require_int_value(dashboard.get(key), 0, key)
    if dashboard.get("student_facing") is not False:
        raise PriorityError("dashboard must be non-student-facing")


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), path.name)


def assert_no_output_leaks(output: JsonObject) -> None:
    text = json.dumps(output, ensure_ascii=False)
    forbidden_hits = [key for key in FORBIDDEN_OUTPUT_KEYS if f'"{key}"' in text]
    if forbidden_hits:
        raise PriorityError(f"priority output contains forbidden fields: {', '.join(forbidden_hits)}")
    path_hits = [token for token in PATH_TOKENS if token in text]
    if path_hits:
        raise PriorityError(f"priority output contains path-like tokens: {', '.join(path_hits)}")


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise PriorityError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise PriorityError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise PriorityError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise PriorityError(f"{label} expected {expected}, got {actual}")


def number_or_none(value: JsonValue) -> float | None:
    match value:
        case None:
            return None
        case int() | float() if not isinstance(value, bool):
            return float(value)
        case bool() | str() | list() | dict():
            return None
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


def markdown(output: JsonObject, rows: tuple[RowPriority, ...], cases: tuple[CasePriority, ...]) -> str:
    lines = [
        "# OCR Accuracy Improvement Priorities",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- production default: `NO-GO`",
        f"- dashboard weighted accuracy: {output['dashboard_weighted_accuracy']}",
        f"- dashboard high-confidence accuracy: {output['dashboard_weighted_high_confidence_accuracy']}",
        f"- wrong safe auto-grade: {output['wrong_safe_auto_grade']}",
        "",
        "| Priority | Case | q | Type | Confidence | OCR | Human | Policy |",
        "|---:|---|---:|---|---|---|---|---|",
    ]
    for item in rows[:12]:
        lines.append(
            f"| {item.priority} | {item.case_id} | {item.question_no} | {item.issue_type} | {item.confidence} | "
            f"{item.recognized} | {item.human_answer} | {item.policy_status} |",
        )
    lines.extend(("", "## Case-Level Targets", ""))
    lines.extend(("| Priority | Case | Type | Review | Safe | Missing | Accuracy |", "|---:|---|---|---:|---:|---:|---:|"))
    for item in cases:
        lines.append(
            f"| {item.priority} | {item.case_id} | {item.issue_type} | {item.review_required} | "
            f"{item.safe_auto_grade} | {item.missing} | {item.accuracy} |",
        )
    return "\n".join(lines) + "\n"
