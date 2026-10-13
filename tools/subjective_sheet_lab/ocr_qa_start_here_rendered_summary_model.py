from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    assert_common_safety,
    require_bool_value,
    require_int,
    require_int_value,
    require_text_value,
)
from ocr_qa_start_here_rendered_summary_snippets import FORBIDDEN_SNIPPETS, REQUIRED_SNIPPETS


def build_report(start_here: JsonObject, markdown_text: str) -> JsonObject:
    assert_common_safety("start_here", start_here)
    require_text_value(
        start_here.get("status"),
        "OCR_QA_START_HERE_READY_WITH_USER_ACTION_REQUIRED",
        "start_here.status",
    )
    require_text_value(
        start_here.get("freshness_guard_status"),
        "OCR_QA_START_HERE_FRESHNESS_GUARD_VERIFIED",
        "start_here.freshness_guard_status",
    )
    require_bool_value(
        start_here.get("freshness_guard_stale_operator_probe_blocked"),
        True,
        "start_here.freshness_guard_stale_operator_probe_blocked",
    )
    require_bool_value(
        start_here.get("freshness_guard_stale_count_probe_blocked"),
        True,
        "start_here.freshness_guard_stale_count_probe_blocked",
    )
    require_text_value(
        start_here.get("runbook_rendered_summary_guard_status"),
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_RENDERED_SUMMARY_GUARD_VERIFIED",
        "start_here.runbook_rendered_summary_guard_status",
    )
    require_text_value(
        start_here.get("runbook_consistency_guard_status"),
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENCY_GUARD_VERIFIED",
        "start_here.runbook_consistency_guard_status",
    )
    require_text_value(
        start_here.get("post_chain_evidence_index_status"),
        "OCR_POST_CHAIN_EVIDENCE_INDEX_VERIFIED",
        "start_here.post_chain_evidence_index_status",
    )
    require_text_value(
        start_here.get("post_chain_evidence_index_manual_qa_handoff_status"),
        "READY",
        "start_here.post_chain_evidence_index_manual_qa_handoff_status",
    )
    require_int_value(
        start_here.get("post_chain_evidence_index_source_report_count"),
        18,
        "start_here.post_chain_evidence_index_source_report_count",
    )
    require_int_value(
        start_here.get("post_chain_evidence_index_failed_source_count"),
        0,
        "start_here.post_chain_evidence_index_failed_source_count",
    )
    require_bool_value(
        start_here.get("freshness_guard_failed_runbook_rendered_guard_probe_blocked"),
        True,
        "start_here.freshness_guard_failed_runbook_rendered_guard_probe_blocked",
    )
    require_bool_value(
        start_here.get("freshness_guard_failed_runbook_consistency_guard_probe_blocked"),
        True,
        "start_here.freshness_guard_failed_runbook_consistency_guard_probe_blocked",
    )
    require_bool_value(
        start_here.get("freshness_guard_live_start_here_write_attempted"),
        False,
        "start_here.freshness_guard_live_start_here_write_attempted",
    )
    manual_refresh_status = str(start_here.get("manual_qa_handoff_refresh_status", ""))
    manual_refresh_step_count = require_int(
        start_here.get("manual_qa_handoff_refresh_step_count"),
        "start_here.manual_refresh_step_count",
    )
    manual_refresh_guard_status = str(start_here.get("manual_qa_handoff_refresh_guard_status", ""))
    manual_refresh_guard_probe_count = require_int(
        start_here.get("manual_qa_handoff_refresh_guard_probe_count"),
        "start_here.manual_refresh_guard_probe_count",
    )
    manual_refresh_serial_guard_status = str(start_here.get("manual_qa_handoff_refresh_serial_guard_status", ""))
    manual_refresh_serial_guard_probe_count = require_int(
        start_here.get("manual_qa_handoff_refresh_serial_guard_probe_count"),
        "start_here.manual_refresh_serial_guard_probe_count",
    )
    manual_refresh_operator_state = str(start_here.get("manual_qa_handoff_refresh_operator_state", ""))
    manual_refresh_manual_qa_ready = start_here.get("manual_qa_handoff_refresh_manual_qa_ready") is True
    manual_refresh_newer_than_sources = start_here.get("manual_qa_handoff_refresh_newer_than_sources") is True
    manual_refresh_guard_newer_than_refresh = start_here.get("manual_qa_handoff_refresh_guard_newer_than_refresh") is True
    manual_refresh_serial_guard_newer_than_guard = (
        start_here.get("manual_qa_handoff_refresh_serial_guard_newer_than_guard") is True
    )
    require_text_value(
        start_here.get("manual_qa_handoff_refresh_serial_guard_status"),
        "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_SERIAL_GUARD_VERIFIED",
        "start_here.manual_refresh_serial_guard_status",
    )
    require_int_value(
        start_here.get("manual_qa_handoff_refresh_serial_guard_failed_probe_count"),
        0,
        "start_here.manual_refresh_serial_guard_failed_probe_count",
    )
    require_bool_value(
        start_here.get("manual_qa_handoff_refresh_serial_guard_refresh_busy_blocked"),
        True,
        "start_here.manual_refresh_serial_guard_refresh_busy_blocked",
    )
    require_bool_value(
        start_here.get("manual_qa_handoff_refresh_serial_guard_guard_busy_blocked"),
        True,
        "start_here.manual_refresh_serial_guard_guard_busy_blocked",
    )
    require_bool_value(
        start_here.get("manual_qa_handoff_refresh_serial_guard_lock_file_removed"),
        True,
        "start_here.manual_refresh_serial_guard_lock_file_removed",
    )
    require_bool_value(
        start_here.get("manual_qa_handoff_refresh_serial_guard_artifacts_preserved"),
        True,
        "start_here.manual_refresh_serial_guard_artifacts_preserved",
    )
    require_int_value(
        start_here.get("manual_qa_handoff_refresh_source_artifact_count"),
        7,
        "start_here.manual_refresh_source_count",
    )
    require_int_value(start_here.get("provider_call_count"), 0, "start_here.provider_call_count")
    require_int_value(start_here.get("external_ocr_api_call_count"), 0, "start_here.external_ocr_api_call_count")
    require_int_value(start_here.get("submit_test_call_count"), 0, "start_here.submit_test_call_count")
    require_int_value(start_here.get("ts_submit_click_count"), 0, "start_here.ts_submit_click_count")
    require_text_value(start_here.get("production_default"), "NO_GO", "start_here.production_default")

    missing_snippets = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in markdown_text]
    forbidden_snippets = [snippet for snippet in FORBIDDEN_SNIPPETS if snippet in markdown_text]
    ok = not missing_snippets and not forbidden_snippets
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_QA_START_HERE_RENDERED_SUMMARY_VERIFIED" if ok else "OCR_QA_START_HERE_RENDERED_SUMMARY_FAILED",
        "start_here_path": "tools/subjective_sheet_lab/OCR_QA_START_HERE.md",
        "required_snippet_count": len(REQUIRED_SNIPPETS),
        "missing_snippet_count": len(missing_snippets),
        "missing_snippets": missing_snippets,
        "forbidden_snippet_count": len(forbidden_snippets),
        "forbidden_snippets": forbidden_snippets,
        "freshness_guard_status": "OCR_QA_START_HERE_FRESHNESS_GUARD_VERIFIED",
        "freshness_guard_report_path": "tools/subjective_sheet_lab/ocr_qa_start_here_freshness_guard.json",
        "freshness_guard_stale_operator_probe_blocked": True,
        "freshness_guard_stale_count_probe_blocked": True,
        "runbook_rendered_summary_guard_status": "OCR_PREFLIGHT_OPERATOR_RUNBOOK_RENDERED_SUMMARY_GUARD_VERIFIED",
        "runbook_consistency_guard_status": "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENCY_GUARD_VERIFIED",
        "post_chain_evidence_index_status": "OCR_POST_CHAIN_EVIDENCE_INDEX_VERIFIED",
        "post_chain_evidence_index_manual_qa_handoff_status": "READY",
        "post_chain_evidence_index_source_report_count": 18,
        "post_chain_evidence_index_failed_source_count": 0,
        "freshness_guard_failed_runbook_rendered_guard_probe_blocked": True,
        "freshness_guard_failed_runbook_consistency_guard_probe_blocked": True,
        "freshness_guard_live_start_here_write_attempted": False,
        "manual_qa_handoff_refresh_status": manual_refresh_status,
        "manual_qa_handoff_refresh_step_count": manual_refresh_step_count,
        "manual_qa_handoff_refresh_guard_status": manual_refresh_guard_status,
        "manual_qa_handoff_refresh_guard_probe_count": manual_refresh_guard_probe_count,
        "manual_qa_handoff_refresh_serial_guard_status": manual_refresh_serial_guard_status,
        "manual_qa_handoff_refresh_serial_guard_probe_count": manual_refresh_serial_guard_probe_count,
        "manual_qa_handoff_refresh_source_artifact_count": 7,
        "manual_qa_handoff_refresh_newer_than_sources": manual_refresh_newer_than_sources,
        "manual_qa_handoff_refresh_guard_newer_than_refresh": manual_refresh_guard_newer_than_refresh,
        "manual_qa_handoff_refresh_serial_guard_newer_than_guard": manual_refresh_serial_guard_newer_than_guard,
        "manual_qa_handoff_refresh_operator_state": manual_refresh_operator_state,
        "manual_qa_handoff_refresh_manual_qa_ready": manual_refresh_manual_qa_ready,
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
        return "Keep rendered start-here summary verification in the provider-free chain."
    return "Regenerate OCR_QA_START_HERE.md and inspect missing or forbidden rendered snippets."


