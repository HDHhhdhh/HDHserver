# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_qa_start_here_rendered_summary_guard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import read_json_object
from ocr_preflight_environment_matrix_model import LAB
from ocr_qa_start_here_rendered_summary_guard_model import GuardReport, build_probes, build_report
from verify_ocr_qa_start_here import REPORT_JSON_OUT as START_HERE_JSON
from verify_ocr_qa_start_here import START_HERE_MD

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_qa_start_here_rendered_summary_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_qa_start_here_rendered_summary_guard.md"


def main() -> int:
    live_mtime_before = START_HERE_MD.stat().st_mtime_ns
    start_here = read_json_object(START_HERE_JSON)
    live_text = START_HERE_MD.read_text(encoding="utf-8")
    probes = build_probes(start_here, live_text)
    live_mtime_after = START_HERE_MD.stat().st_mtime_ns
    report = build_report(probes, live_mtime_before != live_mtime_after)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def markdown(report: GuardReport) -> str:
    probe_lines = [f"- {probe['name']}: ok `{probe['ok']}`, blocked `{probe['blocked']}`" for probe in report["probes"]]
    return "\n".join((
        "# OCR QA Start Here Rendered Summary Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- current_rendered_probe_passed: `{report['current_rendered_probe_passed']}`",
        f"- missing_freshness_section_probe_blocked: `{report['missing_freshness_section_probe_blocked']}`",
        "- missing_manual_handoff_section_probe_blocked: "
        f"`{report['missing_manual_handoff_section_probe_blocked']}`",
        f"- missing_report_path_probe_blocked: `{report['missing_report_path_probe_blocked']}`",
        "- missing_runbook_rendered_guard_path_probe_blocked: "
        f"`{report['missing_runbook_rendered_guard_path_probe_blocked']}`",
        "- missing_runbook_consistency_guard_path_probe_blocked: "
        f"`{report['missing_runbook_consistency_guard_path_probe_blocked']}`",
        f"- missing_queue_state_guard_path_probe_blocked: `{report['missing_queue_state_guard_path_probe_blocked']}`",
        f"- forbidden_path_probe_blocked: `{report['forbidden_path_probe_blocked']}`",
        f"- live_start_here_write_attempted: `{report['live_start_here_write_attempted']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Probes",
        *probe_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
