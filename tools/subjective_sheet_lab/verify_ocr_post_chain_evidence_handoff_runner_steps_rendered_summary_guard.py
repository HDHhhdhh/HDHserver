#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_evidence_handoff_runner_steps_rendered_summary_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
import verify_ocr_post_chain_evidence_handoff_runner_steps_rendered_summary as rendered_summary
from verify_ocr_post_chain_evidence_handoff_runner_steps import HandoffStepSpec, STEP_SPECS

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_handoff_runner_steps_rendered_summary_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_handoff_runner_steps_rendered_summary_guard.md"
BAD_CLEANUP_STATUS: Final[str] = "SYNTHETIC_BAD_CLEANUP_STATUS"


class StepCatalogRenderedSummaryGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_summary_passed: bool
    missing_cleanup_step_blocked: bool
    duplicate_step_name_blocked: bool
    stale_step_count_blocked: bool
    wrong_cleanup_status_blocked: bool
    wrong_cleanup_order_blocked: bool
    live_step_count: int
    live_cleanup_step_position: int
    live_evidence_index_guard_position: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class GuardProbes:
    live_summary_passed: bool
    missing_cleanup_step_blocked: bool
    duplicate_step_name_blocked: bool
    stale_step_count_blocked: bool
    wrong_cleanup_status_blocked: bool
    wrong_cleanup_order_blocked: bool


def main() -> int:
    live = rendered_summary.build_report(STEP_SPECS)
    rendered_summary.write_report(live)
    probes = build_probes(live)
    report = build_guard_report(probes, live)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_probes(
    live: rendered_summary.HandoffStepCatalogSummaryReport,
) -> GuardProbes:
    missing_cleanup = rendered_summary.build_report(without_cleanup_step(STEP_SPECS))
    duplicate_name = rendered_summary.build_report((*STEP_SPECS, STEP_SPECS[0]))
    stale_count = rendered_summary.build_report(STEP_SPECS[:-1])
    wrong_status = rendered_summary.build_report(with_cleanup_status(STEP_SPECS, BAD_CLEANUP_STATUS))
    wrong_order = rendered_summary.build_report(with_cleanup_after_guard(STEP_SPECS))
    return GuardProbes(
        live_summary_passed=live_summary_passed(live),
        missing_cleanup_step_blocked=missing_cleanup["ok"] is False and missing_cleanup["cleanup_step_present"] is False,
        duplicate_step_name_blocked=duplicate_name["ok"] is False and duplicate_name["duplicate_step_name_count"] == 1,
        stale_step_count_blocked=stale_count["ok"] is False and stale_count["step_count"] == rendered_summary.EXPECTED_STEP_COUNT - 1,
        wrong_cleanup_status_blocked=wrong_status["ok"] is False
        and wrong_status["cleanup_step_expected_status"] == BAD_CLEANUP_STATUS,
        wrong_cleanup_order_blocked=wrong_order["ok"] is False
        and wrong_order["cleanup_before_evidence_index_guard"] is False,
    )


def live_summary_passed(report: rendered_summary.HandoffStepCatalogSummaryReport) -> bool:
    return (
        report["ok"] is True
        and report["step_count"] == rendered_summary.EXPECTED_STEP_COUNT
        and report["cleanup_step_present"] is True
        and report["cleanup_before_evidence_index_guard"] is True
        and report["filesystem_path_leak_count"] == 0
    )


def without_cleanup_step(specs: rendered_summary.StepSpecs) -> rendered_summary.StepSpecs:
    return tuple(spec for spec in specs if spec.name != rendered_summary.CLEANUP_STEP_NAME)


def with_cleanup_status(specs: rendered_summary.StepSpecs, status: str) -> rendered_summary.StepSpecs:
    return tuple(rewritten_cleanup_spec(spec, status) for spec in specs)


def rewritten_cleanup_spec(spec: HandoffStepSpec, status: str) -> HandoffStepSpec:
    if spec.name == rendered_summary.CLEANUP_STEP_NAME:
        return HandoffStepSpec(spec.name, spec.verifier, spec.report_path, status)
    return spec


def with_cleanup_after_guard(specs: rendered_summary.StepSpecs) -> rendered_summary.StepSpecs:
    cleanup_specs = tuple(spec for spec in specs if spec.name == rendered_summary.CLEANUP_STEP_NAME)
    other_specs = tuple(spec for spec in specs if spec.name != rendered_summary.CLEANUP_STEP_NAME)
    return (*other_specs, *cleanup_specs)


def build_guard_report(
    probes: GuardProbes,
    live: rendered_summary.HandoffStepCatalogSummaryReport,
) -> StepCatalogRenderedSummaryGuardReport:
    failed_probe_count = sum(
        1
        for passed in (
            probes.live_summary_passed,
            probes.missing_cleanup_step_blocked,
            probes.duplicate_step_name_blocked,
            probes.stale_step_count_blocked,
            probes.wrong_cleanup_status_blocked,
            probes.wrong_cleanup_order_blocked,
        )
        if not passed
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_STEPS_RENDERED_SUMMARY_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_STEPS_RENDERED_SUMMARY_GUARD_FAILED",
        "probe_count": 6,
        "failed_probe_count": failed_probe_count,
        "live_summary_passed": probes.live_summary_passed,
        "missing_cleanup_step_blocked": probes.missing_cleanup_step_blocked,
        "duplicate_step_name_blocked": probes.duplicate_step_name_blocked,
        "stale_step_count_blocked": probes.stale_step_count_blocked,
        "wrong_cleanup_status_blocked": probes.wrong_cleanup_status_blocked,
        "wrong_cleanup_order_blocked": probes.wrong_cleanup_order_blocked,
        "live_step_count": live["step_count"],
        "live_cleanup_step_position": live["cleanup_step_position"],
        "live_evidence_index_guard_position": live["evidence_index_guard_position"],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Run this step-catalog guard before relying on the evidence handoff runner."
    return "Repair the split handoff runner step catalog before running downstream handoff checks."


def markdown(report: StepCatalogRenderedSummaryGuardReport) -> str:
    return "\n".join((
        "# OCR Post-Chain Evidence Handoff Runner Step Catalog Rendered Summary Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_summary_passed: `{report['live_summary_passed']}`",
        f"- missing_cleanup_step_blocked: `{report['missing_cleanup_step_blocked']}`",
        f"- duplicate_step_name_blocked: `{report['duplicate_step_name_blocked']}`",
        f"- stale_step_count_blocked: `{report['stale_step_count_blocked']}`",
        f"- wrong_cleanup_status_blocked: `{report['wrong_cleanup_status_blocked']}`",
        f"- wrong_cleanup_order_blocked: `{report['wrong_cleanup_order_blocked']}`",
        f"- live_step_count: `{report['live_step_count']}`",
        f"- live_cleanup_step_position: `{report['live_cleanup_step_position']}`",
        f"- live_evidence_index_guard_position: `{report['live_evidence_index_guard_position']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
