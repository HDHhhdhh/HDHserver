# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_handoff_runner_rendered_summary_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, read_json_object
import verify_ocr_training_pack_recognized_evidence_handoff_runner as handoff_runner
import verify_ocr_training_pack_recognized_evidence_handoff_runner_rendered_summary as rendered_summary

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_handoff_runner_rendered_summary_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_handoff_runner_rendered_summary_guard.md"


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


class HandoffRunnerRenderedSummaryGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_summary_passed: bool
    missing_status_line_blocked: bool
    missing_acceptance_line_blocked: bool
    copied_bad_step_count_blocked: bool
    copied_bad_failed_step_count_blocked: bool
    missing_provider_zero_line_blocked: bool
    forbidden_path_snippet_blocked: bool
    probes: list[ProbeReport]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    payload = read_json_object(handoff_runner.REPORT_JSON)
    live_markdown = handoff_runner.REPORT_MD.read_text(encoding="utf-8")
    probe_reports = [run_probe(probe) for probe in probes(payload, live_markdown)]
    report = build_guard_report(probe_reports)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def probes(payload: JsonObject, live_markdown: str) -> tuple[Probe, ...]:
    bad_step_count_payload = copied_payload(payload)
    bad_step_count_payload["handoff_step_count"] = 8
    bad_failed_step_payload = copied_payload(payload)
    bad_failed_step_payload["failed_step_count"] = 1
    return (
        Probe("current_rendered", payload, live_markdown),
        Probe(
            "missing_status_line",
            payload,
            without_line(live_markdown, "- status: `TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_READY`"),
        ),
        Probe(
            "missing_acceptance_line",
            payload,
            without_line(live_markdown, "acceptance_dry_run: exit `0`"),
        ),
        Probe("copied_bad_step_count", bad_step_count_payload, live_markdown),
        Probe("copied_bad_failed_step_count", bad_failed_step_payload, live_markdown),
        Probe("missing_provider_zero_line", payload, without_line(live_markdown, "- provider_call_count: `0`")),
        Probe("forbidden_path_snippet", payload, f"{live_markdown}\nC:/server synthetic probe\n"),
    )


def copied_payload(payload: JsonObject) -> JsonObject:
    return {key: value for key, value in payload.items()}


def without_line(text: str, snippet: str) -> str:
    return "\n".join(line for line in text.splitlines() if snippet not in line)


def run_probe(probe: Probe) -> ProbeReport:
    try:
        report = rendered_summary.build_report(probe.payload, probe.markdown_text)
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


def build_guard_report(probe_reports: list[ProbeReport]) -> HandoffRunnerRenderedSummaryGuardReport:
    failed_probe_count = sum(1 for probe in probe_reports if not expected_probe_result(probe))
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_RENDERED_SUMMARY_GUARD_VERIFIED"
        if ok
        else "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_RENDERED_SUMMARY_GUARD_FAILED",
        "probe_count": len(probe_reports),
        "failed_probe_count": failed_probe_count,
        "live_summary_passed": probe_state(probe_reports, "current_rendered", False),
        "missing_status_line_blocked": probe_state(probe_reports, "missing_status_line", True),
        "missing_acceptance_line_blocked": probe_state(probe_reports, "missing_acceptance_line", True),
        "copied_bad_step_count_blocked": probe_state(probe_reports, "copied_bad_step_count", True),
        "copied_bad_failed_step_count_blocked": probe_state(probe_reports, "copied_bad_failed_step_count", True),
        "missing_provider_zero_line_blocked": probe_state(probe_reports, "missing_provider_zero_line", True),
        "forbidden_path_snippet_blocked": probe_state(probe_reports, "forbidden_path_snippet", True),
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
    if probe["name"] == "current_rendered":
        return probe["ok"] and not probe["blocked"]
    return probe["blocked"] and not probe["ok"]


def probe_state(probe_reports: list[ProbeReport], name: str, blocked: bool) -> bool:
    matches = [probe for probe in probe_reports if probe["name"] == name]
    return bool(matches) and matches[0]["ok"] is (not blocked) and matches[0]["blocked"] is blocked


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this guard with the Training Pack evidence handoff runner rendered-summary verifier."
    return "Fix the Training Pack evidence handoff runner rendered-summary verifier before cached browser QA."


def markdown(report: HandoffRunnerRenderedSummaryGuardReport) -> str:
    probe_lines = [f"- {probe['name']}: ok `{probe['ok']}`, blocked `{probe['blocked']}`" for probe in report["probes"]]
    return "\n".join((
        "# OCR Training Pack Recognized Evidence Handoff Runner Rendered Summary Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_summary_passed: `{report['live_summary_passed']}`",
        f"- missing_status_line_blocked: `{report['missing_status_line_blocked']}`",
        f"- missing_acceptance_line_blocked: `{report['missing_acceptance_line_blocked']}`",
        f"- copied_bad_step_count_blocked: `{report['copied_bad_step_count_blocked']}`",
        f"- copied_bad_failed_step_count_blocked: `{report['copied_bad_failed_step_count_blocked']}`",
        f"- missing_provider_zero_line_blocked: `{report['missing_provider_zero_line_blocked']}`",
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
