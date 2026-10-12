from __future__ import annotations

from collections.abc import Mapping

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)


def require_training_pack_dropbox(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_EVIDENCE_DROPBOX_USER_APPROVAL_REQUIRED",
        "training_pack_dropbox.status",
    )
    require_int_value(report.get("required_file_count"), 4, "training_pack_dropbox.required_file_count")
    require_int_value(report.get("present_file_count"), 0, "training_pack_dropbox.present_file_count")
    require_int_value(report.get("missing_file_count"), 4, "training_pack_dropbox.missing_file_count")
    require_int_value(report.get("unexpected_file_count"), 0, "training_pack_dropbox.unexpected_file_count")
    require_bool_value(report.get("dropbox_ready"), False, "training_pack_dropbox.dropbox_ready")


def require_training_pack_handoff(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_OPERATOR_HANDOFF_USER_APPROVAL_REQUIRED",
        "training_pack_handoff.status",
    )
    require_int_value(report.get("pipeline_stage_count"), 6, "training_pack_handoff.pipeline_stage_count")
    require_int_value(report.get("ready_stage_count"), 1, "training_pack_handoff.ready_stage_count")
    require_int_value(report.get("blocked_stage_count"), 5, "training_pack_handoff.blocked_stage_count")
    require_bool_value(report.get("handoff_ready"), False, "training_pack_handoff.handoff_ready")


def require_training_pack_dropbox_ready_simulation(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_DROPBOX_READY_SIMULATION_READY",
        "training_pack_dropbox_ready_simulation.status",
    )
    require_int_value(report.get("simulation_count"), 5, "training_pack_dropbox_ready_simulation.simulation_count")
    require_int_value(report.get("passed_simulation_count"), 5, "training_pack_dropbox_ready_simulation.passed_simulation_count")
    require_bool_value(
        report.get("simulated_full_dropbox_ready"),
        True,
        "training_pack_dropbox_ready_simulation.simulated_full_dropbox_ready",
    )


def require_training_pack_copy_checklist(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_OPERATOR_COPY_CHECKLIST_USER_ACTION_REQUIRED",
        "training_pack_copy_checklist.status",
    )
    require_int_value(report.get("checklist_entry_count"), 4, "training_pack_copy_checklist.checklist_entry_count")
    require_int_value(report.get("operator_action_required_count"), 4, "training_pack_copy_checklist.operator_action_required_count")
    require_bool_value(report.get("evidence_ready"), False, "training_pack_copy_checklist.evidence_ready")


def require_training_pack_post_dropbox_acceptance(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_POST_DROPBOX_ACCEPTANCE_GATE_READY",
        "training_pack_post_dropbox_acceptance.status",
    )
    require_int_value(report.get("acceptance_check_count"), 7, "training_pack_post_dropbox_acceptance.check_count")
    require_int_value(report.get("accepted_check_count"), 7, "training_pack_post_dropbox_acceptance.accepted_check_count")
    require_int_value(
        report.get("safe_auto_grade_evidence_rejected_count"),
        4,
        "training_pack_post_dropbox_acceptance.safe_auto_grade_evidence_rejected_count",
    )
    require_bool_value(report.get("acceptance_ready_now"), False, "training_pack_post_dropbox_acceptance.ready_now")
    require_bool_value(
        report.get("acceptance_ready_after_required_files"),
        True,
        "training_pack_post_dropbox_acceptance.ready_after_required_files",
    )


def require_training_pack_promotion_preview(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_PROMOTION_PREVIEW_USER_APPROVAL_REQUIRED",
        "training_pack_promotion_preview.status",
    )
    require_int_value(report.get("preview_row_count"), 4, "training_pack_promotion_preview.preview_row_count")
    require_int_value(report.get("preview_question_count_total"), 80, "training_pack_promotion_preview.question_count")
    require_bool_value(report.get("promotion_preview_ready"), False, "training_pack_promotion_preview.ready")
    require_bool_value(report.get("promotion_write_attempted"), False, "training_pack_promotion_preview.write_attempted")


