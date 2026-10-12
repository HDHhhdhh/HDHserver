from __future__ import annotations

from ocr_provider_free_handoff_status_card_rendered_summary_guard_model import (
    StatusCardRenderedSummaryGuardReport,
)


def markdown(report: StatusCardRenderedSummaryGuardReport) -> str:
    probe_lines = [
        f"- {probe['name']}: ok `{probe['ok']}`, blocked `{probe['blocked']}`"
        for probe in report["probes"]
    ]
    return "\n".join((
        "# OCR Provider-Free Handoff Status Card Rendered Summary Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- current_status_card_markdown_probe_passed: `{report['current_status_card_markdown_probe_passed']}`",
        f"- missing_helper_line_blocked: `{report['missing_helper_line_blocked']}`",
        f"- missing_partial_evidence_line_blocked: `{report['missing_partial_evidence_line_blocked']}`",
        f"- copied_bad_helper_metric_blocked: `{report['copied_bad_helper_metric_blocked']}`",
        f"- missing_provider_zero_line_blocked: `{report['missing_provider_zero_line_blocked']}`",
        f"- forbidden_filesystem_path_blocked: `{report['forbidden_filesystem_path_blocked']}`",
        f"- live_status_card_markdown_write_attempted: `{report['live_status_card_markdown_write_attempted']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Probes",
        *probe_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))
