from __future__ import annotations

from typing import Callable, TypeAlias

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_intake_only_command_checklist_guard import REPORT_JSON
from verify_ocr_training_pack_intake_only_command_checklist_guard import main as verify_intake_command_checklist_guard

Verifier: TypeAlias = Callable[[], int]


def intake_command_guard_verifiers() -> tuple[tuple[str, Verifier], ...]:
    return (("training pack intake-only command checklist guard", verify_intake_command_checklist_guard),)


def intake_command_guard_reports() -> dict[str, JsonObject]:
    return {"training_pack_intake_only_command_checklist_guard": read_json_object(REPORT_JSON)}


def require_training_pack_intake_only_command_checklist_guard(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_GUARD_VERIFIED",
        "intake_command_checklist_guard.status",
    )
    require_bool_value(report.get("current_checklist_passed"), True, "intake_command_checklist_guard.current_passed")
    require_bool_value(
        report.get("missing_blank_evidence_command_blocked"),
        True,
        "intake_command_checklist_guard.missing_blank_blocked",
    )
    require_bool_value(
        report.get("live_checklist_write_attempted"),
        False,
        "intake_command_checklist_guard.write_attempted",
    )
    for key, value in intake_command_guard_integer_requirements():
        require_int_value(report.get(key), value, f"intake_command_checklist_guard.{key}")


def intake_command_guard_integer_requirements() -> tuple[tuple[str, int], ...]:
    return (
        ("probe_count", 2),
        ("failed_probe_count", 0),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def intake_command_guard_summary_fields() -> JsonObject:
    return {
        "training_pack_intake_only_command_checklist_guard_status": (
            "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_GUARD_VERIFIED"
        ),
        "training_pack_intake_only_command_checklist_guard_probe_count": 2,
        "training_pack_intake_only_command_checklist_missing_blank_blocked": True,
    }
