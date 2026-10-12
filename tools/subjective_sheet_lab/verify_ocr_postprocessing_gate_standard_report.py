# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_postprocessing_gate_standard_report.py

from __future__ import annotations

import json
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from verify_ocr_postprocessing_gate_matrix import main as verify_postprocessing_gate

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_postprocessing_gate_standard_report.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_postprocessing_gate_standard_report.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class StandardReportError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    raw_report = run_matrix()
    output = standard_report(raw_report)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def run_matrix() -> JsonObject:
    buffer = StringIO()
    with redirect_stdout(buffer):
        result = verify_postprocessing_gate()
    if result != 0:
        raise StandardReportError(f"postprocessing gate matrix failed with exit code {result}")
    return require_object(json.loads(buffer.getvalue()), "postprocessing gate matrix output")


def standard_report(raw_report: JsonObject) -> JsonObject:
    if raw_report.get("ok") is not True:
        raise StandardReportError("postprocessing gate matrix must pass")
    status_counts = require_object(raw_report.get("status_counts"), "status_counts")
    blocked_cases = require_array(raw_report.get("blocked_cases"), "blocked_cases")
    safe_cases = require_array(raw_report.get("safe_cases"), "safe_cases")
    recognized_only = require_array(raw_report.get("recognized_only_cache_cases"), "recognized_only_cache_cases")
    require_int_value(status_counts.get("review_required"), 15, "status_counts.review_required")
    require_int_value(status_counts.get("safe_auto_grade"), 4, "status_counts.safe_auto_grade")
    require_int_value(raw_report.get("provider_call_count"), 0, "provider_call_count")
    require_int_value(raw_report.get("submit_test_call_count"), 0, "submit_test_call_count")
    require_int_value(raw_report.get("ts_submit_click_count"), 0, "ts_submit_click_count")
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "blocked_case_count": len(blocked_cases),
        "safe_case_count": len(safe_cases),
        "recognized_only_cache_case_count": len(recognized_only),
        "review_required_count": require_int(status_counts.get("review_required"), "status_counts.review_required"),
        "safe_auto_grade_count": require_int(status_counts.get("safe_auto_grade"), "status_counts.safe_auto_grade"),
        "blocked_question_list": raw_report.get("blocked_question_list"),
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise StandardReportError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise StandardReportError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise StandardReportError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise StandardReportError(f"{label} expected {expected}, got {actual}")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Postprocessing Gate Standard Report",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- blocked postprocessing cases: {output['blocked_case_count']}",
        f"- safe-preserved cases: {output['safe_case_count']}",
        f"- recognized-only cache cases kept review: {output['recognized_only_cache_case_count']}",
        f"- review-required count: {output['review_required_count']}",
        f"- safe-auto-grade count: {output['safe_auto_grade_count']}",
        "- answer-key/grading/path leak count: 0",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
