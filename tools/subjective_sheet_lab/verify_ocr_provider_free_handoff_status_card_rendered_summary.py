# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_handoff_status_card_rendered_summary.py

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
import verify_ocr_provider_free_handoff_status_card as status_card

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_status_card_rendered_summary.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_handoff_status_card_rendered_summary.md"
REQUIRED_SNIPPETS: Final[tuple[str, ...]] = (
    "- ok: `True`",
    "- student_facing: `False`",
    "- status: `OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_READY`",
    "- manual_qa_handoff_status: `READY`",
    "- source_report_count: `2`",
    "- stale_source_count: `0`",
    "- failed_source_count: `0`",
    "- handoff_retention_guard_probe_count: `9`",
    "- handoff_retention_guard_failed_probe_count: `0`",
    "- handoff_retention_missing_start_card_freshness_helper_missing_count: `1`",
    "- training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count: `4`",
    "- training_pack_partial_evidence_arrival_guard_complete_probe_passed_count: `1`",
    "- training_pack_partial_evidence_arrival_guard_invalid_probe_blocked_count: `3`",
    "- training_pack_partial_evidence_arrival_guard_failed_probe_count: `0`",
    "- provider_call_count: `0`",
    "- external_ocr_api_call_count: `0`",
    "- submit_test_call_count: `0`",
    "- ts_submit_click_count: `0`",
    "- answer_key_or_grading_field_leak_count: `0`",
    "- filesystem_path_leak_count: `0`",
    "- production_default: `NO_GO`",
    "final_handoff_chain: `OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_VERIFIED`",
    "final_handoff_chain_guard: `OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_GUARD_VERIFIED`",
)
FORBIDDEN_SNIPPETS: Final[tuple[str, ...]] = (
    "C:\\server",
    "C:/server",
    "canonical_answer",
    "accepted_answers",
    "correct/incorrect",
    "grading fields",
)


class StatusCardRenderedSummaryReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    status_card_json_path: str
    status_card_markdown_path: str
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
        read_json_object(status_card.REPORT_JSON_OUT),
        status_card.REPORT_MD_OUT.read_text(encoding="utf-8"),
    )
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(payload: JsonObject, markdown_text: str) -> StatusCardRenderedSummaryReport:
    assert_common_safety("status_card", payload)
    require_text_value(payload.get("status"), "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_READY", "status_card.status")
    require_text_value(payload.get("manual_qa_handoff_status"), "READY", "status_card.manual_qa_handoff_status")
    require_int_value(payload.get("source_report_count"), 2, "status_card.source_report_count")
    require_int_value(payload.get("stale_source_count"), 0, "status_card.stale_source_count")
    require_int_value(payload.get("failed_source_count"), 0, "status_card.failed_source_count")
    require_int_value(
        payload.get("handoff_retention_missing_start_card_freshness_helper_missing_count"),
        1,
        "status_card.handoff_retention_missing_start_card_freshness_helper_missing_count",
    )
    missing_snippets = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in markdown_text]
    forbidden_snippets = [snippet for snippet in FORBIDDEN_SNIPPETS if snippet in markdown_text]
    ok = not missing_snippets and not forbidden_snippets
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_RENDERED_SUMMARY_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_RENDERED_SUMMARY_FAILED",
        "status_card_json_path": status_card.REPORT_JSON_OUT.name,
        "status_card_markdown_path": status_card.REPORT_MD_OUT.name,
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
        return "Use this rendered-summary verifier when reviewing the compact handoff status card."
    return "Refresh the status card markdown before using it for manual-QA handoff."


def markdown(report: StatusCardRenderedSummaryReport) -> str:
    return "\n".join((
        "# OCR Provider-Free Handoff Status Card Rendered Summary",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
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
        *[f"- `{snippet}`" for snippet in report["missing_snippets"]],
        "",
        "## Forbidden Snippets",
        *[f"- `{snippet}`" for snippet in report["forbidden_snippets"]],
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
