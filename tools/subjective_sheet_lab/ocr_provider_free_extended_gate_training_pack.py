# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_provider_free_accuracy_gate_extended.py

from __future__ import annotations

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_provider_free_extended_gate_training_pack_replacement import (
    require_training_pack_replacement_reports,
    training_pack_replacement_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_promotion import (
    require_training_pack_promotion_gate,
    training_pack_promotion_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_evidence import (
    require_training_pack_blank_evidence_rejection,
    require_training_pack_evidence_contract,
    require_training_pack_evidence_intake,
    require_training_pack_evidence_target_coverage,
    training_pack_blank_evidence_rejection_summary_fields,
    training_pack_evidence_contract_summary_fields,
    training_pack_evidence_intake_summary_fields,
    training_pack_evidence_target_coverage_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_evidence_example import (
    require_training_pack_evidence_example_shape,
    training_pack_evidence_example_shape_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_evidence_target_diff import (
    require_training_pack_evidence_target_diff,
    training_pack_evidence_target_diff_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_operator_checklist import (
    require_training_pack_operator_checklist,
    training_pack_operator_checklist_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_filename_diagnostics import (
    require_training_pack_filename_diagnostics,
    training_pack_filename_diagnostics_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_intake_replay import (
    require_training_pack_intake_replay,
    training_pack_intake_replay_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_model import TrainingPackReports, training_pack_reports


def require_training_pack_reports(reports: TrainingPackReports) -> None:
    require_text_value(
        reports.crop_readiness.get("status"),
        "TRAINING_PACK_CROP_FIXTURES_MISSING",
        "training_pack_crop_readiness.status",
    )
    require_int_value(reports.crop_readiness.get("target_count"), 4, "training_pack_crop_readiness.target_count")
    require_int_value(
        reports.crop_readiness.get("postprocess_verified_count"),
        4,
        "training_pack_crop_readiness.postprocess_verified_count",
    )
    require_int_value(reports.crop_readiness.get("crop_set_count"), 0, "training_pack_crop_readiness.crop_set_count")
    require_int_value(
        reports.crop_readiness.get("complete_crop_set_count"),
        0,
        "training_pack_crop_readiness.complete_crop_set_count",
    )
    require_bool_value(
        reports.crop_readiness.get("manual_fixture_needed"),
        True,
        "training_pack_crop_readiness.manual_fixture_needed",
    )
    require_text_value(
        reports.source_inventory.get("status"),
        "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING",
        "training_pack_source_inventory.status",
    )
    require_int_value(
        reports.source_inventory.get("source_candidate_count"),
        4,
        "training_pack_source_inventory.source_candidate_count",
    )
    require_int_value(
        reports.source_inventory.get("source_assets_ready_count"),
        4,
        "training_pack_source_inventory.source_assets_ready_count",
    )
    require_int_value(
        reports.source_inventory.get("complete_crop_source_count"),
        4,
        "training_pack_source_inventory.complete_crop_source_count",
    )
    require_int_value(
        reports.source_inventory.get("contact_sheet_source_count"),
        4,
        "training_pack_source_inventory.contact_sheet_source_count",
    )
    require_int_value(
        reports.source_inventory.get("enhanced_crop_source_count"),
        4,
        "training_pack_source_inventory.enhanced_crop_source_count",
    )
    require_int_value(
        reports.source_inventory.get("cache_replay_payload_count"),
        0,
        "training_pack_source_inventory.cache_replay_payload_count",
    )
    require_int_value(
        reports.source_inventory.get("fixture_promotion_candidate_count"),
        4,
        "training_pack_source_inventory.fixture_promotion_candidate_count",
    )
    require_int_value(
        reports.replay_skeleton.get("cache_replay_payload_count"),
        4,
        "training_pack_replay_skeleton.cache_replay_payload_count",
    )
    require_int_value(reports.replay_skeleton.get("total_item_count"), 80, "training_pack_replay_skeleton.total_item_count")
    require_int_value(
        reports.replay_skeleton.get("review_required_count"),
        80,
        "training_pack_replay_skeleton.review_required_count",
    )
    require_int_value(
        reports.replay_skeleton.get("safe_auto_grade_count"),
        0,
        "training_pack_replay_skeleton.safe_auto_grade_count",
    )
    require_int_value(
        reports.replay_skeleton.get("recognized_value_count"),
        0,
        "training_pack_replay_skeleton.recognized_value_count",
    )
    require_int_value(reports.ui_replay_bridge.get("payload_count"), 4, "training_pack_ui_replay_bridge.payload_count")
    require_int_value(
        reports.ui_replay_bridge.get("blocked_final_bridge_count"),
        4,
        "training_pack_ui_replay_bridge.blocked_final_bridge_count",
    )
    require_int_value(
        reports.ui_replay_bridge.get("answers_text_fill_allowed_count"),
        0,
        "training_pack_ui_replay_bridge.answers_text_fill_allowed_count",
    )
    require_int_value(
        reports.ui_replay_bridge.get("ui_review_card_count"),
        80,
        "training_pack_ui_replay_bridge.ui_review_card_count",
    )
    require_int_value(
        reports.accuracy_claim_guard.get("skeleton_payload_count"),
        4,
        "training_pack_accuracy_claim_guard.skeleton_payload_count",
    )
    require_int_value(
        reports.accuracy_claim_guard.get("skeleton_recognized_value_count"),
        0,
        "training_pack_accuracy_claim_guard.skeleton_recognized_value_count",
    )
    require_bool_value(
        reports.accuracy_claim_guard.get("accuracy_claim_allowed"),
        False,
        "training_pack_accuracy_claim_guard.accuracy_claim_allowed",
    )
    require_training_pack_evidence_intake(reports.recognized_evidence_intake)
    require_training_pack_evidence_contract(reports.recognized_evidence_contract)
    require_training_pack_evidence_target_coverage(reports.recognized_evidence_target_coverage)
    require_training_pack_evidence_target_diff(reports.recognized_evidence_target_diff)
    require_training_pack_operator_checklist(reports.recognized_evidence_operator_checklist)
    require_training_pack_filename_diagnostics(reports.recognized_evidence_filename_diagnostics)
    require_training_pack_intake_replay(reports.recognized_evidence_intake_replay)
    require_training_pack_blank_evidence_rejection(reports.blank_evidence_rejection)
    require_training_pack_evidence_example_shape(reports.recognized_evidence_example_shape)
    require_training_pack_promotion_gate(reports.evidence_promotion_gate)
    require_training_pack_replacement_reports(reports.replacement_readiness, reports.replacement_sandbox)
    require_int_value(reports.crop_spec.get("capture_required_count"), 4, "training_pack_crop_spec.capture_required_count")


def training_pack_summary_fields(reports: TrainingPackReports) -> JsonObject:
    return {
        "training_pack_crop_fixture_target_count": 4,
        "training_pack_crop_fixture_complete_count": 0,
        "training_pack_source_candidate_count": 4,
        "training_pack_source_assets_ready_count": 4,
        "training_pack_cache_replay_payload_count": 0,
        "training_pack_fixture_promotion_candidate_count": 4,
        "training_pack_replay_skeleton_payload_count": 4,
        "training_pack_replay_skeleton_review_required_count": 80,
        "training_pack_replay_skeleton_recognized_value_count": 0,
        "training_pack_ui_replay_bridge_payload_count": 4,
        "training_pack_ui_replay_bridge_blocked_final_count": 4,
        "training_pack_ui_replay_bridge_fill_allowed_count": 0,
        "training_pack_ui_replay_bridge_review_card_count": 80,
        "training_pack_accuracy_claim_guard_payload_count": 4,
        "training_pack_accuracy_claim_guard_allowed": False,
        "training_pack_accuracy_claim_guard_recognized_value_count": 0,
        **training_pack_evidence_intake_summary_fields(),
        **training_pack_evidence_contract_summary_fields(),
        **training_pack_evidence_target_coverage_summary_fields(),
        **training_pack_evidence_target_diff_summary_fields(),
        **training_pack_operator_checklist_summary_fields(),
        **training_pack_filename_diagnostics_summary_fields(),
        **training_pack_intake_replay_summary_fields(),
        **training_pack_blank_evidence_rejection_summary_fields(),
        **training_pack_evidence_example_shape_summary_fields(),
        **training_pack_promotion_summary_fields(),
        **training_pack_replacement_summary_fields(),
        "training_pack_crop_fixture_spec_capture_required_count": 4,
    }
