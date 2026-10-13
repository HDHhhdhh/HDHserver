from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import JsonObject, read_json_object
from verify_ocr_training_pack_accuracy_claim_guard import REPORT_JSON as TRAINING_PACK_ACCURACY_CLAIM_GUARD_JSON
from verify_ocr_training_pack_accuracy_claim_guard import main as verify_training_pack_accuracy_claim_guard
from verify_ocr_training_pack_blank_evidence_rejection import REPORT_JSON as TRAINING_PACK_BLANK_EVIDENCE_REJECTION_JSON
from verify_ocr_training_pack_blank_evidence_rejection import main as verify_training_pack_blank_evidence_rejection
from verify_ocr_training_pack_crop_fixture_readiness import REPORT_JSON as TRAINING_PACK_CROP_READINESS_JSON
from verify_ocr_training_pack_crop_fixture_readiness import main as verify_training_pack_crop_readiness
from verify_ocr_training_pack_crop_fixture_spec import REPORT_JSON as TRAINING_PACK_CROP_SPEC_JSON
from verify_ocr_training_pack_crop_fixture_spec import main as verify_training_pack_crop_spec
from verify_ocr_training_pack_dropbox_ready_simulation import REPORT_JSON as TRAINING_PACK_DROPBOX_READY_SIMULATION_JSON
from verify_ocr_training_pack_dropbox_ready_simulation import main as verify_training_pack_dropbox_ready_simulation
from verify_ocr_training_pack_evidence_acceptance_bundle_gate import REPORT_JSON as TRAINING_PACK_ACCEPTANCE_BUNDLE_JSON
from verify_ocr_training_pack_evidence_acceptance_bundle_gate import main as verify_training_pack_acceptance_bundle
from verify_ocr_training_pack_evidence_arrival_readiness_gate import REPORT_JSON as TRAINING_PACK_ARRIVAL_READINESS_JSON
from verify_ocr_training_pack_evidence_arrival_readiness_gate import main as verify_training_pack_arrival_readiness
from verify_ocr_training_pack_evidence_dropbox_spec import REPORT_JSON as TRAINING_PACK_EVIDENCE_DROPBOX_JSON
from verify_ocr_training_pack_evidence_dropbox_spec import main as verify_training_pack_evidence_dropbox
from verify_ocr_training_pack_evidence_promotion_gate import REPORT_JSON as TRAINING_PACK_EVIDENCE_PROMOTION_JSON
from verify_ocr_training_pack_evidence_promotion_gate import main as verify_training_pack_evidence_promotion
from verify_ocr_training_pack_operator_copy_checklist import REPORT_JSON as TRAINING_PACK_OPERATOR_COPY_CHECKLIST_JSON
from verify_ocr_training_pack_operator_copy_checklist import main as verify_training_pack_operator_copy_checklist
from verify_ocr_training_pack_operator_evidence_manifest_gate import REPORT_JSON as TRAINING_PACK_OPERATOR_MANIFEST_JSON
from verify_ocr_training_pack_operator_evidence_manifest_gate import main as verify_training_pack_operator_manifest
from verify_ocr_training_pack_operator_handoff import REPORT_JSON as TRAINING_PACK_OPERATOR_HANDOFF_JSON
from verify_ocr_training_pack_operator_handoff import main as verify_training_pack_operator_handoff
from verify_ocr_training_pack_post_dropbox_acceptance_gate import REPORT_JSON as TRAINING_PACK_POST_DROPBOX_ACCEPTANCE_JSON
from verify_ocr_training_pack_post_dropbox_acceptance_gate import main as verify_training_pack_post_dropbox_acceptance
from verify_ocr_training_pack_post_dropbox_intake_replay import REPORT_JSON as TRAINING_PACK_POST_DROPBOX_JSON
from verify_ocr_training_pack_post_dropbox_intake_replay import main as verify_training_pack_post_dropbox
from verify_ocr_training_pack_post_dropbox_real_file_replay_gate import REPORT_JSON as TRAINING_PACK_POST_DROPBOX_REAL_FILE_JSON
from verify_ocr_training_pack_post_dropbox_real_file_replay_gate import main as verify_training_pack_post_dropbox_real_file
from verify_ocr_training_pack_promotion_preview_diff_gate import REPORT_JSON as TRAINING_PACK_PROMOTION_PREVIEW_DIFF_JSON
from verify_ocr_training_pack_promotion_preview_diff_gate import main as verify_training_pack_promotion_preview_diff
from verify_ocr_training_pack_promotion_preview_gate import REPORT_JSON as TRAINING_PACK_PROMOTION_PREVIEW_JSON
from verify_ocr_training_pack_promotion_preview_gate import main as verify_training_pack_promotion_preview
from verify_ocr_training_pack_recognized_cache_replacement_readiness import REPORT_JSON as TRAINING_PACK_REPLACEMENT_READINESS_JSON
from verify_ocr_training_pack_recognized_cache_replacement_readiness import main as verify_training_pack_replacement_readiness
from verify_ocr_training_pack_recognized_evidence_contract import REPORT_JSON as TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_JSON
from verify_ocr_training_pack_recognized_evidence_contract import main as verify_training_pack_recognized_evidence_contract
from verify_ocr_training_pack_recognized_evidence_example_shape import REPORT_JSON as TRAINING_PACK_RECOGNIZED_EVIDENCE_EXAMPLE_SHAPE_JSON
from verify_ocr_training_pack_recognized_evidence_example_shape import main as verify_training_pack_recognized_evidence_example_shape
from verify_ocr_training_pack_recognized_evidence_filename_diagnostics import REPORT_JSON as TRAINING_PACK_RECOGNIZED_EVIDENCE_FILENAME_DIAGNOSTICS_JSON
from verify_ocr_training_pack_recognized_evidence_filename_diagnostics import main as verify_training_pack_recognized_evidence_filename_diagnostics
from verify_ocr_training_pack_recognized_evidence_intake import REPORT_JSON as TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_JSON
from verify_ocr_training_pack_recognized_evidence_intake import main as verify_training_pack_recognized_evidence_intake
from verify_ocr_training_pack_recognized_evidence_intake_replay import REPORT_JSON as TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_JSON
from verify_ocr_training_pack_recognized_evidence_intake_replay import main as verify_training_pack_recognized_evidence_intake_replay
from verify_ocr_training_pack_recognized_evidence_intake_replay_probes import REPORT_JSON as TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_PROBES_JSON
from verify_ocr_training_pack_recognized_evidence_intake_replay_probes import main as verify_training_pack_recognized_evidence_intake_replay_probes
from verify_ocr_training_pack_recognized_evidence_operator_checklist import REPORT_JSON as TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_JSON
from verify_ocr_training_pack_recognized_evidence_operator_checklist import main as verify_training_pack_recognized_evidence_operator_checklist
from verify_ocr_training_pack_recognized_evidence_target_coverage import REPORT_JSON as TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_JSON
from verify_ocr_training_pack_recognized_evidence_target_coverage import main as verify_training_pack_recognized_evidence_target_coverage
from verify_ocr_training_pack_recognized_evidence_target_diff import REPORT_JSON as TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_JSON
from verify_ocr_training_pack_recognized_evidence_target_diff import main as verify_training_pack_recognized_evidence_target_diff
from verify_ocr_training_pack_replay_cache_skeleton import REPORT_JSON as TRAINING_PACK_REPLAY_SKELETON_JSON
from verify_ocr_training_pack_replay_cache_skeleton import main as verify_training_pack_replay_skeleton
from verify_ocr_training_pack_replacement_sandbox import REPORT_JSON as TRAINING_PACK_REPLACEMENT_SANDBOX_JSON
from verify_ocr_training_pack_replacement_sandbox import main as verify_training_pack_replacement_sandbox
from verify_ocr_training_pack_source_inventory import REPORT_JSON as TRAINING_PACK_SOURCE_INVENTORY_JSON
from verify_ocr_training_pack_source_inventory import main as verify_training_pack_source_inventory
from verify_ocr_training_pack_ui_replay_bridge import REPORT_JSON as TRAINING_PACK_UI_REPLAY_BRIDGE_JSON
from verify_ocr_training_pack_ui_replay_bridge import main as verify_training_pack_ui_replay_bridge

