from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_user_action_required_inventory_guard import REPORT_JSON as USER_ACTION_INVENTORY_GUARD_JSON
from verify_ocr_user_action_required_inventory_guard import main as verify_user_action_inventory_guard
from verify_ocr_user_action_required_inventory import REPORT_JSON as USER_ACTION_INVENTORY_JSON
from verify_ocr_user_action_required_inventory import main as verify_user_action_inventory

Verifier: TypeAlias = Callable[[], int]


def user_action_inventory_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (
        ("OCR user-action required inventory", verify_user_action_inventory),
        ("OCR user-action required inventory guard", verify_user_action_inventory_guard),
    )


def user_action_inventory_reports() -> dict[str, JsonObject]:
    return {
        "user_action_required_inventory": read_json_object(USER_ACTION_INVENTORY_JSON),
        "user_action_required_inventory_guard": read_json_object(USER_ACTION_INVENTORY_GUARD_JSON),
    }


def require_user_action_required_inventory(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "OCR_USER_ACTION_REQUIRED_INVENTORY_VERIFIED",
        "user_action_inventory.status",
    )
    require_int_value(report.get("allowed_status_count"), 25, "user_action_inventory.allowed_status_count")
    require_int_value(report.get("user_required_report_count"), 28, "user_action_inventory.user_required_report_count")
    require_int_value(report.get("unexpected_issue_count"), 0, "user_action_inventory.unexpected_issue_count")


def require_user_action_required_inventory_guard(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "OCR_USER_ACTION_REQUIRED_INVENTORY_GUARD_VERIFIED",
        "user_action_inventory_guard.status",
    )
    require_int_value(report.get("probe_count"), 16, "user_action_inventory_guard.probe_count")
    require_int_value(report.get("failed_probe_count"), 0, "user_action_inventory_guard.failed_probe_count")
    for key in (
        "live_inventory_ok",
        "volatile_aggregate_failure_ignored",
        "nonvolatile_failure_blocked",
        "unexpected_user_action_status_blocked",
        "nonzero_provider_count_blocked",
        "student_facing_user_action_blocked",
        "allowed_user_action_status_accepted",
        "required_approval_reports_present",
        "missing_required_approval_report_blocked",
        "required_approval_status_mismatch_blocked",
        "required_blocker_reports_present",
        "missing_required_blocker_report_blocked",
        "required_blocker_status_mismatch_blocked",
        "required_blocker_value_mismatch_blocked",
    ):
        require_bool_value(report.get(key), True, f"user_action_inventory_guard.{key}")


def user_action_inventory_summary_fields() -> JsonObject:
    return {
        "user_action_inventory_status": "OCR_USER_ACTION_REQUIRED_INVENTORY_VERIFIED",
        "user_action_inventory_allowed_status_count": 25,
        "user_action_inventory_report_count": 28,
        "user_action_inventory_unexpected_issue_count": 0,
        "user_action_inventory_guard_status": "OCR_USER_ACTION_REQUIRED_INVENTORY_GUARD_VERIFIED",
        "user_action_inventory_guard_probe_count": 16,
        "user_action_inventory_guard_volatile_aggregate_failure_ignored": True,
        "user_action_inventory_guard_unexpected_status_blocked": True,
        "user_action_inventory_guard_required_approval_reports_present": True,
        "user_action_inventory_guard_required_approval_missing_blocked": True,
        "user_action_inventory_guard_required_approval_mismatch_blocked": True,
        "user_action_inventory_guard_required_blocker_reports_present": True,
        "user_action_inventory_guard_required_blocker_missing_blocked": True,
        "user_action_inventory_guard_required_blocker_status_mismatch_blocked": True,
        "user_action_inventory_guard_required_blocker_value_mismatch_blocked": True,
    }
