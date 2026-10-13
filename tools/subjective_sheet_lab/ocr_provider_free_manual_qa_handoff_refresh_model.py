from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, TypedDict

from ocr_provider_free_extended_gate_common import read_json_object, require_int
from verify_ocr_provider_free_final_handoff_chain import REPORT_JSON_OUT as FINAL_CHAIN_JSON
import verify_ocr_provider_free_final_handoff_chain as final_chain
from verify_ocr_provider_free_final_handoff_chain_guard import REPORT_JSON_OUT as FINAL_GUARD_JSON
import verify_ocr_provider_free_final_handoff_chain_guard as final_guard
from verify_ocr_provider_free_handoff_guard_common_self_check import REPORT_JSON_OUT as COMMON_SELF_CHECK_JSON
from verify_ocr_provider_free_handoff_guard_common_self_check import main as verify_common_self_check
from verify_ocr_provider_free_handoff_status_card import REPORT_JSON_OUT as STATUS_CARD_JSON
from verify_ocr_provider_free_handoff_status_card import main as verify_status_card
from verify_ocr_provider_free_handoff_status_card_guard import REPORT_JSON_OUT as STATUS_CARD_GUARD_JSON
from verify_ocr_provider_free_handoff_status_card_guard import main as verify_status_card_guard
from verify_ocr_provider_free_handoff_status_card_rendered_summary import (
    REPORT_JSON_OUT as STATUS_CARD_RENDERED_JSON,
)
from verify_ocr_provider_free_handoff_status_card_rendered_summary import main as verify_status_card_rendered
from verify_ocr_provider_free_handoff_status_card_rendered_summary_guard import (
    REPORT_JSON_OUT as STATUS_CARD_RENDERED_GUARD_JSON,
)
from verify_ocr_provider_free_handoff_status_card_rendered_summary_guard import (
    main as verify_status_card_rendered_guard,
)
from verify_ocr_provider_free_operator_summary import REPORT_JSON_OUT as OPERATOR_SUMMARY_JSON
from verify_ocr_provider_free_operator_summary import main as verify_operator_summary
from verify_ocr_provider_free_operator_summary_guard import REPORT_JSON_OUT as OPERATOR_SUMMARY_GUARD_JSON
from verify_ocr_provider_free_operator_summary_guard import main as verify_operator_summary_guard

Verifier: TypeAlias = Callable[[], int]


class HandoffRefreshStep(TypedDict):
    name: str
    report_path: str
    exit_code: int
    ok: bool


class HandoffRefreshReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    step_count: int
    failed_step_count: int
    steps: list[HandoffRefreshStep]
    common_self_check_status: str
    common_self_check_probe_count: int
    final_chain_status: str
    final_chain_step_count: int
    final_guard_status: str
    final_guard_probe_count: int
    status_card_status: str
    status_card_manual_qa_handoff_status: str
    status_card_guard_status: str
    status_card_guard_probe_count: int
    status_card_rendered_summary_status: str
    status_card_rendered_summary_missing_snippet_count: int
    status_card_rendered_summary_guard_status: str
    status_card_rendered_summary_guard_probe_count: int
    operator_summary_status: str
    operator_summary_state: str
    operator_summary_manual_qa_ready: bool
    operator_summary_guard_status: str
    operator_summary_guard_probe_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class HandoffRefreshStepSpec:
    name: str
    verifier: Verifier
    report_path: Path


def verify_final_chain_for_locked_refresh() -> int:
    steps = final_chain.run_steps(use_cached_serial_guard=True)
    report = final_chain.build_report(steps)
    FINAL_CHAIN_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    final_chain.REPORT_MD_OUT.write_text(final_chain.markdown(report), encoding="utf-8")
    return 0 if report["ok"] else 1


def verify_final_guard_for_locked_refresh() -> int:
    report = final_guard.run_guard(use_cached_serial_guard=True)
    return 0 if report["ok"] else 1


STEP_SPECS: Final[tuple[HandoffRefreshStepSpec, ...]] = (
    HandoffRefreshStepSpec("handoff_guard_common_self_check", verify_common_self_check, COMMON_SELF_CHECK_JSON),
    HandoffRefreshStepSpec("final_handoff_chain", verify_final_chain_for_locked_refresh, FINAL_CHAIN_JSON),
    HandoffRefreshStepSpec("final_handoff_chain_guard", verify_final_guard_for_locked_refresh, FINAL_GUARD_JSON),
    HandoffRefreshStepSpec("handoff_status_card", verify_status_card, STATUS_CARD_JSON),
    HandoffRefreshStepSpec("handoff_status_card_guard", verify_status_card_guard, STATUS_CARD_GUARD_JSON),
    HandoffRefreshStepSpec("handoff_status_card_rendered_summary", verify_status_card_rendered, STATUS_CARD_RENDERED_JSON),
    HandoffRefreshStepSpec(
        "handoff_status_card_rendered_summary_guard",
        verify_status_card_rendered_guard,
        STATUS_CARD_RENDERED_GUARD_JSON,
    ),
    HandoffRefreshStepSpec("operator_summary", verify_operator_summary, OPERATOR_SUMMARY_JSON),
    HandoffRefreshStepSpec("operator_summary_guard", verify_operator_summary_guard, OPERATOR_SUMMARY_GUARD_JSON),
)


