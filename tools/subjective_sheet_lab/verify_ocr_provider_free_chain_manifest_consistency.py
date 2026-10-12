# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_chain_manifest_consistency.py

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import ExtendedGateError
from ocr_qa_start_here_core import EXPECTED_CHAIN_STEP_COUNT

CHAIN_SOURCE: Final[Path] = LAB / "verify_ocr_provider_free_gate_chain.py"
REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_chain_manifest_consistency.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_chain_manifest_consistency.md"
CANONICAL_CHAIN_STEPS: Final[tuple[str, ...]] = (
    "environment_matrix",
    "failure_classifier",
    "report_freshness",
    "preflight_readiness_guard",
    "queue_state",
    "operator_summary",
    "training_pack_missing_blocker_snapshot",
    "training_pack_missing_blocker_snapshot_guard",
    "training_pack_prearrival_contract",
    "training_pack_filename_diagnostics",
    "training_pack_partial_evidence_arrival_guard",
    "count_consistency",
    "count_consistency_guard",
    "intake_command_checklist",
    "intake_command_checklist_guard",
    "training_pack_standard_field_coverage",
    "chain_manifest_consistency",
    "chain_manifest_consistency_guard",
    "qa_start_here_freshness_guard",
    "qa_start_here",
    "qa_start_here_rendered_summary",
    "qa_start_here_rendered_summary_guard",
    "operator_runbook_rendered_summary",
    "count_consistency_path_rendered_guard",
    "operator_runbook_rendered_summary_guard",
    "operator_runbook_consistency",
    "operator_runbook_consistency_guard",
    "user_action_required_inventory",
    "user_action_required_inventory_guard",
)


class ChainManifestReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    chain_source_path: str
    start_here_core_path: str
    expected_chain_step_count: int
    actual_chain_step_count: int
    chain_step_count_delta: int
    missing_required_chain_step_count: int
    missing_required_chain_steps: list[str]
    canonical_chain_step_mismatch_count: int
    canonical_chain_step_mismatches: list[str]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    source_text = CHAIN_SOURCE.read_text(encoding="utf-8")
    actual_count = chain_step_count(source_text)
    report = build_report(actual_count, chain_step_names(source_text))
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(actual_count: int, step_names: tuple[str, ...]) -> ChainManifestReport:
    delta = actual_count - EXPECTED_CHAIN_STEP_COUNT
    missing_required_steps = [step for step in CANONICAL_CHAIN_STEPS if step not in step_names]
    canonical_mismatches = canonical_chain_step_mismatches(step_names)
    ok = delta == 0 and not missing_required_steps and not canonical_mismatches
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_CHAIN_MANIFEST_CONSISTENT"
        if ok
        else "OCR_PROVIDER_FREE_CHAIN_MANIFEST_STALE",
        "chain_source_path": "tools/subjective_sheet_lab/verify_ocr_provider_free_gate_chain.py",
        "start_here_core_path": "tools/subjective_sheet_lab/ocr_qa_start_here_core.py",
        "expected_chain_step_count": EXPECTED_CHAIN_STEP_COUNT,
        "actual_chain_step_count": actual_count,
        "chain_step_count_delta": delta,
        "missing_required_chain_step_count": len(missing_required_steps),
        "missing_required_chain_steps": missing_required_steps,
        "canonical_chain_step_mismatch_count": len(canonical_mismatches),
        "canonical_chain_step_mismatches": canonical_mismatches,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def chain_step_count(source_text: str) -> int:
    parsed_module = ast.parse(source_text)
    for node in parsed_module.body:
        if node.__class__ is ast.AnnAssign and target_is_name(node.target, "CHAIN_STEPS"):
            value = node.value
            if value is None:
                raise ExtendedGateError("CHAIN_STEPS must have a tuple value")
            return tuple_length(value, "CHAIN_STEPS")
    raise ExtendedGateError("CHAIN_STEPS assignment was not found")


def chain_step_names(source_text: str) -> tuple[str, ...]:
    parsed_module = ast.parse(source_text)
    for node in parsed_module.body:
        if node.__class__ is ast.AnnAssign and target_is_name(node.target, "CHAIN_STEPS"):
            value = node.value
            if value is None:
                raise ExtendedGateError("CHAIN_STEPS must have a tuple value")
            if value.__class__ is not ast.Tuple:
                raise ExtendedGateError("CHAIN_STEPS must be a tuple literal")
            names: list[str] = []
            for index, step in enumerate(value.elts, start=1):
                if step.__class__ is not ast.Tuple or not step.elts:
                    raise ExtendedGateError(f"CHAIN_STEPS[{index}] must be a tuple literal")
                step_name = step.elts[0]
                if step_name.__class__ is not ast.Constant or not isinstance(step_name.value, str):
                    raise ExtendedGateError(f"CHAIN_STEPS[{index}] first item must be a string literal")
                names.append(step_name.value)
            return tuple(names)
    raise ExtendedGateError("CHAIN_STEPS assignment was not found")


def canonical_chain_step_mismatches(step_names: tuple[str, ...]) -> list[str]:
    mismatches: list[str] = []
    for index, expected_name in enumerate(CANONICAL_CHAIN_STEPS, start=1):
        actual_name = step_names[index - 1] if index <= len(step_names) else "<missing>"
        if actual_name != expected_name:
            mismatches.append(f"{index}: expected {expected_name}, got {actual_name}")
    for index, actual_name in enumerate(step_names[len(CANONICAL_CHAIN_STEPS) :], start=len(CANONICAL_CHAIN_STEPS) + 1):
        mismatches.append(f"{index}: expected <none>, got {actual_name}")
    return mismatches


def target_is_name(target: ast.AST, expected_name: str) -> bool:
    return target.__class__ is ast.Name and target.id == expected_name


def tuple_length(value: ast.AST, label: str) -> int:
    if value.__class__ is ast.Tuple:
        return len(value.elts)
    raise ExtendedGateError(f"{label} must be a tuple literal")


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep the chain manifest consistency verifier before start-here generation."
    return "Update EXPECTED_CHAIN_STEP_COUNT or restore the canonical CHAIN_STEPS sequence before regeneration."


def markdown(report: ChainManifestReport) -> str:
    return "\n".join((
        "# OCR Provider-Free Chain Manifest Consistency",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- chain_source_path: `{report['chain_source_path']}`",
        f"- start_here_core_path: `{report['start_here_core_path']}`",
        f"- expected_chain_step_count: `{report['expected_chain_step_count']}`",
        f"- actual_chain_step_count: `{report['actual_chain_step_count']}`",
        f"- chain_step_count_delta: `{report['chain_step_count_delta']}`",
        f"- missing_required_chain_step_count: `{report['missing_required_chain_step_count']}`",
        f"- missing_required_chain_steps: `{report['missing_required_chain_steps']}`",
        f"- canonical_chain_step_mismatch_count: `{report['canonical_chain_step_mismatch_count']}`",
        f"- canonical_chain_step_mismatches: `{report['canonical_chain_step_mismatches']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
