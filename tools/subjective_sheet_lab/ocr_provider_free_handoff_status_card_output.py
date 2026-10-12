from __future__ import annotations

from ocr_provider_free_handoff_status_card_model import HandoffStatusCardReport, HandoffStatusSourceRow


def markdown(report: HandoffStatusCardReport) -> str:
    source_lines = [source_markdown(row) for row in report["source_reports"]]
    return "\n".join((
        "# OCR Provider-Free Handoff Status Card",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- manual_qa_handoff_status: `{report['manual_qa_handoff_status']}`",
        f"- source_report_count: `{report['source_report_count']}`",
        f"- stale_source_count: `{report['stale_source_count']}`",
        f"- failed_source_count: `{report['failed_source_count']}`",
        f"- handoff_retention_guard_probe_count: `{report['handoff_retention_guard_probe_count']}`",
        f"- handoff_retention_guard_failed_probe_count: `{report['handoff_retention_guard_failed_probe_count']}`",
        "- handoff_retention_missing_start_card_freshness_helper_missing_count: "
        f"`{report['handoff_retention_missing_start_card_freshness_helper_missing_count']}`",
        "- training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count: "
        f"`{report['training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count']}`",
        "- training_pack_partial_evidence_arrival_guard_complete_probe_passed_count: "
        f"`{report['training_pack_partial_evidence_arrival_guard_complete_probe_passed_count']}`",
        "- training_pack_partial_evidence_arrival_guard_invalid_probe_blocked_count: "
        f"`{report['training_pack_partial_evidence_arrival_guard_invalid_probe_blocked_count']}`",
        "- training_pack_partial_evidence_arrival_guard_failed_probe_count: "
        f"`{report['training_pack_partial_evidence_arrival_guard_failed_probe_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Source Reports",
        *source_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


def source_markdown(row: HandoffStatusSourceRow) -> str:
    return (
        f"- {row['label']}: `{row['status']}`, fresh `{row['fresh']}`, "
        f"failed_metric_count `{row['failed_metric_count']}`, metrics `{row['metrics']}`"
    )
