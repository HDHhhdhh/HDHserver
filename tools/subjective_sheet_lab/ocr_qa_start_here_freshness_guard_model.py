from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

import ocr_qa_start_here_manual_handoff_freshness as handoff
from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    require_int,
    require_int_value,
    require_text_value,
)
from ocr_qa_start_here_core import ReportModifiedTimes, StartHereInputs, build_output


@dataclass(frozen=True, slots=True)
class GuardInputs:
    count: JsonObject
    operator: JsonObject
    freshness: JsonObject
    command_checklist: JsonObject
    runbook_rendered_guard: JsonObject
    runbook_consistency_guard: JsonObject
    current_times: ReportModifiedTimes
    manual_handoff_times: handoff.ManualHandoffRefreshTimes


def build_report(inputs: GuardInputs) -> JsonObject:
    probes = build_probes(inputs)
    runbook_rendered_guard_passed = runbook_guard_passed(
        inputs.runbook_rendered_guard,
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_RENDERED_SUMMARY_GUARD_VERIFIED",
        "runbook_rendered_guard",
    )
    runbook_consistency_guard_passed = runbook_guard_passed(
        inputs.runbook_consistency_guard,
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENCY_GUARD_VERIFIED",
        "runbook_consistency_guard",
    )
    ok = all(probe.ok for probe in probes) and runbook_rendered_guard_passed and runbook_consistency_guard_passed
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_QA_START_HERE_FRESHNESS_GUARD_VERIFIED" if ok else "OCR_QA_START_HERE_FRESHNESS_GUARD_FAILED",
        "probe_count": len(probes),
        "passed_probe_count": sum(1 for probe in probes if probe.ok),
        "failed_probe_count": sum(1 for probe in probes if not probe.ok),
        "current_command_checklist_newer_than_operator": inputs.current_times.command_checklist >= inputs.current_times.operator_summary,
        "current_command_checklist_newer_than_count": inputs.current_times.command_checklist >= inputs.current_times.count_consistency,
        "stale_operator_probe_blocked": probe_by_name(probes, "stale_against_operator").blocked,
        "stale_count_probe_blocked": probe_by_name(probes, "stale_against_count").blocked,
        "current_manual_qa_handoff_refresh_newer_than_sources": handoff.refresh_newer_than_sources(inputs.manual_handoff_times),
        "current_manual_qa_handoff_refresh_guard_newer_than_refresh": handoff.guard_newer_than_refresh(inputs.manual_handoff_times),
        "stale_manual_handoff_source_probe_blocked": probe_by_name(probes, "stale_manual_handoff_source").blocked,
        "stale_manual_handoff_guard_probe_blocked": probe_by_name(probes, "stale_manual_handoff_guard").blocked,
        "runbook_rendered_summary_guard_status": text_value(
            inputs.runbook_rendered_guard.get("status"),
            "runbook_rendered_guard.status",
        ),
        "runbook_rendered_summary_guard_failed_probe_count": require_int(
            inputs.runbook_rendered_guard.get("failed_probe_count"),
            "runbook_rendered_guard.failed_probe_count",
        ),
        "runbook_consistency_guard_status": text_value(
            inputs.runbook_consistency_guard.get("status"),
            "runbook_consistency_guard.status",
        ),
        "runbook_consistency_guard_failed_probe_count": require_int(
            inputs.runbook_consistency_guard.get("failed_probe_count"),
            "runbook_consistency_guard.failed_probe_count",
        ),
        "failed_runbook_rendered_guard_probe_blocked": probe_by_name(probes, "failed_runbook_rendered_guard").blocked,
        "failed_runbook_consistency_guard_probe_blocked": probe_by_name(probes, "failed_runbook_consistency_guard").blocked,
        "live_start_here_write_attempted": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "probes": [probe_fields(probe) for probe in probes],
        "next_safe_action": next_safe_action(ok),
    }


def build_probes(inputs: GuardInputs) -> tuple[handoff.ProbeResult, ...]:
    equal_boundary_time = max(
        inputs.current_times.command_checklist,
        inputs.current_times.operator_summary,
        inputs.current_times.count_consistency,
    )
    return (
        pass_probe("current_fresh", inputs, inputs.current_times),
        pass_probe("equal_boundary", inputs, ReportModifiedTimes(equal_boundary_time, equal_boundary_time, equal_boundary_time)),
        stale_against_operator_probe(inputs),
        stale_against_count_probe(inputs),
        failed_runbook_rendered_guard_probe(inputs),
        failed_runbook_consistency_guard_probe(inputs),
        handoff.manual_handoff_block_probe(
            "stale_manual_handoff_source",
            handoff.stale_manual_handoff_source_times(inputs.manual_handoff_times),
        ),
        handoff.manual_handoff_block_probe(
            "stale_manual_handoff_guard",
            handoff.stale_manual_handoff_guard_times(inputs.manual_handoff_times),
        ),
    )


