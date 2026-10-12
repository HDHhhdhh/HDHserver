# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by ocr_provider_free_extended_gate_training_pack.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ocr_provider_free_extended_gate_common import JsonObject


@dataclass(frozen=True, slots=True)
class TrainingPackReports:
    crop_readiness: JsonObject
    source_inventory: JsonObject
    replay_skeleton: JsonObject
    ui_replay_bridge: JsonObject
    accuracy_claim_guard: JsonObject
    recognized_evidence_intake: JsonObject
    recognized_evidence_contract: JsonObject
    recognized_evidence_target_coverage: JsonObject
    recognized_evidence_target_diff: JsonObject
    recognized_evidence_operator_checklist: JsonObject
    recognized_evidence_filename_diagnostics: JsonObject
    recognized_evidence_intake_replay: JsonObject
    blank_evidence_rejection: JsonObject
    recognized_evidence_example_shape: JsonObject
    evidence_promotion_gate: JsonObject
    replacement_readiness: JsonObject
    replacement_sandbox: JsonObject
    crop_spec: JsonObject


def training_pack_reports(reports: Mapping[str, JsonObject]) -> TrainingPackReports:
    return TrainingPackReports(
        crop_readiness=reports["training_pack_crop_readiness"],
        source_inventory=reports["training_pack_source_inventory"],
        replay_skeleton=reports["training_pack_replay_skeleton"],
        ui_replay_bridge=reports["training_pack_ui_replay_bridge"],
        accuracy_claim_guard=reports["training_pack_accuracy_claim_guard"],
        recognized_evidence_intake=reports["training_pack_recognized_evidence_intake"],
        recognized_evidence_contract=reports["training_pack_recognized_evidence_contract"],
        recognized_evidence_target_coverage=reports["training_pack_recognized_evidence_target_coverage"],
        recognized_evidence_target_diff=reports["training_pack_recognized_evidence_target_diff"],
        recognized_evidence_operator_checklist=reports["training_pack_recognized_evidence_operator_checklist"],
        recognized_evidence_filename_diagnostics=reports["training_pack_recognized_evidence_filename_diagnostics"],
        recognized_evidence_intake_replay=reports["training_pack_recognized_evidence_intake_replay"],
        blank_evidence_rejection=reports["training_pack_blank_evidence_rejection"],
        recognized_evidence_example_shape=reports["training_pack_recognized_evidence_example_shape"],
        evidence_promotion_gate=reports["training_pack_evidence_promotion"],
        replacement_readiness=reports["training_pack_replacement_readiness"],
        replacement_sandbox=reports["training_pack_replacement_sandbox"],
        crop_spec=reports["training_pack_crop_spec"],
    )
