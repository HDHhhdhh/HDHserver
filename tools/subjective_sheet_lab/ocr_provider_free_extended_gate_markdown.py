from __future__ import annotations

from ocr_provider_free_extended_gate_common import JsonObject
from ocr_provider_free_extended_gate_markdown_core import core_markdown_lines
from ocr_provider_free_extended_gate_markdown_training_pack import training_pack_markdown_lines


def markdown(output: JsonObject) -> str:
    lines = (
        *core_markdown_lines(output),
        f"- extended gate count source: {output['extended_gate_count_source']}",
        f"- count consistency verifier: {output['count_consistency_verifier']}",
        f"- queue-state verified: {output['queue_state_verified']}",
        f"- queue-state expected extended gate count: {output['queue_state_expected_extended_gate_count']}",
        f"- queue-state required snippets: {output['queue_state_required_snippet_count']}",
        f"- queue-state missing snippets: {output['queue_state_missing_snippet_count']}",
        f"- queue-state latest required snippets: {output['queue_state_latest_required_snippet_count']}",
        f"- queue-state latest missing snippets: {output['queue_state_latest_missing_snippet_count']}",
        f"- queue-state latest heading at tail: {output['queue_state_latest_heading_at_tail']}",
        f"- queue-state classifier status: {output['queue_state_classifier_status']}",
        f"- queue-state freshness status: {output['queue_state_freshness_status']}",
        f"- queue-state guard verified: {output['queue_state_guard_verified']}",
        f"- queue-state guard probe count: {output['queue_state_guard_probe_count']}",
        "- queue-state guard missing latest required snippet blocked: "
        f"{output['queue_state_guard_missing_latest_required_snippet_blocked']}",
        f"- user-action inventory status: {output['user_action_inventory_status']}",
        f"- user-action inventory report count: {output['user_action_inventory_report_count']}",
        "- user-action inventory unexpected issue count: "
        f"{output['user_action_inventory_unexpected_issue_count']}",
        f"- user-action inventory guard status: {output['user_action_inventory_guard_status']}",
        f"- user-action inventory guard probe count: {output['user_action_inventory_guard_probe_count']}",
        "- user-action inventory guard volatile aggregate failure ignored: "
        f"{output['user_action_inventory_guard_volatile_aggregate_failure_ignored']}",
        "- user-action inventory guard unexpected status blocked: "
        f"{output['user_action_inventory_guard_unexpected_status_blocked']}",
        f"- report field-access inventory status: {output['report_field_access_inventory_status']}",
        f"- report field-access helper definitions: {output['report_field_access_helper_definition_count']}",
        f"- report field-access default reader candidates: {output['report_field_access_default_reader_candidate_count']}",
        f"- report field-access strict local contracts: {output['report_field_access_strict_local_contract_count']}",
        f"- report field-access inventory guard status: {output['report_field_access_inventory_guard_status']}",
        f"- report field-access inventory guard probe count: {output['report_field_access_inventory_guard_probe_count']}",
        "- report field-access default reader candidate probe blocked: "
        f"{output['report_field_access_default_reader_candidate_probe_blocked']}",
        f"- training-pack missing blocker guard status: {output['training_pack_evidence_missing_blocker_guard_status']}",
        f"- training-pack missing blocker guard probe count: {output['training_pack_evidence_missing_blocker_guard_probe_count']}",
        "- training-pack missing blocker guard ready-now mutation blocked: "
        f"{output['training_pack_evidence_missing_blocker_guard_ready_now_true_blocked']}",
        "- training-pack missing blocker guard authorization mutation blocked: "
        f"{output['training_pack_evidence_missing_blocker_guard_weakened_authorization_blocked']}",
        *training_pack_markdown_lines(output),
        "- answer-key/grading/path leak count: 0",
    )
    return "\n".join(lines) + "\n"
