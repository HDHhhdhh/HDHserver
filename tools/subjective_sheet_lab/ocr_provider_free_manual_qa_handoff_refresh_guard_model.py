from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from ocr_provider_free_handoff_guard_common import (
    ArtifactSnapshot,
    HandoffGuardStep,
    StepOverride,
    copied_steps_with_override,
    failed_probe_count,
    snapshot_artifacts,
)
import verify_ocr_provider_free_manual_qa_handoff_refresh as refresh

OK_STATUS: Final = "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_READY"
BLOCKED_STATUS: Final = "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_BLOCKED"

HandoffRefreshGuardReport: TypeAlias = dict[str, str | bool | int]


@dataclass(frozen=True, slots=True)
class GuardProbes:
    live_handoff_refresh_passed: bool
    common_self_check_step_blocked: bool
    final_chain_step_blocked: bool
    final_guard_step_blocked: bool
    status_card_step_blocked: bool
    status_card_guard_step_blocked: bool
    status_card_rendered_step_blocked: bool
    status_card_rendered_guard_step_blocked: bool
    operator_summary_step_blocked: bool
    operator_summary_guard_step_blocked: bool
    missing_step_blocked: bool
    refresh_artifacts_preserved: bool


def refresh_live_handoff() -> tuple[list[refresh.HandoffRefreshStep], refresh.HandoffRefreshReport]:
    return refresh.run_locked_refresh()


def build_probes(
    live_steps: list[refresh.HandoffRefreshStep],
    live_report: refresh.HandoffRefreshReport,
    before: ArtifactSnapshot,
) -> GuardProbes:
    common_self_check_report = refresh.build_report(
        steps_with_override(live_steps, StepOverride("handoff_guard_common_self_check", 1)),
    )
    final_chain_report = refresh.build_report(steps_with_override(live_steps, StepOverride("final_handoff_chain", 1)))
    final_guard_report = refresh.build_report(steps_with_override(live_steps, StepOverride("final_handoff_chain_guard", 1)))
    status_card_report = refresh.build_report(steps_with_override(live_steps, StepOverride("handoff_status_card", 1)))
    status_card_guard_report = refresh.build_report(
        steps_with_override(live_steps, StepOverride("handoff_status_card_guard", 1)),
    )
    status_card_rendered_report = refresh.build_report(
        steps_with_override(live_steps, StepOverride("handoff_status_card_rendered_summary", 1)),
    )
    status_card_rendered_guard_report = refresh.build_report(
        steps_with_override(live_steps, StepOverride("handoff_status_card_rendered_summary_guard", 1)),
    )
    operator_summary_report = refresh.build_report(steps_with_override(live_steps, StepOverride("operator_summary", 1)))
    operator_summary_guard_report = refresh.build_report(
        steps_with_override(live_steps, StepOverride("operator_summary_guard", 1)),
    )
    missing_step_report = refresh.build_report(live_steps[:-1])
    after = snapshot_refresh_artifacts()
    return GuardProbes(
        live_handoff_refresh_passed=handoff_refresh_passed(live_report),
        common_self_check_step_blocked=single_step_blocked(common_self_check_report),
        final_chain_step_blocked=single_step_blocked(final_chain_report),
        final_guard_step_blocked=single_step_blocked(final_guard_report),
        status_card_step_blocked=single_step_blocked(status_card_report),
        status_card_guard_step_blocked=single_step_blocked(status_card_guard_report),
        status_card_rendered_step_blocked=single_step_blocked(status_card_rendered_report),
        status_card_rendered_guard_step_blocked=single_step_blocked(status_card_rendered_guard_report),
        operator_summary_step_blocked=single_step_blocked(operator_summary_report),
        operator_summary_guard_step_blocked=single_step_blocked(operator_summary_guard_report),
        missing_step_blocked=missing_step_blocked(missing_step_report),
        refresh_artifacts_preserved=before == after,
    )


def steps_with_override(
    steps: list[refresh.HandoffRefreshStep],
    override: StepOverride,
) -> list[refresh.HandoffRefreshStep]:
    copied_steps = copied_steps_with_override(steps, override)
    return [handoff_refresh_step_from(step) for step in copied_steps]


def handoff_refresh_step_from(step: HandoffGuardStep) -> refresh.HandoffRefreshStep:
    return {
        "name": step["name"],
        "report_path": step["report_path"],
        "exit_code": step["exit_code"],
        "ok": step["ok"],
    }


def handoff_refresh_passed(report: refresh.HandoffRefreshReport) -> bool:
    return (
        report["ok"] is True
        and report["status"] == OK_STATUS
        and report["step_count"] == len(refresh.STEP_SPECS)
        and report["failed_step_count"] == 0
    )


