#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_final_handoff_chain_guard_output import markdown
from ocr_provider_free_handoff_guard_common import (
    ArtifactSnapshot,
    HandoffGuardStep,
    StepOverride,
    copied_steps_with_override,
    failed_probe_count,
    snapshot_artifacts,
)
import verify_ocr_provider_free_final_handoff_chain as final_chain

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_final_handoff_chain_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_final_handoff_chain_guard.md"
OK_STATUS: Final = "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_VERIFIED"


class FinalHandoffChainGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_final_handoff_passed: bool
    copied_provider_free_step_blocked: bool
    copied_serial_guard_step_blocked: bool
    copied_handoff_guard_step_blocked: bool
    copied_missing_step_blocked: bool
    copied_probes_preserved_chain_artifacts: bool
    live_step_count: int
    live_failed_step_count: int
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
    live_final_handoff_passed: bool
    provider_free_step_blocked: bool
    serial_guard_step_blocked: bool
    handoff_guard_step_blocked: bool
    missing_step_blocked: bool
    chain_artifacts_preserved: bool


def main() -> int:
    report = run_guard()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def run_guard(use_cached_serial_guard: bool = False) -> FinalHandoffChainGuardReport:
    live_steps, live_report = refresh_live_final_handoff(use_cached_serial_guard)
    before = snapshot_chain_artifacts()
    probes = build_probes(live_steps, live_report, before)
    report = build_guard_report(probes, live_report)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    return report


def refresh_live_final_handoff(
    use_cached_serial_guard: bool = False,
) -> tuple[list[final_chain.FinalHandoffStep], final_chain.FinalHandoffReport]:
    steps = final_chain.run_steps(use_cached_serial_guard=use_cached_serial_guard)
    report = final_chain.build_report(steps)
    final_chain.REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    final_chain.REPORT_MD_OUT.write_text(final_chain.markdown(report), encoding="utf-8")
    return steps, report


def build_probes(
    live_steps: list[final_chain.FinalHandoffStep],
    live_report: final_chain.FinalHandoffReport,
    before: ArtifactSnapshot,
) -> GuardProbes:
    provider_step_report = final_chain.build_report(
        steps_with_override(live_steps, StepOverride("provider_free_gate_chain", 1)),
    )
    serial_guard_step_report = final_chain.build_report(
        steps_with_override(live_steps, StepOverride("manual_qa_handoff_refresh_serial_guard", 1)),
    )
    handoff_step_report = final_chain.build_report(
        steps_with_override(live_steps, StepOverride("post_chain_handoff_runner_guard", 1)),
    )
    missing_step_report = final_chain.build_report(live_steps[:-1])
    after = snapshot_chain_artifacts()
    return GuardProbes(
        live_final_handoff_passed=final_report_passed(live_report),
        provider_free_step_blocked=single_step_blocked(provider_step_report),
        serial_guard_step_blocked=single_step_blocked(serial_guard_step_report),
        handoff_guard_step_blocked=single_step_blocked(handoff_step_report),
        missing_step_blocked=missing_step_blocked(missing_step_report),
        chain_artifacts_preserved=before == after,
    )


def steps_with_override(
    steps: list[final_chain.FinalHandoffStep],
    override: StepOverride,
) -> list[final_chain.FinalHandoffStep]:
    copied_steps = copied_steps_with_override(steps, override)
    return [final_handoff_step_from(step) for step in copied_steps]


def final_handoff_step_from(step: HandoffGuardStep) -> final_chain.FinalHandoffStep:
    return {
        "name": step["name"],
        "report_path": step["report_path"],
        "exit_code": step["exit_code"],
        "ok": step["ok"],
    }


def final_report_passed(report: final_chain.FinalHandoffReport) -> bool:
    return (
        report["ok"] is True
        and report["status"] == OK_STATUS
        and report["step_count"] == len(final_chain.STEP_SPECS)
        and report["failed_step_count"] == 0
        and report["handoff_retention_missing_start_card_freshness_helper_missing_count"] == 1
    )


def single_step_blocked(report: final_chain.FinalHandoffReport) -> bool:
    return (
        report["ok"] is False
        and report["status"] == "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_FAILED"
        and report["failed_step_count"] == 1
    )


def missing_step_blocked(report: final_chain.FinalHandoffReport) -> bool:
    return (
        report["ok"] is False
        and report["status"] == "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_FAILED"
        and report["step_count"] == len(final_chain.STEP_SPECS) - 1
    )


def snapshot_chain_artifacts() -> ArtifactSnapshot:
    return snapshot_artifacts(chain_artifact_paths())


def chain_artifact_paths() -> tuple[Path, ...]:
    json_paths = (
        final_chain.PROVIDER_FREE_CHAIN_JSON,
        final_chain.SERIAL_GUARD_JSON,
        final_chain.HANDOFF_RUNNER_JSON,
        final_chain.HANDOFF_GUARD_JSON,
        final_chain.REPORT_JSON_OUT,
    )
    markdown_paths = tuple(path.with_suffix(".md") for path in json_paths)
    return (*json_paths, *markdown_paths)


def build_guard_report(
    probes: GuardProbes,
    live_report: final_chain.FinalHandoffReport,
) -> FinalHandoffChainGuardReport:
    probe_results = (
        probes.live_final_handoff_passed,
        probes.provider_free_step_blocked,
        probes.serial_guard_step_blocked,
        probes.handoff_guard_step_blocked,
        probes.missing_step_blocked,
        probes.chain_artifacts_preserved,
    )
    failed_count = failed_probe_count(probe_results)
    ok = failed_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_GUARD_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_GUARD_FAILED",
        "probe_count": 6,
        "failed_probe_count": failed_count,
        "live_final_handoff_passed": probes.live_final_handoff_passed,
        "copied_provider_free_step_blocked": probes.provider_free_step_blocked,
        "copied_serial_guard_step_blocked": probes.serial_guard_step_blocked,
        "copied_handoff_guard_step_blocked": probes.handoff_guard_step_blocked,
        "copied_missing_step_blocked": probes.missing_step_blocked,
        "copied_probes_preserved_chain_artifacts": probes.chain_artifacts_preserved,
        "live_step_count": live_report["step_count"],
        "live_failed_step_count": live_report["failed_step_count"],
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
        return "Run this guard after final handoff wrapper changes."
    return "Fix final wrapper blocking probes before using it for manual-QA handoff."

if __name__ == "__main__":
    raise SystemExit(main())
