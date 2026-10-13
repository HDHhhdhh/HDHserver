from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import JsonObject, read_json_object
from ocr_provider_free_extended_gate_registry_training_pack import (
    training_pack_reports_by_key,
    training_pack_verifiers,
)
from verify_ocr_accuracy_next_items_gate import REPORT_JSON as NEXT_ITEMS_JSON
from verify_ocr_accuracy_next_items_gate import main as verify_next_items
from verify_ocr_digit_shape_candidate_comparison import REPORT_JSON as DIGIT_SHAPE_CANDIDATE_COMPARISON_JSON
from verify_ocr_digit_shape_candidate_comparison import main as verify_digit_shape_candidate_comparison
from verify_ocr_digit_shape_generalization_matrix import REPORT_JSON as DIGIT_GENERALIZATION_JSON
from verify_ocr_digit_shape_generalization_matrix import main as verify_digit_generalization
from verify_ocr_high_priority_mismatch_crop_quality import main as verify_high_priority_mismatch_crop_quality
from verify_ocr_person03_second_pass_live_handoff import REPORT_JSON as PERSON03_LIVE_HANDOFF_JSON
from verify_ocr_person03_second_pass_live_handoff import main as verify_person03_live_handoff
from verify_ocr_person_second_pass_request_manifests import REPORT_JSON as PERSON_SECOND_PASS_JSON
from verify_ocr_person_second_pass_request_manifests import main as verify_person_second_pass
from verify_ocr_priority_crop_feature_targets import REPORT_JSON as CROP_FEATURE_JSON
from verify_ocr_priority_crop_feature_targets import main as verify_crop_feature
from verify_ocr_priority_digit_shape_scores import REPORT_JSON as DIGIT_SHAPE_JSON
from verify_ocr_priority_digit_shape_scores import main as verify_digit_shape
from verify_ocr_provider_free_accuracy_gate import REPORT_JSON as BASE_GATE_JSON
from verify_ocr_provider_free_accuracy_gate import main as verify_base_gate
from verify_ocr_q003_q018_ambiguity_manifest import REPORT_JSON as AMBIGUITY_MANIFEST_JSON
from verify_ocr_q003_q018_ambiguity_manifest import main as verify_ambiguity_manifest
from verify_ocr_q003_signal_audit import REPORT_JSON as Q003_AUDIT_JSON
from verify_ocr_q003_signal_audit import main as verify_q003_audit
from verify_ocr_q015_q016_relation_operator_manifest import REPORT_JSON as RELATION_OPERATOR_MANIFEST_JSON
from verify_ocr_q015_q016_relation_operator_manifest import main as verify_relation_operator_manifest
from verify_ocr_route_visible_digit_geometry_guard import REPORT_JSON as ROUTE_GEOMETRY_JSON
from verify_ocr_route_visible_digit_geometry_guard import main as verify_route_geometry
from verify_ocr_second_pass_batch_request_manifest import REPORT_JSON as SECOND_PASS_BATCH_REQUEST_JSON
from verify_ocr_second_pass_batch_request_manifest import main as verify_second_pass_batch_request
from verify_ocr_second_pass_internal_candidate_links import REPORT_JSON as SECOND_PASS_INTERNAL_CANDIDATE_JSON
from verify_ocr_second_pass_internal_candidate_links import main as verify_second_pass_internal_candidate
from verify_ocr_second_pass_manifest_from_review_payload import REPORT_JSON as SECOND_PASS_MANIFEST_JSON
from verify_ocr_second_pass_manifest_from_review_payload import main as verify_second_pass_manifest
from verify_ocr_visible_digit_candidate_targets import REPORT_JSON as VISIBLE_DIGIT_JSON
from verify_ocr_visible_digit_candidate_targets import main as verify_visible_digit
from verify_ocr_visible_digit_second_pass_batch import REPORT_JSON as VISIBLE_SECOND_PASS_JSON
from verify_ocr_visible_digit_second_pass_batch import main as verify_visible_second_pass
from verify_ocr_visible_digit_second_pass_eligibility import REPORT_JSON as VISIBLE_ELIGIBILITY_JSON
from verify_ocr_visible_digit_second_pass_eligibility import main as verify_visible_eligibility

Verifier: TypeAlias = Callable[[], int]


def verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (
        ("base provider-free accuracy gate", verify_base_gate),
        ("priority crop feature targets", verify_crop_feature),
        ("priority digit shape scores", verify_digit_shape),
        ("digit shape generalization matrix", verify_digit_generalization),
        ("digit shape candidate comparison", verify_digit_shape_candidate_comparison),
        ("q003 signal audit", verify_q003_audit),
        ("q003/q018 ambiguity manifest", verify_ambiguity_manifest),
        ("q015/q016 relation operator manifest", verify_relation_operator_manifest),
        ("high-priority mismatch crop quality", verify_high_priority_mismatch_crop_quality),
        ("visible digit candidate targets", verify_visible_digit),
        ("visible digit second-pass batch", verify_visible_second_pass),
        ("visible digit second-pass eligibility", verify_visible_eligibility),
        ("route visible digit geometry guard", verify_route_geometry),
        ("second-pass manifest from review payload", verify_second_pass_manifest),
        ("second-pass batch request manifest", verify_second_pass_batch_request),
        ("person second-pass request manifests", verify_person_second_pass),
        ("second-pass internal candidate links", verify_second_pass_internal_candidate),
        ("person03 second-pass live handoff", verify_person03_live_handoff),
        *training_pack_verifiers(),
        ("accuracy next-items gate", verify_next_items),
    )


def reports_by_key() -> dict[str, JsonObject]:
    return {
        "base": read_json_object(BASE_GATE_JSON),
        "crop_feature": read_json_object(CROP_FEATURE_JSON),
        "digit_shape": read_json_object(DIGIT_SHAPE_JSON),
        "digit_generalization": read_json_object(DIGIT_GENERALIZATION_JSON),
        "digit_shape_candidate_comparison": read_json_object(DIGIT_SHAPE_CANDIDATE_COMPARISON_JSON),
        "q003_audit": read_json_object(Q003_AUDIT_JSON),
        "ambiguity_manifest": read_json_object(AMBIGUITY_MANIFEST_JSON),
        "relation_operator_manifest": read_json_object(RELATION_OPERATOR_MANIFEST_JSON),
        "visible_digit": read_json_object(VISIBLE_DIGIT_JSON),
        "visible_second_pass": read_json_object(VISIBLE_SECOND_PASS_JSON),
        "visible_eligibility": read_json_object(VISIBLE_ELIGIBILITY_JSON),
        "route_geometry": read_json_object(ROUTE_GEOMETRY_JSON),
        "second_pass_manifest": read_json_object(SECOND_PASS_MANIFEST_JSON),
        "second_pass_batch_request": read_json_object(SECOND_PASS_BATCH_REQUEST_JSON),
        "person_second_pass": read_json_object(PERSON_SECOND_PASS_JSON),
        "second_pass_internal_candidate": read_json_object(SECOND_PASS_INTERNAL_CANDIDATE_JSON),
        "person03_live_handoff": read_json_object(PERSON03_LIVE_HANDOFF_JSON),
        **training_pack_reports_by_key(),
        "next_items": read_json_object(NEXT_ITEMS_JSON),
    }
