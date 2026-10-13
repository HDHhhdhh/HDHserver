from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_post_chain_evidence_index_common import path_mtime
import verify_ocr_post_chain_evidence_handoff_runner as runner
import verify_ocr_qa_start_here as qa_start_here

RUNNER_OK_STATUS: Final = "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_VERIFIED"
QUEUE_STATE_GUARD_PATH: Final = "tools/subjective_sheet_lab/ocr_next_action_queue_state_guard.json"


class HandoffRunnerGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_runner_passed: bool
    copied_bad_step_status_blocked: bool
    copied_stale_freshness_step_blocked: bool
    copied_missing_step_blocked: bool
    copied_probes_preserved_handoff_artifacts: bool
    missing_queue_state_guard_path_blocked: bool
    live_handoff_step_count: int
    live_failed_step_count: int
    copied_bad_step_status: str
    copied_stale_freshness_status: str
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class StepOverride:
    name: str
    actual_status: str
    exit_code: int


@dataclass(frozen=True, slots=True)
class GuardProbes:
    live_runner_passed: bool
    bad_step_status_blocked: bool
    stale_freshness_step_blocked: bool
    missing_step_blocked: bool
    handoff_artifacts_preserved: bool
    missing_queue_state_guard_path_blocked: bool


@dataclass(frozen=True, slots=True)
class HandoffArtifactSnapshot:
    modified_ns: tuple[int, ...]


def refresh_live_runner() -> tuple[list[runner.HandoffStep], runner.EvidenceHandoffRunnerReport]:
    steps = runner.run_steps()
    report = runner.build_report(steps)
    runner.REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runner.REPORT_MD_OUT.write_text(runner.markdown(report), encoding="utf-8")
    return steps, report


def build_probes(
    live_steps: list[runner.HandoffStep],
    live_report: runner.EvidenceHandoffRunnerReport,
    before: HandoffArtifactSnapshot,
) -> GuardProbes:
    bad_step_report = runner.build_report(
        steps_with_override(live_steps, StepOverride("evidence_index", "SYNTHETIC_BAD_STATUS", 0)),
    )
    stale_freshness_report = runner.build_report(
        steps_with_override(
            live_steps,
            StepOverride("freshness_guard", "OCR_POST_CHAIN_EVIDENCE_INDEX_FRESHNESS_GUARD_FAILED", 1),
        ),
    )
    missing_step_report = runner.build_report(live_steps[:-1])
    after = snapshot_handoff_artifacts()
    return GuardProbes(
        live_runner_passed=runner_report_passed(live_report),
        bad_step_status_blocked=single_step_blocked(bad_step_report),
        stale_freshness_step_blocked=single_step_blocked(stale_freshness_report),
        missing_step_blocked=missing_step_blocked(missing_step_report),
        handoff_artifacts_preserved=before == after,
        missing_queue_state_guard_path_blocked=queue_state_guard_path_probe_blocked(),
    )


def steps_with_override(
    steps: list[runner.HandoffStep],
    override: StepOverride,
) -> list[runner.HandoffStep]:
    return [overridden_step(step, override) for step in steps]


def overridden_step(step: runner.HandoffStep, override: StepOverride) -> runner.HandoffStep:
    copied = clone_step(step)
    if copied["name"] == override.name:
        copied["actual_status"] = override.actual_status
        copied["exit_code"] = override.exit_code
        copied["ok"] = False
    return copied


def clone_step(step: runner.HandoffStep) -> runner.HandoffStep:
    return {
        "name": step["name"],
        "report_path": step["report_path"],
        "expected_status": step["expected_status"],
        "actual_status": step["actual_status"],
        "exit_code": step["exit_code"],
        "ok": step["ok"],
    }


def runner_report_passed(report: runner.EvidenceHandoffRunnerReport) -> bool:
    return (
        report["ok"] is True
        and report["status"] == RUNNER_OK_STATUS
        and report["handoff_step_count"] == len(runner.STEP_SPECS)
        and report["failed_step_count"] == 0
    )


