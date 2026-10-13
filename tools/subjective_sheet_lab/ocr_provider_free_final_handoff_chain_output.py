from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from verify_ocr_provider_free_final_handoff_chain import FinalHandoffReport


def markdown(report: FinalHandoffReport) -> str:
    step_lines = [f"- {step['name']}: exit `{step['exit_code']}`, ok `{step['ok']}`" for step in report["steps"]]
    return "\n".join((
        "# OCR Provider-Free Final Handoff Chain",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- step_count: `{report['step_count']}`",
        f"- failed_step_count: `{report['failed_step_count']}`",
        f"- provider_free_chain_step_count: `{report['provider_free_chain_step_count']}`",
        f"- provider_free_chain_failed_step_count: `{report['provider_free_chain_failed_step_count']}`",
        f"- handoff_runner_status: `{report['handoff_runner_status']}`",
        f"- handoff_runner_step_count: `{report['handoff_runner_step_count']}`",
        f"- handoff_runner_failed_step_count: `{report['handoff_runner_failed_step_count']}`",
        f"- handoff_guard_status: `{report['handoff_guard_status']}`",
        f"- handoff_guard_probe_count: `{report['handoff_guard_probe_count']}`",
        f"- handoff_guard_failed_probe_count: `{report['handoff_guard_failed_probe_count']}`",
        "- handoff_runner_common_self_check_source_report_count: "
        f"`{report['handoff_runner_common_self_check_source_report_count']}`",
        "- handoff_runner_evidence_index_source_report_count: "
        f"`{report['handoff_runner_evidence_index_source_report_count']}`",
        "- handoff_runner_evidence_index_guard_failed_probe_count: "
        f"`{report['handoff_runner_evidence_index_guard_failed_probe_count']}`",
        "- post_chain_evidence_index_source_report_count: "
        f"`{report['post_chain_evidence_index_source_report_count']}`",
        f"- post_chain_qa_start_here_source_count: `{report['post_chain_qa_start_here_source_count']}`",
        f"- handoff_retention_guard_probe_count: `{report['handoff_retention_guard_probe_count']}`",
        "- handoff_retention_guard_failed_probe_count: "
        f"`{report['handoff_retention_guard_failed_probe_count']}`",
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
        "- manual_qa_handoff_refresh_serial_guard_status: "
        f"`{report['manual_qa_handoff_refresh_serial_guard_status']}`",
        "- manual_qa_handoff_refresh_serial_guard_probe_count: "
        f"`{report['manual_qa_handoff_refresh_serial_guard_probe_count']}`",
        "- manual_qa_handoff_refresh_serial_guard_failed_probe_count: "
        f"`{report['manual_qa_handoff_refresh_serial_guard_failed_probe_count']}`",
        "- manual_qa_handoff_refresh_serial_guard_lock_file_removed: "
        f"`{report['manual_qa_handoff_refresh_serial_guard_lock_file_removed']}`",
        "- manual_qa_handoff_refresh_serial_guard_artifacts_preserved: "
        f"`{report['manual_qa_handoff_refresh_serial_guard_artifacts_preserved']}`",
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
