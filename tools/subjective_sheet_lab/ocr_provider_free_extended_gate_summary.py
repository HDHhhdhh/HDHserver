from __future__ import annotations

from typing import Mapping

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    assert_common_safety,
    read_json_object,
)
from ocr_provider_free_extended_gate_count import EXTENDED_GATE_COUNT, EXTENDED_GATE_COUNT_SOURCE
from ocr_provider_free_extended_gate_arrival_smoke import (
    arrival_smoke_summary_fields,
    require_training_pack_evidence_arrival_smoke,
)
from ocr_provider_free_extended_gate_arrival_digest import (
    arrival_digest_summary_fields,
    require_training_pack_arrival_smoke_operator_digest,
)
from ocr_provider_free_extended_gate_arrival_transitions import (
    arrival_transition_summary_fields,
    require_training_pack_arrival_status_transitions,
)
from ocr_provider_free_extended_gate_core import core_summary_fields, require_core_reports
from ocr_provider_free_extended_gate_intake_commands import (
    intake_command_checklist_summary_fields,
    require_training_pack_intake_only_command_checklist,
)
from ocr_provider_free_extended_gate_intake_command_guard import (
    intake_command_guard_summary_fields,
    require_training_pack_intake_only_command_checklist_guard,
)
from ocr_provider_free_extended_gate_markdown import markdown
from ocr_provider_free_extended_gate_missing_blocker import (
    missing_blocker_summary_fields,
    require_training_pack_evidence_missing_blocker,
    require_training_pack_evidence_missing_blocker_guard,
)
from ocr_provider_free_extended_gate_operator_action import (
    intake_only_no_promotion_summary_fields,
    operator_next_action_summary_fields,
    require_operator_next_action_summary,
    require_training_pack_intake_only_no_promotion,
)
from ocr_provider_free_extended_gate_post_arrival_matrix import (
    post_arrival_matrix_summary_fields,
    require_training_pack_post_arrival_readiness_matrix,
)
from ocr_provider_free_extended_gate_post_arrival_acceptance import (
    post_arrival_acceptance_summary_fields,
    require_training_pack_post_arrival_acceptance_summary,
)
from ocr_provider_free_extended_gate_post_arrival_runbook import (
    post_arrival_runbook_summary_fields,
    require_training_pack_post_arrival_operator_runbook,
)
from ocr_provider_free_extended_gate_post_arrival_bundle import (
    post_arrival_bundle_summary_fields,
    require_training_pack_post_arrival_command_bundle,
)
from ocr_provider_free_extended_gate_post_arrival import (
    post_arrival_summary_fields,
    require_training_pack_post_arrival_sequence,
)
from ocr_provider_free_extended_gate_queue_state import (
    queue_state_summary_fields,
    require_ocr_next_action_queue_state,
    require_ocr_next_action_queue_state_guard,
)
from ocr_provider_free_extended_gate_report_field_access import (
    report_field_access_summary_fields,
    require_report_field_access_inventory,
    require_report_field_access_inventory_guard,
)
from ocr_provider_free_extended_gate_user_action_inventory import (
    require_user_action_required_inventory_guard,
    require_user_action_required_inventory,
    user_action_inventory_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack import (
    require_training_pack_reports,
    training_pack_reports,
    training_pack_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_post_dropbox import (
    require_training_pack_post_dropbox_replay,
    training_pack_post_dropbox_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_arrival import (
    require_training_pack_arrival_readiness,
    training_pack_arrival_readiness_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_acceptance import (
    require_training_pack_acceptance_bundle,
    training_pack_acceptance_bundle_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_post_dropbox_real_file import (
    require_training_pack_post_dropbox_real_file_replay,
    training_pack_post_dropbox_real_file_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_operator_manifest import (
    require_training_pack_operator_evidence_manifest,
    training_pack_operator_evidence_manifest_summary_fields,
)
from ocr_provider_free_extended_gate_training_pack_flow import (
    require_training_pack_flow_reports,
    training_pack_flow_summary_fields,
)


def summary(reports: Mapping[str, JsonObject]) -> JsonObject:
    for label, payload in reports.items():
        assert_common_safety(label, payload)
    require_core_reports(reports)
    require_training_pack_flow_reports(reports)
    require_training_pack_post_dropbox_replay(reports["training_pack_post_dropbox"])
    require_training_pack_arrival_readiness(reports["training_pack_arrival_readiness"])
    require_training_pack_acceptance_bundle(reports["training_pack_acceptance_bundle"])
    require_training_pack_post_dropbox_real_file_replay(reports["training_pack_post_dropbox_real_file"])
    require_training_pack_operator_evidence_manifest(reports["training_pack_operator_manifest"])
    require_operator_next_action_summary(reports["operator_next_action"])
    require_training_pack_intake_only_no_promotion(reports["training_pack_intake_only_no_promotion"])
    require_training_pack_evidence_arrival_smoke(reports["training_pack_evidence_arrival_smoke"])
    require_training_pack_arrival_smoke_operator_digest(reports["training_pack_arrival_smoke_operator_digest"])
    require_training_pack_intake_only_command_checklist(reports["training_pack_intake_only_command_checklist"])
    require_training_pack_intake_only_command_checklist_guard(
        reports["training_pack_intake_only_command_checklist_guard"],
    )
    require_training_pack_post_arrival_sequence(reports["training_pack_post_arrival_dry_run_sequence"])
    require_training_pack_arrival_status_transitions(reports["training_pack_arrival_status_transitions"])
    require_training_pack_evidence_missing_blocker(reports["training_pack_evidence_missing_blocker_snapshot"])
    require_training_pack_evidence_missing_blocker_guard(reports["training_pack_evidence_missing_blocker_guard"])
    require_training_pack_post_arrival_readiness_matrix(reports["training_pack_post_arrival_dry_run_readiness_matrix"])
    require_training_pack_post_arrival_acceptance_summary(reports["training_pack_post_arrival_acceptance_summary"])
    require_training_pack_post_arrival_operator_runbook(reports["training_pack_post_arrival_operator_runbook"])
    require_training_pack_post_arrival_command_bundle(reports["training_pack_post_arrival_command_bundle"])
    require_ocr_next_action_queue_state(reports["ocr_next_action_queue_state"])
    require_ocr_next_action_queue_state_guard(reports["ocr_next_action_queue_state_guard"])
    require_user_action_required_inventory(reports["user_action_required_inventory"])
    require_user_action_required_inventory_guard(reports["user_action_required_inventory_guard"])
    require_report_field_access_inventory(reports["report_field_access_inventory"])
    require_report_field_access_inventory_guard(reports["report_field_access_inventory_guard"])
    training_pack = training_pack_reports(reports)
    require_training_pack_reports(training_pack)
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        **core_summary_fields(),
        "extended_gate_count": EXTENDED_GATE_COUNT,
        "extended_gate_count_source": EXTENDED_GATE_COUNT_SOURCE,
        "count_consistency_verifier": "verify_ocr_extended_gate_count_consistency.py",
        **training_pack_flow_summary_fields(),
        **training_pack_post_dropbox_summary_fields(),
        **training_pack_arrival_readiness_summary_fields(),
        **training_pack_acceptance_bundle_summary_fields(),
        **training_pack_post_dropbox_real_file_summary_fields(),
        **training_pack_operator_evidence_manifest_summary_fields(),
        **operator_next_action_summary_fields(),
        **intake_only_no_promotion_summary_fields(),
        **arrival_smoke_summary_fields(reports["training_pack_evidence_arrival_smoke"]),
        **arrival_digest_summary_fields(),
        **intake_command_checklist_summary_fields(),
        **intake_command_guard_summary_fields(),
        **post_arrival_summary_fields(),
        **arrival_transition_summary_fields(),
        **missing_blocker_summary_fields(),
        **post_arrival_matrix_summary_fields(),
        **post_arrival_acceptance_summary_fields(),
        **post_arrival_runbook_summary_fields(),
        **post_arrival_bundle_summary_fields(),
        **queue_state_summary_fields(),
        **user_action_inventory_summary_fields(),
        **report_field_access_summary_fields(),
        **training_pack_summary_fields(training_pack),
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
