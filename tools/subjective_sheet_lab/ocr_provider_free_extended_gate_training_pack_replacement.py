# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by ocr_provider_free_extended_gate_training_pack.py

from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)


def require_training_pack_replacement_reports(readiness: JsonObject, sandbox: JsonObject) -> None:
    require_int_value(
        readiness.get("source_assets_ready_count"),
        4,
        "training_pack_replacement_readiness.source_assets_ready_count",
    )
    require_int_value(
        readiness.get("approved_ocr_evidence_count"),
        0,
        "training_pack_replacement_readiness.approved_ocr_evidence_count",
    )
    require_int_value(readiness.get("readiness_probe_count"), 3, "training_pack_replacement_readiness.readiness_probe_count")
    require_int_value(
        readiness.get("readiness_ready_probe_count"),
        1,
        "training_pack_replacement_readiness.readiness_ready_probe_count",
    )
    require_int_value(
        readiness.get("readiness_blocked_probe_count"),
        2,
        "training_pack_replacement_readiness.readiness_blocked_probe_count",
    )
    require_bool_value(
        readiness.get("replacement_allowed"),
        False,
        "training_pack_replacement_readiness.replacement_allowed",
    )
    require_text_value(
        readiness.get("next_status"),
        "USER_APPROVAL_REQUIRED",
        "training_pack_replacement_readiness.next_status",
    )
    require_text_value(
        sandbox.get("status"),
        "TRAINING_PACK_REPLACEMENT_SANDBOX_BLOCKED_BY_MISSING_EVIDENCE",
        "training_pack_replacement_sandbox.status",
    )
    require_bool_value(
        sandbox.get("contract_ready"),
        True,
        "training_pack_replacement_sandbox.contract_ready",
    )
    require_int_value(
        sandbox.get("contract_evidence_file_count"),
        0,
        "training_pack_replacement_sandbox.contract_evidence_file_count",
    )
    require_int_value(
        sandbox.get("contract_probe_rejected_count"),
        9,
        "training_pack_replacement_sandbox.contract_probe_rejected_count",
    )
    require_int_value(
        sandbox.get("safe_auto_grade_status_probe_rejected_count"),
        1,
        "training_pack_replacement_sandbox.safe_auto_grade_status_probe_rejected_count",
    )
    require_int_value(
        sandbox.get("approved_ocr_evidence_count"),
        0,
        "training_pack_replacement_sandbox.approved_ocr_evidence_count",
    )
    require_bool_value(
        sandbox.get("replacement_attempted"),
        False,
        "training_pack_replacement_sandbox.replacement_attempted",
    )
    require_int_value(
        sandbox.get("replacement_decision_probe_count"),
        5,
        "training_pack_replacement_sandbox.replacement_decision_probe_count",
    )
    require_int_value(
        sandbox.get("replacement_decision_allowed_probe_count"),
        1,
        "training_pack_replacement_sandbox.replacement_decision_allowed_probe_count",
    )
    require_int_value(
        sandbox.get("replacement_decision_blocked_probe_count"),
        4,
        "training_pack_replacement_sandbox.replacement_decision_blocked_probe_count",
    )
    require_int_value(
        sandbox.get("replacement_payload_created_count"),
        0,
        "training_pack_replacement_sandbox.replacement_payload_created_count",
    )
    require_bool_value(
        sandbox.get("accuracy_recompute_attempted"),
        False,
        "training_pack_replacement_sandbox.accuracy_recompute_attempted",
    )
    require_int_value(
        sandbox.get("accuracy_report_created_count"),
        0,
        "training_pack_replacement_sandbox.accuracy_report_created_count",
    )
    require_text_value(
        sandbox.get("next_status"),
        "USER_APPROVAL_REQUIRED",
        "training_pack_replacement_sandbox.next_status",
    )


def training_pack_replacement_summary_fields() -> JsonObject:
    return {
        "training_pack_replacement_readiness_source_assets_ready_count": 4,
        "training_pack_replacement_readiness_evidence_count": 0,
        "training_pack_replacement_readiness_probe_count": 3,
        "training_pack_replacement_readiness_ready_probe_count": 1,
        "training_pack_replacement_readiness_blocked_probe_count": 2,
        "training_pack_replacement_readiness_allowed": False,
        "training_pack_replacement_readiness_next_status": "USER_APPROVAL_REQUIRED",
        "training_pack_replacement_sandbox_contract_ready": True,
        "training_pack_replacement_sandbox_contract_file_count": 0,
        "training_pack_replacement_sandbox_contract_rejected_probe_count": 9,
        "training_pack_replacement_sandbox_safe_auto_grade_status_rejected_count": 1,
        "training_pack_replacement_sandbox_decision_probe_count": 5,
        "training_pack_replacement_sandbox_decision_allowed_probe_count": 1,
        "training_pack_replacement_sandbox_decision_blocked_probe_count": 4,
        "training_pack_replacement_sandbox_attempted": False,
        "training_pack_replacement_sandbox_payload_created_count": 0,
        "training_pack_replacement_sandbox_accuracy_attempted": False,
        "training_pack_replacement_sandbox_accuracy_report_count": 0,
    }