def require_training_pack_promotion_preview_diff(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_PROMOTION_PREVIEW_DIFF_USER_APPROVAL_REQUIRED",
        "training_pack_promotion_preview_diff.status",
    )
    require_int_value(report.get("preview_row_count"), 4, "training_pack_promotion_preview_diff.preview_row_count")
    require_int_value(report.get("actual_payload_count"), 0, "training_pack_promotion_preview_diff.actual_payload_count")
    require_int_value(
        report.get("actual_preview_match_count"),
        0,
        "training_pack_promotion_preview_diff.actual_match_count",
    )
    require_int_value(
        report.get("actual_missing_preview_count"),
        4,
        "training_pack_promotion_preview_diff.actual_missing_count",
    )
    require_int_value(
        report.get("simulated_preview_match_count"),
        4,
        "training_pack_promotion_preview_diff.simulated_match_count",
    )
    require_int_value(
        report.get("simulated_preview_mismatch_count"),
        0,
        "training_pack_promotion_preview_diff.simulated_mismatch_count",
    )
    require_bool_value(report.get("current_diff_ready"), False, "training_pack_promotion_preview_diff.ready_now")
    require_bool_value(report.get("post_file_diff_ready"), True, "training_pack_promotion_preview_diff.ready_after_files")
    require_bool_value(report.get("promotion_write_attempted"), False, "training_pack_promotion_preview_diff.write_attempted")


def require_training_pack_flow_reports(reports: Mapping[str, JsonObject]) -> None:
    require_training_pack_dropbox(reports["training_pack_evidence_dropbox"])
    require_training_pack_dropbox_ready_simulation(reports["training_pack_dropbox_ready_simulation"])
    require_training_pack_handoff(reports["training_pack_operator_handoff"])
    require_training_pack_copy_checklist(reports["training_pack_operator_copy_checklist"])
    require_training_pack_post_dropbox_acceptance(reports["training_pack_post_dropbox_acceptance"])
    require_training_pack_promotion_preview(reports["training_pack_promotion_preview"])
    require_training_pack_promotion_preview_diff(reports["training_pack_promotion_preview_diff"])


def training_pack_dropbox_fields() -> JsonObject:
    return {
        "training_pack_evidence_dropbox_required_file_count": 4,
        "training_pack_evidence_dropbox_present_file_count": 0,
        "training_pack_evidence_dropbox_missing_file_count": 4,
        "training_pack_evidence_dropbox_unexpected_file_count": 0,
        "training_pack_evidence_dropbox_ready": False,
    }


def training_pack_handoff_fields() -> JsonObject:
    return {
        "training_pack_operator_handoff_stage_count": 6,
        "training_pack_operator_handoff_ready_stage_count": 1,
        "training_pack_operator_handoff_blocked_stage_count": 5,
        "training_pack_operator_handoff_ready": False,
    }


def training_pack_dropbox_ready_simulation_fields() -> JsonObject:
    return {
        "training_pack_dropbox_ready_simulation_count": 5,
        "training_pack_dropbox_ready_simulation_passed_count": 5,
        "training_pack_dropbox_ready_simulated_full_ready": True,
        "training_pack_dropbox_ready_simulated_copy_ready": True,
    }


def training_pack_copy_checklist_fields() -> JsonObject:
    return {
        "training_pack_operator_copy_checklist_entry_count": 4,
        "training_pack_operator_copy_checklist_action_required_count": 4,
        "training_pack_operator_copy_checklist_ready": False,
    }


def training_pack_post_dropbox_acceptance_fields() -> JsonObject:
    return {
        "training_pack_post_dropbox_acceptance_check_count": 7,
        "training_pack_post_dropbox_acceptance_passed_count": 7,
        "training_pack_post_dropbox_acceptance_safe_auto_grade_rejected_count": 4,
        "training_pack_post_dropbox_acceptance_ready_now": False,
        "training_pack_post_dropbox_acceptance_ready_after_required_files": True,
    }


def training_pack_promotion_preview_fields() -> JsonObject:
    return {
        "training_pack_promotion_preview_row_count": 4,
        "training_pack_promotion_preview_question_count": 80,
        "training_pack_promotion_preview_ready": False,
        "training_pack_promotion_preview_write_attempted": False,
    }


def training_pack_promotion_preview_diff_fields() -> JsonObject:
    return {
        "training_pack_promotion_preview_diff_row_count": 4,
        "training_pack_promotion_preview_diff_actual_payload_count": 0,
        "training_pack_promotion_preview_diff_actual_match_count": 0,
        "training_pack_promotion_preview_diff_actual_missing_count": 4,
        "training_pack_promotion_preview_diff_simulated_match_count": 4,
        "training_pack_promotion_preview_diff_simulated_mismatch_count": 0,
        "training_pack_promotion_preview_diff_ready_now": False,
        "training_pack_promotion_preview_diff_ready_after_files": True,
        "training_pack_promotion_preview_diff_write_attempted": False,
    }


def training_pack_flow_summary_fields() -> JsonObject:
    return {
        **training_pack_dropbox_fields(),
        **training_pack_dropbox_ready_simulation_fields(),
        **training_pack_handoff_fields(),
        **training_pack_copy_checklist_fields(),
        **training_pack_post_dropbox_acceptance_fields(),
        **training_pack_promotion_preview_fields(),
        **training_pack_promotion_preview_diff_fields(),
    }
