# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_preflight_operator_runbook_consistency_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import JsonObject, read_json_object, require_int
from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_preflight_operator_runbook_consistency import RUNBOOK_PATH, build_report
from verify_ocr_qa_start_here import REPORT_JSON_OUT as START_HERE_JSON

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_preflight_operator_runbook_consistency_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_preflight_operator_runbook_consistency_guard.md"
START_HERE_GUARD_REPORT_PATH: Final[str] = "tools/subjective_sheet_lab/ocr_qa_start_here_freshness_guard.json"
RENDERED_GUARD_REPORT_PATH: Final[str] = "tools/subjective_sheet_lab/ocr_qa_start_here_rendered_summary_guard.json"
CHAIN_RENDERED_STEPS_GUARD_REPORT_PATH: Final[str] = (
    "tools/subjective_sheet_lab/ocr_provider_free_gate_chain_rendered_steps_guard.json"
)
QUEUE_STATE_GUARD_REPORT_PATH: Final[str] = "tools/subjective_sheet_lab/ocr_next_action_queue_state_guard.json"
COMMON_SELF_CHECK_REPORT_PATH: Final[str] = (
    "tools/subjective_sheet_lab/ocr_provider_free_handoff_guard_common_self_check.json"
)


class ProbeReport(TypedDict):
    name: str
    blocked: bool
    ok: bool
    missing_snippet_count: int


class GuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    current_runbook_probe_passed: bool
    missing_start_here_guard_report_path_blocked: bool
    missing_rendered_summary_guard_report_path_blocked: bool
    missing_chain_rendered_steps_guard_report_path_blocked: bool
    missing_queue_state_guard_report_path_blocked: bool
    missing_common_self_check_report_path_blocked: bool
    stale_chain_step_count_probe_blocked: bool
    live_runbook_write_attempted: bool
    probes: list[ProbeReport]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    runbook_text: str
    should_pass: bool


def main() -> int:
    start_here = read_json_object(START_HERE_JSON)
    before_mtime = RUNBOOK_PATH.stat().st_mtime_ns
    live_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    report = build_guard_report(start_here, live_text, before_mtime)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_guard_report(start_here: JsonObject, live_text: str, before_mtime: int) -> GuardReport:
    chain_step_count = require_int(start_here.get("chain_step_count"), "start_here.chain_step_count")
    probe_reports = [run_probe(start_here, probe) for probe in probes(live_text, chain_step_count)]
    current_passed = probe_reports[0]["ok"] is True and probe_reports[0]["blocked"] is False
    missing_start_blocked = probe_reports[1]["blocked"]
    missing_rendered_blocked = probe_reports[2]["blocked"]
    missing_chain_rendered_steps_blocked = probe_reports[3]["blocked"]
    missing_queue_state_guard_blocked = probe_reports[4]["blocked"]
    missing_common_self_check_blocked = probe_reports[5]["blocked"]
    stale_count_blocked = probe_reports[6]["blocked"]
    live_write_attempted = RUNBOOK_PATH.stat().st_mtime_ns != before_mtime
    failed_probe_count = sum(1 for probe in probe_reports if not expected_probe_outcome(probe))
    ok = failed_probe_count == 0 and not live_write_attempted
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENCY_GUARD_VERIFIED"
        if ok
        else "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENCY_GUARD_FAILED",
        "probe_count": len(probe_reports),
        "failed_probe_count": failed_probe_count,
        "current_runbook_probe_passed": current_passed,
        "missing_start_here_guard_report_path_blocked": missing_start_blocked,
        "missing_rendered_summary_guard_report_path_blocked": missing_rendered_blocked,
        "missing_chain_rendered_steps_guard_report_path_blocked": missing_chain_rendered_steps_blocked,
        "missing_queue_state_guard_report_path_blocked": missing_queue_state_guard_blocked,
        "missing_common_self_check_report_path_blocked": missing_common_self_check_blocked,
        "stale_chain_step_count_probe_blocked": stale_count_blocked,
        "live_runbook_write_attempted": live_write_attempted,
        "probes": probe_reports,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def probes(live_text: str, chain_step_count: int) -> tuple[Probe, ...]:
    return (
        Probe("current_runbook", live_text, True),
        Probe("missing_start_here_guard_report_path", live_text.replace(START_HERE_GUARD_REPORT_PATH, ""), False),
        Probe("missing_rendered_summary_guard_report_path", live_text.replace(RENDERED_GUARD_REPORT_PATH, ""), False),
        Probe(
            "missing_chain_rendered_steps_guard_report_path",
            live_text.replace(CHAIN_RENDERED_STEPS_GUARD_REPORT_PATH, ""),
            False,
        ),
        Probe("missing_queue_state_guard_report_path", live_text.replace(QUEUE_STATE_GUARD_REPORT_PATH, ""), False),
        Probe("missing_common_self_check_report_path", live_text.replace(COMMON_SELF_CHECK_REPORT_PATH, ""), False),
        Probe("stale_chain_step_count", stale_chain_count_text(live_text, chain_step_count), False),
    )


def stale_chain_count_text(live_text: str, chain_step_count: int) -> str:
    stale_count = chain_step_count - 1
    return live_text.replace(
        f"`chain_step_count`: `{chain_step_count}`",
        f"`chain_step_count`: `{stale_count}`",
    ).replace(
        f"chain_step_count = {chain_step_count}",
        f"chain_step_count = {stale_count}",
    )


def run_probe(start_here: JsonObject, probe: Probe) -> ProbeReport:
    report = build_report(start_here, probe.runbook_text)
    blocked = report["ok"] is False and report["missing_snippet_count"] > 0
    return {
        "name": probe.name,
        "blocked": blocked,
        "ok": report["ok"],
        "missing_snippet_count": report["missing_snippet_count"],
    }


def expected_probe_outcome(probe: ProbeReport) -> bool:
    if probe["name"] == "current_runbook":
        return probe["ok"] is True and probe["blocked"] is False
    return probe["blocked"] is True


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep the operator runbook consistency guard in the provider-free chain."
    return "Refresh the operator runbook or the guard probes before treating the chain as current."


def markdown(report: GuardReport) -> str:
    probe_lines = [
        f"- {probe['name']}: blocked `{probe['blocked']}`, ok `{probe['ok']}`, "
        f"missing_snippet_count `{probe['missing_snippet_count']}`"
        for probe in report["probes"]
    ]
    return "\n".join((
        "# OCR Preflight Operator Runbook Consistency Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- current_runbook_probe_passed: `{report['current_runbook_probe_passed']}`",
        f"- missing_start_here_guard_report_path_blocked: `{report['missing_start_here_guard_report_path_blocked']}`",
        f"- missing_rendered_summary_guard_report_path_blocked: `{report['missing_rendered_summary_guard_report_path_blocked']}`",
        "- missing_chain_rendered_steps_guard_report_path_blocked: "
        f"`{report['missing_chain_rendered_steps_guard_report_path_blocked']}`",
        f"- missing_queue_state_guard_report_path_blocked: `{report['missing_queue_state_guard_report_path_blocked']}`",
        f"- missing_common_self_check_report_path_blocked: `{report['missing_common_self_check_report_path_blocked']}`",
        f"- stale_chain_step_count_probe_blocked: `{report['stale_chain_step_count_probe_blocked']}`",
        f"- live_runbook_write_attempted: `{report['live_runbook_write_attempted']}`",
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
