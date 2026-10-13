# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by ocr_provider_free_extended_gate_summary.py

from __future__ import annotations

from typing import Mapping

from ocr_provider_free_extended_gate_common import JsonObject, require_bool_value, require_int_value, require_object
from ocr_provider_free_extended_gate_common import require_text_value


def require_core_reports(reports: Mapping[str, JsonObject]) -> None:
    base = reports["base"]
    crop = reports["crop_feature"]
    digit = reports["digit_shape"]
    digit_generalization = reports["digit_generalization"]
    digit_shape_candidate_comparison = reports["digit_shape_candidate_comparison"]
    generalization = require_object(digit_generalization.get("summary"), "digit_generalization.summary")
    q003_audit = reports["q003_audit"]
    ambiguity_manifest = reports["ambiguity_manifest"]
    relation_operator_manifest = reports["relation_operator_manifest"]
    visible = reports["visible_digit"]
    visible_second_pass = reports["visible_second_pass"]
    visible_eligibility = reports["visible_eligibility"]
    route_geometry = reports["route_geometry"]
    second_pass_manifest = reports["second_pass_manifest"]
    second_pass_batch_request = reports["second_pass_batch_request"]
    person_second_pass = reports["person_second_pass"]
    second_pass_internal_candidate = reports["second_pass_internal_candidate"]
    person03_live_handoff = reports["person03_live_handoff"]
    next_items = reports["next_items"]
    require_int_value(base.get("gate_count"), 5, "base.gate_count")
    require_int_value(crop.get("case_count"), 4, "crop.case_count")
    require_int_value(digit.get("case_count"), 4, "digit.case_count")
    require_int_value(digit_generalization.get("case_set_count"), 11, "digit_generalization.case_set_count")
    require_int_value(digit_generalization.get("row_count"), 22, "digit_generalization.row_count")
    require_int_value(generalization.get("q003_three_n_signal_count"), 2, "generalization.q003_three_n_signal_count")
    require_int_value(generalization.get("q018_leading_digit_not_nine_like_count"), 1, "generalization.q018_leading_digit_not_nine_like_count")
    require_int_value(digit_shape_candidate_comparison.get("row_count"), 6, "digit_shape_candidate_comparison.row_count")
    require_int_value(digit_shape_candidate_comparison.get("review_required_count"), 4, "digit_shape_candidate_comparison.review_required_count")
    require_int_value(digit_shape_candidate_comparison.get("safe_control_count"), 2, "digit_shape_candidate_comparison.safe_control_count")
    require_int_value(digit_shape_candidate_comparison.get("auto_fill_allowed_count"), 0, "digit_shape_candidate_comparison.auto_fill_allowed_count")
    require_int_value(q003_audit.get("case_count"), 4, "q003_audit.case_count")
    require_int_value(q003_audit.get("review_required_count"), 3, "q003_audit.review_required_count")
    require_int_value(q003_audit.get("safe_auto_grade_count"), 1, "q003_audit.safe_auto_grade_count")
    require_int_value(ambiguity_manifest.get("manifest_item_count"), 6, "ambiguity_manifest.manifest_item_count")
    require_int_value(ambiguity_manifest.get("review_required_count"), 4, "ambiguity_manifest.review_required_count")
    require_int_value(ambiguity_manifest.get("safe_control_count"), 2, "ambiguity_manifest.safe_control_count")
    require_int_value(ambiguity_manifest.get("auto_confirm_allowed_count"), 0, "ambiguity_manifest.auto_confirm_allowed_count")
    require_int_value(relation_operator_manifest.get("manifest_item_count"), 2, "relation_operator_manifest.manifest_item_count")
    require_int_value(relation_operator_manifest.get("review_required_count"), 2, "relation_operator_manifest.review_required_count")
    require_int_value(relation_operator_manifest.get("safe_control_count"), 0, "relation_operator_manifest.safe_control_count")
    require_int_value(relation_operator_manifest.get("auto_confirm_allowed_count"), 0, "relation_operator_manifest.auto_confirm_allowed_count")
    require_int_value(relation_operator_manifest.get("relation_symbol_confusion_count"), 2, "relation_operator_manifest.relation_symbol_confusion_count")
    require_int_value(relation_operator_manifest.get("expression_operator_confusion_count"), 1, "relation_operator_manifest.expression_operator_confusion_count")
    require_int_value(relation_operator_manifest.get("arrow_equal_confusion_count"), 1, "relation_operator_manifest.arrow_equal_confusion_count")
    require_int_value(visible.get("target_count"), 2, "visible.target_count")
    require_int_value(visible.get("visible_candidate_count"), 2, "visible.visible_candidate_count")
    require_int_value(visible_second_pass.get("candidate_count"), 2, "visible_second_pass.candidate_count")
    require_int_value(visible_eligibility.get("case_count"), 7, "visible_eligibility.case_count")
    require_int_value(visible_eligibility.get("eligible_count"), 2, "visible_eligibility.eligible_count")
    require_int_value(visible_eligibility.get("negative_blocked_count"), 5, "visible_eligibility.negative_blocked_count")
    require_int_value(route_geometry.get("question_scan_count"), 80, "route_geometry.question_scan_count")
    require_int_value(route_geometry.get("geometry_only_candidate_count"), 80, "route_geometry.geometry_only_candidate_count")
    require_int_value(route_geometry.get("geometry_only_second_pass_allowed_count"), 0, "route_geometry.geometry_only_second_pass_allowed_count")
    require_int_value(second_pass_manifest.get("review_payload_item_count"), 20, "second_pass_manifest.review_payload_item_count")
    require_int_value(second_pass_manifest.get("candidate_count"), 2, "second_pass_manifest.candidate_count")
    require_int_value(second_pass_manifest.get("blocked_review_required_count"), 2, "second_pass_manifest.blocked_review_required_count")
    require_int_value(second_pass_manifest.get("auto_confirm_allowed_count"), 0, "second_pass_manifest.auto_confirm_allowed_count")
    require_text_value(second_pass_batch_request.get("status"), "USER_APPROVAL_REQUIRED", "second_pass_batch_request.status")
    require_int_value(second_pass_batch_request.get("batch_item_count"), 2, "second_pass_batch_request.batch_item_count")
    require_int_value(second_pass_batch_request.get("auto_confirm_allowed_count"), 0, "second_pass_batch_request.auto_confirm_allowed_count")
    require_int_value(second_pass_batch_request.get("provider_call_budget_required_for_future_run"), 1, "second_pass_batch_request.provider_call_budget_required_for_future_run")
    require_int_value(person_second_pass.get("case_count"), 2, "person_second_pass.case_count")
    require_int_value(person_second_pass.get("request_item_count"), 2, "person_second_pass.request_item_count")
    require_int_value(person_second_pass.get("control_item_count"), 2, "person_second_pass.control_item_count")
    require_int_value(person_second_pass.get("auto_confirm_allowed_count"), 0, "person_second_pass.auto_confirm_allowed_count")
    require_int_value(person_second_pass.get("future_provider_call_budget_required"), 1, "person_second_pass.future_provider_call_budget_required")
    require_int_value(second_pass_internal_candidate.get("linked_question_count"), 2, "second_pass_internal_candidate.linked_question_count")
    require_int_value(second_pass_internal_candidate.get("candidate_signal_count"), 0, "second_pass_internal_candidate.candidate_signal_count")
    require_int_value(second_pass_internal_candidate.get("auto_confirm_allowed_count"), 0, "second_pass_internal_candidate.auto_confirm_allowed_count")
    require_bool_value(second_pass_internal_candidate.get("model_load_allowed"), False, "second_pass_internal_candidate.model_load_allowed")
    require_text_value(person03_live_handoff.get("status"), "USER_APPROVAL_REQUIRED", "person03_live_handoff.status")
    require_int_value(person03_live_handoff.get("request_item_count"), 2, "person03_live_handoff.request_item_count")
    require_int_value(person03_live_handoff.get("declared_provider_call_budget_required"), 1, "person03_live_handoff.declared_provider_call_budget_required")
    require_bool_value(person03_live_handoff.get("live_call_allowed_now"), False, "person03_live_handoff.live_call_allowed_now")
    require_int_value(next_items.get("gate_count"), 5, "next_items.gate_count")
    route_generalization = require_object(next_items.get("route_upload_visible_digit_generalization"), "next_items.route_upload_visible_digit_generalization")
    require_int_value(route_generalization.get("question_scan_count"), 80, "next_items.route.question_scan_count")


