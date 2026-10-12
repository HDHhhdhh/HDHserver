#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_evidence_handoff_runner.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import JsonObject, read_json_object, require_int
import verify_ocr_post_chain_evidence_index as evidence_index
import verify_ocr_post_chain_evidence_index_common_self_check as common_self_check
import verify_ocr_post_chain_evidence_index_freshness_guard as freshness_guard
import verify_ocr_post_chain_evidence_index_guard as evidence_guard
from verify_ocr_post_chain_evidence_handoff_runner_steps import HandoffStepSpec, STEP_SPECS

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_handoff_runner.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_handoff_runner.md"
EXPECTED_COMMON_SOURCE_COUNT: Final = 16
EXPECTED_EVIDENCE_SOURCE_COUNT: Final = 18


class HandoffStep(TypedDict):
    name: str
    report_path: str
    expected_status: str
    actual_status: str
    exit_code: int
    ok: bool


class EvidenceHandoffRunnerReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    handoff_step_count: int
    failed_step_count: int
    steps: list[HandoffStep]
    common_self_check_source_report_count: int
    freshness_guard_failed_probe_count: int
    evidence_index_source_report_count: int
    evidence_index_guard_failed_probe_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str

def main() -> int:
    steps = run_steps()
    report = build_report(steps)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def run_steps() -> list[HandoffStep]:
    steps: list[HandoffStep] = []
    for spec in STEP_SPECS:
        step = run_step(spec)
        steps.append(step)
        if not step["ok"]:
            break
    return steps


def run_step(spec: HandoffStepSpec) -> HandoffStep:
    exit_code = spec.verifier()
    actual_status = report_status(spec.report_path)
    return {
        "name": spec.name,
        "report_path": display_path(spec.report_path),
        "expected_status": spec.expected_status,
        "actual_status": actual_status,
        "exit_code": exit_code,
        "ok": exit_code == 0 and actual_status == spec.expected_status,
    }


def report_status(path: Path) -> str:
    payload = read_json_object(path)
    value = payload.get("status")
    if isinstance(value, str):
        return value
    return ""


def build_report(steps: list[HandoffStep]) -> EvidenceHandoffRunnerReport:
    self_check_payload = read_json_object(common_self_check.REPORT_JSON_OUT)
    freshness_payload = read_json_object(freshness_guard.REPORT_JSON_OUT)
    evidence_payload = read_json_object(evidence_index.REPORT_JSON_OUT)
    guard_payload = read_json_object(evidence_guard.REPORT_JSON_OUT)
    failed_step_count = sum(1 for step in steps if not step["ok"])
    self_source_count = require_int(self_check_payload.get("source_report_count"), "common_self_check.source_report_count")
    freshness_failed_count = require_int(freshness_payload.get("failed_probe_count"), "freshness_guard.failed_probe_count")
    evidence_source_count = require_int(evidence_payload.get("source_report_count"), "evidence_index.source_report_count")
    guard_failed_count = require_int(guard_payload.get("failed_probe_count"), "evidence_guard.failed_probe_count")
    ok = (
        failed_step_count == 0
        and len(steps) == len(STEP_SPECS)
        and self_source_count == EXPECTED_COMMON_SOURCE_COUNT
        and freshness_failed_count == 0
        and evidence_source_count == EXPECTED_EVIDENCE_SOURCE_COUNT
        and guard_failed_count == 0
    )
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_FAILED",
        "handoff_step_count": len(steps),
        "failed_step_count": failed_step_count,
        "steps": steps,
        "common_self_check_source_report_count": self_source_count,
        "freshness_guard_failed_probe_count": freshness_failed_count,
        "evidence_index_source_report_count": evidence_source_count,
        "evidence_index_guard_failed_probe_count": guard_failed_count,
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
        return "Use this runner after provider-free gate refreshes to keep the compact evidence handoff fresh."
    return "Inspect the first failed handoff step, then rerun this runner before manual-QA handoff."


def markdown(report: EvidenceHandoffRunnerReport) -> str:
    step_lines = [
        (
            f"- {step['name']}: exit `{step['exit_code']}`, ok `{step['ok']}`, "
            f"status `{step['actual_status']}`"
        )
        for step in report["steps"]
    ]
    return "\n".join((
        "# OCR Post-Chain Evidence Handoff Runner",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- handoff_step_count: `{report['handoff_step_count']}`",
        f"- failed_step_count: `{report['failed_step_count']}`",
        f"- common_self_check_source_report_count: `{report['common_self_check_source_report_count']}`",
        f"- freshness_guard_failed_probe_count: `{report['freshness_guard_failed_probe_count']}`",
        f"- evidence_index_source_report_count: `{report['evidence_index_source_report_count']}`",
        f"- evidence_index_guard_failed_probe_count: `{report['evidence_index_guard_failed_probe_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Steps",
        *step_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"


if __name__ == "__main__":
    raise SystemExit(main())
