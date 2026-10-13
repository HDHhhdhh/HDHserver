#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_handoff_command_checklist_rendered_summary.py

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
import verify_ocr_post_chain_handoff_command_checklist as command_checklist

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_command_checklist_rendered_summary.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_command_checklist_rendered_summary.md"
REQUIRED_SNIPPETS: Final[tuple[str, ...]] = (
    "- ok: `True`",
    "- student_facing: `False`",
    "- status: `OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_READY`",
    "- ordered_command_count: `16`",
    "- expected_command_count: `16`",
    "- missing_report_count: `0`",
    "- step_catalog_guard_order: `8`",
    "- evidence_handoff_runner_order: `15`",
    "- step_catalog_guard_before_runner: `True`",
    "- forbidden_command_snippet_count: `0`",
    "- provider_call_count: `0`",
    "- external_ocr_api_call_count: `0`",
    "- submit_test_call_count: `0`",
    "- ts_submit_click_count: `0`",
    "- answer_key_or_grading_field_leak_count: `0`",
    "- filesystem_path_leak_count: `0`",
    "- production_default: `NO_GO`",
    "## Ordered Commands",
    "8. `python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_handoff_runner_steps_rendered_summary_guard.py`",
    "15. `python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_handoff_runner.py`",
    "## Forbidden Command Snippets",
    "- none",
)
FORBIDDEN_SNIPPETS: Final[tuple[str, ...]] = (
    "C:\\server",
    "C:/server",
    "/api/submit-test",
    "#tsSubmit",
    "GEMINI_API_KEY",
    ".env",
    "canonical_answer",
    "accepted_answers",
    "correct/incorrect",
)


class HandoffCommandChecklistRenderedSummaryReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    source_checklist_json_path: str
    source_checklist_markdown_path: str
    required_snippet_count: int
    missing_snippet_count: int
    missing_snippets: list[str]
    forbidden_snippet_count: int
    forbidden_snippets: list[str]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    report = build_report(
        read_json_object(command_checklist.REPORT_JSON_OUT),
        command_checklist.REPORT_MD_OUT.read_text(encoding="utf-8"),
    )
    write_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(payload: JsonObject, markdown_text: str) -> HandoffCommandChecklistRenderedSummaryReport:
    assert_checklist_payload(payload)
    missing_snippets = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in markdown_text]
    forbidden_snippets = [snippet for snippet in FORBIDDEN_SNIPPETS if snippet in markdown_text]
    ok = not missing_snippets and not forbidden_snippets
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_RENDERED_SUMMARY_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_RENDERED_SUMMARY_FAILED",
        "source_checklist_json_path": "tools/subjective_sheet_lab/ocr_post_chain_handoff_command_checklist.json",
        "source_checklist_markdown_path": "tools/subjective_sheet_lab/ocr_post_chain_handoff_command_checklist.md",
        "required_snippet_count": len(REQUIRED_SNIPPETS),
        "missing_snippet_count": len(missing_snippets),
        "missing_snippets": missing_snippets,
        "forbidden_snippet_count": len(forbidden_snippets),
        "forbidden_snippets": forbidden_snippets,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def assert_checklist_payload(payload: JsonObject) -> None:
    assert_common_safety("post_chain_handoff_command_checklist", payload)
    require_text_value(
        payload.get("status"),
        "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_READY",
        "post_chain_handoff_command_checklist.status",
    )
    require_int_value(payload.get("ordered_command_count"), 16, "post_chain_handoff_command_checklist.count")
    require_int_value(payload.get("missing_report_count"), 0, "post_chain_handoff_command_checklist.missing")
    require_int_value(payload.get("step_catalog_guard_order"), 8, "post_chain_handoff_command_checklist.guard_order")
    require_int_value(payload.get("evidence_handoff_runner_order"), 15, "post_chain_handoff_command_checklist.runner")
    require_bool_value(
        payload.get("step_catalog_guard_before_runner"),
        True,
        "post_chain_handoff_command_checklist.guard_before_runner",
    )
    require_int_value(payload.get("forbidden_command_snippet_count"), 0, "post_chain_handoff_command_checklist.forbidden")
    require_text_value(payload.get("production_default"), "NO_GO", "post_chain_handoff_command_checklist.production")


def write_report(report: HandoffCommandChecklistRenderedSummaryReport) -> None:
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this rendered-summary check beside the post-chain handoff command checklist."
    return "Regenerate the post-chain handoff command checklist and inspect missing or forbidden markdown snippets."


def markdown(report: HandoffCommandChecklistRenderedSummaryReport) -> str:
    missing_lines = [f"- {snippet}" for snippet in report["missing_snippets"]] or ["- none"]
    forbidden_lines = [f"- {snippet}" for snippet in report["forbidden_snippets"]] or ["- none"]
    return "\n".join((
        "# OCR Post-Chain Handoff Command Checklist Rendered Summary",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- source_checklist_json_path: `{report['source_checklist_json_path']}`",
        f"- source_checklist_markdown_path: `{report['source_checklist_markdown_path']}`",
        f"- required_snippet_count: `{report['required_snippet_count']}`",
        f"- missing_snippet_count: `{report['missing_snippet_count']}`",
        f"- forbidden_snippet_count: `{report['forbidden_snippet_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Missing Snippets",
        *missing_lines,
        "",
        "## Forbidden Snippets",
        *forbidden_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
