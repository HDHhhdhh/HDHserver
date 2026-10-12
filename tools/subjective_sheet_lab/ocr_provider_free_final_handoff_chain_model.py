from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, TypedDict, assert_never

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import JsonObject, JsonValue, read_json_object, require_int, require_object
from verify_ocr_post_chain_evidence_index import REPORT_JSON_OUT as EVIDENCE_INDEX_JSON
from verify_ocr_post_chain_evidence_handoff_runner import REPORT_JSON_OUT as HANDOFF_RUNNER_JSON
from verify_ocr_post_chain_evidence_handoff_runner_guard import REPORT_JSON_OUT as HANDOFF_GUARD_JSON
from verify_ocr_post_chain_evidence_handoff_runner_guard import main as verify_handoff_guard
import verify_ocr_post_chain_handoff_retention_manifest_guard as retention_guard
from verify_ocr_provider_free_gate_chain import REPORT_JSON_OUT as PROVIDER_FREE_CHAIN_JSON
from verify_ocr_provider_free_gate_chain import main as verify_provider_free_chain
from verify_ocr_training_pack_partial_evidence_arrival_guard import REPORT_JSON as PARTIAL_EVIDENCE_GUARD_JSON

Verifier: TypeAlias = Callable[[], int]
SERIAL_GUARD_JSON: Final[Path] = LAB / "ocr_provider_free_manual_qa_handoff_refresh_serial_guard.json"
SERIAL_GUARD_STEP_NAME: Final[str] = "manual_qa_handoff_refresh_serial_guard"
QA_START_HERE_SOURCE_LABELS: Final[tuple[str, ...]] = (
    "qa_start_here_freshness_guard",
    "qa_start_here_verification",
    "qa_start_here_rendered_summary",
    "qa_start_here_rendered_summary_guard",
)


class FinalHandoffStep(TypedDict):
    name: str
    report_path: str
    exit_code: int
    ok: bool


class FinalHandoffReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    step_count: int
    failed_step_count: int
    steps: list[FinalHandoffStep]
    provider_free_chain_step_count: int
    provider_free_chain_failed_step_count: int
    handoff_runner_status: str
    handoff_runner_step_count: int
    handoff_runner_failed_step_count: int
    handoff_guard_status: str
    handoff_guard_probe_count: int
    handoff_guard_failed_probe_count: int
    handoff_runner_common_self_check_source_report_count: int
    handoff_runner_evidence_index_source_report_count: int
    handoff_runner_evidence_index_guard_failed_probe_count: int
    post_chain_evidence_index_source_report_count: int
    post_chain_qa_start_here_source_count: int
    handoff_retention_guard_probe_count: int
    handoff_retention_guard_failed_probe_count: int
    handoff_retention_missing_start_card_freshness_helper_missing_count: int
    training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count: int
    training_pack_partial_evidence_arrival_guard_complete_probe_passed_count: int
    training_pack_partial_evidence_arrival_guard_invalid_probe_blocked_count: int
    training_pack_partial_evidence_arrival_guard_failed_probe_count: int
    manual_qa_handoff_refresh_serial_guard_status: str
    manual_qa_handoff_refresh_serial_guard_probe_count: int
    manual_qa_handoff_refresh_serial_guard_failed_probe_count: int
    manual_qa_handoff_refresh_serial_guard_lock_file_removed: bool
    manual_qa_handoff_refresh_serial_guard_artifacts_preserved: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class FinalHandoffStepSpec:
    name: str
    verifier: Verifier
    report_path: Path


def verify_serial_guard() -> int:
    from verify_ocr_provider_free_manual_qa_handoff_refresh_serial_guard import main

    return main()


STEP_SPECS: Final[tuple[FinalHandoffStepSpec, ...]] = (
    FinalHandoffStepSpec("provider_free_gate_chain", verify_provider_free_chain, PROVIDER_FREE_CHAIN_JSON),
    FinalHandoffStepSpec(SERIAL_GUARD_STEP_NAME, verify_serial_guard, SERIAL_GUARD_JSON),
    FinalHandoffStepSpec("post_chain_handoff_runner_guard", verify_handoff_guard, HANDOFF_GUARD_JSON),
)


