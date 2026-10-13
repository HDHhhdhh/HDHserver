# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_handoff_retention_manifest_guard_rendered_summary.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import (
    JsonObject,
    assert_common_safety,
    read_json_object,
    require_int_value,
    require_text_value,
)
import verify_ocr_post_chain_handoff_retention_manifest_guard as guard

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_retention_manifest_guard_rendered_summary.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_retention_manifest_guard_rendered_summary.md"
REQUIRED_SNIPPETS: Final[tuple[str, ...]] = (
    "- ok: `True`",
    "- student_facing: `False`",
    "- status: `OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_VERIFIED`",
    "- probe_count: `9`",
    "- failed_probe_count: `0`",
    "- live_probe_passed: `True`",
    "- live_file_write_attempted: `False`",
    "- copied_missing_canonical_handoff_missing_count: `1`",
    "- copied_missing_start_here_missing_count: `1`",
    "- copied_missing_queue_state_guard_missing_count: `1`",
    "- copied_missing_evidence_rendered_guard_missing_count: `1`",
    "- copied_missing_evidence_rendered_guard_summary_missing_count: `1`",
    "- copied_missing_retention_guard_summary_missing_count: `1`",
    "- copied_missing_start_card_freshness_helper_missing_count: `1`",
    "- copied_unsafe_helper_json_unsafe_count: `1`",
    "- provider_call_count: `0`",
    "- external_ocr_api_call_count: `0`",
    "- submit_test_call_count: `0`",
    "- ts_submit_click_count: `0`",
    "- answer_key_or_grading_field_leak_count: `0`",
    "- filesystem_path_leak_count: `0`",
    "- production_default: `NO_GO`",
)
FORBIDDEN_SNIPPETS: Final[tuple[str, ...]] = (
    "C:\\server",
    "C:/server",
    "canonical_answer",
    "accepted_answers",
    "correct/incorrect",
    "grading fields",
)


class GuardRenderedSummaryReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    source_guard_json_path: str
    source_guard_markdown_path: str
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
        read_json_object(guard.REPORT_JSON_OUT),
        guard.REPORT_MD_OUT.read_text(encoding="utf-8"),
    )
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(payload: JsonObject, markdown_text: str) -> GuardRenderedSummaryReport:
    assert_common_safety("handoff_retention_manifest_guard", payload)
    require_text_value(
        payload.get("status"),
        "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_VERIFIED",
        "handoff_retention_manifest_guard.status",
    )
    require_int_value(payload.get("probe_count"), 9, "handoff_retention_manifest_guard.probe_count")
    require_int_value(payload.get("failed_probe_count"), 0, "handoff_retention_manifest_guard.failed_probe_count")
    require_text_value(payload.get("production_default"), "NO_GO", "handoff_retention_manifest_guard.production_default")
    missing_snippets = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in markdown_text]
    forbidden_snippets = [snippet for snippet in FORBIDDEN_SNIPPETS if snippet in markdown_text]
    ok = not missing_snippets and not forbidden_snippets
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_RENDERED_SUMMARY_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_RENDERED_SUMMARY_FAILED",
        "source_guard_json_path": "tools/subjective_sheet_lab/ocr_post_chain_handoff_retention_manifest_guard.json",
        "source_guard_markdown_path": "tools/subjective_sheet_lab/ocr_post_chain_handoff_retention_manifest_guard.md",
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


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep the retention guard rendered-summary check in the evidence handoff runner."
    return "Regenerate the handoff retention guard and inspect missing or forbidden markdown snippets."


def markdown(report: GuardRenderedSummaryReport) -> str:
    missing_lines = [f"- {snippet}" for snippet in report["missing_snippets"]] or ["- none"]
    forbidden_lines = [f"- {snippet}" for snippet in report["forbidden_snippets"]] or ["- none"]
    return "\n".join((
        "# OCR Post-Chain Handoff Retention Manifest Guard Rendered Summary",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- source_guard_json_path: `{report['source_guard_json_path']}`",
        f"- source_guard_markdown_path: `{report['source_guard_markdown_path']}`",
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
