from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_provider_free_extended_gate_count import EXTENDED_GATE_COUNT

EXPECTED_BASE_GATE_COUNT = 5
EXPECTED_COPY_CHECKLIST_ACTIONS = 4


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    payload: JsonObject
    should_pass: bool


def build_guard_report(live_readiness: JsonObject) -> JsonObject:
    probe_results = [run_probe(probe) for probe in probes(live_readiness)]
    failed_probe_count = sum(1 for row in probe_results if row["passed"] is False)
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_PREFLIGHT_READINESS_GUARD_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_PREFLIGHT_READINESS_GUARD_FAILED",
        "probe_count": len(probe_results),
        "failed_probe_count": failed_probe_count,
        "live_readiness_passed": probe_flag(probe_results, "live_readiness", "passed"),
        "preflight_modified_blocked": probe_flag(probe_results, "preflight_modified", "blocked"),
        "preflight_check_present_blocked": probe_flag(probe_results, "preflight_check_present", "blocked"),
        "ready_to_add_false_blocked": probe_flag(probe_results, "ready_to_add_false", "blocked"),
        "operator_copy_ready_blocked": probe_flag(probe_results, "operator_copy_ready", "blocked"),
        "nonzero_provider_count_blocked": probe_flag(probe_results, "nonzero_provider_count", "blocked"),
        "nonzero_submit_count_blocked": probe_flag(probe_results, "nonzero_submit_count", "blocked"),
        "production_default_enable_blocked": probe_flag(probe_results, "production_default_enable", "blocked"),
        "answer_key_leak_blocked": probe_flag(probe_results, "answer_key_leak", "blocked"),
        "absolute_patch_path_blocked": probe_flag(probe_results, "absolute_patch_path", "blocked"),
        "probes": probe_results,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def probes(live_readiness: JsonObject) -> tuple[Probe, ...]:
    return (
        Probe("live_readiness", clone_with(live_readiness), True),
        Probe("preflight_modified", clone_with(live_readiness, preflight_file_modified=True), False),
        Probe(
            "preflight_check_present",
            clone_with(live_readiness, preflight_check_already_present=True, ready_to_add_when_approved=False),
            False,
        ),
        Probe("ready_to_add_false", clone_with(live_readiness, ready_to_add_when_approved=False), False),
        Probe("operator_copy_ready", clone_with(live_readiness, operator_copy_checklist_ready=True), False),
        Probe("nonzero_provider_count", clone_with(live_readiness, provider_call_count=1), False),
        Probe("nonzero_submit_count", clone_with(live_readiness, submit_test_call_count=1), False),
        Probe("production_default_enable", clone_with(live_readiness, production_default="GO"), False),
        Probe("answer_key_leak", clone_with(live_readiness, answer_key_or_grading_field_leak_count=1), False),
        Probe("absolute_patch_path", clone_with(live_readiness, proposed_patch_path="C:/server/tmp.patch"), False),
    )


def clone_with(payload: JsonObject, **updates: JsonValue) -> JsonObject:
    return {**payload, **updates}


def run_probe(probe: Probe) -> JsonObject:
    passed = report_passes(probe.payload)
    blocked = not passed
    expected = passed is probe.should_pass
    return {
        "name": probe.name,
        "passed": expected,
        "blocked": blocked,
        "report_passed": passed,
    }


def report_passes(payload: JsonObject) -> bool:
    try:
        require_preflight_readiness(payload)
    except ExtendedGateError:
        return False
    return True


