# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_training_pack_recognized_evidence_start_card_guard.py.

from __future__ import annotations

from ocr_training_pack_recognized_evidence_start_card_guard_model import StartCardGuardReport


def markdown(report: StartCardGuardReport) -> str:
    probe_lines = [f"- {probe['name']}: ok `{probe['ok']}`, blocked `{probe['blocked']}`" for probe in report["probes"]]
    return "\n".join((
        "# OCR Training Pack Recognized Evidence Start Card Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_start_card_passed: `{report['live_start_card_passed']}`",
        f"- missing_status_line_blocked: `{report['missing_status_line_blocked']}`",
        f"- missing_command_line_blocked: `{report['missing_command_line_blocked']}`",
        f"- missing_required_file_line_blocked: `{report['missing_required_file_line_blocked']}`",
        f"- copied_bad_missing_file_count_blocked: `{report['copied_bad_missing_file_count_blocked']}`",
        f"- copied_nonzero_provider_count_blocked: `{report['copied_nonzero_provider_count_blocked']}`",
        f"- missing_provider_zero_line_blocked: `{report['missing_provider_zero_line_blocked']}`",
        f"- forbidden_path_snippet_blocked: `{report['forbidden_path_snippet_blocked']}`",
        f"- forbidden_submit_path_blocked: `{report['forbidden_submit_path_blocked']}`",
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
