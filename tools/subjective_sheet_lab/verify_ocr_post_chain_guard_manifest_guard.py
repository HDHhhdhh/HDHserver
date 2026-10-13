# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_guard_manifest_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_post_chain_guard_manifest import (
    REQUIRED_COMMAND_SNIPPETS,
    REQUIRED_REPORT_PATHS,
    RENDERED_STEPS_GUARD_JSON,
    RENDERED_STEPS_JSON,
    RUNBOOK_PATH,
    build_report,
)
from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, read_json_object

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_guard_manifest_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_guard_manifest_guard.md"


class ProbeReport(TypedDict):
    name: str
    blocked: bool
    ok: bool
    missing_command_count: int
    missing_report_path_count: int
    error_message: str


class PostChainGuardManifestGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    current_runbook_probe_passed: bool
    missing_refresh_command_blocked: bool
    missing_refresh_report_path_blocked: bool
    stale_rendered_steps_guard_probe_count_blocked: bool
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


def main() -> int:
    rendered_steps = read_json_object(RENDERED_STEPS_JSON)
    rendered_steps_guard = read_json_object(RENDERED_STEPS_GUARD_JSON)
    before_mtime = RUNBOOK_PATH.stat().st_mtime_ns
    live_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    report = build_guard_report(rendered_steps, rendered_steps_guard, live_text, before_mtime)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_guard_report(
    rendered_steps: JsonObject,
    rendered_steps_guard: JsonObject,
    live_text: str,
    before_mtime: int,
) -> PostChainGuardManifestGuardReport:
    probe_reports = [run_probe(rendered_steps, rendered_steps_guard, probe) for probe in probes(live_text)]
    current_passed = probe_reports[0]["ok"] is True and probe_reports[0]["blocked"] is False
    missing_refresh_command_blocked = probe_reports[1]["blocked"]
    missing_refresh_path_blocked = probe_reports[2]["blocked"]
    stale_probe_count_blocked = probe_reports[3]["blocked"]
    live_write_attempted = RUNBOOK_PATH.stat().st_mtime_ns != before_mtime
    failed_probe_count = sum(1 for probe in probe_reports if not expected_probe_outcome(probe))
    ok = failed_probe_count == 0 and not live_write_attempted
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_GUARD_MANIFEST_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_GUARD_MANIFEST_GUARD_FAILED",
        "probe_count": len(probe_reports),
        "failed_probe_count": failed_probe_count,
        "current_runbook_probe_passed": current_passed,
        "missing_refresh_command_blocked": missing_refresh_command_blocked,
        "missing_refresh_report_path_blocked": missing_refresh_path_blocked,
        "stale_rendered_steps_guard_probe_count_blocked": stale_probe_count_blocked,
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


def probes(live_text: str) -> tuple[Probe, ...]:
    return (
        Probe("current_runbook", live_text),
        Probe("missing_refresh_command", text_without(REQUIRED_COMMAND_SNIPPETS[0], live_text)),
        Probe("missing_refresh_report_path", text_without(REQUIRED_REPORT_PATHS[0], live_text)),
        Probe("stale_rendered_steps_guard_probe_count", live_text),
    )


def text_without(snippet: str, text: str) -> str:
    return text.replace(snippet, "")


def run_probe(rendered_steps: JsonObject, rendered_steps_guard: JsonObject, probe: Probe) -> ProbeReport:
    guard_payload = (
        stale_rendered_steps_guard_probe_count(rendered_steps_guard)
        if probe.name == "stale_rendered_steps_guard_probe_count"
        else rendered_steps_guard
    )
    try:
        report = build_report(probe.runbook_text, rendered_steps, guard_payload)
    except ExtendedGateError as error:
        return {
            "name": probe.name,
            "blocked": True,
            "ok": False,
            "missing_command_count": 0,
            "missing_report_path_count": 0,
            "error_message": str(error),
        }
    blocked = (
        report["ok"] is False
        and report["missing_command_count"] + report["missing_report_path_count"] > 0
    )
    return {
        "name": probe.name,
        "blocked": blocked,
        "ok": report["ok"],
        "missing_command_count": report["missing_command_count"],
        "missing_report_path_count": report["missing_report_path_count"],
        "error_message": "",
    }


def stale_rendered_steps_guard_probe_count(rendered_steps_guard: JsonObject) -> JsonObject:
    mutated = dict(rendered_steps_guard)
    mutated["probe_count"] = 6
    return mutated


def expected_probe_outcome(probe: ProbeReport) -> bool:
    if probe["name"] == "current_runbook":
        return probe["ok"] is True and probe["blocked"] is False
    return probe["blocked"] is True


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this guard after the post-chain guard manifest verifier."
    return "Refresh the post-chain refresh wrapper guard probes before trusting manifest coverage."


def markdown(report: PostChainGuardManifestGuardReport) -> str:
    probe_lines = [
        f"- {probe['name']}: blocked `{probe['blocked']}`, ok `{probe['ok']}`, "
        f"missing_command_count `{probe['missing_command_count']}`, "
        f"missing_report_path_count `{probe['missing_report_path_count']}`, "
        f"error_message `{probe['error_message']}`"
        for probe in report["probes"]
    ]
    return "\n".join((
        "# OCR Post-Chain Guard Manifest Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- current_runbook_probe_passed: `{report['current_runbook_probe_passed']}`",
        f"- missing_refresh_command_blocked: `{report['missing_refresh_command_blocked']}`",
        f"- missing_refresh_report_path_blocked: `{report['missing_refresh_report_path_blocked']}`",
        "- stale_rendered_steps_guard_probe_count_blocked: "
        f"`{report['stale_rendered_steps_guard_probe_count_blocked']}`",
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
