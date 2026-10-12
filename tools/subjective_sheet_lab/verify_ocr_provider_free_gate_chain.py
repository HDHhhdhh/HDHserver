# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_provider_free_gate_chain.py

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeAlias

from ocr_preflight_environment_matrix_model import LAB, REPORT_JSON as MATRIX_JSON
from ocr_provider_free_gate_chain_model import ChainSourceReports, ChainStep, build_report
from ocr_provider_free_gate_chain_output import markdown
from ocr_report_field_access import read_report
from ocr_preflight_report_freshness_model import REPORT_FRESHNESS_JSON
from verify_ocr_extended_gate_count_consistency import REPORT_JSON_OUT as COUNT_JSON
from verify_ocr_extended_gate_count_consistency import main as verify_count_consistency
from verify_ocr_extended_gate_count_consistency_guard import REPORT_JSON_OUT as COUNT_GUARD_JSON
from verify_ocr_extended_gate_count_consistency_guard import main as verify_count_consistency_guard
from verify_ocr_count_consistency_path_rendered_guard import REPORT_JSON_OUT as COUNT_PATH_GUARD_JSON
from verify_ocr_count_consistency_path_rendered_guard import main as verify_count_path_guard
from verify_ocr_next_action_queue_state import REPORT_JSON_OUT as QUEUE_STATE_JSON
from verify_ocr_next_action_queue_state import main as verify_queue_state
from verify_ocr_operator_next_action_summary import REPORT_JSON as OPERATOR_SUMMARY_JSON
from verify_ocr_operator_next_action_summary import main as verify_operator_summary
from verify_ocr_user_action_required_inventory import REPORT_JSON as USER_ACTION_INVENTORY_JSON
from verify_ocr_user_action_required_inventory import main as verify_user_action_inventory
from verify_ocr_user_action_required_inventory_guard import REPORT_JSON as USER_ACTION_INVENTORY_GUARD_JSON
from verify_ocr_user_action_required_inventory_guard import main as verify_user_action_inventory_guard
from verify_ocr_training_pack_evidence_missing_blocker_snapshot import REPORT_JSON as MISSING_BLOCKER_JSON
from verify_ocr_training_pack_evidence_missing_blocker_snapshot import main as verify_missing_blocker
from verify_ocr_training_pack_evidence_missing_blocker_snapshot_guard import (
    REPORT_JSON as MISSING_BLOCKER_GUARD_JSON,
)
from verify_ocr_training_pack_evidence_missing_blocker_snapshot_guard import (
    main as verify_missing_blocker_guard,
)
from verify_ocr_training_pack_evidence_prearrival_contract_gate import (
    REPORT_JSON as PREARRIVAL_CONTRACT_JSON,
)
from verify_ocr_training_pack_evidence_prearrival_contract_gate import (
    main as verify_prearrival_contract,
)
from verify_ocr_training_pack_recognized_evidence_filename_diagnostics import (
    REPORT_JSON as FILENAME_DIAGNOSTICS_JSON,
)
from verify_ocr_training_pack_recognized_evidence_filename_diagnostics import (
    main as verify_filename_diagnostics,
)
from verify_ocr_training_pack_partial_evidence_arrival_guard import (
    REPORT_JSON as PARTIAL_EVIDENCE_GUARD_JSON,
)
from verify_ocr_training_pack_partial_evidence_arrival_guard import (
    main as verify_partial_evidence_guard,
)
from verify_ocr_provider_free_chain_manifest_consistency import REPORT_JSON_OUT as CHAIN_MANIFEST_JSON
from verify_ocr_provider_free_chain_manifest_consistency import main as verify_chain_manifest
from verify_ocr_provider_free_chain_manifest_consistency_guard import REPORT_JSON_OUT as CHAIN_MANIFEST_GUARD_JSON
from verify_ocr_provider_free_chain_manifest_consistency_guard import main as verify_chain_manifest_guard
from verify_ocr_preflight_operator_runbook_consistency import REPORT_JSON_OUT as RUNBOOK_CONSISTENCY_JSON
from verify_ocr_preflight_operator_runbook_consistency import main as verify_runbook_consistency
from verify_ocr_preflight_operator_runbook_consistency_guard import REPORT_JSON_OUT as RUNBOOK_CONSISTENCY_GUARD_JSON
from verify_ocr_preflight_operator_runbook_consistency_guard import main as verify_runbook_consistency_guard
from verify_ocr_preflight_operator_runbook_rendered_summary import REPORT_JSON_OUT as RUNBOOK_RENDERED_JSON
from verify_ocr_preflight_operator_runbook_rendered_summary import main as verify_runbook_rendered_summary
from verify_ocr_preflight_operator_runbook_rendered_summary_guard import REPORT_JSON_OUT as RUNBOOK_RENDERED_GUARD_JSON
from verify_ocr_preflight_operator_runbook_rendered_summary_guard import main as verify_runbook_rendered_summary_guard
from verify_ocr_preflight_environment_matrix import main as verify_matrix
from verify_ocr_preflight_failure_classifier import REPORT_CLASSIFIER_JSON
from verify_ocr_preflight_failure_classifier import main as verify_classifier
from verify_ocr_preflight_report_freshness import main as verify_freshness
from verify_ocr_provider_free_accuracy_gate_preflight_readiness_guard import (
    REPORT_JSON as PREFLIGHT_READINESS_GUARD_JSON,
)
from verify_ocr_provider_free_accuracy_gate_preflight_readiness_guard import (
    main as verify_preflight_readiness_guard,
)
from verify_ocr_qa_start_here_freshness_guard import REPORT_JSON_OUT as START_HERE_GUARD_JSON
from verify_ocr_qa_start_here_freshness_guard import main as verify_start_here_freshness_guard
from verify_ocr_qa_start_here_rendered_summary import REPORT_JSON_OUT as START_HERE_RENDERED_JSON
from verify_ocr_qa_start_here_rendered_summary import main as verify_start_here_rendered_summary
from verify_ocr_qa_start_here_rendered_summary_guard import REPORT_JSON_OUT as START_HERE_RENDERED_GUARD_JSON
from verify_ocr_qa_start_here_rendered_summary_guard import main as verify_start_here_rendered_summary_guard
from verify_ocr_qa_start_here import REPORT_JSON_OUT as START_HERE_JSON
from verify_ocr_qa_start_here import main as verify_start_here
from verify_ocr_training_pack_intake_only_command_checklist import REPORT_JSON as COMMAND_CHECKLIST_JSON
from verify_ocr_training_pack_intake_only_command_checklist import main as verify_intake_command_checklist
from verify_ocr_training_pack_intake_only_command_checklist_guard import REPORT_JSON as COMMAND_CHECKLIST_GUARD_JSON
from verify_ocr_training_pack_intake_only_command_checklist_guard import main as verify_intake_command_checklist_guard
from verify_ocr_training_pack_standard_field_coverage import REPORT_JSON as STANDARD_FIELD_COVERAGE_JSON
from verify_ocr_training_pack_standard_field_coverage import main as verify_standard_field_coverage

