# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_guard_manifest.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    assert_common_safety,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_preflight_environment_matrix_model import LAB
from ocr_qa_start_here_core import EXPECTED_CHAIN_STEP_COUNT
from verify_ocr_preflight_operator_runbook_consistency import RUNBOOK_PATH
from verify_ocr_provider_free_gate_chain_rendered_steps import REPORT_JSON_OUT as RENDERED_STEPS_JSON
from verify_ocr_provider_free_gate_chain_rendered_steps_guard import REPORT_JSON_OUT as RENDERED_STEPS_GUARD_JSON

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_guard_manifest.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_guard_manifest.md"
RENDERED_STEPS_GUARD_PROBE_COUNT: Final[int] = 7
REQUIRED_COMMAND_SNIPPETS: Final[tuple[str, ...]] = (
    "verify_ocr_post_chain_operator_refresh.py",
)
REQUIRED_REPORT_PATHS: Final[tuple[str, ...]] = (
    "tools/subjective_sheet_lab/ocr_post_chain_operator_refresh.json",
)


class PostChainGuardManifestReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    required_command_count: int
    missing_command_count: int
    missing_commands: list[str]
    required_report_path_count: int
    missing_report_path_count: int
    missing_report_paths: list[str]
    rendered_steps_status: str
    rendered_steps_guard_status: str
    expected_chain_step_count: int
    rendered_step_count: int
    guard_probe_count: int
    failed_probe_count: int
    live_chain_markdown_write_attempted: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    rendered_steps = read_json_object(RENDERED_STEPS_JSON)
    rendered_steps_guard = read_json_object(RENDERED_STEPS_GUARD_JSON)
    report = build_report(runbook_text, rendered_steps, rendered_steps_guard)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(
    runbook_text: str,
    rendered_steps: JsonObject,
    rendered_steps_guard: JsonObject,
) -> PostChainGuardManifestReport:
    assert_rendered_steps_report(rendered_steps)
    assert_rendered_steps_guard_report(rendered_steps_guard)
    missing_commands = [snippet for snippet in REQUIRED_COMMAND_SNIPPETS if snippet not in runbook_text]
    missing_report_paths = [path for path in REQUIRED_REPORT_PATHS if path not in runbook_text]
    ok = not missing_commands and not missing_report_paths
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_GUARD_MANIFEST_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_GUARD_MANIFEST_STALE",
        "required_command_count": len(REQUIRED_COMMAND_SNIPPETS),
        "missing_command_count": len(missing_commands),
        "missing_commands": missing_commands,
        "required_report_path_count": len(REQUIRED_REPORT_PATHS),
        "missing_report_path_count": len(missing_report_paths),
        "missing_report_paths": missing_report_paths,
        "rendered_steps_status": "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_VERIFIED",
        "rendered_steps_guard_status": "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_GUARD_VERIFIED",
        "expected_chain_step_count": EXPECTED_CHAIN_STEP_COUNT,
        "rendered_step_count": EXPECTED_CHAIN_STEP_COUNT,
        "guard_probe_count": RENDERED_STEPS_GUARD_PROBE_COUNT,
        "failed_probe_count": 0,
        "live_chain_markdown_write_attempted": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def assert_rendered_steps_report(report: JsonObject) -> None:
    assert_common_safety("rendered_steps", report)
    require_text_value(
        report.get("status"),
        "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_VERIFIED",
        "rendered_steps.status",
    )
    require_int_value(
        report.get("expected_chain_step_count"),
        EXPECTED_CHAIN_STEP_COUNT,
        "rendered_steps.expected_chain_step_count",
    )
    require_int_value(
        report.get("rendered_step_count"),
        EXPECTED_CHAIN_STEP_COUNT,
        "rendered_steps.rendered_step_count",
    )
    require_int_value(report.get("missing_step_count"), 0, "rendered_steps.missing_step_count")
    require_int_value(report.get("missing_snippet_count"), 0, "rendered_steps.missing_snippet_count")
    require_int_value(report.get("forbidden_snippet_count"), 0, "rendered_steps.forbidden_snippet_count")


def assert_rendered_steps_guard_report(report: JsonObject) -> None:
    assert_common_safety("rendered_steps_guard", report)
    require_text_value(
        report.get("status"),
        "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_GUARD_VERIFIED",
        "rendered_steps_guard.status",
    )
    require_int_value(
        report.get("probe_count"),
        RENDERED_STEPS_GUARD_PROBE_COUNT,
        "rendered_steps_guard.probe_count",
    )
    require_int_value(report.get("failed_probe_count"), 0, "rendered_steps_guard.failed_probe_count")
    require_bool_value(
        report.get("missing_intake_command_checklist_guard_blocked"),
        True,
        "rendered_steps_guard.missing_intake_command_checklist_guard_blocked",
    )
    require_bool_value(
        report.get("live_chain_markdown_write_attempted"),
        False,
        "rendered_steps_guard.live_chain_markdown_write_attempted",
    )


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep the post-chain refresh wrapper listed in the operator runbook."
    return "Refresh the operator runbook post-chain wrapper command and report-path manifest."


def markdown(report: PostChainGuardManifestReport) -> str:
    missing_command_lines = [f"- {snippet}" for snippet in report["missing_commands"]] or ["- none"]
    missing_report_path_lines = [f"- {path}" for path in report["missing_report_paths"]] or ["- none"]
    return "\n".join((
        "# OCR Post-Chain Guard Manifest",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- required_command_count: `{report['required_command_count']}`",
        f"- missing_command_count: `{report['missing_command_count']}`",
        f"- required_report_path_count: `{report['required_report_path_count']}`",
        f"- missing_report_path_count: `{report['missing_report_path_count']}`",
        f"- rendered_steps_status: `{report['rendered_steps_status']}`",
        f"- rendered_steps_guard_status: `{report['rendered_steps_guard_status']}`",
        f"- expected_chain_step_count: `{report['expected_chain_step_count']}`",
        f"- rendered_step_count: `{report['rendered_step_count']}`",
        f"- guard_probe_count: `{report['guard_probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_chain_markdown_write_attempted: `{report['live_chain_markdown_write_attempted']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Missing Commands",
        *missing_command_lines,
        "",
        "## Missing Report Paths",
        *missing_report_path_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
