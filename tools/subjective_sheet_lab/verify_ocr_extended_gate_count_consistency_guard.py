from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final, TypedDict

from ocr_extended_gate_count_consistency_model import (
    COUNT_PATTERN,
    CountConsistencyReport,
    build_report,
)
from ocr_next_action_queue_state_model import LATEST_HEADING, QUEUE_PATH, latest_heading_index
from ocr_preflight_environment_matrix_model import LAB, JsonValue, REPORT_JSON
from ocr_report_field_access import read_report
from verify_ocr_extended_gate_count_consistency import EXTENDED_REPORT_JSON, modified_times_ns
from verify_ocr_next_action_queue_state import REPORT_JSON_OUT as QUEUE_STATE_JSON
from verify_ocr_operator_next_action_summary import REPORT_JSON as OPERATOR_SUMMARY_JSON
from verify_ocr_preflight_failure_classifier import REPORT_CLASSIFIER_JSON
from verify_ocr_preflight_report_freshness import REPORT_FRESHNESS_JSON

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_extended_gate_count_consistency_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_extended_gate_count_consistency_guard.md"


class CountConsistencyGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_probe_passed: bool
    missing_latest_queue_count_line_probe_blocked: bool
    latest_queue_count_line_removed_count: int
    live_latest_queue_count_match_count: int
    mutated_latest_queue_count_match_count: int
    mutated_issue_count: int
    mutated_issues: list[str]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    report_paths = consistency_report_paths()
    reports = consistency_reports(report_paths)
    queue_text = QUEUE_PATH.read_text(encoding="utf-8")
    live = build_report(reports, queue_text, modified_times_ns(report_paths))
    mutated_queue_text, removed_count = remove_latest_count_lines(queue_text)
    mutated = build_report(reports, mutated_queue_text, modified_times_ns(report_paths))
    report = build_guard_report(live, mutated, removed_count)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def consistency_report_paths() -> Mapping[str, Path]:
    return {
        "extended": EXTENDED_REPORT_JSON,
        "matrix": REPORT_JSON,
        "classifier": REPORT_CLASSIFIER_JSON,
        "freshness": REPORT_FRESHNESS_JSON,
        "queue_state": QUEUE_STATE_JSON,
        "operator_summary": OPERATOR_SUMMARY_JSON,
    }


def consistency_reports(paths: Mapping[str, Path]) -> Mapping[str, Mapping[str, JsonValue]]:
    return {name: read_report(path) for name, path in paths.items()}


def remove_latest_count_lines(queue_text: str) -> tuple[str, int]:
    lines = queue_text.splitlines(keepends=True)
    latest_start = latest_heading_index([line.rstrip("\r\n") for line in lines])
    if latest_start is None:
        return queue_text, 0
    latest_end = next(
        (
            index
            for index, line in enumerate(lines[latest_start + 1 :], start=latest_start + 1)
            if line.startswith("## ")
        ),
        len(lines),
    )
    removed_count = 0
    kept_lines: list[str] = []
    for index, line in enumerate(lines):
        if latest_start <= index < latest_end and COUNT_PATTERN.search(line):
            removed_count += 1
            continue
        kept_lines.append(line)
    return "".join(kept_lines), removed_count


def latest_heading() -> str:
    return LATEST_HEADING


def build_guard_report(
    live: CountConsistencyReport,
    mutated: CountConsistencyReport,
    removed_count: int,
) -> CountConsistencyGuardReport:
    live_probe_passed = live["ok"] is True and live["latest_queue_count_match_count"] == 1
    missing_count_line_blocked = (
        removed_count == 1
        and mutated["ok"] is False
        and mutated["latest_queue_count_match_count"] == 0
        and "latest queue section should contain one count, found 0" in mutated["issues"]
    )
    failed_probe_count = sum(
        1
        for passed in (
            live_probe_passed,
            missing_count_line_blocked,
            live["provider_call_count"] == 0,
            live["external_ocr_api_call_count"] == 0,
            live["submit_test_call_count"] == 0,
            live["ts_submit_click_count"] == 0,
            live["answer_key_or_grading_field_leak_count"] == 0,
            live["filesystem_path_leak_count"] == 0,
            live["production_default"] == "NO_GO",
        )
        if not passed
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_EXTENDED_GATE_COUNT_CONSISTENCY_GUARD_VERIFIED"
        if ok
        else "OCR_EXTENDED_GATE_COUNT_CONSISTENCY_GUARD_FAILED",
        "probe_count": 2,
        "failed_probe_count": failed_probe_count,
        "live_probe_passed": live_probe_passed,
        "missing_latest_queue_count_line_probe_blocked": missing_count_line_blocked,
        "latest_queue_count_line_removed_count": removed_count,
        "live_latest_queue_count_match_count": live["latest_queue_count_match_count"],
        "mutated_latest_queue_count_match_count": mutated["latest_queue_count_match_count"],
        "mutated_issue_count": mutated["issue_count"],
        "mutated_issues": mutated["issues"],
        "provider_call_count": live["provider_call_count"],
        "external_ocr_api_call_count": live["external_ocr_api_call_count"],
        "submit_test_call_count": live["submit_test_call_count"],
        "ts_submit_click_count": live["ts_submit_click_count"],
        "answer_key_or_grading_field_leak_count": live["answer_key_or_grading_field_leak_count"],
        "filesystem_path_leak_count": live["filesystem_path_leak_count"],
        "production_default": live["production_default"],
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this guard in the provider-free chain before operator handoff."
    return "Fix latest queue count evidence before refreshing operator handoff."


def markdown(report: CountConsistencyGuardReport) -> str:
    issue_lines = [f"- {issue}" for issue in report["mutated_issues"]] or ["- none"]
    return "\n".join((
        "# OCR Extended Gate Count Consistency Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_probe_passed: `{report['live_probe_passed']}`",
        f"- missing_latest_queue_count_line_probe_blocked: `{report['missing_latest_queue_count_line_probe_blocked']}`",
        f"- latest_queue_count_line_removed_count: `{report['latest_queue_count_line_removed_count']}`",
        f"- live_latest_queue_count_match_count: `{report['live_latest_queue_count_match_count']}`",
        f"- mutated_latest_queue_count_match_count: `{report['mutated_latest_queue_count_match_count']}`",
        f"- mutated_issue_count: `{report['mutated_issue_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Mutated Issues",
        *issue_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
