#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_handoff_command_checklist_rendered_summary_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import JsonObject, read_json_object
from ocr_preflight_environment_matrix_model import LAB
import verify_ocr_post_chain_handoff_command_checklist as command_checklist
import verify_ocr_post_chain_handoff_command_checklist_rendered_summary as rendered_summary

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_command_checklist_rendered_summary_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_command_checklist_rendered_summary_guard.md"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    ok: bool
    blocked: bool
    missing_snippet_count: int
    forbidden_snippet_count: int


class ProbeJson(TypedDict):
    name: str
    ok: bool
    blocked: bool
    missing_snippet_count: int
    forbidden_snippet_count: int


class HandoffCommandChecklistRenderedSummaryGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_summary_passed: bool
    missing_ordered_count_blocked: bool
    missing_step_catalog_guard_command_blocked: bool
    missing_runner_command_blocked: bool
    forbidden_submit_snippet_blocked: bool
    forbidden_path_snippet_blocked: bool
    probes: list[ProbeJson]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    command_checklist.main()
    payload = read_json_object(command_checklist.REPORT_JSON_OUT)
    live_text = command_checklist.REPORT_MD_OUT.read_text(encoding="utf-8")
    probes = build_probes(payload, live_text)
    report = build_guard_report(probes)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_probes(payload: JsonObject, live_text: str) -> tuple[ProbeResult, ...]:
    return (
        pass_probe("current_rendered", payload, live_text),
        block_missing_probe("missing_ordered_count", payload, without_line(live_text, "- ordered_command_count: `16`")),
        block_missing_probe("missing_step_catalog_guard_command", payload, without_line(live_text, "steps_rendered_summary_guard.py`")),
        block_missing_probe("missing_runner_command", payload, without_line(live_text, "verify_ocr_post_chain_evidence_handoff_runner.py`")),
        block_forbidden_probe("forbidden_submit_snippet", payload, f"{live_text}\n/api/submit-test synthetic probe\n"),
        block_forbidden_probe("forbidden_path_snippet", payload, f"{live_text}\nC:/server synthetic probe\n"),
    )


def without_line(text: str, snippet: str) -> str:
    return "\n".join(line for line in text.splitlines() if snippet not in line)


def pass_probe(name: str, payload: JsonObject, markdown_text: str) -> ProbeResult:
    report = rendered_summary.build_report(payload, markdown_text)
    ok = report["ok"] is True and report["missing_snippet_count"] == 0 and report["forbidden_snippet_count"] == 0
    return ProbeResult(
        name,
        ok=ok,
        blocked=False,
        missing_snippet_count=report["missing_snippet_count"],
        forbidden_snippet_count=report["forbidden_snippet_count"],
    )


def block_missing_probe(name: str, payload: JsonObject, markdown_text: str) -> ProbeResult:
    report = rendered_summary.build_report(payload, markdown_text)
    blocked = report["ok"] is False and report["missing_snippet_count"] > 0
    return ProbeResult(
        name,
        ok=blocked,
        blocked=blocked,
        missing_snippet_count=report["missing_snippet_count"],
        forbidden_snippet_count=report["forbidden_snippet_count"],
    )


def block_forbidden_probe(name: str, payload: JsonObject, markdown_text: str) -> ProbeResult:
    report = rendered_summary.build_report(payload, markdown_text)
    blocked = report["ok"] is False and report["forbidden_snippet_count"] > 0
    return ProbeResult(
        name,
        ok=blocked,
        blocked=blocked,
        missing_snippet_count=report["missing_snippet_count"],
        forbidden_snippet_count=report["forbidden_snippet_count"],
    )


def build_guard_report(
    probes: tuple[ProbeResult, ...],
) -> HandoffCommandChecklistRenderedSummaryGuardReport:
    failed_probe_count = sum(1 for probe in probes if not probe.ok)
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_RENDERED_SUMMARY_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_RENDERED_SUMMARY_GUARD_FAILED",
        "probe_count": len(probes),
        "failed_probe_count": failed_probe_count,
        "live_summary_passed": probe_block_state(probes, "current_rendered", False),
        "missing_ordered_count_blocked": probe_block_state(probes, "missing_ordered_count", True),
        "missing_step_catalog_guard_command_blocked": probe_block_state(probes, "missing_step_catalog_guard_command", True),
        "missing_runner_command_blocked": probe_block_state(probes, "missing_runner_command", True),
        "forbidden_submit_snippet_blocked": probe_block_state(probes, "forbidden_submit_snippet", True),
        "forbidden_path_snippet_blocked": probe_block_state(probes, "forbidden_path_snippet", True),
        "probes": [probe_json(probe) for probe in probes],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def probe_block_state(probes: tuple[ProbeResult, ...], name: str, blocked: bool) -> bool:
    matching = [probe for probe in probes if probe.name == name]
    return bool(matching) and matching[0].ok is True and matching[0].blocked is blocked


def probe_json(probe: ProbeResult) -> ProbeJson:
    return {
        "name": probe.name,
        "ok": probe.ok,
        "blocked": probe.blocked,
        "missing_snippet_count": probe.missing_snippet_count,
        "forbidden_snippet_count": probe.forbidden_snippet_count,
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this rendered-summary guard after the post-chain handoff command checklist."
    return "Repair the handoff command checklist markdown before operator use."


def markdown(report: HandoffCommandChecklistRenderedSummaryGuardReport) -> str:
    probe_lines = [f"- {probe['name']}: ok `{probe['ok']}`, blocked `{probe['blocked']}`" for probe in report["probes"]]
    return "\n".join((
        "# OCR Post-Chain Handoff Command Checklist Rendered Summary Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_summary_passed: `{report['live_summary_passed']}`",
        f"- missing_ordered_count_blocked: `{report['missing_ordered_count_blocked']}`",
        f"- missing_step_catalog_guard_command_blocked: `{report['missing_step_catalog_guard_command_blocked']}`",
        f"- missing_runner_command_blocked: `{report['missing_runner_command_blocked']}`",
        f"- forbidden_submit_snippet_blocked: `{report['forbidden_submit_snippet_blocked']}`",
        f"- forbidden_path_snippet_blocked: `{report['forbidden_path_snippet_blocked']}`",
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