Verifier: TypeAlias = Callable[[], int]


def training_pack_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (
        ("training pack crop fixture readiness", verify_training_pack_crop_readiness),
        ("training pack source inventory", verify_training_pack_source_inventory),
        ("training pack replay cache skeleton", verify_training_pack_replay_skeleton),
        ("training pack evidence dropbox spec", verify_training_pack_evidence_dropbox),
        ("training pack dropbox ready simulation", verify_training_pack_dropbox_ready_simulation),
        ("training pack UI replay bridge", verify_training_pack_ui_replay_bridge),
        ("training pack accuracy claim guard", verify_training_pack_accuracy_claim_guard),
        ("training pack recognized evidence intake", verify_training_pack_recognized_evidence_intake),
        ("training pack recognized evidence contract", verify_training_pack_recognized_evidence_contract),
        ("training pack recognized evidence target coverage", verify_training_pack_recognized_evidence_target_coverage),
        ("training pack recognized evidence target diff", verify_training_pack_recognized_evidence_target_diff),
        ("training pack recognized evidence operator checklist", verify_training_pack_recognized_evidence_operator_checklist),
        ("training pack recognized evidence filename diagnostics", verify_training_pack_recognized_evidence_filename_diagnostics),
        ("training pack recognized evidence intake replay", verify_training_pack_recognized_evidence_intake_replay),
        ("training pack recognized evidence intake replay probes", verify_training_pack_recognized_evidence_intake_replay_probes),
        ("training pack blank evidence rejection", verify_training_pack_blank_evidence_rejection),
        ("training pack recognized evidence example shape", verify_training_pack_recognized_evidence_example_shape),
        ("training pack evidence promotion gate", verify_training_pack_evidence_promotion),
        ("training pack operator handoff", verify_training_pack_operator_handoff),
        ("training pack operator copy checklist", verify_training_pack_operator_copy_checklist),
        ("training pack post-dropbox intake replay", verify_training_pack_post_dropbox),
        ("training pack post-dropbox acceptance gate", verify_training_pack_post_dropbox_acceptance),
        ("training pack promotion preview gate", verify_training_pack_promotion_preview),
        ("training pack promotion preview diff gate", verify_training_pack_promotion_preview_diff),
        ("training pack evidence arrival readiness gate", verify_training_pack_arrival_readiness),
        ("training pack evidence acceptance bundle gate", verify_training_pack_acceptance_bundle),
        ("training pack post-dropbox real-file replay gate", verify_training_pack_post_dropbox_real_file),
        ("training pack operator evidence manifest gate", verify_training_pack_operator_manifest),
        ("training pack recognized cache replacement readiness", verify_training_pack_replacement_readiness),
        ("training pack replacement sandbox", verify_training_pack_replacement_sandbox),
        ("training pack crop fixture spec", verify_training_pack_crop_spec),
    )


