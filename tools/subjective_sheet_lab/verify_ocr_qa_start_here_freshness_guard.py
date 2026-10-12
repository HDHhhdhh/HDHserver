# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_qa_start_here_freshness_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
)
import ocr_qa_start_here_manual_handoff_freshness as handoff
from ocr_preflight_environment_matrix_model import LAB
from ocr_qa_start_here_core import ReportModifiedTimes
from ocr_qa_start_here_freshness_guard_model import GuardInputs, build_report
from verify_ocr_extended_gate_count_consistency import REPORT_JSON_OUT as COUNT_JSON
from verify_ocr_operator_next_action_summary import REPORT_JSON as OPERATOR_SUMMARY_JSON
from verify_ocr_preflight_report_freshness import REPORT_FRESHNESS_JSON
from verify_ocr_training_pack_intake_only_command_checklist import REPORT_JSON as COMMAND_CHECKLIST_JSON, write_report as refresh_command_checklist

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_qa_start_here_freshness_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_qa_start_here_freshness_guard.md"
RUNBOOK_RENDERED_GUARD_JSON: Final[Path] = LAB / "ocr_preflight_operator_runbook_rendered_summary_guard.json"
RUNBOOK_CONSISTENCY_GUARD_JSON: Final[Path] = LAB / "ocr_preflight_operator_runbook_consistency_guard.json"


def main() -> int:
    report = write_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] is True else 1


def write_report() -> JsonObject:
    refresh_command_checklist()
    report = build_report(read_inputs())
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    return report


def read_inputs() -> GuardInputs:
    return GuardInputs(
        count=read_json_object(COUNT_JSON),
        operator=read_json_object(OPERATOR_SUMMARY_JSON),
        freshness=read_json_object(REPORT_FRESHNESS_JSON),
        command_checklist=read_json_object(COMMAND_CHECKLIST_JSON),
        runbook_rendered_guard=read_json_object(RUNBOOK_RENDERED_GUARD_JSON),
        runbook_consistency_guard=read_json_object(RUNBOOK_CONSISTENCY_GUARD_JSON),
        current_times=ReportModifiedTimes(
            command_checklist=COMMAND_CHECKLIST_JSON.stat().st_mtime_ns,
            operator_summary=OPERATOR_SUMMARY_JSON.stat().st_mtime_ns,
            count_consistency=COUNT_JSON.stat().st_mtime_ns,
        ),
        manual_handoff_times=handoff.current_manual_handoff_refresh_times(),
    )


def markdown(report: JsonObject) -> str:
    return "\n".join((
        "# OCR QA Start Here Freshness Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- passed_probe_count: `{report['passed_probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- stale_operator_probe_blocked: `{report['stale_operator_probe_blocked']}`",
        f"- stale_count_probe_blocked: `{report['stale_count_probe_blocked']}`",
        "- current_manual_qa_handoff_refresh_newer_than_sources: "
        f"`{report['current_manual_qa_handoff_refresh_newer_than_sources']}`",
        "- current_manual_qa_handoff_refresh_guard_newer_than_refresh: "
        f"`{report['current_manual_qa_handoff_refresh_guard_newer_than_refresh']}`",
        f"- stale_manual_handoff_source_probe_blocked: `{report['stale_manual_handoff_source_probe_blocked']}`",
        f"- stale_manual_handoff_guard_probe_blocked: `{report['stale_manual_handoff_guard_probe_blocked']}`",
        f"- runbook_rendered_summary_guard_status: `{report['runbook_rendered_summary_guard_status']}`",
        f"- runbook_rendered_summary_guard_failed_probe_count: `{report['runbook_rendered_summary_guard_failed_probe_count']}`",
        f"- runbook_consistency_guard_status: `{report['runbook_consistency_guard_status']}`",
        f"- runbook_consistency_guard_failed_probe_count: `{report['runbook_consistency_guard_failed_probe_count']}`",
        f"- failed_runbook_rendered_guard_probe_blocked: `{report['failed_runbook_rendered_guard_probe_blocked']}`",
        f"- failed_runbook_consistency_guard_probe_blocked: `{report['failed_runbook_consistency_guard_probe_blocked']}`",
        f"- live_start_here_write_attempted: `{report['live_start_here_write_attempted']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Next Safe Action",
        str(report["next_safe_action"]),
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
