#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_manual_qa_handoff_refresh.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_file_lock import FileLockBusy, display_path, file_lock
from ocr_provider_free_manual_qa_handoff_refresh_model import (
    COMMON_SELF_CHECK_JSON,
    FINAL_CHAIN_JSON,
    FINAL_GUARD_JSON,
    OPERATOR_SUMMARY_GUARD_JSON,
    OPERATOR_SUMMARY_JSON,
    STATUS_CARD_GUARD_JSON,
    STATUS_CARD_JSON,
    STATUS_CARD_RENDERED_GUARD_JSON,
    STATUS_CARD_RENDERED_JSON,
    STEP_SPECS,
    HandoffRefreshReport,
    HandoffRefreshStep,
    build_report,
    run_steps,
)
from ocr_provider_free_manual_qa_handoff_refresh_output import markdown

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh.md"
LOCK_PATH: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh.lock"


class LockBusyReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    lock_path: str
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    try:
        _steps, report = run_locked_refresh()
    except FileLockBusy as exc:
        report = lock_busy_report(exc)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def run_locked_refresh() -> tuple[list[HandoffRefreshStep], HandoffRefreshReport]:
    if not LOCK_PATH.exists():
        refresh_serial_guard_report()
    with file_lock(LOCK_PATH):
        steps = run_steps()
        report = build_report(steps)
        write_report(report)
        return steps, report


def refresh_serial_guard_report() -> None:
    from verify_ocr_provider_free_manual_qa_handoff_refresh_serial_guard import main as verify_serial_guard

    verify_serial_guard()


def write_report(report: HandoffRefreshReport) -> None:
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")


def run_unlocked_refresh() -> tuple[list[HandoffRefreshStep], HandoffRefreshReport]:
    steps = run_steps()
    report = build_report(steps)
    write_report(report)
    return steps, report


def lock_busy_report(error: FileLockBusy) -> LockBusyReport:
    return {
        "ok": False,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_BUSY",
        "lock_path": display_path(error.lock_path),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": "Wait for the active provider-free handoff refresh to finish, then rerun sequentially.",
    }


if __name__ == "__main__":
    raise SystemExit(main())
