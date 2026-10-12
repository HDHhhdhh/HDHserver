# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_preflight_report_freshness.py

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import assert_never

from ocr_preflight_environment_matrix_model import REPORT_JSON, ROOT, JsonValue
from ocr_preflight_environment_matrix_output import parse_json
from ocr_preflight_report_freshness_model import (
    AGREEMENT_FIELDS,
    REPORT_FRESHNESS_JSON,
    REPORT_FRESHNESS_MD,
    ZERO_COUNT_FIELDS,
    FreshnessReport,
    FreshnessStatus,
    ParsedReport,
)
from ocr_preflight_report_freshness_output import markdown, next_safe_action
from ocr_report_field_access import bool_field, int_field, nullable_int_field, str_field
from verify_ocr_preflight_failure_classifier import REPORT_CLASSIFIER_JSON


def main() -> int:
    matrix = load_report("matrix", REPORT_JSON)
    classifier = load_report("classifier", REPORT_CLASSIFIER_JSON)
    report = build_freshness_report(matrix, classifier)
    REPORT_FRESHNESS_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_FRESHNESS_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def load_report(label: str, path: Path) -> ParsedReport:
    if not path.is_file():
        return ParsedReport(label, path, False, None, None)
    parsed = parse_json(path.read_text(encoding="utf-8"))
    match parsed:
        case dict() as data:
            return ParsedReport(label, path, True, path.stat().st_mtime_ns, data)
        case None | bool() | int() | float() | str() | list():
            return ParsedReport(label, path, True, path.stat().st_mtime_ns, None)
        case unreachable:
            assert_never(unreachable)


def build_freshness_report(matrix: ParsedReport, classifier: ParsedReport) -> FreshnessReport:
    issues = collect_issues(matrix, classifier)
    status: FreshnessStatus = "fresh_and_consistent" if len(issues) == 0 else "stale_or_inconsistent"
    matrix_data = data_or_empty(matrix)
    classifier_data = data_or_empty(classifier)
    production_default = str_field(classifier_data, "production_default")
    return {
        "ok": len(issues) == 0,
        "status": status,
        "student_facing": False,
        "matrix_report": relative_label(matrix.path),
        "classifier_report": relative_label(classifier.path),
        "matrix_exists": matrix.exists,
        "classifier_exists": classifier.exists,
        "matrix_modified_ns": matrix.modified_ns,
        "classifier_modified_ns": classifier.modified_ns,
        "classifier_newer_than_matrix": classifier_newer_than_matrix(matrix, classifier),
        "matrix_ok": bool_field(matrix_data, "ok"),
        "classifier_ok": bool_field(classifier_data, "ok"),
        "classifier_status": str_field(classifier_data, "status"),
        "matrix_path_matches": matrix_path_matches(classifier_data),
        "counts_agree": counts_agree(matrix_data, classifier_data),
        "zero_call_counts": zero_call_counts(classifier_data),
        "zero_leak_counts": zero_leak_counts(classifier_data),
        "production_default": production_default,
        "production_default_no_go": production_default == "NO_GO",
        "preflight_script_modified": bool_field(classifier_data, "preflight_script_modified"),
        "extended_gate_count": nullable_int_field(classifier_data, "extended_gate_count"),
        "issue_count": len(issues),
        "issues": issues,
        "provider_call_count": int_field(classifier_data, "provider_call_count"),
        "external_ocr_api_call_count": int_field(classifier_data, "external_ocr_api_call_count"),
        "submit_test_call_count": int_field(classifier_data, "submit_test_call_count"),
        "ts_submit_click_count": int_field(classifier_data, "ts_submit_click_count"),
        "answer_key_or_grading_field_leak_count": int_field(
            classifier_data,
            "answer_key_or_grading_field_leak_count",
        ),
        "filesystem_path_leak_count": int_field(classifier_data, "filesystem_path_leak_count"),
        "next_safe_action": next_safe_action(status),
    }


def collect_issues(matrix: ParsedReport, classifier: ParsedReport) -> list[str]:
    issues: list[str] = []
    matrix_data = data_or_empty(matrix)
    classifier_data = data_or_empty(classifier)
    add_file_issues(issues, matrix)
    add_file_issues(issues, classifier)
    if not classifier_newer_than_matrix(matrix, classifier):
        issues.append("classifier report is older than matrix report")
    if not bool_field(matrix_data, "ok"):
        issues.append("matrix report is not ok")
    if not bool_field(classifier_data, "ok"):
        issues.append("classifier report is not ok")
    if str_field(classifier_data, "status") != "environment_split_verified":
        issues.append("classifier status is not environment_split_verified")
    if not matrix_path_matches(classifier_data):
        issues.append("classifier matrix_report does not match matrix report path")
    if not counts_agree(matrix_data, classifier_data):
        issues.append("matrix and classifier safety fields disagree")
    if not zero_call_counts(classifier_data):
        issues.append("provider or submit call count is nonzero")
    if not zero_leak_counts(classifier_data):
        issues.append("answer-key/grading or filesystem-path leak count is nonzero")
    if str_field(classifier_data, "production_default") != "NO_GO":
        issues.append("production default is not NO_GO")
    if bool_field(classifier_data, "preflight_script_modified"):
        issues.append("forbidden preflight script was modified")
    return issues


def add_file_issues(issues: list[str], report: ParsedReport) -> None:
    if not report.exists:
        issues.append(f"{report.label} report is missing")
    if report.data is None:
        issues.append(f"{report.label} report is not a JSON object")


def data_or_empty(report: ParsedReport) -> Mapping[str, JsonValue]:
    if report.data is None:
        return {}
    return report.data


def classifier_newer_than_matrix(matrix: ParsedReport, classifier: ParsedReport) -> bool:
    if matrix.modified_ns is None or classifier.modified_ns is None:
        return False
    return classifier.modified_ns >= matrix.modified_ns


def matrix_path_matches(classifier_data: Mapping[str, JsonValue]) -> bool:
    return str_field(classifier_data, "matrix_report") == relative_label(REPORT_JSON)


def counts_agree(matrix_data: Mapping[str, JsonValue], classifier_data: Mapping[str, JsonValue]) -> bool:
    return all(json_field(matrix_data, field) == json_field(classifier_data, field) for field in AGREEMENT_FIELDS)


def zero_call_counts(classifier_data: Mapping[str, JsonValue]) -> bool:
    return all(int_field(classifier_data, field) == 0 for field in ZERO_COUNT_FIELDS[:4])


def zero_leak_counts(classifier_data: Mapping[str, JsonValue]) -> bool:
    return all(int_field(classifier_data, field) == 0 for field in ZERO_COUNT_FIELDS[4:])


def relative_label(path: Path) -> str:
    return str(path.relative_to(ROOT))


def json_field(data: Mapping[str, JsonValue], field: str) -> JsonValue:
    return data.get(field)


if __name__ == "__main__":
    raise SystemExit(main())