def training_pack_reports_by_key() -> dict[str, JsonObject]:
    return {
        "training_pack_crop_readiness": read_json_object(TRAINING_PACK_CROP_READINESS_JSON),
        "training_pack_source_inventory": read_json_object(TRAINING_PACK_SOURCE_INVENTORY_JSON),
        "training_pack_replay_skeleton": read_json_object(TRAINING_PACK_REPLAY_SKELETON_JSON),
        "training_pack_evidence_dropbox": read_json_object(TRAINING_PACK_EVIDENCE_DROPBOX_JSON),
        "training_pack_dropbox_ready_simulation": read_json_object(TRAINING_PACK_DROPBOX_READY_SIMULATION_JSON),
        "training_pack_ui_replay_bridge": read_json_object(TRAINING_PACK_UI_REPLAY_BRIDGE_JSON),
        "training_pack_accuracy_claim_guard": read_json_object(TRAINING_PACK_ACCURACY_CLAIM_GUARD_JSON),
        "training_pack_recognized_evidence_intake": read_json_object(TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_JSON),
        "training_pack_recognized_evidence_contract": read_json_object(TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_JSON),
        "training_pack_recognized_evidence_target_coverage": read_json_object(TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_JSON),
        "training_pack_recognized_evidence_target_diff": read_json_object(TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_JSON),
        "training_pack_recognized_evidence_operator_checklist": read_json_object(TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_JSON),
        "training_pack_recognized_evidence_filename_diagnostics": read_json_object(TRAINING_PACK_RECOGNIZED_EVIDENCE_FILENAME_DIAGNOSTICS_JSON),
        "training_pack_recognized_evidence_intake_replay": read_json_object(TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_JSON),
        "training_pack_recognized_evidence_intake_replay_probes": read_json_object(TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_PROBES_JSON),
        "training_pack_blank_evidence_rejection": read_json_object(TRAINING_PACK_BLANK_EVIDENCE_REJECTION_JSON),
        "training_pack_recognized_evidence_example_shape": read_json_object(TRAINING_PACK_RECOGNIZED_EVIDENCE_EXAMPLE_SHAPE_JSON),
        "training_pack_evidence_promotion": read_json_object(TRAINING_PACK_EVIDENCE_PROMOTION_JSON),
        "training_pack_operator_handoff": read_json_object(TRAINING_PACK_OPERATOR_HANDOFF_JSON),
        "training_pack_operator_copy_checklist": read_json_object(TRAINING_PACK_OPERATOR_COPY_CHECKLIST_JSON),
        "training_pack_post_dropbox": read_json_object(TRAINING_PACK_POST_DROPBOX_JSON),
        "training_pack_post_dropbox_acceptance": read_json_object(TRAINING_PACK_POST_DROPBOX_ACCEPTANCE_JSON),
        "training_pack_promotion_preview": read_json_object(TRAINING_PACK_PROMOTION_PREVIEW_JSON),
        "training_pack_promotion_preview_diff": read_json_object(TRAINING_PACK_PROMOTION_PREVIEW_DIFF_JSON),
        "training_pack_arrival_readiness": read_json_object(TRAINING_PACK_ARRIVAL_READINESS_JSON),
        "training_pack_acceptance_bundle": read_json_object(TRAINING_PACK_ACCEPTANCE_BUNDLE_JSON),
        "training_pack_post_dropbox_real_file": read_json_object(TRAINING_PACK_POST_DROPBOX_REAL_FILE_JSON),
        "training_pack_operator_manifest": read_json_object(TRAINING_PACK_OPERATOR_MANIFEST_JSON),
        "training_pack_replacement_readiness": read_json_object(TRAINING_PACK_REPLACEMENT_READINESS_JSON),
        "training_pack_replacement_sandbox": read_json_object(TRAINING_PACK_REPLACEMENT_SANDBOX_JSON),
        "training_pack_crop_spec": read_json_object(TRAINING_PACK_CROP_SPEC_JSON),
    }
