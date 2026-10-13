from __future__ import annotations

from typing import TypedDict

from ocr_provider_free_extended_gate_common import JsonObject


class GuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_inventory_ok: bool
    volatile_aggregate_failure_ignored: bool
    nonvolatile_failure_blocked: bool
    unexpected_user_action_status_blocked: bool
    nonzero_provider_count_blocked: bool
    student_facing_user_action_blocked: bool
    allowed_user_action_status_accepted: bool
    required_approval_reports_present: bool
    missing_required_approval_report_blocked: bool
    required_approval_status_mismatch_blocked: bool
    required_blocker_reports_present: bool
    missing_required_blocker_report_blocked: bool
    required_blocker_status_mismatch_blocked: bool
    required_blocker_value_mismatch_blocked: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def markdown(report: JsonObject) -> str:
    return "\n".join((
        "# OCR User-Action Required Inventory Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- live_inventory_ok: `{report['live_inventory_ok']}`",
        f"- volatile_aggregate_failure_ignored: `{report['volatile_aggregate_failure_ignored']}`",
        f"- nonvolatile_failure_blocked: `{report['nonvolatile_failure_blocked']}`",
        f"- unexpected_user_action_status_blocked: `{report['unexpected_user_action_status_blocked']}`",
        f"- nonzero_provider_count_blocked: `{report['nonzero_provider_count_blocked']}`",
        f"- student_facing_user_action_blocked: `{report['student_facing_user_action_blocked']}`",
        f"- allowed_user_action_status_accepted: `{report['allowed_user_action_status_accepted']}`",
        f"- required_approval_reports_present: `{report['required_approval_reports_present']}`",
        "- missing_required_approval_report_blocked: "
        f"`{report['missing_required_approval_report_blocked']}`",
        "- required_approval_status_mismatch_blocked: "
        f"`{report['required_approval_status_mismatch_blocked']}`",
        f"- required_blocker_reports_present: `{report['required_blocker_reports_present']}`",
        "- missing_required_blocker_report_blocked: "
        f"`{report['missing_required_blocker_report_blocked']}`",
        "- required_blocker_status_mismatch_blocked: "
        f"`{report['required_blocker_status_mismatch_blocked']}`",
        "- required_blocker_value_mismatch_blocked: "
        f"`{report['required_blocker_value_mismatch_blocked']}`",
        "- provider_call_count: `0`",
        "- external_ocr_api_call_count: `0`",
        "- submit_test_call_count: `0`",
        "- ts_submit_click_count: `0`",
        "- answer_key_or_grading_field_leak_count: `0`",
        "- filesystem_path_leak_count: `0`",
        "- production_default: `NO_GO`",
        "",
        "## Next Safe Action",
        str(report["next_safe_action"]),
        "",
    ))
