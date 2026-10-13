from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from ocr_post_chain_evidence_index_common import path_mtime
from ocr_provider_free_extended_gate_common import ExtendedGateError, JsonObject, JsonValue, read_json_object
import verify_ocr_provider_free_handoff_status_card as status_card
import verify_ocr_provider_free_operator_summary as operator_summary


class OperatorSummaryGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_summary_ready: bool
    copied_stale_status_card_reported: bool
    copied_blocked_status_card_reported: bool
    copied_unknown_status_rejected: bool
    copied_leak_rejected: bool
    copied_next_action_leak_rejected: bool
    copied_next_action_missing_count_rejected: bool
    live_operator_next_action_bridged: bool
    summary_does_not_refresh_status_card: bool
    live_operator_state: str
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class GuardProbes:
    live_summary_ready: bool
    stale_status_card_reported: bool
    blocked_status_card_reported: bool
    unknown_status_rejected: bool
    leak_rejected: bool
    next_action_leak_rejected: bool
    next_action_missing_count_rejected: bool
    operator_next_action_bridged: bool
    status_card_preserved: bool


def build_probes(
    live_report: operator_summary.OperatorSummaryReport,
    before: tuple[int, int],
) -> GuardProbes:
    operator_summary.build_report(
        read_json_object(status_card.REPORT_JSON_OUT),
        read_json_object(operator_summary.OPERATOR_NEXT_ACTION_JSON),
    )
    after = snapshot_status_card()
    return GuardProbes(
        live_summary_ready=live_report["operator_state"] == "READY" and live_report["manual_qa_ready"] is True,
        stale_status_card_reported=summary_state(copied_status_card(stale_count=1, failed_count=0)) == "STALE",
        blocked_status_card_reported=summary_state(copied_status_card(stale_count=0, failed_count=1)) == "BLOCKED",
        unknown_status_rejected=payload_rejected(copied_payload("status", "SYNTHETIC_STATUS")),
        leak_rejected=payload_rejected(copied_payload("filesystem_path_leak_count", 1)),
        next_action_leak_rejected=next_action_payload_rejected(copied_next_action_payload("provider_call_count", 1)),
        next_action_missing_count_rejected=next_action_payload_rejected(copied_next_action_payload("missing_file_count", 3)),
        operator_next_action_bridged=operator_next_action_bridged(live_report),
        status_card_preserved=before == after,
    )


def copied_status_card(*, stale_count: int, failed_count: int) -> JsonObject:
    payload = read_json_object(status_card.REPORT_JSON_OUT)
    copied = dict(payload)
    copied["ok"] = False
    copied["status"] = "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_BLOCKED"
    copied["manual_qa_handoff_status"] = "BLOCKED"
    copied["stale_source_count"] = stale_count
    copied["failed_source_count"] = failed_count
    return copied


def copied_payload(key: str, value: JsonValue) -> JsonObject:
    payload = read_json_object(status_card.REPORT_JSON_OUT)
    copied = dict(payload)
    copied[key] = value
    return copied


def summary_state(payload: JsonObject) -> str:
    return operator_summary.build_report(payload, read_json_object(operator_summary.OPERATOR_NEXT_ACTION_JSON))["operator_state"]


def payload_rejected(payload: JsonObject) -> bool:
    try:
        operator_summary.build_report(payload, read_json_object(operator_summary.OPERATOR_NEXT_ACTION_JSON))
    except ExtendedGateError:
        return True
    return False


def copied_next_action_payload(key: str, value: JsonValue) -> JsonObject:
    payload = read_json_object(operator_summary.OPERATOR_NEXT_ACTION_JSON)
    copied = dict(payload)
    copied[key] = value
    return copied


def next_action_payload_rejected(payload: JsonObject) -> bool:
    try:
        operator_summary.build_report(read_json_object(status_card.REPORT_JSON_OUT), payload)
    except ExtendedGateError:
        return True
    return False


def operator_next_action_bridged(report: operator_summary.OperatorSummaryReport) -> bool:
    return (
        report["required_user_action"] == "copy_four_contract_valid_training_pack_recognized_evidence_files"
        and report["operator_next_action"] == "copy_four_contract_valid_training_pack_recognized_evidence_files"
        and report["current_blocker"] == "training_pack_recognized_evidence_files_missing"
        and report["operator_required_file_count"] == 4
        and report["operator_present_file_count"] == 0
        and report["operator_missing_file_count"] == 4
        and report["operator_ready_now"] is False
        and report["operator_ready_after_required_files"] is True
        and report["promotion_write_authorization_required"] is True
    )


def snapshot_status_card() -> tuple[int, int]:
    return (
        path_mtime(status_card.REPORT_JSON_OUT),
        path_mtime(status_card.REPORT_MD_OUT),
    )


def build_guard_report(
    probes: GuardProbes,
    live_report: operator_summary.OperatorSummaryReport,
) -> OperatorSummaryGuardReport:
    probe_results = (
        probes.live_summary_ready,
        probes.stale_status_card_reported,
        probes.blocked_status_card_reported,
        probes.unknown_status_rejected,
        probes.leak_rejected,
        probes.next_action_leak_rejected,
        probes.next_action_missing_count_rejected,
        probes.operator_next_action_bridged,
        probes.status_card_preserved,
    )
    failed_probe_count = sum(1 for passed in probe_results if not passed)
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_OPERATOR_SUMMARY_GUARD_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_OPERATOR_SUMMARY_GUARD_FAILED",
        "probe_count": len(probe_results),
        "failed_probe_count": failed_probe_count,
        "live_summary_ready": probes.live_summary_ready,
        "copied_stale_status_card_reported": probes.stale_status_card_reported,
        "copied_blocked_status_card_reported": probes.blocked_status_card_reported,
        "copied_unknown_status_rejected": probes.unknown_status_rejected,
        "copied_leak_rejected": probes.leak_rejected,
        "copied_next_action_leak_rejected": probes.next_action_leak_rejected,
        "copied_next_action_missing_count_rejected": probes.next_action_missing_count_rejected,
        "live_operator_next_action_bridged": probes.operator_next_action_bridged,
        "summary_does_not_refresh_status_card": probes.status_card_preserved,
        "live_operator_state": live_report["operator_state"],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Use the operator summary as the compact manual-QA start state."
    return "Fix operator summary probes before using compact manual-QA state."
