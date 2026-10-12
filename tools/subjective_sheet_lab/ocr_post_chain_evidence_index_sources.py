from __future__ import annotations

from typing import Final

from ocr_post_chain_evidence_index_common import MetricSpec, SourceSpec
from ocr_preflight_environment_matrix_model import LAB

POST_CHAIN_REFRESH_JSON: Final = LAB / "ocr_post_chain_operator_refresh.json"
POST_CHAIN_REFRESH_GUARD_JSON: Final = LAB / "ocr_post_chain_operator_refresh_guard.json"
POST_CHAIN_REFRESH_OUTPUT_SPLIT_JSON: Final = LAB / "ocr_post_chain_operator_refresh_output_split.json"
RUNBOOK_RENDERED_JSON_OUT: Final = LAB / "ocr_preflight_operator_runbook_rendered_summary.json"
RUNBOOK_RENDERED_GUARD_JSON_OUT: Final = LAB / "ocr_preflight_operator_runbook_rendered_summary_guard.json"
RUNBOOK_CONSISTENCY_JSON_OUT: Final = LAB / "ocr_preflight_operator_runbook_consistency.json"
RUNBOOK_CONSISTENCY_GUARD_JSON_OUT: Final = LAB / "ocr_preflight_operator_runbook_consistency_guard.json"
OPERATOR_SUMMARY_JSON: Final = LAB / "ocr_post_chain_operator_summary.json"
OPERATOR_SUMMARY_GUARD_JSON: Final = LAB / "ocr_post_chain_operator_summary_guard.json"
RETENTION_JSON: Final = LAB / "ocr_post_chain_handoff_retention_manifest.json"
RETENTION_GUARD_JSON: Final = LAB / "ocr_post_chain_handoff_retention_manifest_guard.json"
CHECKLIST_RENDERED_JSON: Final = LAB / "ocr_post_chain_handoff_command_checklist_rendered_summary.json"
CHECKLIST_RENDERED_GUARD_JSON: Final = LAB / "ocr_post_chain_handoff_command_checklist_rendered_summary_guard.json"
QA_FRESHNESS_GUARD_JSON: Final = LAB / "ocr_qa_start_here_freshness_guard.json"
QA_START_HERE_JSON: Final = LAB / "ocr_qa_start_here_verification.json"
QA_START_HERE_MD: Final = LAB / "OCR_QA_START_HERE.md"
QA_RENDERED_JSON: Final = LAB / "ocr_qa_start_here_rendered_summary.json"
QA_RENDERED_GUARD_JSON: Final = LAB / "ocr_qa_start_here_rendered_summary_guard.json"
USER_ACTION_INVENTORY_JSON: Final = LAB / "ocr_user_action_required_inventory.json"
USER_ACTION_INVENTORY_GUARD_JSON: Final = LAB / "ocr_user_action_required_inventory_guard.json"
COMMON_SELF_CHECK_JSON: Final = LAB / "ocr_post_chain_evidence_index_common_self_check.json"
FRESHNESS_GUARD_JSON: Final = LAB / "ocr_post_chain_evidence_index_freshness_guard.json"

