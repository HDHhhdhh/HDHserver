# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_gate_chain_rendered_steps_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, read_json_object
from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_provider_free_gate_chain import REPORT_JSON_OUT as CHAIN_JSON
from verify_ocr_provider_free_gate_chain import REPORT_MD_OUT as CHAIN_MD
from verify_ocr_provider_free_gate_chain_rendered_steps import build_report, expected_step_names

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_gate_chain_rendered_steps_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_gate_chain_rendered_steps_guard.md"
INTAKE_COMMAND_GUARD_STEP_LINE: Final[str] = "- intake_command_checklist_guard: exit 0, ok True"
RENDERED_GUARD_STEP_LINE: Final[str] = "- operator_runbook_rendered_summary_guard: exit 0, ok True"
COUNT_PATH_GUARD_STEP_LINE: Final[str] = "- count_consistency_path_rendered_guard: exit 0, ok True"
PROVIDER_CALL_ZERO_LINE: Final[str] = "- provider_call_count: 0"
FORBIDDEN_PATH_SNIPPET: Final[str] = "C:/server"


class ProbeReport(TypedDict):
    name: str
    blocked: bool
    ok: bool
    missing_step_count: int
    missing_snippet_count: int
    forbidden_snippet_count: int


class ChainRenderedStepsGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    current_chain_markdown_probe_passed: bool
    missing_intake_command_checklist_guard_blocked: bool
    missing_operator_runbook_rendered_summary_guard_blocked: bool
    missing_count_consistency_path_rendered_guard_blocked: bool
    missing_provider_call_zero_snippet_blocked: bool
    stale_chain_step_count_blocked: bool
    forbidden_filesystem_path_blocked: bool
    live_chain_markdown_write_attempted: bool
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
    markdown_text: str


def main() -> int:
    chain_report = read_json_object(CHAIN_JSON)
    before_mtime = CHAIN_MD.stat().st_mtime_ns
    live_markdown = CHAIN_MD.read_text(encoding="utf-8")
    report = build_guard_report(chain_report, live_markdown, before_mtime)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_guard_report(
    chain_report: JsonObject,
    live_markdown: str,
    before_mtime: int,
) -> ChainRenderedStepsGuardReport:
    probe_reports = [run_probe(chain_report, probe) for probe in probes(live_markdown)]
    current_passed = probe_reports[0]["ok"] is True and probe_reports[0]["blocked"] is False
    missing_intake_guard_blocked = probe_reports[1]["blocked"]
    missing_guard_blocked = probe_reports[2]["blocked"]
    missing_count_path_guard_blocked = probe_reports[3]["blocked"]
    missing_provider_zero_blocked = probe_reports[4]["blocked"]
    stale_count_blocked = probe_reports[5]["blocked"]
    forbidden_path_blocked = probe_reports[6]["blocked"]
    live_write_attempted = CHAIN_MD.stat().st_mtime_ns != before_mtime
    failed_probe_count = sum(1 for probe in probe_reports if not expected_probe_outcome(probe))
    ok = failed_probe_count == 0 and not live_write_attempted
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_GUARD_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_GUARD_FAILED",
        "probe_count": len(probe_reports),
        "failed_probe_count": failed_probe_count,
        "current_chain_markdown_probe_passed": current_passed,
        "missing_intake_command_checklist_guard_blocked": missing_intake_guard_blocked,
        "missing_operator_runbook_rendered_summary_guard_blocked": missing_guard_blocked,
        "missing_count_consistency_path_rendered_guard_blocked": missing_count_path_guard_blocked,
        "missing_provider_call_zero_snippet_blocked": missing_provider_zero_blocked,
        "stale_chain_step_count_blocked": stale_count_blocked,
        "forbidden_filesystem_path_blocked": forbidden_path_blocked,
        "live_chain_markdown_write_attempted": live_write_attempted,
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