Verifier: TypeAlias = Callable[[], int]
REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_gate_chain.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_gate_chain.md"


CHAIN_STEPS: Final[tuple[tuple[str, Verifier, Path], ...]] = (
    ("environment_matrix", verify_matrix, MATRIX_JSON),
    ("failure_classifier", verify_classifier, REPORT_CLASSIFIER_JSON),
    ("report_freshness", verify_freshness, REPORT_FRESHNESS_JSON),
    ("preflight_readiness_guard", verify_preflight_readiness_guard, PREFLIGHT_READINESS_GUARD_JSON),
    ("queue_state", verify_queue_state, QUEUE_STATE_JSON),
    ("operator_summary", verify_operator_summary, OPERATOR_SUMMARY_JSON),
    ("training_pack_missing_blocker_snapshot", verify_missing_blocker, MISSING_BLOCKER_JSON),
    ("training_pack_missing_blocker_snapshot_guard", verify_missing_blocker_guard, MISSING_BLOCKER_GUARD_JSON),
    ("training_pack_prearrival_contract", verify_prearrival_contract, PREARRIVAL_CONTRACT_JSON),
    ("training_pack_filename_diagnostics", verify_filename_diagnostics, FILENAME_DIAGNOSTICS_JSON),
    ("training_pack_partial_evidence_arrival_guard", verify_partial_evidence_guard, PARTIAL_EVIDENCE_GUARD_JSON),
    ("count_consistency", verify_count_consistency, COUNT_JSON),
    ("count_consistency_guard", verify_count_consistency_guard, COUNT_GUARD_JSON),
    ("intake_command_checklist", verify_intake_command_checklist, COMMAND_CHECKLIST_JSON),
    ("intake_command_checklist_guard", verify_intake_command_checklist_guard, COMMAND_CHECKLIST_GUARD_JSON),
    ("training_pack_standard_field_coverage", verify_standard_field_coverage, STANDARD_FIELD_COVERAGE_JSON),
    ("chain_manifest_consistency", verify_chain_manifest, CHAIN_MANIFEST_JSON),
    ("chain_manifest_consistency_guard", verify_chain_manifest_guard, CHAIN_MANIFEST_GUARD_JSON),
    ("qa_start_here_freshness_guard", verify_start_here_freshness_guard, START_HERE_GUARD_JSON),
    ("qa_start_here", verify_start_here, START_HERE_JSON),
    ("qa_start_here_rendered_summary", verify_start_here_rendered_summary, START_HERE_RENDERED_JSON),
    ("qa_start_here_rendered_summary_guard", verify_start_here_rendered_summary_guard, START_HERE_RENDERED_GUARD_JSON),
    ("operator_runbook_rendered_summary", verify_runbook_rendered_summary, RUNBOOK_RENDERED_JSON),
    ("count_consistency_path_rendered_guard", verify_count_path_guard, COUNT_PATH_GUARD_JSON),
    ("operator_runbook_rendered_summary_guard", verify_runbook_rendered_summary_guard, RUNBOOK_RENDERED_GUARD_JSON),
    ("operator_runbook_consistency", verify_runbook_consistency, RUNBOOK_CONSISTENCY_JSON),
    ("operator_runbook_consistency_guard", verify_runbook_consistency_guard, RUNBOOK_CONSISTENCY_GUARD_JSON),
    ("user_action_required_inventory", verify_user_action_inventory, USER_ACTION_INVENTORY_JSON),
    ("user_action_required_inventory_guard", verify_user_action_inventory_guard, USER_ACTION_INVENTORY_GUARD_JSON),
)


def main() -> int:
    steps = run_steps()
    report = build_report(steps, source_reports())
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def run_steps() -> list[ChainStep]:
    steps: list[ChainStep] = []
    for name, verifier, report_path in CHAIN_STEPS:
        exit_code = verifier()
        steps.append({
            "name": name,
            "report_path": relative_path(report_path),
            "exit_code": exit_code,
            "ok": exit_code == 0,
        })
        if exit_code != 0:
            break
    return steps


def source_reports() -> ChainSourceReports:
    return ChainSourceReports(
        matrix=read_report(MATRIX_JSON),
        classifier=read_report(REPORT_CLASSIFIER_JSON),
        freshness=read_report(REPORT_FRESHNESS_JSON),
        count=read_report(COUNT_JSON),
    )


def relative_path(path: Path) -> str:
    return str(path.relative_to(LAB.parents[1]))


if __name__ == "__main__":
    raise SystemExit(main())
