# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_preflight_operator_runbook_consistency.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import JsonObject, assert_common_safety, read_json_object, require_int
from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_qa_start_here import REPORT_JSON_OUT as START_HERE_JSON

RUNBOOK_PATH: Final[Path] = LAB / "ocr_preflight_env_split_operator_runbook.md"
REPORT_JSON_OUT: Final[Path] = LAB / "ocr_preflight_operator_runbook_consistency.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_preflight_operator_runbook_consistency.md"
REQUIRED_REPORT_PATHS: Final[tuple[str, ...]] = (
    "tools/subjective_sheet_lab/ocr_training_pack_standard_field_coverage.json",
    "tools/subjective_sheet_lab/ocr_training_pack_evidence_missing_blocker_snapshot.json",
    "tools/subjective_sheet_lab/ocr_training_pack_evidence_missing_blocker_snapshot_guard.json",
    "tools/subjective_sheet_lab/ocr_user_action_required_inventory.json",
    "tools/subjective_sheet_lab/ocr_user_action_required_inventory_guard.json",
    "tools/subjective_sheet_lab/ocr_provider_free_chain_manifest_consistency.json",
    "tools/subjective_sheet_lab/ocr_provider_free_chain_manifest_consistency_guard.json",
    "tools/subjective_sheet_lab/ocr_qa_start_here_freshness_guard.json",
    "tools/subjective_sheet_lab/ocr_qa_start_here_verification.json",
    "tools/subjective_sheet_lab/ocr_qa_start_here_rendered_summary.json",
    "tools/subjective_sheet_lab/ocr_qa_start_here_rendered_summary_guard.json",
    "tools/subjective_sheet_lab/ocr_next_action_queue_state_guard.json",
    "tools/subjective_sheet_lab/ocr_provider_free_gate_chain_rendered_steps.json",
    "tools/subjective_sheet_lab/ocr_provider_free_gate_chain_rendered_steps_guard.json",
    "tools/subjective_sheet_lab/ocr_extended_gate_count_consistency_guard.json",
    "tools/subjective_sheet_lab/ocr_count_consistency_path_rendered_guard.json",
    "tools/subjective_sheet_lab/ocr_post_chain_guard_manifest.json",
    "tools/subjective_sheet_lab/ocr_post_chain_guard_manifest_guard.json",
    "tools/subjective_sheet_lab/ocr_post_chain_operator_summary.json",
    "tools/subjective_sheet_lab/ocr_post_chain_operator_summary_guard.json",
    "tools/subjective_sheet_lab/ocr_post_chain_operator_refresh.json",
    "tools/subjective_sheet_lab/ocr_post_chain_operator_refresh_guard.json",
    "tools/subjective_sheet_lab/ocr_post_chain_evidence_index.json",
    "tools/subjective_sheet_lab/ocr_post_chain_evidence_index_guard.json",
    "tools/subjective_sheet_lab/ocr_post_chain_evidence_handoff_runner.json",
    "tools/subjective_sheet_lab/ocr_post_chain_evidence_handoff_runner_guard.json",
    "tools/subjective_sheet_lab/ocr_post_chain_handoff_retention_manifest.json",
    "tools/subjective_sheet_lab/ocr_post_chain_handoff_retention_manifest_guard.json",
    "tools/subjective_sheet_lab/ocr_post_chain_cleanup_candidate_manifest.json",
    "tools/subjective_sheet_lab/ocr_post_chain_cleanup_candidate_manifest_guard.json",
    "tools/subjective_sheet_lab/ocr_preflight_operator_runbook_rendered_summary.json",
    "tools/subjective_sheet_lab/ocr_preflight_operator_runbook_rendered_summary_guard.json",
    "tools/subjective_sheet_lab/ocr_preflight_operator_runbook_consistency.json",
    "tools/subjective_sheet_lab/ocr_preflight_operator_runbook_consistency_guard.json",
    "tools/subjective_sheet_lab/ocr_provider_free_final_handoff_chain.json",
    "tools/subjective_sheet_lab/ocr_provider_free_final_handoff_chain_guard.json",
    "tools/subjective_sheet_lab/ocr_provider_free_handoff_status_card.json",
    "tools/subjective_sheet_lab/ocr_provider_free_handoff_status_card_guard.json",
    "tools/subjective_sheet_lab/ocr_provider_free_handoff_guard_common_self_check.json",
    "tools/subjective_sheet_lab/ocr_provider_free_manual_qa_handoff_refresh.json",
    "tools/subjective_sheet_lab/ocr_provider_free_manual_qa_handoff_refresh_guard.json",
)
REQUIRED_ZERO_COUNT_SNIPPETS: Final[tuple[str, ...]] = (
    "`provider_call_count`: `0`",
    "`external_ocr_api_call_count`: `0`",
    "`submit_test_call_count`: `0`",
    "`ts_submit_click_count`: `0`",
    "`answer_key_or_grading_field_leak_count`: `0`",
    "`filesystem_path_leak_count`: `0`",
)


class RunbookConsistencyReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    runbook_path: str
    expected_chain_step_count: int
    missing_snippet_count: int
    missing_snippets: list[str]
    required_report_path_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    start_here = read_json_object(START_HERE_JSON)
    runbook_text = RUNBOOK_PATH.read_text(encoding="utf-8")
    report = build_report(start_here, runbook_text)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(start_here: JsonObject, runbook_text: str) -> RunbookConsistencyReport:
    assert_common_safety("start_here", start_here)
    chain_step_count = require_int(start_here.get("chain_step_count"), "start_here.chain_step_count")
    required_snippets = required_runbook_snippets(chain_step_count)
    missing_snippets = [snippet for snippet in required_snippets if snippet not in runbook_text]
    ok = not missing_snippets
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENT" if ok else "OCR_PREFLIGHT_OPERATOR_RUNBOOK_STALE",
        "runbook_path": "tools/subjective_sheet_lab/ocr_preflight_env_split_operator_runbook.md",
        "expected_chain_step_count": chain_step_count,
        "missing_snippet_count": len(missing_snippets),
        "missing_snippets": missing_snippets,
        "required_report_path_count": len(REQUIRED_REPORT_PATHS),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def required_runbook_snippets(chain_step_count: int) -> tuple[str, ...]:
    return (
        f"`chain_step_count`: `{chain_step_count}`",
        f"chain_step_count = {chain_step_count}",
        *REQUIRED_REPORT_PATHS,
        *REQUIRED_ZERO_COUNT_SNIPPETS,
        "status = OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_READY",
        "status = OCR_PROVIDER_FREE_HANDOFF_GUARD_COMMON_SELF_CHECK_VERIFIED",
        "status = OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_GUARD_VERIFIED",
        "status_card_manual_qa_handoff_status = READY",
        "common_self_check_status = OCR_PROVIDER_FREE_HANDOFF_GUARD_COMMON_SELF_CHECK_VERIFIED",
        "copied_common_self_check_step_blocked = true",
        "copied_status_card_guard_step_blocked = true",
        "`production_default`: `NO_GO`",
        "production_default = NO_GO",
    )


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep operator runbook consistency verification in the provider-free chain."
    return "Refresh ocr_preflight_env_split_operator_runbook.md from current provider-free chain evidence."


def markdown(report: RunbookConsistencyReport) -> str:
    missing_lines = [f"- {snippet}" for snippet in report["missing_snippets"]] or ["- none"]
    return "\n".join((
        "# OCR Preflight Operator Runbook Consistency",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- runbook_path: `{report['runbook_path']}`",
        f"- expected_chain_step_count: `{report['expected_chain_step_count']}`",
        f"- missing_snippet_count: `{report['missing_snippet_count']}`",
        f"- required_report_path_count: `{report['required_report_path_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Missing Snippets",
        *missing_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
