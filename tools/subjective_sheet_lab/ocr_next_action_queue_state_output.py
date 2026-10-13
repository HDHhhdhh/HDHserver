from __future__ import annotations

from ocr_next_action_queue_state_model import QueueStateReport


def markdown(report: QueueStateReport) -> str:
    missing_lines = [f"- {snippet}" for snippet in report["missing_snippets"]] or ["- none"]
    latest_missing_lines = [f"- {snippet}" for snippet in report["latest_missing_snippets"]] or ["- none"]
    scalar_lines = markdown_scalar_lines(report)
    return "\n".join((
        "# OCR Next-Action Queue State Verification",
        "",
        *scalar_lines,
        "",
        "## Missing Snippets",
        *missing_lines,
        "",
        "## Latest Missing Snippets",
        *latest_missing_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


def markdown_scalar_lines(report: QueueStateReport) -> list[str]:
    return [
        f"- ok: {report['ok']}",
        f"- student_facing: {report['student_facing']}",
        f"- latest_heading: {report['latest_heading']}",
        f"- latest_heading_present: {report['latest_heading_present']}",
        f"- latest_heading_at_tail: {report['latest_heading_at_tail']}",
        f"- required_snippet_count: {report['required_snippet_count']}",
        f"- missing_snippet_count: {report['missing_snippet_count']}",
        f"- latest_required_snippet_count: {report['latest_required_snippet_count']}",
        f"- latest_missing_snippet_count: {report['latest_missing_snippet_count']}",
        f"- expected_extended_gate_count: {report['expected_extended_gate_count']}",
        f"- matrix_ok: {report['matrix_ok']}",
        f"- classifier_status: {report['classifier_status']}",
        f"- freshness_status: {report['freshness_status']}",
        f"- extended_gate_count: {report['extended_gate_count']}",
        f"- provider_call_count: {report['provider_call_count']}",
        f"- external_ocr_api_call_count: {report['external_ocr_api_call_count']}",
        f"- submit_test_call_count: {report['submit_test_call_count']}",
        f"- ts_submit_click_count: {report['ts_submit_click_count']}",
        f"- answer_key_or_grading_field_leak_count: {report['answer_key_or_grading_field_leak_count']}",
        f"- filesystem_path_leak_count: {report['filesystem_path_leak_count']}",
        f"- production_default: {report['production_default']}",
        f"- issue_count: {report['issue_count']}",
    ]