def probes(live_markdown: str) -> tuple[Probe, ...]:
    return (
        Probe("current_chain_markdown", live_markdown),
        Probe(
            "missing_intake_command_checklist_guard",
            text_without_snippet(live_markdown, INTAKE_COMMAND_GUARD_STEP_LINE),
        ),
        Probe(
            "missing_operator_runbook_rendered_summary_guard",
            text_without_snippet(live_markdown, RENDERED_GUARD_STEP_LINE),
        ),
        Probe(
            "missing_count_consistency_path_rendered_guard",
            text_without_snippet(live_markdown, COUNT_PATH_GUARD_STEP_LINE),
        ),
        Probe("missing_provider_call_zero_snippet", text_without_snippet(live_markdown, PROVIDER_CALL_ZERO_LINE)),
        Probe("stale_chain_step_count", stale_chain_step_count_text(live_markdown)),
        Probe("forbidden_filesystem_path", f"{live_markdown}\n{FORBIDDEN_PATH_SNIPPET}\n"),
    )


def text_without_snippet(markdown_text: str, snippet: str) -> str:
    if snippet not in markdown_text:
        raise ExtendedGateError(f"chain markdown probe snippet was not found: {snippet}")
    return markdown_text.replace(f"{snippet}\n", "")


def stale_chain_step_count_text(markdown_text: str) -> str:
    current_count = len(expected_step_names())
    current_line = f"- chain_step_count: {current_count}"
    stale_line = f"- chain_step_count: {current_count - 1}"
    if current_line not in markdown_text:
        raise ExtendedGateError("chain markdown step-count line was not found")
    return markdown_text.replace(current_line, stale_line)


def run_probe(chain_report: JsonObject, probe: Probe) -> ProbeReport:
    report = build_report(chain_report, probe.markdown_text)
    blocked = (
        report["ok"] is False
        and report["missing_step_count"] + report["missing_snippet_count"] + report["forbidden_snippet_count"] > 0
    )
    return {
        "name": probe.name,
        "blocked": blocked,
        "ok": report["ok"],
        "missing_step_count": report["missing_step_count"],
        "missing_snippet_count": report["missing_snippet_count"],
        "forbidden_snippet_count": report["forbidden_snippet_count"],
    }


def expected_probe_outcome(probe: ProbeReport) -> bool:
    if probe["name"] == "current_chain_markdown":
        return probe["ok"] is True and probe["blocked"] is False
    return probe["blocked"] is True


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep running this guard after provider-free chain rendered-step verification."
    return "Refresh the rendered-step guard probes before treating chain markdown evidence as protected."


def markdown(report: ChainRenderedStepsGuardReport) -> str:
    probe_lines = [
        f"- {probe['name']}: blocked `{probe['blocked']}`, ok `{probe['ok']}`, "
        f"missing_step_count `{probe['missing_step_count']}`, "
        f"missing_snippet_count `{probe['missing_snippet_count']}`, "
        f"forbidden_snippet_count `{probe['forbidden_snippet_count']}`"
        for probe in report["probes"]
    ]
    return "\n".join((
        "# OCR Provider-Free Gate Chain Rendered Steps Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- current_chain_markdown_probe_passed: `{report['current_chain_markdown_probe_passed']}`",
        "- missing_intake_command_checklist_guard_blocked: "
        f"`{report['missing_intake_command_checklist_guard_blocked']}`",
        "- missing_operator_runbook_rendered_summary_guard_blocked: "
        f"`{report['missing_operator_runbook_rendered_summary_guard_blocked']}`",
        "- missing_count_consistency_path_rendered_guard_blocked: "
        f"`{report['missing_count_consistency_path_rendered_guard_blocked']}`",
        f"- missing_provider_call_zero_snippet_blocked: `{report['missing_provider_call_zero_snippet_blocked']}`",
        f"- stale_chain_step_count_blocked: `{report['stale_chain_step_count_blocked']}`",
        f"- forbidden_filesystem_path_blocked: `{report['forbidden_filesystem_path_blocked']}`",
        f"- live_chain_markdown_write_attempted: `{report['live_chain_markdown_write_attempted']}`",
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