def require_preflight_readiness(payload: JsonObject) -> None:
    require_bool_value(payload.get("ok"), True, "preflight_readiness.ok")
    require_bool_value(payload.get("student_facing"), False, "preflight_readiness.student_facing")
    require_int_value(payload.get("provider_call_count"), 0, "preflight_readiness.provider_call_count")
    require_int_value(payload.get("external_ocr_api_call_count"), 0, "preflight_readiness.external_ocr_api_call_count")
    require_int_value(payload.get("submit_test_call_count"), 0, "preflight_readiness.submit_test_call_count")
    require_int_value(payload.get("ts_submit_click_count"), 0, "preflight_readiness.ts_submit_click_count")
    require_text_value(payload.get("production_default"), "NO_GO", "preflight_readiness.production_default")
    require_bool_value(payload.get("gate_script_exists"), True, "preflight_readiness.gate_script_exists")
    require_bool_value(payload.get("preflight_file_modified"), False, "preflight_readiness.preflight_file_modified")
    require_bool_value(
        payload.get("preflight_check_already_present"),
        False,
        "preflight_readiness.preflight_check_already_present",
    )
    require_bool_value(
        payload.get("ready_to_add_when_approved"),
        True,
        "preflight_readiness.ready_to_add_when_approved",
    )
    require_text_value(
        payload.get("proposed_patch_path"),
        "ocr_provider_free_accuracy_gate_preflight_proposed.patch",
        "preflight_readiness.proposed_patch_path",
    )
    require_text_value(
        payload.get("proposed_check_name"),
        "ocr_provider_free_accuracy_gate_extended",
        "preflight_readiness.proposed_check_name",
    )
    require_text_value(
        payload.get("proposed_required_path"),
        "tools/subjective_sheet_lab/verify_ocr_provider_free_accuracy_gate_extended.py",
        "preflight_readiness.proposed_required_path",
    )
    require_int_value(
        payload.get("provider_free_base_gate_count"),
        EXPECTED_BASE_GATE_COUNT,
        "preflight_readiness.provider_free_base_gate_count",
    )
    require_int_value(
        payload.get("provider_free_extended_gate_count"),
        EXTENDED_GATE_COUNT,
        "preflight_readiness.provider_free_extended_gate_count",
    )
    require_int_value(
        payload.get("operator_copy_checklist_action_required_count"),
        EXPECTED_COPY_CHECKLIST_ACTIONS,
        "preflight_readiness.operator_copy_checklist_action_required_count",
    )
    require_bool_value(
        payload.get("operator_copy_checklist_ready"),
        False,
        "preflight_readiness.operator_copy_checklist_ready",
    )
    require_int_value(
        payload.get("answer_key_or_grading_field_leak_count"),
        0,
        "preflight_readiness.answer_key_or_grading_field_leak_count",
    )
    require_int_value(payload.get("filesystem_path_leak_count"), 0, "preflight_readiness.filesystem_path_leak_count")
    require_relative_text(text_field(payload.get("proposed_patch_path"), "proposed_patch_path"), "proposed_patch_path")
    require_relative_text(
        text_field(payload.get("proposed_required_path"), "proposed_required_path"),
        "proposed_required_path",
    )


def require_relative_text(value: str, label: str) -> None:
    if ":" in value or value.startswith("/") or value.startswith("\\"):
        raise ExtendedGateError(f"{label} must remain a relative lab path")


def text_field(value: JsonValue, label: str) -> str:
    match value:
        case str() as text:
            return text
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def probe_flag(rows: list[JsonObject], name: str, field: str) -> bool:
    for row in rows:
        if row.get("name") == name:
            match row.get(field):
                case bool() as value:
                    return value
                case None | int() | float() | str() | list() | dict():
                    raise ExtendedGateError(f"{name}.{field} must be boolean")
                case unreachable:
                    assert_never(unreachable)
    raise ExtendedGateError(f"probe {name} was not found")


def require_guard_report(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "OCR_PROVIDER_FREE_PREFLIGHT_READINESS_GUARD_VERIFIED",
        "preflight_readiness_guard.status",
    )
    require_int_value(output.get("probe_count"), 10, "preflight_readiness_guard.probe_count")
    require_int_value(output.get("failed_probe_count"), 0, "preflight_readiness_guard.failed_probe_count")
    for key in (
        "live_readiness_passed",
        "preflight_modified_blocked",
        "preflight_check_present_blocked",
        "ready_to_add_false_blocked",
        "operator_copy_ready_blocked",
        "nonzero_provider_count_blocked",
        "nonzero_submit_count_blocked",
        "production_default_enable_blocked",
        "answer_key_leak_blocked",
        "absolute_patch_path_blocked",
    ):
        require_bool_value(output.get(key), True, f"preflight_readiness_guard.{key}")


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep preflight integration report-only until separate protected-file approval is present."
    return "Fix the preflight readiness guard before using the proposed run_phase1 preflight patch."
