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
class CaseSummary:
    case_id: str
    source: str
    total: int
    evaluated_total: int
    exact_matches: int
    ocr_vs_human_accuracy: float | None
    high_confidence_evaluated_total: int
    high_confidence_exact_matches: int
    high_confidence_ocr_vs_human_accuracy: float | None
    safe_auto_grade: int
    review_required: int
    retake_required: int
    data_check_required: int
    missing: int
    wrong_safe_auto_grade: int
    ambiguous_human_labels: int


@dataclass(frozen=True, slots=True)
class DashboardError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def dashboard(cases: tuple[CaseSummary, ...], gate_report: JsonObject) -> JsonObject:
    if len(cases) != 4:
        raise DashboardError("dashboard must cover four OCR accuracy cases")
    total_wrong_safe = sum(case.wrong_safe_auto_grade for case in cases)
    total_evaluated = sum(case.evaluated_total for case in cases)
    total_matches = sum(case.exact_matches for case in cases)
    high_total = sum(case.high_confidence_evaluated_total for case in cases)
    high_matches = sum(case.high_confidence_exact_matches for case in cases)
    return {
        "ok": total_wrong_safe == 0,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "provider_free_gate_count": require_int(gate_report.get("gate_count"), "gate_count"),
        "case_count": len(cases),
        "total_questions": sum(case.total for case in cases),
        "evaluated_total": total_evaluated,
        "exact_matches": total_matches,
        "weighted_ocr_vs_human_accuracy": accuracy(total_matches, total_evaluated),
        "high_confidence_evaluated_total": high_total,
        "high_confidence_exact_matches": high_matches,
        "weighted_high_confidence_ocr_vs_human_accuracy": accuracy(high_matches, high_total),
        "safe_auto_grade": sum(case.safe_auto_grade for case in cases),
        "review_required": sum(case.review_required for case in cases),
        "retake_required": sum(case.retake_required for case in cases),
        "data_check_required": sum(case.data_check_required for case in cases),
        "missing": sum(case.missing for case in cases),
        "ambiguous_human_labels": sum(case.ambiguous_human_labels for case in cases),
        "wrong_safe_auto_grade": total_wrong_safe,
        "cases": [asdict(case) for case in cases],
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_common_zero_calls(report: JsonObject) -> None:
    if report.get("ok") is not True:
        raise DashboardError("provider-free gate must pass before dashboard")
    if report.get("student_facing") is not False:
        raise DashboardError("provider-free gate must be non-student-facing")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(report.get(key), 0, key)


def recognized_value(item: JsonObject) -> bool:
    value = text_value(item.get("recognized"))
    return value != "" and value != "?"


def accuracy(matches: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(matches * 100 / total, 1)


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), str(path.name))


def assert_no_output_leaks(output: JsonObject) -> None:
    text = json.dumps(output, ensure_ascii=False)
    forbidden_hits = [key for key in FORBIDDEN_OUTPUT_KEYS if f'"{key}"' in text]
    if forbidden_hits:
        raise DashboardError(f"dashboard output contains forbidden fields: {', '.join(forbidden_hits)}")
    path_hits = [token for token in PATH_TOKENS if token in text]
    if path_hits:
        raise DashboardError(f"dashboard output contains path-like tokens: {', '.join(path_hits)}")


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise DashboardError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise DashboardError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise DashboardError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise DashboardError(f"{label} expected {expected}, got {actual}")


def require_number_or_none(value: JsonValue, label: str) -> float | None:
    match value:
        case None:
            return None
        case int() | float() if not isinstance(value, bool):
            return float(value)
        case bool() | str() | list() | dict():
            raise DashboardError(f"{label} must be numeric or null")
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


def markdown(output: JsonObject, cases: tuple[CaseSummary, ...]) -> str:
    lines = [
        "# OCR Case Accuracy Dashboard",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- production default: `NO-GO`",
        f"- provider-free gates covered: {output['provider_free_gate_count']}",
        f"- cases covered: {output['case_count']}",
        f"- weighted OCR vs human accuracy: {output['weighted_ocr_vs_human_accuracy']}",
        f"- weighted high-confidence OCR vs human accuracy: {output['weighted_high_confidence_ocr_vs_human_accuracy']}",
        f"- wrong safe auto-grade total: {output['wrong_safe_auto_grade']}",
        "",
        "| Case | OCR vs human | High-confidence | Evaluated | Safe | Review | Missing | Wrong safe | Ambiguous |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in cases:
        lines.append(
            f"| {case.case_id} | {case.ocr_vs_human_accuracy} | {case.high_confidence_ocr_vs_human_accuracy} | "
            f"{case.evaluated_total} | {case.safe_auto_grade} | {case.review_required} | {case.missing} | "
            f"{case.wrong_safe_auto_grade} | {case.ambiguous_human_labels} |",
        )
    lines.extend(
        (
            "",
            "Notes:",
            "- This dashboard reuses existing human-transcription eval artifacts and does not regenerate recognized/cache files.",
            "- The output intentionally omits expected/canonical/grading fields and filesystem paths.",
        ),
    )
    return "\n".join(lines) + "\n"