def run_steps() -> list[HandoffRefreshStep]:
    steps: list[HandoffRefreshStep] = []
    for spec in STEP_SPECS:
        exit_code = spec.verifier()
        steps.append({
            "name": spec.name,
            "report_path": display_path(spec.report_path),
            "exit_code": exit_code,
            "ok": exit_code == 0,
        })
        if exit_code != 0:
            break
    return steps


def build_report(steps: list[HandoffRefreshStep]) -> HandoffRefreshReport:
    common_self_check = read_json_object(COMMON_SELF_CHECK_JSON)
    final_chain = read_json_object(FINAL_CHAIN_JSON)
    final_guard = read_json_object(FINAL_GUARD_JSON)
    status_card = read_json_object(STATUS_CARD_JSON)
    status_card_guard = read_json_object(STATUS_CARD_GUARD_JSON)
    status_card_rendered = read_json_object(STATUS_CARD_RENDERED_JSON)
    status_card_rendered_guard = read_json_object(STATUS_CARD_RENDERED_GUARD_JSON)
    operator_summary = read_json_object(OPERATOR_SUMMARY_JSON)
    operator_summary_guard = read_json_object(OPERATOR_SUMMARY_GUARD_JSON)
    failed_step_count = sum(1 for step in steps if not step["ok"])
    ok = (
        failed_step_count == 0
        and len(steps) == len(STEP_SPECS)
        and common_self_check.get("ok") is True
        and final_chain.get("ok") is True
        and final_guard.get("ok") is True
        and status_card.get("ok") is True
        and status_card_guard.get("ok") is True
        and status_card_rendered.get("ok") is True
        and status_card_rendered_guard.get("ok") is True
        and operator_summary.get("ok") is True
        and operator_summary_guard.get("ok") is True
        and operator_summary.get("operator_state") == "READY"
        and operator_summary.get("manual_qa_ready") is True
    )
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_READY"
        if ok
        else "OCR_PROVIDER_FREE_MANUAL_QA_HANDOFF_REFRESH_BLOCKED",
        "step_count": len(steps),
        "failed_step_count": failed_step_count,
        "steps": steps,
        "common_self_check_status": str(common_self_check.get("status", "")),
        "common_self_check_probe_count": require_int(
            common_self_check.get("probe_count"),
            "common_self_check.probe_count",
        ),
        "final_chain_status": str(final_chain.get("status", "")),
        "final_chain_step_count": require_int(final_chain.get("step_count"), "final_chain.step_count"),
        "final_guard_status": str(final_guard.get("status", "")),
        "final_guard_probe_count": require_int(final_guard.get("probe_count"), "final_guard.probe_count"),
        "status_card_status": str(status_card.get("status", "")),
        "status_card_manual_qa_handoff_status": str(status_card.get("manual_qa_handoff_status", "")),
        "status_card_guard_status": str(status_card_guard.get("status", "")),
        "status_card_guard_probe_count": require_int(
            status_card_guard.get("probe_count"),
            "status_card_guard.probe_count",
        ),
        "status_card_rendered_summary_status": str(status_card_rendered.get("status", "")),
        "status_card_rendered_summary_missing_snippet_count": require_int(
            status_card_rendered.get("missing_snippet_count"),
            "status_card_rendered.missing_snippet_count",
        ),
        "status_card_rendered_summary_guard_status": str(status_card_rendered_guard.get("status", "")),
        "status_card_rendered_summary_guard_probe_count": require_int(
            status_card_rendered_guard.get("probe_count"),
            "status_card_rendered_guard.probe_count",
        ),
        "operator_summary_status": str(operator_summary.get("status", "")),
        "operator_summary_state": str(operator_summary.get("operator_state", "")),
        "operator_summary_manual_qa_ready": operator_summary.get("manual_qa_ready") is True,
        "operator_summary_guard_status": str(operator_summary_guard.get("status", "")),
        "operator_summary_guard_probe_count": require_int(
            operator_summary_guard.get("probe_count"),
            "operator_summary_guard.probe_count",
        ),
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Use this wrapper as the one-command provider-free manual-QA handoff refresh."
    return "Inspect the first failed handoff refresh step before manual-QA handoff."


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"