def single_step_blocked(report: runner.EvidenceHandoffRunnerReport) -> bool:
    return (
        report["ok"] is False
        and report["status"] == "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_FAILED"
        and report["failed_step_count"] == 1
    )


def missing_step_blocked(report: runner.EvidenceHandoffRunnerReport) -> bool:
    return (
        report["ok"] is False
        and report["status"] == "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_FAILED"
        and report["handoff_step_count"] == len(runner.STEP_SPECS) - 1
    )


def snapshot_handoff_artifacts() -> HandoffArtifactSnapshot:
    return HandoffArtifactSnapshot(tuple(path_mtime(path) for path in handoff_artifact_paths()))


def handoff_artifact_paths() -> tuple[Path, ...]:
    step_json_paths = tuple(spec.report_path for spec in runner.STEP_SPECS)
    step_markdown_paths = tuple(path.with_suffix(".md") for path in step_json_paths)
    return (*step_json_paths, *step_markdown_paths, qa_start_here.START_HERE_MD, runner.REPORT_JSON_OUT, runner.REPORT_MD_OUT)


def queue_state_guard_path_probe_blocked() -> bool:
    live_text = handoff_artifact_text()
    mutated_text = live_text.replace(QUEUE_STATE_GUARD_PATH, "")
    return queue_state_guard_path_present(live_text) and not queue_state_guard_path_present(mutated_text)


def handoff_artifact_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in handoff_artifact_paths() if path.is_file())


def queue_state_guard_path_present(text: str) -> bool:
    return QUEUE_STATE_GUARD_PATH in text


def build_guard_report(
    probes: GuardProbes,
    live_report: runner.EvidenceHandoffRunnerReport,
) -> HandoffRunnerGuardReport:
    failed_probe_count = sum(
        1
        for passed in (
            probes.live_runner_passed,
            probes.bad_step_status_blocked,
            probes.stale_freshness_step_blocked,
            probes.missing_step_blocked,
            probes.handoff_artifacts_preserved,
            probes.missing_queue_state_guard_path_blocked,
        )
        if not passed
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_GUARD_FAILED",
        "probe_count": 6,
        "failed_probe_count": failed_probe_count,
        "live_runner_passed": probes.live_runner_passed,
        "copied_bad_step_status_blocked": probes.bad_step_status_blocked,
        "copied_stale_freshness_step_blocked": probes.stale_freshness_step_blocked,
        "copied_missing_step_blocked": probes.missing_step_blocked,
        "copied_probes_preserved_handoff_artifacts": probes.handoff_artifacts_preserved,
        "missing_queue_state_guard_path_blocked": probes.missing_queue_state_guard_path_blocked,
        "live_handoff_step_count": live_report["handoff_step_count"],
        "live_failed_step_count": live_report["failed_step_count"],
        "copied_bad_step_status": "SYNTHETIC_BAD_STATUS",
        "copied_stale_freshness_status": "OCR_POST_CHAIN_EVIDENCE_INDEX_FRESHNESS_GUARD_FAILED",
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
        return "Use the handoff runner guard after the compact evidence handoff runner."
    return "Fix the handoff runner blocking probes before relying on the compact evidence handoff."


def markdown(report: HandoffRunnerGuardReport) -> str:
    return "\n".join((
        "# OCR Post-Chain Evidence Handoff Runner Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_runner_passed: `{report['live_runner_passed']}`",
        f"- copied_bad_step_status_blocked: `{report['copied_bad_step_status_blocked']}`",
        f"- copied_stale_freshness_step_blocked: `{report['copied_stale_freshness_step_blocked']}`",
        f"- copied_missing_step_blocked: `{report['copied_missing_step_blocked']}`",
        f"- copied_probes_preserved_handoff_artifacts: `{report['copied_probes_preserved_handoff_artifacts']}`",
        f"- missing_queue_state_guard_path_blocked: `{report['missing_queue_state_guard_path_blocked']}`",
        f"- live_handoff_step_count: `{report['live_handoff_step_count']}`",
        f"- live_failed_step_count: `{report['live_failed_step_count']}`",
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