def run_steps(use_cached_serial_guard: bool = False) -> list[FinalHandoffStep]:
    steps: list[FinalHandoffStep] = []
    for spec in STEP_SPECS:
        exit_code = cached_serial_guard_exit_code() if use_cached_serial_guard and spec.name == SERIAL_GUARD_STEP_NAME else spec.verifier()
        steps.append({
            "name": spec.name,
            "report_path": display_path(spec.report_path),
            "exit_code": exit_code,
            "ok": exit_code == 0,
        })
        if exit_code != 0:
            break
    return steps


def cached_serial_guard_exit_code() -> int:
    payload = read_json_object(SERIAL_GUARD_JSON)
    ok = (
        payload.get("ok") is True
        and require_int(payload.get("failed_probe_count"), "serial_guard.failed_probe_count") == 0
        and payload.get("lock_file_removed") is True
        and payload.get("busy_probes_preserved_refresh_artifacts") is True
    )
    return 0 if ok else 1


def build_report(steps: list[FinalHandoffStep]) -> FinalHandoffReport:
    chain = read_json_object(PROVIDER_FREE_CHAIN_JSON)
    runner = read_json_object(HANDOFF_RUNNER_JSON)
    guard = read_json_object(HANDOFF_GUARD_JSON)
    evidence = read_json_object(EVIDENCE_INDEX_JSON)
    retention_payload = read_json_object(retention_guard.REPORT_JSON_OUT)
    partial_guard = read_json_object(PARTIAL_EVIDENCE_GUARD_JSON)
    serial_guard = read_json_object(SERIAL_GUARD_JSON)
    failed_step_count = sum(1 for step in steps if not step["ok"])
    handoff_guard_failed_probe_count = require_int(guard.get("failed_probe_count"), "handoff_guard.failed_probe_count")
    common_source_count = require_int(runner.get("common_self_check_source_report_count"), "runner.common_self_check_source_report_count")
    evidence_source_count = require_int(runner.get("evidence_index_source_report_count"), "runner.evidence_index_source_report_count")
    evidence_guard_failed_probe_count = require_int(
        runner.get("evidence_index_guard_failed_probe_count"),
        "runner.evidence_index_guard_failed_probe_count",
    )
    post_chain_source_count = require_int(evidence.get("source_report_count"), "evidence_index.source_report_count")
    qa_source_count = source_label_count(evidence, QA_START_HERE_SOURCE_LABELS)
    retention_probe_count = require_int(retention_payload.get("probe_count"), "retention_guard.probe_count")
    retention_failed_count = require_int(retention_payload.get("failed_probe_count"), "retention_guard.failed_probe_count")
    missing_helper_count = require_int(
        retention_payload.get("copied_missing_start_card_freshness_helper_missing_count"),
        "retention_guard.copied_missing_start_card_freshness_helper_missing_count",
    )
    serial_probe_count = require_int(serial_guard.get("probe_count"), "serial_guard.probe_count")
    serial_failed_count = require_int(serial_guard.get("failed_probe_count"), "serial_guard.failed_probe_count")
    partial_probe_blocked_count = require_int(
        partial_guard.get("partial_probe_blocked_count"),
        "partial_guard.partial_probe_blocked_count",
    )
    partial_complete_passed_count = 1 if partial_guard.get("complete_probe_passed") is True else 0
    partial_invalid_blocked_count = require_int(
        partial_guard.get("invalid_probe_blocked_count"),
        "partial_guard.invalid_probe_blocked_count",
    )
    partial_failed_count = require_int(partial_guard.get("failed_probe_count"), "partial_guard.failed_probe_count")
    ok = (
        failed_step_count == 0
        and len(steps) == len(STEP_SPECS)
        and chain.get("ok") is True
        and runner.get("ok") is True
        and guard.get("ok") is True
        and handoff_guard_failed_probe_count == 0
        and common_source_count == 16
        and evidence_source_count == 18
        and evidence_guard_failed_probe_count == 0
        and post_chain_source_count == 18
        and qa_source_count == 4
        and retention_probe_count == 9
        and retention_failed_count == 0
        and missing_helper_count == 1
        and partial_guard.get("ok") is True
        and partial_probe_blocked_count == 4
        and partial_complete_passed_count == 1
        and partial_invalid_blocked_count == 3
        and partial_failed_count == 0
        and serial_guard.get("ok") is True
        and serial_failed_count == 0
        and serial_guard.get("lock_file_removed") is True
        and serial_guard.get("busy_probes_preserved_refresh_artifacts") is True
    )
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_VERIFIED" if ok else "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_FAILED",
        "step_count": len(steps),
        "failed_step_count": failed_step_count,
        "steps": steps,
        "provider_free_chain_step_count": require_int(chain.get("chain_step_count"), "chain.chain_step_count"),
        "provider_free_chain_failed_step_count": require_int(chain.get("failed_step_count"), "chain.failed_step_count"),
        "handoff_runner_status": str(runner.get("status", "")),
        "handoff_runner_step_count": require_int(runner.get("handoff_step_count"), "runner.handoff_step_count"),
        "handoff_runner_failed_step_count": require_int(runner.get("failed_step_count"), "runner.failed_step_count"),
        "handoff_guard_status": str(guard.get("status", "")),
        "handoff_guard_probe_count": require_int(guard.get("probe_count"), "handoff_guard.probe_count"),
        "handoff_guard_failed_probe_count": handoff_guard_failed_probe_count,
        "handoff_runner_common_self_check_source_report_count": common_source_count,
        "handoff_runner_evidence_index_source_report_count": evidence_source_count,
        "handoff_runner_evidence_index_guard_failed_probe_count": evidence_guard_failed_probe_count,
        "post_chain_evidence_index_source_report_count": post_chain_source_count,
        "post_chain_qa_start_here_source_count": qa_source_count,
        "handoff_retention_guard_probe_count": retention_probe_count,
        "handoff_retention_guard_failed_probe_count": retention_failed_count,
        "handoff_retention_missing_start_card_freshness_helper_missing_count": missing_helper_count,
        "training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count": partial_probe_blocked_count,
        "training_pack_partial_evidence_arrival_guard_complete_probe_passed_count": partial_complete_passed_count,
        "training_pack_partial_evidence_arrival_guard_invalid_probe_blocked_count": partial_invalid_blocked_count,
        "training_pack_partial_evidence_arrival_guard_failed_probe_count": partial_failed_count,
        "manual_qa_handoff_refresh_serial_guard_status": str(serial_guard.get("status", "")),
        "manual_qa_handoff_refresh_serial_guard_probe_count": serial_probe_count,
        "manual_qa_handoff_refresh_serial_guard_failed_probe_count": serial_failed_count,
        "manual_qa_handoff_refresh_serial_guard_lock_file_removed": serial_guard.get("lock_file_removed") is True,
        "manual_qa_handoff_refresh_serial_guard_artifacts_preserved": (
            serial_guard.get("busy_probes_preserved_refresh_artifacts") is True
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
        return "Use this final wrapper as the one-command provider-free manual-QA handoff refresh."
    return "Inspect the first failed final handoff step before manual-QA handoff."


def source_label_count(payload: JsonObject, labels: tuple[str, ...]) -> int:
    reports = payload.get("source_reports")
    match reports:
        case list():
            labels_seen = source_labels(reports)
        case None | bool() | int() | float() | str() | dict():
            return 0
        case unreachable:
            assert_never(unreachable)
    return sum(1 for label in labels if label in labels_seen)


def source_labels(reports: list[JsonValue]) -> set[str]:
    labels: set[str] = set()
    for index, row in enumerate(reports, start=1):
        row_object = require_object(row, f"evidence_index.source_reports[{index}]")
        label = row_object.get("label")
        match label:
            case str():
                labels.add(label)
            case None | bool() | int() | float() | list() | dict():
                continue
            case unreachable:
                assert_never(unreachable)
    return labels


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"
