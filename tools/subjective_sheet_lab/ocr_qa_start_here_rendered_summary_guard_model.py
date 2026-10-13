from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject
from verify_ocr_qa_start_here_rendered_summary import build_report as build_rendered_summary

FRESHNESS_HEADING: Final[str] = "## Freshness Guard"
MANUAL_HANDOFF_HEADING: Final[str] = "## Manual QA Handoff Refresh"
NEXT_HEADING: Final[str] = "## 지금 해야 할 일"
FRESHNESS_REPORT_PATH: Final[str] = "tools/subjective_sheet_lab/ocr_qa_start_here_freshness_guard.json"
RUNBOOK_RENDERED_GUARD_PATH: Final[str] = (
    "tools/subjective_sheet_lab/ocr_preflight_operator_runbook_rendered_summary_guard.json"
)
RUNBOOK_CONSISTENCY_GUARD_PATH: Final[str] = (
    "tools/subjective_sheet_lab/ocr_preflight_operator_runbook_consistency_guard.json"
)
QUEUE_STATE_GUARD_PATH: Final[str] = "tools/subjective_sheet_lab/ocr_next_action_queue_state_guard.json"
SERIAL_GUARD_PATH: Final[str] = "tools/subjective_sheet_lab/ocr_provider_free_manual_qa_handoff_refresh_serial_guard.json"
STALE_HANDOFF_SOURCE_LINE: Final[str] = "stale manual handoff source blocked: `True`"
STALE_HANDOFF_GUARD_LINE: Final[str] = "stale manual handoff guard blocked: `True`"
SERIAL_GUARD_STATUS_LINE: Final[str] = (
    "serial guard status: `OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_SERIAL_GUARD_VERIFIED`"
)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    ok: bool
    blocked: bool
    missing_snippet_count: int
    forbidden_snippet_count: int
    error: str


class ProbeJson(TypedDict):
    name: str
    ok: bool
    blocked: bool
    missing_snippet_count: int
    forbidden_snippet_count: int
    error: str


class GuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    current_rendered_probe_passed: bool
    missing_freshness_section_probe_blocked: bool
    missing_manual_handoff_section_probe_blocked: bool
    missing_report_path_probe_blocked: bool
    missing_runbook_rendered_guard_path_probe_blocked: bool
    missing_runbook_consistency_guard_path_probe_blocked: bool
    missing_queue_state_guard_path_probe_blocked: bool
    missing_serial_guard_path_probe_blocked: bool
    missing_serial_guard_status_probe_blocked: bool
    forbidden_path_probe_blocked: bool
    live_start_here_write_attempted: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    probes: list[ProbeJson]
    next_safe_action: str


def build_probes(start_here: JsonObject, live_text: str) -> tuple[ProbeResult, ...]:
    return (
        pass_probe("current_rendered", start_here, live_text),
        block_missing_probe(
            "missing_freshness_section",
            start_here,
            without_section(live_text, FRESHNESS_HEADING, NEXT_HEADING),
        ),
        block_missing_probe(
            "missing_manual_handoff_section",
            start_here,
            without_section(live_text, MANUAL_HANDOFF_HEADING, NEXT_HEADING),
        ),
        block_missing_probe("missing_stale_handoff_source_line", start_here, live_text.replace(STALE_HANDOFF_SOURCE_LINE, "")),
        block_missing_probe("missing_stale_handoff_guard_line", start_here, live_text.replace(STALE_HANDOFF_GUARD_LINE, "")),
        block_missing_probe("missing_report_path", start_here, live_text.replace(FRESHNESS_REPORT_PATH, "missing_report.json")),
        block_missing_probe(
            "missing_runbook_rendered_guard_path",
            start_here,
            live_text.replace(RUNBOOK_RENDERED_GUARD_PATH, "missing_runbook_rendered_guard.json"),
        ),
        block_missing_probe(
            "missing_runbook_consistency_guard_path",
            start_here,
            live_text.replace(RUNBOOK_CONSISTENCY_GUARD_PATH, "missing_runbook_consistency_guard.json"),
        ),
        block_missing_probe("missing_queue_state_guard_path", start_here, live_text.replace(QUEUE_STATE_GUARD_PATH, "")),
        block_missing_probe("missing_serial_guard_path", start_here, live_text.replace(SERIAL_GUARD_PATH, "")),
        block_missing_probe("missing_serial_guard_status", start_here, live_text.replace(SERIAL_GUARD_STATUS_LINE, "")),
        block_forbidden_probe("forbidden_path", start_here, f"{live_text}\nC:/server redacted probe\n"),
    )


