from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)


def require_training_pack_operator_checklist(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED",
        "training_pack_recognized_evidence_operator_checklist.status",
    )
    require_int_value(report.get("checklist_entry_count"), 4, "training_pack_operator_checklist.entry_count")
    require_int_value(report.get("operator_action_required_count"), 4, "training_pack_operator_checklist.action_count")
    require_int_value(report.get("ready_entry_count"), 0, "training_pack_operator_checklist.ready_count")
    require_int_value(report.get("required_file_count"), 4, "training_pack_operator_checklist.file_count")
    require_int_value(report.get("required_review_item_count_per_payload"), 20, "training_pack_operator_checklist.item_count")
    require_bool_value(report.get("checklist_ready"), False, "training_pack_operator_checklist.ready")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_operator_checklist.next_status")


def training_pack_operator_checklist_summary_fields() -> JsonObject:
    return {
        "training_pack_recognized_evidence_operator_checklist_entry_count": 4,
        "training_pack_recognized_evidence_operator_checklist_action_required_count": 4,
        "training_pack_recognized_evidence_operator_checklist_ready_count": 0,
        "training_pack_recognized_evidence_operator_checklist_file_count": 4,
        "training_pack_recognized_evidence_operator_checklist_item_count_per_payload": 20,
        "training_pack_recognized_evidence_operator_checklist_ready": False,
    }
