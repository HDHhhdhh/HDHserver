from __future__ import annotations

from dataclasses import dataclass

from ocr_provider_free_extended_gate_common import JsonObject
from ocr_user_action_required_inventory_guard_policy import (
    required_approval_rows,
    required_approval_rows_present,
    required_blocker_rows,
    required_blocker_rows_present,
)
from verify_ocr_user_action_required_inventory import InventoryRow, inspect_payload


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    passed: bool
    issue_count: int
    row_count: int


@dataclass(frozen=True, slots=True)
class PayloadProbeSpec:
    name: str
    file_name: str
    payload: JsonObject
    expected_issue: str
    expected_row_count: int


def guard_probes() -> tuple[ProbeResult, ...]:
    return (
        *(payload_probe(spec) for spec in payload_probe_specs()),
        missing_required_approval_report_probe(),
        required_approval_status_mismatch_probe(),
        missing_required_blocker_report_probe(),
        required_blocker_status_mismatch_probe(),
        required_blocker_value_mismatch_probe(),
    )


def payload_probe_specs() -> tuple[PayloadProbeSpec, ...]:
    return (
        PayloadProbeSpec(
            name="volatile_aggregate_failure_ignored",
            file_name="ocr_provider_free_gate_chain.json",
            payload=base_payload(ok=False),
            expected_issue="",
            expected_row_count=0,
        ),
        PayloadProbeSpec(
            name="final_handoff_aggregate_failure_ignored",
            file_name="ocr_provider_free_final_handoff_chain.json",
            payload=base_payload(ok=False),
            expected_issue="",
            expected_row_count=0,
        ),
        PayloadProbeSpec(
            name="handoff_status_card_aggregate_failure_ignored",
            file_name="ocr_provider_free_handoff_status_card.json",
            payload=base_payload(ok=False),
            expected_issue="",
            expected_row_count=0,
        ),
        PayloadProbeSpec(
            name="nonvolatile_failure_blocked",
            file_name="ordinary_lab_report.json",
            payload=base_payload(ok=False),
            expected_issue="ordinary_lab_report.json: ok=false",
            expected_row_count=0,
        ),
        PayloadProbeSpec(
            name="unexpected_user_action_status_blocked",
            file_name="unexpected_user_action.json",
            payload={**base_payload(ok=True), "status": "NEW_USER_ACTION_REQUIRED"},
            expected_issue="unexpected user-required status NEW_USER_ACTION_REQUIRED",
            expected_row_count=1,
        ),
        PayloadProbeSpec(
            name="nonzero_provider_count_blocked",
            file_name="nonzero_provider.json",
            payload={**allowed_user_payload(), "provider_call_count": 1},
            expected_issue="nonzero_provider.json: provider_call_count=1",
            expected_row_count=1,
        ),
        PayloadProbeSpec(
            name="student_facing_user_action_blocked",
            file_name="student_facing_user_action.json",
            payload={**allowed_user_payload(), "student_facing": True},
            expected_issue="student_facing_user_action.json: student_facing=true",
            expected_row_count=1,
        ),
        PayloadProbeSpec(
            name="allowed_user_action_status_accepted",
            file_name="allowed_user_action.json",
            payload=allowed_user_payload(),
            expected_issue="",
            expected_row_count=1,
        ),
    )


def payload_probe(spec: PayloadProbeSpec) -> ProbeResult:
    rows: list[InventoryRow] = []
    issues: list[str] = []
    inspect_payload(spec.file_name, spec.payload, rows, issues)
    issue_matched = (spec.expected_issue == "" and not issues) or any(spec.expected_issue in issue for issue in issues)
    row_count = len(rows)
    return ProbeResult(
        name=spec.name,
        passed=issue_matched and row_count == spec.expected_row_count,
        issue_count=len(issues),
        row_count=row_count,
    )


def missing_required_approval_report_probe() -> ProbeResult:
    rows = required_approval_rows()[1:]
    return ProbeResult(
        name="missing_required_approval_report_blocked",
        passed=not required_approval_rows_present(rows),
        issue_count=0,
        row_count=len(rows),
    )


def required_approval_status_mismatch_probe() -> ProbeResult:
    rows = list(required_approval_rows())
    first_row = rows[0]
    rows[0] = {**first_row, "status": "READY"}
    return ProbeResult(
        name="required_approval_status_mismatch_blocked",
        passed=not required_approval_rows_present(tuple(rows)),
        issue_count=0,
        row_count=len(rows),
    )


def missing_required_blocker_report_probe() -> ProbeResult:
    rows = required_blocker_rows()[1:]
    return ProbeResult(
        name="missing_required_blocker_report_blocked",
        passed=not required_blocker_rows_present(rows),
        issue_count=0,
        row_count=len(rows),
    )


def required_blocker_status_mismatch_probe() -> ProbeResult:
    rows = list(required_blocker_rows())
    first_row = rows[0]
    rows[0] = {**first_row, "status": "READY"}
    return ProbeResult(
        name="required_blocker_status_mismatch_blocked",
        passed=not required_blocker_rows_present(tuple(rows)),
        issue_count=0,
        row_count=len(rows),
    )


def required_blocker_value_mismatch_probe() -> ProbeResult:
    rows = list(required_blocker_rows())
    first_row = rows[0]
    rows[0] = {**first_row, "current_blocker": ""}
    return ProbeResult(
        name="required_blocker_value_mismatch_blocked",
        passed=not required_blocker_rows_present(tuple(rows)),
        issue_count=0,
        row_count=len(rows),
    )


def base_payload(*, ok: bool) -> JsonObject:
    return {
        "ok": ok,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
    }


def allowed_user_payload() -> JsonObject:
    return {**base_payload(ok=True), "status": "USER_APPROVAL_REQUIRED"}
