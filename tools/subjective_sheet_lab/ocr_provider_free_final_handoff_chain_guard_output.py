from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from verify_ocr_provider_free_final_handoff_chain_guard import FinalHandoffChainGuardReport


def markdown(report: FinalHandoffChainGuardReport) -> str:
    return "\n".join((
        "# OCR Provider-Free Final Handoff Chain Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_final_handoff_passed: `{report['live_final_handoff_passed']}`",
        f"- copied_provider_free_step_blocked: `{report['copied_provider_free_step_blocked']}`",
        f"- copied_serial_guard_step_blocked: `{report['copied_serial_guard_step_blocked']}`",
        f"- copied_handoff_guard_step_blocked: `{report['copied_handoff_guard_step_blocked']}`",
        f"- copied_missing_step_blocked: `{report['copied_missing_step_blocked']}`",
        f"- copied_probes_preserved_chain_artifacts: `{report['copied_probes_preserved_chain_artifacts']}`",
        f"- live_step_count: `{report['live_step_count']}`",
        f"- live_failed_step_count: `{report['live_failed_step_count']}`",
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
