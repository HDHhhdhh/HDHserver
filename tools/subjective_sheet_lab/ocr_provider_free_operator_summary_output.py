from __future__ import annotations

from ocr_provider_free_operator_summary_model import OperatorSummaryReport


def markdown(report: OperatorSummaryReport) -> str:
    return "\n".join((
        "# OCR Provider-Free Operator Summary",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- operator_state: `{report['operator_state']}`",
        f"- status_card_report_path: `{report['status_card_report_path']}`",
        f"- status_card_status: `{report['status_card_status']}`",
        f"- manual_qa_handoff_status: `{report['manual_qa_handoff_status']}`",
        f"- manual_qa_ready: `{report['manual_qa_ready']}`",
        f"- source_report_count: `{report['source_report_count']}`",
        f"- stale_source_count: `{report['stale_source_count']}`",
        f"- failed_source_count: `{report['failed_source_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        f"- operator_next_action_status: `{report['operator_next_action_status']}`",
        f"- operator_next_action: `{report['operator_next_action']}`",
        f"- current_blocker: `{report['current_blocker']}`",
        f"- operator_required_file_count: `{report['operator_required_file_count']}`",
        f"- operator_present_file_count: `{report['operator_present_file_count']}`",
        f"- operator_missing_file_count: `{report['operator_missing_file_count']}`",
        f"- operator_ready_now: `{report['operator_ready_now']}`",
        f"- operator_ready_after_required_files: `{report['operator_ready_after_required_files']}`",
        f"- promotion_write_authorization_required: `{report['promotion_write_authorization_required']}`",
        "",
        "## Required User Action",
        report["required_user_action"],
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))
