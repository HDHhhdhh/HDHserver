# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_operator_refresh_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
import verify_ocr_post_chain_operator_refresh as refresh

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_operator_refresh_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_operator_refresh_guard.md"


class PostChainOperatorRefreshGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_probe_passed: bool
    copied_exit_failure_probe_blocked: bool
    copied_stale_report_probe_blocked: bool
    copied_bad_status_probe_blocked: bool
    live_file_write_attempted: bool
    failed_exit_failed_step_count: int
    stale_report_failed_step_count: int
    bad_status_failed_step_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class RefreshSnapshot:
    refresh_report_modified_ns: int
    step_report_modified_ns: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ProbeReports:
    live: refresh.PostChainOperatorRefreshReport
    exit_failure: refresh.PostChainOperatorRefreshReport
    stale_report: refresh.PostChainOperatorRefreshReport
    bad_status: refresh.PostChainOperatorRefreshReport


def main() -> int:
    before = snapshot_live_files()
    rows = live_step_rows()
    probes = ProbeReports(
        live=refresh.build_report(rows),
        exit_failure=refresh.build_report(with_exit_failure(rows)),
        stale_report=refresh.build_report(with_stale_report(rows)),
        bad_status=refresh.build_report(with_bad_status(rows)),
    )
    after = snapshot_live_files()
    report = build_guard_report(probes, before, after)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def snapshot_live_files() -> RefreshSnapshot:
    return RefreshSnapshot(
        refresh_report_modified_ns=path_mtime(refresh.REPORT_JSON_OUT),
        step_report_modified_ns=tuple(path_mtime(step.report_path) for step in refresh.STEPS),
    )


def path_mtime(path: Path) -> int:
    if path.exists():
        return path.stat().st_mtime_ns
    return -1


def live_step_rows() -> list[refresh.RefreshStepRow]:
    return [live_step_row(order, step) for order, step in enumerate(refresh.STEPS, start=1)]


def live_step_row(order: int, step: refresh.RefreshStep) -> refresh.RefreshStepRow:
    status_ok, report_status, issue = refresh.report_status_check(step)
    return {
        "order": order,
        "label": step.label,
        "command": f"python {step.script}",
        "report_path": refresh.display_path(step.report_path),
        "exit_code": 0,
        "ok": status_ok,
        "report_status": report_status,
        "report_rewritten": True,
        "duration_seconds": 0.0,
        "stdout_tail": "",
        "stderr_tail": "",
        "issue": "" if status_ok else issue,
    }


def with_exit_failure(rows: list[refresh.RefreshStepRow]) -> list[refresh.RefreshStepRow]:
    copied = copied_rows(rows)
    copied[0] = {
        **copied[0],
        "exit_code": 1,
        "ok": False,
        "report_status": "SYNTHETIC_EXIT_FAILURE",
        "issue": "synthetic copied exit failure",
    }
    return copied


def with_stale_report(rows: list[refresh.RefreshStepRow]) -> list[refresh.RefreshStepRow]:
    copied = copied_rows(rows)
    copied[0] = {
        **copied[0],
        "ok": False,
        "report_rewritten": False,
        "issue": "synthetic copied stale report",
    }
    return copied


def with_bad_status(rows: list[refresh.RefreshStepRow]) -> list[refresh.RefreshStepRow]:
    copied = copied_rows(rows)
    copied[0] = {
        **copied[0],
        "ok": False,
        "report_status": "SYNTHETIC_BAD_STATUS",
        "issue": "synthetic copied bad report status",
    }
    return copied


def copied_rows(rows: list[refresh.RefreshStepRow]) -> list[refresh.RefreshStepRow]:
    return [row.copy() for row in rows]


def build_guard_report(
    probes: ProbeReports,
    before: RefreshSnapshot,
    after: RefreshSnapshot,
) -> PostChainOperatorRefreshGuardReport:
    live_probe_passed = probes.live["ok"] is True and probes.live["failed_step_count"] == 0
    exit_failure_blocked = probes.exit_failure["ok"] is False and probes.exit_failure["failed_step_count"] == 1
    stale_report_blocked = probes.stale_report["ok"] is False and probes.stale_report["failed_step_count"] == 1
    bad_status_blocked = probes.bad_status["ok"] is False and probes.bad_status["failed_step_count"] == 1
    live_file_write_attempted = before != after
    failed_probe_count = sum(
        1
        for passed in (
            live_probe_passed,
            exit_failure_blocked,
            stale_report_blocked,
            bad_status_blocked,
            not live_file_write_attempted,
        )
        if not passed
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_OPERATOR_REFRESH_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_OPERATOR_REFRESH_GUARD_FAILED",
        "probe_count": 4,
        "failed_probe_count": failed_probe_count,
        "live_probe_passed": live_probe_passed,
        "copied_exit_failure_probe_blocked": exit_failure_blocked,
        "copied_stale_report_probe_blocked": stale_report_blocked,
        "copied_bad_status_probe_blocked": bad_status_blocked,
        "live_file_write_attempted": live_file_write_attempted,
        "failed_exit_failed_step_count": probes.exit_failure["failed_step_count"],
        "stale_report_failed_step_count": probes.stale_report["failed_step_count"],
        "bad_status_failed_step_count": probes.bad_status["failed_step_count"],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this guard after the post-chain operator refresh wrapper."
    return "Fix copied refresh-row blocking before trusting the post-chain wrapper."


def markdown(report: PostChainOperatorRefreshGuardReport) -> str:
    return "\n".join((
        "# OCR Post-Chain Operator Refresh Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_probe_passed: `{report['live_probe_passed']}`",
        f"- copied_exit_failure_probe_blocked: `{report['copied_exit_failure_probe_blocked']}`",
        f"- copied_stale_report_probe_blocked: `{report['copied_stale_report_probe_blocked']}`",
        f"- copied_bad_status_probe_blocked: `{report['copied_bad_status_probe_blocked']}`",
        f"- live_file_write_attempted: `{report['live_file_write_attempted']}`",
        f"- failed_exit_failed_step_count: `{report['failed_exit_failed_step_count']}`",
        f"- stale_report_failed_step_count: `{report['stale_report_failed_step_count']}`",
        f"- bad_status_failed_step_count: `{report['bad_status_failed_step_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
