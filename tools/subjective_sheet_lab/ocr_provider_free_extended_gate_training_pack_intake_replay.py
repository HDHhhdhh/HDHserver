from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)


def require_training_pack_intake_replay(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED",
        "training_pack_recognized_evidence_intake_replay.status",
    )
    require_int_value(report.get("checklist_entry_count"), 4, "training_pack_intake_replay.entry_count")
    require_int_value(report.get("evidence_file_count"), 0, "training_pack_intake_replay.file_count")
    require_int_value(report.get("accepted_file_count"), 0, "training_pack_intake_replay.accepted_count")
    require_int_value(report.get("rejected_file_count"), 0, "training_pack_intake_replay.rejected_count")
    require_int_value(report.get("missing_required_file_count"), 4, "training_pack_intake_replay.missing_count")
    require_int_value(report.get("unexpected_file_count"), 0, "training_pack_intake_replay.unexpected_count")
    require_int_value(report.get("target_mismatch_file_count"), 0, "training_pack_intake_replay.mismatch_count")
    require_bool_value(report.get("intake_replay_ready"), False, "training_pack_intake_replay.ready")
    require_text_value(report.get("next_status"), "USER_APPROVAL_REQUIRED", "training_pack_intake_replay.next_status")


def training_pack_intake_replay_summary_fields() -> JsonObject:
    return {
        "training_pack_recognized_evidence_intake_replay_entry_count": 4,
        "training_pack_recognized_evidence_intake_replay_file_count": 0,
        "training_pack_recognized_evidence_intake_replay_accepted_count": 0,
        "training_pack_recognized_evidence_intake_replay_rejected_count": 0,
        "training_pack_recognized_evidence_intake_replay_missing_count": 4,
        "training_pack_recognized_evidence_intake_replay_unexpected_count": 0,
        "training_pack_recognized_evidence_intake_replay_mismatch_count": 0,
        "training_pack_recognized_evidence_intake_replay_ready": False,
    }
