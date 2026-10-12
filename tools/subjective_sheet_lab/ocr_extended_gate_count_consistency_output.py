from __future__ import annotations

from ocr_extended_gate_count_consistency_model import CountConsistencyReport


def markdown(report: CountConsistencyReport) -> str:
    issue_lines = [f"- {issue}" for issue in report["issues"]] or ["- none"]
    return "\n".join((
        "# OCR Extended Gate Count Consistency",
        "",
        f"- ok: {report['ok']}",
        f"- student_facing: {report['student_facing']}",
        f"- expected_extended_gate_count: {report['expected_extended_gate_count']}",
        f"- extended_report_count: {report['extended_report_count']}",
        f"- matrix_report_count: {report['matrix_report_count']}",
        f"- classifier_report_count: {report['classifier_report_count']}",
        f"- freshness_report_count: {report['freshness_report_count']}",
        f"- queue_state_report_count: {report['queue_state_report_count']}",
        f"- operator_summary_report_count: {report['operator_summary_report_count']}",
        f"- queue_state_modified_ns: {report['queue_state_modified_ns']}",
        f"- operator_summary_modified_ns: {report['operator_summary_modified_ns']}",
        f"- operator_summary_newer_than_queue_state: {report['operator_summary_newer_than_queue_state']}",
        f"- latest_queue_count: {report['latest_queue_count']}",
        f"- latest_queue_count_match_count: {report['latest_queue_count_match_count']}",
        f"- total_queue_count_occurrence_count: {report['total_queue_count_occurrence_count']}",
        f"- historical_queue_count_occurrence_count: {report['historical_queue_count_occurrence_count']}",
        f"- historical_counts_ignored_for_current: {report['historical_counts_ignored_for_current']}",
        "- training_pack_recognized_evidence_contract_rejected_probe_count: "
        f"{report['training_pack_recognized_evidence_contract_rejected_probe_count']}",
        "- training_pack_recognized_evidence_contract_sensitive_probe_count: "
        f"{report['training_pack_recognized_evidence_contract_sensitive_probe_count']}",
        "- training_pack_recognized_evidence_contract_path_probe_count: "
        f"{report['training_pack_recognized_evidence_contract_path_probe_count']}",
        "- training_pack_recognized_evidence_contract_schema_probe_count: "
        f"{report['training_pack_recognized_evidence_contract_schema_probe_count']}",
        "- training_pack_recognized_evidence_contract_safe_auto_grade_status_probe_count: "
        f"{report['training_pack_recognized_evidence_contract_safe_auto_grade_status_probe_count']}",
        "- training_pack_replacement_sandbox_safe_auto_grade_status_rejected_count: "
        f"{report['training_pack_replacement_sandbox_safe_auto_grade_status_rejected_count']}",
        f"- provider_call_count: {report['provider_call_count']}",
        f"- external_ocr_api_call_count: {report['external_ocr_api_call_count']}",
        f"- submit_test_call_count: {report['submit_test_call_count']}",
        f"- ts_submit_click_count: {report['ts_submit_click_count']}",
        f"- answer_key_or_grading_field_leak_count: {report['answer_key_or_grading_field_leak_count']}",
        f"- filesystem_path_leak_count: {report['filesystem_path_leak_count']}",
        f"- production_default: {report['production_default']}",
        f"- issue_count: {report['issue_count']}",
        "",
        "## Issues",
        *issue_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))
