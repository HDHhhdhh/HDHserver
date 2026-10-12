from __future__ import annotations

from ocr_provider_free_operator_summary_guard_model import OperatorSummaryGuardReport


def markdown(report: OperatorSummaryGuardReport) -> str:
    return "\n".join((
        "# OCR Provider-Free Operator Summary Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_summary_ready: `{report['live_summary_ready']}`",
        f"- copied_stale_status_card_reported: `{report['copied_stale_status_card_reported']}`",
        f"- copied_blocked_status_card_reported: `{report['copied_blocked_status_card_reported']}`",
        f"- copied_unknown_status_rejected: `{report['copied_unknown_status_rejected']}`",
        f"- copied_leak_rejected: `{report['copied_leak_rejected']}`",
        f"- copied_next_action_leak_rejected: `{report['copied_next_action_leak_rejected']}`",
        f"- copied_next_action_missing_count_rejected: `{report['copied_next_action_missing_count_rejected']}`",
        f"- live_operator_next_action_bridged: `{report['live_operator_next_action_bridged']}`",
        f"- summary_does_not_refresh_status_card: `{report['summary_does_not_refresh_status_card']}`",
        f"- live_operator_state: `{report['live_operator_state']}`",
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
