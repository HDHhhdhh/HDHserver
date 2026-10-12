from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_evidence_missing_blocker_snapshot import REPORT_JSON as MISSING_BLOCKER_JSON
from verify_ocr_training_pack_evidence_missing_blocker_snapshot import main as verify_missing_blocker
from verify_ocr_training_pack_evidence_missing_blocker_snapshot_guard import (
    REPORT_JSON as MISSING_BLOCKER_GUARD_JSON,
)
from verify_ocr_training_pack_evidence_missing_blocker_snapshot_guard import main as verify_missing_blocker_guard

Verifier: TypeAlias = Callable[[], int]


def missing_blocker_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (
        ("training pack evidence missing blocker snapshot", verify_missing_blocker),
        ("training pack evidence missing blocker guard", verify_missing_blocker_guard),
    )


def missing_blocker_reports() -> dict[str, JsonObject]:
    return {
        "training_pack_evidence_missing_blocker_snapshot": read_json_object(MISSING_BLOCKER_JSON),
        "training_pack_evidence_missing_blocker_guard": read_json_object(MISSING_BLOCKER_GUARD_JSON),
    }


def require_training_pack_evidence_missing_blocker(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_SNAPSHOT_READY",
        "missing_blocker.status",
    )
    require_text_value(
        report.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "missing_blocker.current_blocker",
    )
    require_text_value(
        report.get("safe_next_action"),
        "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "missing_blocker.safe_next_action",
    )
    require_int_value(report.get("required_file_count"), 4, "missing_blocker.required_file_count")
    require_int_value(report.get("present_file_count"), 0, "missing_blocker.present_file_count")
    require_int_value(report.get("missing_file_count"), 4, "missing_blocker.missing_file_count")
    require_bool_value(report.get("ready_now"), False, "missing_blocker.ready_now")
    require_bool_value(report.get("ready_after_required_files"), True, "missing_blocker.ready_after_required_files")
    require_bool_value(
        report.get("payload_parse_before_arrival_smoke_allowed"),
        False,
        "missing_blocker.payload_parse_before_arrival_smoke_allowed",
    )
    require_text_value(
        report.get("allowed_after_files_arrive"),
        "smoke_then_blank_rejection_then_contract_validate_then_intake_replay_only",
        "missing_blocker.allowed_after_files_arrive",
    )
    require_text_value(
        report.get("blocked_without_separate_authorization"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "missing_blocker.blocked_without_separate_authorization",
    )


def require_training_pack_evidence_missing_blocker_guard(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_GUARD_VERIFIED",
        "missing_blocker_guard.status",
    )
    require_int_value(report.get("probe_count"), 9, "missing_blocker_guard.probe_count")
    require_int_value(report.get("failed_probe_count"), 0, "missing_blocker_guard.failed_probe_count")
    for key in (
        "live_snapshot_passed",
        "ready_now_true_blocked",
        "ready_after_files_false_blocked",
        "zero_missing_files_blocked",
        "payload_parse_before_smoke_blocked",
        "weakened_arrival_sequence_blocked",
        "weakened_authorization_blocked",
        "nonzero_provider_count_blocked",
        "production_default_enable_blocked",
    ):
        require_bool_value(report.get(key), True, f"missing_blocker_guard.{key}")


def missing_blocker_summary_fields() -> JsonObject:
    return {
        "training_pack_evidence_missing_blocker_status": "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_SNAPSHOT_READY",
        "training_pack_evidence_missing_blocker": "training_pack_recognized_evidence_files_missing",
        "training_pack_evidence_missing_blocker_required_file_count": 4,
        "training_pack_evidence_missing_blocker_present_file_count": 0,
        "training_pack_evidence_missing_blocker_missing_file_count": 4,
        "training_pack_evidence_missing_blocker_ready_now": False,
        "training_pack_evidence_missing_blocker_ready_after_required_files": True,
        "training_pack_evidence_missing_blocker_guard_status": "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_GUARD_VERIFIED",
        "training_pack_evidence_missing_blocker_guard_probe_count": 9,
        "training_pack_evidence_missing_blocker_guard_ready_now_true_blocked": True,
        "training_pack_evidence_missing_blocker_guard_weakened_authorization_blocked": True,
    }