def stale_against_operator_probe(inputs: GuardInputs) -> handoff.ProbeResult:
    fresh_time = max(inputs.current_times.operator_summary, inputs.current_times.count_consistency)
    times = ReportModifiedTimes(fresh_time - 1, fresh_time, fresh_time - 1)
    return block_probe("stale_against_operator", inputs, times)


def stale_against_count_probe(inputs: GuardInputs) -> handoff.ProbeResult:
    fresh_time = max(inputs.current_times.operator_summary, inputs.current_times.count_consistency)
    times = ReportModifiedTimes(fresh_time - 1, fresh_time - 1, fresh_time)
    return block_probe("stale_against_count", inputs, times)


def failed_runbook_rendered_guard_probe(inputs: GuardInputs) -> handoff.ProbeResult:
    return guard_block_probe(
        "failed_runbook_rendered_guard",
        inputs.runbook_rendered_guard,
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_RENDERED_SUMMARY_GUARD_VERIFIED",
    )


def failed_runbook_consistency_guard_probe(inputs: GuardInputs) -> handoff.ProbeResult:
    return guard_block_probe(
        "failed_runbook_consistency_guard",
        inputs.runbook_consistency_guard,
        "OCR_PREFLIGHT_OPERATOR_RUNBOOK_CONSISTENCY_GUARD_VERIFIED",
    )


def pass_probe(name: str, inputs: GuardInputs, times: ReportModifiedTimes) -> handoff.ProbeResult:
    try:
        build_output(start_here_inputs(inputs, times))
    except ExtendedGateError as error:
        return handoff.ProbeResult(name=name, ok=False, blocked=False, error=str(error))
    return handoff.ProbeResult(name=name, ok=True, blocked=False, error="")


def guard_block_probe(name: str, payload: JsonObject, expected_status: str) -> handoff.ProbeResult:
    failed_payload = {**payload, "failed_probe_count": 1}
    try:
        require_clean_guard(failed_payload, expected_status, name)
    except ExtendedGateError as error:
        return handoff.ProbeResult(name=name, ok=True, blocked=True, error=str(error))
    return handoff.ProbeResult(name=name, ok=False, blocked=False, error="failed runbook guard was accepted")


def block_probe(name: str, inputs: GuardInputs, times: ReportModifiedTimes) -> handoff.ProbeResult:
    try:
        build_output(start_here_inputs(inputs, times))
    except ExtendedGateError as error:
        return handoff.ProbeResult(name=name, ok=True, blocked=True, error=str(error))
    return handoff.ProbeResult(name=name, ok=False, blocked=False, error="stale input was accepted")


def runbook_guard_passed(payload: JsonObject, expected_status: str, label: str) -> bool:
    try:
        require_clean_guard(payload, expected_status, label)
    except ExtendedGateError:
        return False
    return True


def require_clean_guard(payload: JsonObject, expected_status: str, label: str) -> None:
    require_text_value(payload.get("status"), expected_status, f"{label}.status")
    require_int_value(payload.get("failed_probe_count"), 0, f"{label}.failed_probe_count")


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def start_here_inputs(inputs: GuardInputs, times: ReportModifiedTimes) -> StartHereInputs:
    return StartHereInputs(
        count=inputs.count,
        operator=inputs.operator,
        freshness=inputs.freshness,
        command_checklist=inputs.command_checklist,
        modified_times=times,
    )


def probe_by_name(probes: tuple[handoff.ProbeResult, ...], name: str) -> handoff.ProbeResult:
    for probe in probes:
        if probe.name == name:
            return probe
    raise ExtendedGateError(f"missing probe {name}")


def probe_fields(probe: handoff.ProbeResult) -> JsonObject:
    return {
        "name": probe.name,
        "ok": probe.ok,
        "blocked": probe.blocked,
        "error": probe.error,
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep the freshness guard regression in the provider-free chain."
    return "Inspect stale checklist guard probes before regenerating OCR_QA_START_HERE.md."
