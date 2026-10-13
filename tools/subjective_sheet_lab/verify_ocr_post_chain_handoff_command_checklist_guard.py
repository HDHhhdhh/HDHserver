#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_handoff_command_checklist_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
import verify_ocr_post_chain_handoff_command_checklist as checklist

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_command_checklist_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_command_checklist_guard.md"


@dataclass(frozen=True, slots=True)
class GuardProbes:
    live_checklist_passed: bool
    missing_step_catalog_guard_blocked: bool
    runner_before_step_catalog_guard_blocked: bool
    stale_command_count_blocked: bool
    forbidden_submit_command_blocked: bool


class HandoffCommandChecklistGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_checklist_passed: bool
    missing_step_catalog_guard_blocked: bool
    runner_before_step_catalog_guard_blocked: bool
    stale_command_count_blocked: bool
    forbidden_submit_command_blocked: bool
    live_ordered_command_count: int
    live_step_catalog_guard_order: int
    live_evidence_handoff_runner_order: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    live = checklist.build_report(checklist.COMMAND_SPECS)
    checklist.write_report(live)
    probes = build_probes(live)
    report = build_report(probes, live)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_probes(live: checklist.HandoffCommandChecklistReport) -> GuardProbes:
    missing_guard = checklist.build_report(without_step_catalog_guard())
    wrong_order = checklist.build_report(with_runner_before_guard())
    stale_count = checklist.build_report(checklist.COMMAND_SPECS[:-1])
    forbidden_submit = checklist.build_report(with_forbidden_submit_command())
    return GuardProbes(
        live_checklist_passed=live["ok"] is True and live["ordered_command_count"] == checklist.EXPECTED_COMMAND_COUNT,
        missing_step_catalog_guard_blocked=missing_guard["ok"] is False
        and missing_guard["step_catalog_guard_order"] == 0,
        runner_before_step_catalog_guard_blocked=wrong_order["ok"] is False
        and wrong_order["step_catalog_guard_before_runner"] is False,
        stale_command_count_blocked=stale_count["ok"] is False
        and stale_count["ordered_command_count"] == checklist.EXPECTED_COMMAND_COUNT - 1,
        forbidden_submit_command_blocked=forbidden_submit["ok"] is False
        and forbidden_submit["forbidden_command_snippet_count"] == 1,
    )


def without_step_catalog_guard() -> tuple[checklist.CommandSpec, ...]:
    return tuple(spec for spec in checklist.COMMAND_SPECS if spec.label != checklist.STEP_CATALOG_GUARD_LABEL)


def with_runner_before_guard() -> tuple[checklist.CommandSpec, ...]:
    runner = tuple(spec for spec in checklist.COMMAND_SPECS if spec.label == checklist.HANDOFF_RUNNER_LABEL)
    guard = tuple(spec for spec in checklist.COMMAND_SPECS if spec.label == checklist.STEP_CATALOG_GUARD_LABEL)
    others = tuple(
        spec
        for spec in checklist.COMMAND_SPECS
        if spec.label not in (checklist.HANDOFF_RUNNER_LABEL, checklist.STEP_CATALOG_GUARD_LABEL)
    )
    return (*runner, *others, *guard)


def with_forbidden_submit_command() -> tuple[checklist.CommandSpec, ...]:
    return (
        *checklist.COMMAND_SPECS[:-1],
        checklist.CommandSpec(
            "synthetic_forbidden_submit",
            "curl http://127.0.0.1:8003/api/submit-test",
            "ocr_post_chain_evidence_handoff_runner_guard.json",
        ),
    )


def build_report(
    probes: GuardProbes,
    live: checklist.HandoffCommandChecklistReport,
) -> HandoffCommandChecklistGuardReport:
    failed_probe_count = sum(
        1
        for passed in (
            probes.live_checklist_passed,
            probes.missing_step_catalog_guard_blocked,
            probes.runner_before_step_catalog_guard_blocked,
            probes.stale_command_count_blocked,
            probes.forbidden_submit_command_blocked,
        )
        if not passed
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_GUARD_FAILED",
        "probe_count": 5,
        "failed_probe_count": failed_probe_count,
        "live_checklist_passed": probes.live_checklist_passed,
        "missing_step_catalog_guard_blocked": probes.missing_step_catalog_guard_blocked,
        "runner_before_step_catalog_guard_blocked": probes.runner_before_step_catalog_guard_blocked,
        "stale_command_count_blocked": probes.stale_command_count_blocked,
        "forbidden_submit_command_blocked": probes.forbidden_submit_command_blocked,
        "live_ordered_command_count": live["ordered_command_count"],
        "live_step_catalog_guard_order": live["step_catalog_guard_order"],
        "live_evidence_handoff_runner_order": live["evidence_handoff_runner_order"],
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
        return "Keep this guard beside the post-chain handoff command checklist."
    return "Repair the post-chain handoff command checklist before operator use."


def markdown(report: HandoffCommandChecklistGuardReport) -> str:
    return "\n".join((
        "# OCR Post-Chain Handoff Command Checklist Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_checklist_passed: `{report['live_checklist_passed']}`",
        f"- missing_step_catalog_guard_blocked: `{report['missing_step_catalog_guard_blocked']}`",
        f"- runner_before_step_catalog_guard_blocked: `{report['runner_before_step_catalog_guard_blocked']}`",
        f"- stale_command_count_blocked: `{report['stale_command_count_blocked']}`",
        f"- forbidden_submit_command_blocked: `{report['forbidden_submit_command_blocked']}`",
        f"- live_ordered_command_count: `{report['live_ordered_command_count']}`",
        f"- live_step_catalog_guard_order: `{report['live_step_catalog_guard_order']}`",
        f"- live_evidence_handoff_runner_order: `{report['live_evidence_handoff_runner_order']}`",
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