def markdown(report: JsonObject) -> str:
    missing_lines = [f"- {snippet}" for snippet in report["missing_snippets"]] or ["- none"]
    forbidden_lines = [f"- {snippet}" for snippet in report["forbidden_snippets"]] or ["- none"]
    return "\n".join((
        "# OCR QA Start Here Rendered Summary Verification",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- start_here_path: `{report['start_here_path']}`",
        f"- required_snippet_count: `{report['required_snippet_count']}`",
        f"- missing_snippet_count: `{report['missing_snippet_count']}`",
        f"- forbidden_snippet_count: `{report['forbidden_snippet_count']}`",
        f"- freshness_guard_status: `{report['freshness_guard_status']}`",
        f"- freshness_guard_stale_operator_probe_blocked: `{report['freshness_guard_stale_operator_probe_blocked']}`",
        f"- freshness_guard_stale_count_probe_blocked: `{report['freshness_guard_stale_count_probe_blocked']}`",
        f"- runbook_rendered_summary_guard_status: `{report['runbook_rendered_summary_guard_status']}`",
        f"- runbook_consistency_guard_status: `{report['runbook_consistency_guard_status']}`",
        f"- post_chain_evidence_index_status: `{report['post_chain_evidence_index_status']}`",
        "- post_chain_evidence_index_manual_qa_handoff_status: "
        f"`{report['post_chain_evidence_index_manual_qa_handoff_status']}`",
        f"- post_chain_evidence_index_source_report_count: `{report['post_chain_evidence_index_source_report_count']}`",
        f"- post_chain_evidence_index_failed_source_count: `{report['post_chain_evidence_index_failed_source_count']}`",
        "- freshness_guard_failed_runbook_rendered_guard_probe_blocked: "
        f"`{report['freshness_guard_failed_runbook_rendered_guard_probe_blocked']}`",
        "- freshness_guard_failed_runbook_consistency_guard_probe_blocked: "
        f"`{report['freshness_guard_failed_runbook_consistency_guard_probe_blocked']}`",
        f"- freshness_guard_live_start_here_write_attempted: `{report['freshness_guard_live_start_here_write_attempted']}`",
        f"- manual_qa_handoff_refresh_status: `{report['manual_qa_handoff_refresh_status']}`",
        f"- manual_qa_handoff_refresh_step_count: `{report['manual_qa_handoff_refresh_step_count']}`",
        f"- manual_qa_handoff_refresh_guard_status: `{report['manual_qa_handoff_refresh_guard_status']}`",
        f"- manual_qa_handoff_refresh_guard_probe_count: `{report['manual_qa_handoff_refresh_guard_probe_count']}`",
        f"- manual_qa_handoff_refresh_serial_guard_status: `{report['manual_qa_handoff_refresh_serial_guard_status']}`",
        f"- manual_qa_handoff_refresh_serial_guard_probe_count: `{report['manual_qa_handoff_refresh_serial_guard_probe_count']}`",
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
