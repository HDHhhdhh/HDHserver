# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_provider_free_gate_chain.py

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypedDict

from ocr_preflight_environment_matrix_model import JsonValue
from ocr_report_field_access import int_field, str_field


class ChainStep(TypedDict):
    name: str
    report_path: str
    exit_code: int
    ok: bool


class ChainReport(TypedDict):
    ok: bool
    student_facing: bool
    chain_step_count: int
    failed_step_count: int
    steps: list[ChainStep]
    matrix_ok: bool
    classifier_status: str
    freshness_status: str
    count_consistency_ok: bool
    extended_gate_count: int
    expected_extended_gate_count: int
    latest_queue_count: int
    training_pack_recognized_evidence_contract_rejected_probe_count: int
    training_pack_replacement_sandbox_safe_auto_grade_status_rejected_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    issue_count: int
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class ChainSourceReports:
    matrix: Mapping[str, JsonValue]
    classifier: Mapping[str, JsonValue]
    freshness: Mapping[str, JsonValue]
    count: Mapping[str, JsonValue]


def build_report(steps: Sequence[ChainStep], reports: ChainSourceReports) -> ChainReport:
    failed_step_count = sum(1 for step in steps if not step["ok"])
    issue_count = failed_step_count + int_field(reports.freshness, "issue_count") + int_field(reports.count, "issue_count")
    ok = failed_step_count == 0 and reports.count.get("ok") is True and issue_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "chain_step_count": len(steps),
        "failed_step_count": failed_step_count,
        "steps": list(steps),
        "matrix_ok": reports.matrix.get("ok") is True,
        "classifier_status": str_field(reports.classifier, "status"),
        "freshness_status": str_field(reports.freshness, "status"),
        "count_consistency_ok": reports.count.get("ok") is True,
        "extended_gate_count": int_field(reports.count, "extended_report_count"),
        "expected_extended_gate_count": int_field(reports.count, "expected_extended_gate_count"),
        "latest_queue_count": int_field(reports.count, "latest_queue_count"),
        "training_pack_recognized_evidence_contract_rejected_probe_count": int_field(
            reports.count,
            "training_pack_recognized_evidence_contract_rejected_probe_count",
        ),
        "training_pack_replacement_sandbox_safe_auto_grade_status_rejected_count": int_field(
            reports.count,
            "training_pack_replacement_sandbox_safe_auto_grade_status_rejected_count",
        ),
        "provider_call_count": int_field(reports.freshness, "provider_call_count"),
        "external_ocr_api_call_count": int_field(reports.freshness, "external_ocr_api_call_count"),
        "submit_test_call_count": int_field(reports.freshness, "submit_test_call_count"),
        "ts_submit_click_count": int_field(reports.freshness, "ts_submit_click_count"),
        "answer_key_or_grading_field_leak_count": int_field(
            reports.freshness,
            "answer_key_or_grading_field_leak_count",
        ),
        "filesystem_path_leak_count": int_field(reports.freshness, "filesystem_path_leak_count"),
        "production_default": str_field(reports.freshness, "production_default"),
        "issue_count": issue_count,
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Use this chain runner for provider-free OCR gate refreshes."
    return "Inspect the first failed chain step and rerun this chain after fixing the lab report."