BASE_SOURCE_SPECS: Final[tuple[SourceSpec, ...]] = (
    SourceSpec(
        "post_chain_refresh",
        POST_CHAIN_REFRESH_JSON,
        "OCR_POST_CHAIN_OPERATOR_REFRESH_VERIFIED",
        (MetricSpec("ordered_step_count", 8), MetricSpec("failed_step_count", 0)),
    ),
    SourceSpec(
        "post_chain_refresh_guard",
        POST_CHAIN_REFRESH_GUARD_JSON,
        "OCR_POST_CHAIN_OPERATOR_REFRESH_GUARD_VERIFIED",
        (MetricSpec("probe_count", 4), MetricSpec("failed_probe_count", 0)),
    ),
    SourceSpec(
        "post_chain_refresh_output_split",
        POST_CHAIN_REFRESH_OUTPUT_SPLIT_JSON,
        "OCR_POST_CHAIN_OPERATOR_REFRESH_OUTPUT_SPLIT_VERIFIED",
        (
            MetricSpec("file_contract_count", 3),
            MetricSpec("failed_file_contract_count", 0),
            MetricSpec("refresh_step_count", 8),
            MetricSpec("refresh_failed_step_count", 0),
        ),
        fresh_after_paths=(POST_CHAIN_REFRESH_JSON,),
    ),
    SourceSpec(
        "runbook_rendered_summary",
        RUNBOOK_RENDERED_JSON_OUT,
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_RENDERED_SUMMARY_VERIFIED",
        (MetricSpec("required_snippet_count", None), MetricSpec("missing_snippet_count", 0)),
    ),
    SourceSpec(
        "runbook_consistency",
        RUNBOOK_CONSISTENCY_JSON_OUT,
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENT",
        (MetricSpec("required_report_path_count", None), MetricSpec("missing_snippet_count", 0)),
    ),
    SourceSpec(
        "post_chain_operator_summary",
        OPERATOR_SUMMARY_JSON,
        "OCR_POST_CHAIN_OPERATOR_SUMMARY_VERIFIED",
        (
            MetricSpec("ordered_command_count", 7),
            MetricSpec("report_count", 6),
            MetricSpec("stale_report_count", 0),
        ),
        (
            "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_VERIFIED",
            "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_GUARD_VERIFIED",
        ),
    ),
    SourceSpec(
        "post_chain_operator_summary_guard",
        OPERATOR_SUMMARY_GUARD_JSON,
        "OCR_POST_CHAIN_OPERATOR_SUMMARY_GUARD_VERIFIED",
        (MetricSpec("copied_stale_report_count", 6),),
    ),
    SourceSpec(
        "post_chain_handoff_retention_manifest",
        RETENTION_JSON,
        "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_VERIFIED",
        (
            MetricSpec("artifact_count", 15),
            MetricSpec("canonical_operator_handoff_count", 4),
            MetricSpec("regenerated_helper_artifact_count", 10),
            MetricSpec("missing_artifact_count", 0),
            MetricSpec("unsafe_json_artifact_count", 0),
        ),
    ),
    SourceSpec(
        "post_chain_handoff_retention_manifest_guard",
        RETENTION_GUARD_JSON,
        "OCR_POST_CHAIN_HANDOFF_RETENTION_MANIFEST_GUARD_VERIFIED",
        (
            MetricSpec("probe_count", 9),
            MetricSpec("failed_probe_count", 0),
            MetricSpec("copied_missing_start_here_missing_count", 1),
            MetricSpec("copied_missing_queue_state_guard_missing_count", 1),
            MetricSpec("copied_missing_evidence_rendered_guard_missing_count", 1),
            MetricSpec("copied_missing_evidence_rendered_guard_summary_missing_count", 1),
            MetricSpec("copied_missing_retention_guard_summary_missing_count", 1),
            MetricSpec("copied_missing_start_card_freshness_helper_missing_count", 1),
        ),
        fresh_after_paths=(RETENTION_JSON,),
    ),
    SourceSpec(
        "post_chain_handoff_command_checklist_rendered_summary_guard",
        CHECKLIST_RENDERED_GUARD_JSON,
        "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_RENDERED_SUMMARY_GUARD_VERIFIED",
        (MetricSpec("probe_count", 6), MetricSpec("failed_probe_count", 0)),
        fresh_after_paths=(CHECKLIST_RENDERED_JSON,),
    ),
    SourceSpec(
        "qa_start_here_freshness_guard",
        QA_FRESHNESS_GUARD_JSON,
        "OCR_QA_START_HERE_FRESHNESS_GUARD_VERIFIED",
        (MetricSpec("probe_count", 8), MetricSpec("failed_probe_count", 0)),
        fresh_after_paths=(RUNBOOK_RENDERED_GUARD_JSON_OUT, RUNBOOK_CONSISTENCY_GUARD_JSON_OUT),
    ),
    SourceSpec(
        "qa_start_here_verification",
        QA_START_HERE_JSON,
        "OCR_QA_START_HERE_READY_WITH_USER_ACTION_REQUIRED",
        (MetricSpec("chain_step_count", 29), MetricSpec("failed_step_count", 0)),
        fresh_after_paths=(QA_FRESHNESS_GUARD_JSON,),
    ),
    SourceSpec(
        "qa_start_here_rendered_summary",
        QA_RENDERED_JSON,
        "OCR_QA_START_HERE_RENDERED_SUMMARY_VERIFIED",
        (MetricSpec("missing_snippet_count", 0), MetricSpec("forbidden_snippet_count", 0)),
        fresh_after_paths=(QA_START_HERE_JSON, QA_START_HERE_MD),
    ),
    SourceSpec(
        "qa_start_here_rendered_summary_guard",
        QA_RENDERED_GUARD_JSON,
        "OCR_QA_START_HERE_RENDERED_SUMMARY_GUARD_VERIFIED",
        (MetricSpec("probe_count", 12), MetricSpec("failed_probe_count", 0)),
        fresh_after_paths=(QA_RENDERED_JSON,),
    ),
    SourceSpec(
        "user_action_required_inventory",
        USER_ACTION_INVENTORY_JSON,
        "OCR_USER_ACTION_REQUIRED_INVENTORY_VERIFIED",
        (
            MetricSpec("user_required_report_count", None),
            MetricSpec("unexpected_issue_count", 0),
        ),
    ),
    SourceSpec(
        "user_action_required_inventory_guard",
        USER_ACTION_INVENTORY_GUARD_JSON,
        "OCR_USER_ACTION_REQUIRED_INVENTORY_GUARD_VERIFIED",
        (MetricSpec("probe_count", 16), MetricSpec("failed_probe_count", 0)),
        fresh_after_paths=(USER_ACTION_INVENTORY_JSON,),
    ),
)

SOURCE_SPECS: Final[tuple[SourceSpec, ...]] = (
    *BASE_SOURCE_SPECS,
    SourceSpec(
        "evidence_index_common_self_check",
        COMMON_SELF_CHECK_JSON,
        "OCR_POST_CHAIN_EVIDENCE_INDEX_COMMON_SELF_CHECK_VERIFIED",
        (
            MetricSpec("probe_count", 4),
            MetricSpec("failed_probe_count", 0),
            MetricSpec("source_report_count", len(BASE_SOURCE_SPECS)),
        ),
        fresh_after_paths=tuple(spec.path for spec in BASE_SOURCE_SPECS),
    ),
    SourceSpec(
        "evidence_index_freshness_guard",
        FRESHNESS_GUARD_JSON,
        "OCR_POST_CHAIN_EVIDENCE_INDEX_FRESHNESS_GUARD_VERIFIED",
        (
            MetricSpec("probe_count", 3),
            MetricSpec("failed_probe_count", 0),
        ),
        fresh_after_paths=(COMMON_SELF_CHECK_JSON,),
    ),
)
