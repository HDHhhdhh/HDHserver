from __future__ import annotations

from ocr_provider_free_manual_qa_handoff_refresh_model import HandoffRefreshReport


def markdown(report: HandoffRefreshReport) -> str:
    step_lines = [f"- {step['name']}: exit `{step['exit_code']}`, ok `{step['ok']}`" for step in report["steps"]]
    return "\n".join((
        "# OCR Provider-Free Manual QA Handoff Refresh",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- step_count: `{report['step_count']}`",
        f"- failed_step_count: `{report['failed_step_count']}`",
        f"- common_self_check_status: `{report['common_self_check_status']}`",
        f"- common_self_check_probe_count: `{report['common_self_check_probe_count']}`",
        f"- final_chain_status: `{report['final_chain_status']}`",
        f"- final_chain_step_count: `{report['final_chain_step_count']}`",
        f"- final_guard_status: `{report['final_guard_status']}`",
        f"- final_guard_probe_count: `{report['final_guard_probe_count']}`",
        f"- status_card_status: `{report['status_card_status']}`",
        f"- status_card_manual_qa_handoff_status: `{report['status_card_manual_qa_handoff_status']}`",
        f"- status_card_guard_status: `{report['status_card_guard_status']}`",
        f"- status_card_guard_probe_count: `{report['status_card_guard_probe_count']}`",
        f"- status_card_rendered_summary_status: `{report['status_card_rendered_summary_status']}`",
        "- status_card_rendered_summary_missing_snippet_count: "
        f"`{report['status_card_rendered_summary_missing_snippet_count']}`",
        f"- status_card_rendered_summary_guard_status: `{report['status_card_rendered_summary_guard_status']}`",
        f"- status_card_rendered_summary_guard_probe_count: `{report['status_card_rendered_summary_guard_probe_count']}`",
        f"- operator_summary_status: `{report['operator_summary_status']}`",
        f"- operator_summary_state: `{report['operator_summary_state']}`",
        f"- operator_summary_manual_qa_ready: `{report['operator_summary_manual_qa_ready']}`",
        f"- operator_summary_guard_status: `{report['operator_summary_guard_status']}`",
        f"- operator_summary_guard_probe_count: `{report['operator_summary_guard_probe_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Steps",
        *step_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))