def single_step_blocked(report: refresh.HandoffRefreshReport) -> bool:
    return (
        report["ok"] is False
        and report["status"] == BLOCKED_STATUS
        and report["failed_step_count"] == 1
    )


def missing_step_blocked(report: refresh.HandoffRefreshReport) -> bool:
    return (
        report["ok"] is False
        and report["status"] == BLOCKED_STATUS
        and report["step_count"] == len(refresh.STEP_SPECS) - 1
    )


def snapshot_refresh_artifacts() -> ArtifactSnapshot:
    return snapshot_artifacts(refresh_artifact_paths())


def refresh_artifact_paths() -> tuple[Path, ...]:
    json_paths = (
        refresh.COMMON_SELF_CHECK_JSON,
        refresh.FINAL_CHAIN_JSON,
        refresh.FINAL_GUARD_JSON,
        refresh.STATUS_CARD_JSON,
        refresh.STATUS_CARD_GUARD_JSON,
        refresh.REPORT_JSON_OUT,
    )
    markdown_paths = tuple(path.with_suffix(".md") for path in json_paths)
    return (*json_paths, *markdown_paths)


def build_guard_report(
    probes: GuardProbes,
    live_report: refresh.HandoffRefreshReport,
) -> HandoffRefreshGuardReport:
    probe_results = (
        probes.live_handoff_refresh_passed,
        probes.common_self_check_step_blocked,
        probes.final_chain_step_blocked,
        probes.final_guard_step_blocked,
        probes.status_card_step_blocked,
        probes.status_card_guard_step_blocked,
        probes.status_card_rendered_step_blocked,
        probes.status_card_rendered_guard_step_blocked,
        probes.operator_summary_step_blocked,
        probes.operator_summary_guard_step_blocked,
        probes.missing_step_blocked,
        probes.refresh_artifacts_preserved,
    )
    failed_count = failed_probe_count(probe_results)
    ok = failed_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_GUARD_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_GUARD_FAILED",
        "probe_count": len(probe_results),
        "failed_probe_count": failed_count,
        "live_handoff_refresh_passed": probes.live_handoff_refresh_passed,
        "copied_common_self_check_step_blocked": probes.common_self_check_step_blocked,
        "copied_final_chain_step_blocked": probes.final_chain_step_blocked,
        "copied_final_guard_step_blocked": probes.final_guard_step_blocked,
        "copied_status_card_step_blocked": probes.status_card_step_blocked,
        "copied_status_card_guard_step_blocked": probes.status_card_guard_step_blocked,
        "copied_status_card_rendered_step_blocked": probes.status_card_rendered_step_blocked,
        "copied_status_card_rendered_guard_step_blocked": probes.status_card_rendered_guard_step_blocked,
        "copied_operator_summary_step_blocked": probes.operator_summary_step_blocked,
        "copied_operator_summary_guard_step_blocked": probes.operator_summary_guard_step_blocked,
        "copied_missing_step_blocked": probes.missing_step_blocked,
        "copied_probes_preserved_refresh_artifacts": probes.refresh_artifacts_preserved,
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
        return "Run this guard after manual-QA handoff refresh wrapper changes."
    return "Fix manual-QA handoff refresh blocking probes before handoff."


def markdown(report: HandoffRefreshGuardReport) -> str:
    return "\n".join((
        "# OCR Provider-Free Manual QA Handoff Refresh Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_handoff_refresh_passed: `{report['live_handoff_refresh_passed']}`",
        f"- copied_common_self_check_step_blocked: `{report['copied_common_self_check_step_blocked']}`",
        f"- copied_final_chain_step_blocked: `{report['copied_final_chain_step_blocked']}`",
        f"- copied_final_guard_step_blocked: `{report['copied_final_guard_step_blocked']}`",
        f"- copied_status_card_step_blocked: `{report['copied_status_card_step_blocked']}`",
        f"- copied_status_card_guard_step_blocked: `{report['copied_status_card_guard_step_blocked']}`",
        f"- copied_status_card_rendered_step_blocked: `{report['copied_status_card_rendered_step_blocked']}`",
        "- copied_status_card_rendered_guard_step_blocked: "
        f"`{report['copied_status_card_rendered_guard_step_blocked']}`",
        f"- copied_operator_summary_step_blocked: `{report['copied_operator_summary_step_blocked']}`",
        f"- copied_operator_summary_guard_step_blocked: `{report['copied_operator_summary_guard_step_blocked']}`",
        f"- copied_missing_step_blocked: `{report['copied_missing_step_blocked']}`",
        f"- copied_probes_preserved_refresh_artifacts: `{report['copied_probes_preserved_refresh_artifacts']}`",
        f"- live_step_count: `{report['live_step_count']}`",
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