def pass_probe(name: str, start_here: JsonObject, markdown_text: str) -> ProbeResult:
    try:
        report = build_rendered_summary(start_here, markdown_text)
    except ExtendedGateError as error:
        return ProbeResult(name, ok=False, blocked=False, missing_snippet_count=0, forbidden_snippet_count=0, error=str(error))
    ok = report["ok"] is True and report["missing_snippet_count"] == 0 and report["forbidden_snippet_count"] == 0
    return ProbeResult(
        name,
        ok=ok,
        blocked=False,
        missing_snippet_count=report["missing_snippet_count"],
        forbidden_snippet_count=report["forbidden_snippet_count"],
        error="" if ok else "current rendered summary did not pass",
    )


def block_missing_probe(name: str, start_here: JsonObject, markdown_text: str) -> ProbeResult:
    try:
        report = build_rendered_summary(start_here, markdown_text)
    except ExtendedGateError as error:
        return ProbeResult(name, ok=False, blocked=False, missing_snippet_count=0, forbidden_snippet_count=0, error=str(error))
    blocked = report["ok"] is False and report["missing_snippet_count"] > 0
    return ProbeResult(
        name,
        ok=blocked,
        blocked=blocked,
        missing_snippet_count=report["missing_snippet_count"],
        forbidden_snippet_count=report["forbidden_snippet_count"],
        error="" if blocked else "stale rendered summary was accepted",
    )


def block_forbidden_probe(name: str, start_here: JsonObject, markdown_text: str) -> ProbeResult:
    try:
        report = build_rendered_summary(start_here, markdown_text)
    except ExtendedGateError as error:
        return ProbeResult(name, ok=False, blocked=False, missing_snippet_count=0, forbidden_snippet_count=0, error=str(error))
    blocked = report["ok"] is False and report["forbidden_snippet_count"] > 0
    return ProbeResult(
        name,
        ok=blocked,
        blocked=blocked,
        missing_snippet_count=report["missing_snippet_count"],
        forbidden_snippet_count=report["forbidden_snippet_count"],
        error="" if blocked else "forbidden rendered summary was accepted",
    )


def without_section(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start < 0 or end < 0 or end <= start:
        return text
    return text[:start] + text[end:]


def build_report(probes: tuple[ProbeResult, ...], live_start_here_write_attempted: bool) -> GuardReport:
    failed_probe_count = sum(1 for probe in probes if not probe.ok)
    ok = failed_probe_count == 0 and not live_start_here_write_attempted
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_QA_START_HERE_RENDERED_SUMMARY_GUARD_VERIFIED" if ok else "OCR_QA_START_HERE_RENDERED_SUMMARY_GUARD_FAILED",
        "probe_count": len(probes),
        "failed_probe_count": failed_probe_count,
        "current_rendered_probe_passed": probe_by_name(probes, "current_rendered").ok,
        "missing_freshness_section_probe_blocked": probe_by_name(probes, "missing_freshness_section").blocked,
        "missing_manual_handoff_section_probe_blocked": probe_by_name(probes, "missing_manual_handoff_section").blocked,
        "missing_report_path_probe_blocked": probe_by_name(probes, "missing_report_path").blocked,
        "missing_runbook_rendered_guard_path_probe_blocked": probe_by_name(probes, "missing_runbook_rendered_guard_path").blocked,
        "missing_runbook_consistency_guard_path_probe_blocked": probe_by_name(probes, "missing_runbook_consistency_guard_path").blocked,
        "missing_queue_state_guard_path_probe_blocked": probe_by_name(probes, "missing_queue_state_guard_path").blocked,
        "missing_serial_guard_path_probe_blocked": probe_by_name(probes, "missing_serial_guard_path").blocked,
        "missing_serial_guard_status_probe_blocked": probe_by_name(probes, "missing_serial_guard_status").blocked,
        "forbidden_path_probe_blocked": probe_by_name(probes, "forbidden_path").blocked,
        "live_start_here_write_attempted": live_start_here_write_attempted,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "probes": [probe_json(probe) for probe in probes],
        "next_safe_action": next_safe_action(ok),
    }


def probe_by_name(probes: tuple[ProbeResult, ...], name: str) -> ProbeResult:
    for probe in probes:
        if probe.name == name:
            return probe
    raise ExtendedGateError(f"missing probe {name}")


def probe_json(probe: ProbeResult) -> ProbeJson:
    return {
        "name": probe.name,
        "ok": probe.ok,
        "blocked": probe.blocked,
        "missing_snippet_count": probe.missing_snippet_count,
        "forbidden_snippet_count": probe.forbidden_snippet_count,
        "error": probe.error,
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep stale rendered-summary guard regression in the provider-free chain."
    return "Inspect rendered summary guard probes before refreshing OCR_QA_START_HERE.md."
