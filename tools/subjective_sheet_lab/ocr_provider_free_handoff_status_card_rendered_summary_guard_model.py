from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject
from verify_ocr_provider_free_handoff_status_card_rendered_summary import build_report


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    payload: JsonObject
    markdown_text: str


class ProbeReport(TypedDict):
    name: str
    ok: bool
    blocked: bool
    missing_snippet_count: int
    forbidden_snippet_count: int
    error: str


class StatusCardRenderedSummaryGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    current_status_card_markdown_probe_passed: bool
    missing_helper_line_blocked: bool
    missing_partial_evidence_line_blocked: bool
    copied_bad_helper_metric_blocked: bool
    missing_provider_zero_line_blocked: bool
    forbidden_filesystem_path_blocked: bool
    live_status_card_markdown_write_attempted: bool
    probes: list[ProbeReport]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def probes(payload: JsonObject, live_markdown: str) -> tuple[Probe, ...]:
    bad_helper_payload = copied_payload(payload)
    bad_helper_payload["handoff_retention_missing_start_card_freshness_helper_missing_count"] = 0
    return (
        Probe("current_status_card_markdown", payload, live_markdown),
        Probe(
            "missing_helper_line",
            payload,
            live_markdown.replace("- handoff_retention_missing_start_card_freshness_helper_missing_count: `1`", ""),
        ),
        Probe(
            "missing_partial_evidence_line",
            payload,
            live_markdown.replace(
                "- training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count: `4`",
                "",
            ),
        ),
        Probe("copied_bad_helper_metric", bad_helper_payload, live_markdown),
        Probe("missing_provider_zero_line", payload, live_markdown.replace("- provider_call_count: `0`", "")),
        Probe("forbidden_filesystem_path", payload, f"{live_markdown}\nC:/server\n"),
    )


def copied_payload(payload: JsonObject) -> JsonObject:
    return {key: value for key, value in payload.items()}


def run_probe(probe: Probe) -> ProbeReport:
    try:
        report = build_report(probe.payload, probe.markdown_text)
    except ExtendedGateError as exc:
        return {
            "name": probe.name,
            "ok": False,
            "blocked": True,
            "missing_snippet_count": -1,
            "forbidden_snippet_count": -1,
            "error": str(exc),
        }
    return {
        "name": probe.name,
        "ok": report["ok"],
        "blocked": not report["ok"],
        "missing_snippet_count": report["missing_snippet_count"],
        "forbidden_snippet_count": report["forbidden_snippet_count"],
        "error": "",
    }


def build_guard_report(
    probe_reports: list[ProbeReport],
    live_markdown_write_attempted: bool,
) -> StatusCardRenderedSummaryGuardReport:
    current_passed = probe_reports[0]["ok"] and not probe_reports[0]["blocked"]
    missing_helper_blocked = probe_reports[1]["blocked"]
    missing_partial_blocked = probe_reports[2]["blocked"]
    bad_helper_blocked = probe_reports[3]["blocked"]
    missing_provider_blocked = probe_reports[4]["blocked"]
    forbidden_path_blocked = probe_reports[5]["blocked"]
    failed_count = sum(1 for probe in probe_reports if not expected_probe_result(probe))
    ok = failed_count == 0 and not live_markdown_write_attempted
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_RENDERED_SUMMARY_GUARD_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_RENDERED_SUMMARY_GUARD_FAILED",
        "probe_count": len(probe_reports),
        "failed_probe_count": failed_count,
        "current_status_card_markdown_probe_passed": current_passed,
        "missing_helper_line_blocked": missing_helper_blocked,
        "missing_partial_evidence_line_blocked": missing_partial_blocked,
        "copied_bad_helper_metric_blocked": bad_helper_blocked,
        "missing_provider_zero_line_blocked": missing_provider_blocked,
        "forbidden_filesystem_path_blocked": forbidden_path_blocked,
        "live_status_card_markdown_write_attempted": live_markdown_write_attempted,
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


def expected_probe_result(probe: ProbeReport) -> bool:
    if probe["name"] == "current_status_card_markdown":
        return probe["ok"] and not probe["blocked"]
    return probe["blocked"] and not probe["ok"]


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this guard with the compact handoff status card rendered-summary verifier."
    return "Fix status-card rendered-summary blocking before using the compact handoff card."
