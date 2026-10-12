# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_handoff_guard_common_self_check.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_handoff_guard_common import (
    ArtifactSnapshot,
    HandoffGuardStep,
    StepOverride,
    copied_step_with_override,
    copied_steps_with_override,
    copy_step,
    failed_probe_count,
    snapshot_artifacts,
)

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_guard_common_self_check.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_guard_common_self_check.md"
SOURCE_ARTIFACTS: Final[tuple[Path, ...]] = (
    LAB / "ocr_provider_free_handoff_guard_common.py",
    LAB / "verify_ocr_provider_free_final_handoff_chain_guard.py",
    LAB / "verify_ocr_provider_free_manual_qa_handoff_refresh_guard.py",
)


class CommonHandoffGuardSelfCheckReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    copied_step_mutation_isolated: bool
    override_targets_only_requested_step: bool
    copied_steps_preserve_order: bool
    failed_probe_count_counts_false: bool
    source_artifact_snapshot_stable: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class HelperProbes:
    copied_step_mutation_isolated: bool
    override_targets_only_requested_step: bool
    copied_steps_preserve_order: bool
    failed_probe_count_counts_false: bool
    source_artifact_snapshot_stable: bool


def main() -> int:
    before = snapshot_source_artifacts()
    probes = run_helper_probes(before)
    report = build_report(probes)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def run_helper_probes(before: ArtifactSnapshot) -> HelperProbes:
    return HelperProbes(
        copied_step_mutation_isolated=copied_step_mutation_isolated(),
        override_targets_only_requested_step=override_targets_only_requested_step(),
        copied_steps_preserve_order=copied_steps_preserve_order(),
        failed_probe_count_counts_false=failed_probe_count((True, False, False, True)) == 2,
        source_artifact_snapshot_stable=before == snapshot_source_artifacts(),
    )


def copied_step_mutation_isolated() -> bool:
    original = step("first", 0, True)
    copied = copy_step(original)
    copied["exit_code"] = 7
    copied["ok"] = False
    return original["exit_code"] == 0 and original["ok"] is True and copied["exit_code"] == 7


def override_targets_only_requested_step() -> bool:
    original = step("target", 0, True)
    copied = copied_step_with_override(original, StepOverride("target", 9))
    missed = copied_step_with_override(original, StepOverride("other", 9))
    return (
        copied["name"] == "target"
        and copied["exit_code"] == 9
        and copied["ok"] is False
        and missed["exit_code"] == 0
        and missed["ok"] is True
        and original["exit_code"] == 0
        and original["ok"] is True
    )


def copied_steps_preserve_order() -> bool:
    steps = (step("first", 0, True), step("target", 0, True), step("last", 0, True))
    copied_steps = copied_steps_with_override(steps, StepOverride("target", 3))
    copied_names = tuple(item["name"] for item in copied_steps)
    copied_exit_codes = tuple(item["exit_code"] for item in copied_steps)
    original_exit_codes = tuple(item["exit_code"] for item in steps)
    return copied_names == ("first", "target", "last") and copied_exit_codes == (0, 3, 0) and original_exit_codes == (0, 0, 0)


def step(name: str, exit_code: int, ok: bool) -> HandoffGuardStep:
    return {
        "name": name,
        "report_path": f"tools/subjective_sheet_lab/{name}.json",
        "exit_code": exit_code,
        "ok": ok,
    }


def snapshot_source_artifacts() -> ArtifactSnapshot:
    return snapshot_artifacts(SOURCE_ARTIFACTS)


def build_report(probes: HelperProbes) -> CommonHandoffGuardSelfCheckReport:
    probe_results = (
        probes.copied_step_mutation_isolated,
        probes.override_targets_only_requested_step,
        probes.copied_steps_preserve_order,
        probes.failed_probe_count_counts_false,
        probes.source_artifact_snapshot_stable,
    )
    failed_count = failed_probe_count(probe_results)
    ok = failed_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_HANDOFF_GUARD_COMMON_SELF_CHECK_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_HANDOFF_GUARD_COMMON_SELF_CHECK_FAILED",
        "probe_count": len(probe_results),
        "failed_probe_count": failed_count,
        "copied_step_mutation_isolated": probes.copied_step_mutation_isolated,
        "override_targets_only_requested_step": probes.override_targets_only_requested_step,
        "copied_steps_preserve_order": probes.copied_steps_preserve_order,
        "failed_probe_count_counts_false": probes.failed_probe_count_counts_false,
        "source_artifact_snapshot_stable": probes.source_artifact_snapshot_stable,
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
        return "Run this self-check before adding more provider-free handoff guard layers."
    return "Fix common handoff guard helper contracts before extending guard wrappers."


def markdown(report: CommonHandoffGuardSelfCheckReport) -> str:
    return "\n".join((
        "# OCR Provider-Free Handoff Guard Common Self-Check",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- copied_step_mutation_isolated: `{report['copied_step_mutation_isolated']}`",
        f"- override_targets_only_requested_step: `{report['override_targets_only_requested_step']}`",
        f"- copied_steps_preserve_order: `{report['copied_steps_preserve_order']}`",
        f"- failed_probe_count_counts_false: `{report['failed_probe_count_counts_false']}`",
        f"- source_artifact_snapshot_stable: `{report['source_artifact_snapshot_stable']}`",
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
