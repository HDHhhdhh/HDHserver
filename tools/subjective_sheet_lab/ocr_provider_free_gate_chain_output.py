# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_provider_free_gate_chain.py

from __future__ import annotations

from ocr_provider_free_gate_chain_model import ChainReport


def markdown(report: ChainReport) -> str:
    step_lines = [f"- {step['name']}: exit {step['exit_code']}, ok {step['ok']}" for step in report["steps"]]
    return "\n".join((
        "# OCR Provider-Free Gate Chain",
        "",
        f"- ok: {report['ok']}",
        f"- student_facing: {report['student_facing']}",
        f"- chain_step_count: {report['chain_step_count']}",
        f"- failed_step_count: {report['failed_step_count']}",
        f"- matrix_ok: {report['matrix_ok']}",
        f"- classifier_status: {report['classifier_status']}",
        f"- freshness_status: {report['freshness_status']}",
        f"- count_consistency_ok: {report['count_consistency_ok']}",
        f"- extended_gate_count: {report['extended_gate_count']}",
        f"- expected_extended_gate_count: {report['expected_extended_gate_count']}",
        f"- latest_queue_count: {report['latest_queue_count']}",
        "- training_pack_recognized_evidence_contract_rejected_probe_count: "
        f"{report['training_pack_recognized_evidence_contract_rejected_probe_count']}",
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
        "## Steps",
        *step_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))
