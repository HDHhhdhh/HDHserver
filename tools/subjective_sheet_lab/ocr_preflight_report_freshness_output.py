from __future__ import annotations

from typing import assert_never

from ocr_preflight_report_freshness_model import FreshnessReport, FreshnessStatus


def next_safe_action(status: FreshnessStatus) -> str:
    match status:
        case "fresh_and_consistent":
            return "Continue provider-free OCR lab work; live OCR remains approval gated."
        case "stale_or_inconsistent":
            return "Refresh matrix/classifier reports before using env split readiness."
        case unreachable:
            assert_never(unreachable)


def markdown(report: FreshnessReport) -> str:
    issue_lines = [f"- {issue}" for issue in report["issues"]] or ["- none"]
    return "\n".join((
        "# OCR Preflight Report Freshness",
        "",
        f"- ok: {report['ok']}",
        f"- status: {report['status']}",
        f"- classifier_newer_than_matrix: {report['classifier_newer_than_matrix']}",
        f"- counts_agree: {report['counts_agree']}",
        f"- zero_call_counts: {report['zero_call_counts']}",
        f"- zero_leak_counts: {report['zero_leak_counts']}",
        f"- production_default: {report['production_default']}",
        f"- production_default_no_go: {report['production_default_no_go']}",
        f"- preflight_script_modified: {report['preflight_script_modified']}",
        f"- extended_gate_count: {report['extended_gate_count']}",
        f"- issue_count: {report['issue_count']}",
        "",
        "## Source Reports",
        f"- matrix: {report['matrix_report']}",
        f"- classifier: {report['classifier_report']}",
        "",
        "## Issues",
        *issue_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))
