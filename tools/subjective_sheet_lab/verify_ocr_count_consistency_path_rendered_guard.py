# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_count_consistency_path_rendered_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypedDict

from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, read_json_object
from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_preflight_operator_runbook_rendered_summary import RUNBOOK_PATH
from verify_ocr_preflight_operator_runbook_rendered_summary import build_report as build_runbook_report
from verify_ocr_qa_start_here import REPORT_JSON_OUT as START_HERE_JSON
from verify_ocr_qa_start_here import START_HERE_MD
from verify_ocr_qa_start_here_rendered_summary import build_report as build_start_here_report

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_count_consistency_path_rendered_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_count_consistency_path_rendered_guard.md"
COUNT_CONSISTENCY_GUARD_PATH: Final[str] = (
    "tools/subjective_sheet_lab/ocr_extended_gate_count_consistency_guard.json"
)
ProbeName = Literal["current_surfaces", "start_here_missing_count_guard_path", "runbook_missing_count_guard_path"]


@dataclass(frozen=True, slots=True)
class Probe:
    name: ProbeName
    ok: bool
    blocked: bool
    missing_snippet_count: int
    error: str


class ProbeJson(TypedDict):
    name: str
    ok: bool
    blocked: bool
    missing_snippet_count: int
    error: str


class GuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    current_surfaces_probe_passed: bool
    start_here_missing_count_guard_path_blocked: bool
    runbook_missing_count_guard_path_blocked: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    probes: list[ProbeJson]
    next_safe_action: str


def main() -> int:
    start_here = read_json_object(START_HERE_JSON)
    start_here_text = START_HERE_MD.read_text(encoding="utf-8")
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    report = build_guard_report(start_here, start_here_text, runbook_text)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_guard_report(start_here: JsonObject, start_here_text: str, runbook_text: str) -> GuardReport:
    probes = (
        current_surfaces_probe(start_here, start_here_text, runbook_text),
        start_here_missing_path_probe(start_here, start_here_text),
        runbook_missing_path_probe(start_here, runbook_text),
    )
    failed_probe_count = sum(1 for probe in probes if not probe.ok)
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_COUNT_CONSISTENCY_PATH_RENDERED_GUARD_VERIFIED"
        if ok
        else "OCR_COUNT_CONSISTENCY_PATH_RENDERED_GUARD_FAILED",
        "probe_count": len(probes),
        "failed_probe_count": failed_probe_count,
        "current_surfaces_probe_passed": probe_by_name(probes, "current_surfaces").ok,
        "start_here_missing_count_guard_path_blocked": probe_by_name(
            probes,
            "start_here_missing_count_guard_path",
        ).blocked,
        "runbook_missing_count_guard_path_blocked": probe_by_name(
            probes,
            "runbook_missing_count_guard_path",
        ).blocked,
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


def current_surfaces_probe(start_here: JsonObject, start_here_text: str, runbook_text: str) -> Probe:
    start_report = build_start_here_report(start_here, start_here_text)
    runbook_report = build_runbook_report(start_here, runbook_text)
    ok = start_report["ok"] is True and runbook_report["ok"] is True
    missing_count = start_report["missing_snippet_count"] + runbook_report["missing_snippet_count"]
    return Probe("current_surfaces", ok=ok, blocked=False, missing_snippet_count=missing_count, error="" if ok else "current surfaces failed")


def start_here_missing_path_probe(start_here: JsonObject, start_here_text: str) -> Probe:
    report = build_start_here_report(start_here, start_here_text.replace(COUNT_CONSISTENCY_GUARD_PATH, ""))
    blocked = report["ok"] is False and report["missing_snippet_count"] > 0
    return Probe(
        "start_here_missing_count_guard_path",
        ok=blocked,
        blocked=blocked,
        missing_snippet_count=report["missing_snippet_count"],
        error="" if blocked else "start-here accepted missing count guard path",
    )


def runbook_missing_path_probe(start_here: JsonObject, runbook_text: str) -> Probe:
    report = build_runbook_report(start_here, runbook_text.replace(COUNT_CONSISTENCY_GUARD_PATH, ""))
    blocked = report["ok"] is False and report["missing_snippet_count"] > 0
    return Probe(
        "runbook_missing_count_guard_path",
        ok=blocked,
        blocked=blocked,
        missing_snippet_count=report["missing_snippet_count"],
        error="" if blocked else "runbook accepted missing count guard path",
    )


def probe_by_name(probes: tuple[Probe, ...], name: ProbeName) -> Probe:
    for probe in probes:
        if probe.name == name:
            return probe
    raise ExtendedGateError(f"missing probe {name}")


def probe_json(probe: Probe) -> ProbeJson:
    return {
        "name": probe.name,
        "ok": probe.ok,
        "blocked": probe.blocked,
        "missing_snippet_count": probe.missing_snippet_count,
        "error": probe.error,
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep count-consistency guard report paths visible in start-here and operator runbook handoffs."
    return "Restore the count-consistency guard report path in start-here and operator runbook rendered evidence."


def markdown(report: GuardReport) -> str:
    probe_lines = [f"- {probe['name']}: ok `{probe['ok']}`, blocked `{probe['blocked']}`" for probe in report["probes"]]
    return "\n".join((
        "# OCR Count Consistency Path Rendered Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- current_surfaces_probe_passed: `{report['current_surfaces_probe_passed']}`",
        "- start_here_missing_count_guard_path_blocked: "
        f"`{report['start_here_missing_count_guard_path_blocked']}`",
        f"- runbook_missing_count_guard_path_blocked: `{report['runbook_missing_count_guard_path_blocked']}`",
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