def core_summary_fields() -> JsonObject:
    return {
        "base_gate_count": 5,
        "priority_crop_feature_case_count": 4,
        "priority_digit_shape_case_count": 4,
        "digit_shape_generalization_case_set_count": 11,
        "digit_shape_generalization_row_count": 22,
        "digit_shape_candidate_comparison_row_count": 6,
        "digit_shape_candidate_comparison_review_required_count": 4,
        "digit_shape_candidate_comparison_auto_fill_allowed_count": 0,
        "q003_signal_audit_case_count": 4,
        "q003_q018_ambiguity_manifest_item_count": 6,
        "q003_q018_ambiguity_review_required_count": 4,
        "q003_q018_ambiguity_safe_control_count": 2,
        "q015_q016_relation_manifest_item_count": 2,
        "q015_q016_relation_review_required_count": 2,
        "q015_q016_relation_auto_confirm_count": 0,
        "visible_digit_target_count": 2,
        "visible_digit_candidate_count": 2,
        "visible_digit_second_pass_candidate_count": 2,
        "visible_digit_second_pass_eligibility_case_count": 7,
        "visible_digit_second_pass_eligible_count": 2,
        "visible_digit_second_pass_negative_blocked_count": 5,
        "route_visible_digit_geometry_scan_count": 80,
        "route_visible_digit_geometry_only_candidate_count": 80,
        "route_visible_digit_geometry_only_allowed_count": 0,
        "second_pass_manifest_candidate_count": 2,
        "second_pass_manifest_blocked_review_count": 2,
        "second_pass_batch_request_item_count": 2,
        "second_pass_batch_request_future_call_budget_required": 1,
        "person_second_pass_request_item_count": 2,
        "person_second_pass_control_item_count": 2,
        "second_pass_internal_candidate_link_count": 2,
        "second_pass_internal_candidate_signal_count": 0,
        "person03_live_handoff_request_item_count": 2,
        "accuracy_next_items_gate_count": 5,
        "route_upload_visible_digit_scan_count": 80,
    }
