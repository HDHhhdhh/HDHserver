# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_next_action_queue_state_guard.py

from __future__ import annotations

import json
from typing import Final, TypedDict

from ocr_next_action_queue_state_model import (
    LATEST_HEADING,
    QUEUE_PATH,
    QueueStateReport,
    build_report as build_queue_state_report,
)
from ocr_preflight_environment_matrix_model import LAB, REPORT_JSON
from ocr_report_field_access import read_report
from verify_ocr_preflight_failure_classifier import REPORT_CLASSIFIER_JSON
from verify_ocr_preflight_report_freshness import REPORT_FRESHNESS_JSON

REPORT_JSON_OUT: Final = LAB / "ocr_next_action_queue_state_guard.json"
REPORT_MD_OUT: Final = LAB / "ocr_next_action_queue_state_guard.md"
TARGET_LINE: Final[str] = "- Current blocker: `training_pack_recognized_evidence_files_missing`"


class QueueStateGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_probe_passed: bool
    missing_latest_required_snippet_blocked: bool
    latest_required_snippet_removed_count: int
    mutated_missing_snippet_count: int
    mutated_missing_snippets: list[str]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    queue_text = QUEUE_PATH.read_text(encoding="utf-8")
    matrix = read_report(REPORT_JSON)
    classifier = read_report(REPORT_CLASSIFIER_JSON)
    freshness = read_report(REPORT_FRESHNESS_JSON)
    live = build_queue_state_report(queue_text, matrix, classifier, freshness)
    mutated_text, removed_count = remove_latest_line(queue_text, TARGET_LINE)
    mutated = build_queue_state_report(mutated_text, matrix, classifier, freshness)
    report = build_guard_report(live, mutated, removed_count)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def remove_latest_line(queue_text: str, target_line: str) -> tuple[str, int]:
    lines = queue_text.splitlines(keepends=True)
    latest_start = next(
        (index for index in range(len(lines) - 1, -1, -1) if lines[index].startswith("## ")),
        -1,
    )
    if latest_start < 0:
        return queue_text, 0
    if lines[latest_start].rstrip("\r\n") != LATEST_HEADING:
        return queue_text, 0
    latest_end = next(
        (index for index, line in enumerate(lines[latest_start + 1 :], start=latest_start + 1) if line.startswith("## ")),
        len(lines),
    )
    removed_count = 0
    kept_lines: list[str] = []
    for index, line in enumerate(lines):
        if latest_start <= index < latest_end and line.rstrip("\r\n") == target_line:
            removed_count += 1
            continue
        kept_lines.append(line)
    return "".join(kept_lines), removed_count


def build_guard_report(
    live: QueueStateReport,
    mutated: QueueStateReport,
    removed_count: int,
) -> QueueStateGuardReport:
    live_probe_passed = (
        live["ok"] is True and live["missing_snippet_count"] == 0 and live["latest_heading_at_tail"] is True
    )
    missing_probe_blocked = (
        removed_count == 1
        and mutated["ok"] is False
        and TARGET_LINE.removeprefix("- ") in mutated["latest_missing_snippets"]
        and mutated["latest_missing_snippet_count"] > 0
    )
    failed_probe_count = sum(
        1
        for passed in (
            live_probe_passed,
            missing_probe_blocked,
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
        "status": "OCR_NEXT_ACTION_QUEUE_STATE_GUARD_VERIFIED"
        if ok
        else "OCR_NEXT_ACTION_QUEUE_STATE_GUARD_FAILED",
        "probe_count": 2,
        "failed_probe_count": failed_probe_count,
        "live_probe_passed": live_probe_passed,
        "missing_latest_required_snippet_blocked": missing_probe_blocked,
        "latest_required_snippet_removed_count": removed_count,
        "mutated_missing_snippet_count": mutated["latest_missing_snippet_count"],
        "mutated_missing_snippets": mutated["latest_missing_snippets"],
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
        return "Keep this guard with queue-state verification before operator handoff."
    return "Restore the latest queue tail handoff section before operator handoff."


def markdown(report: QueueStateGuardReport) -> str:
    missing_lines = [f"- {snippet}" for snippet in report["mutated_missing_snippets"]] or ["- none"]
    return "\n".join((
        "# OCR Next-Action Queue State Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_probe_passed: `{report['live_probe_passed']}`",
        "- missing_latest_required_snippet_blocked: "
        f"`{report['missing_latest_required_snippet_blocked']}`",
        "- latest_required_snippet_removed_count: "
        f"`{report['latest_required_snippet_removed_count']}`",
        f"- mutated_missing_snippet_count: `{report['mutated_missing_snippet_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Mutated Missing Snippets",
        *missing_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
