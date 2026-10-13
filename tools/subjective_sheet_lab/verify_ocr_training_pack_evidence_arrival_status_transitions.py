# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_evidence_arrival_status_transitions.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
ARRIVAL_SMOKE_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_smoke.json"
POST_ARRIVAL_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_dry_run_sequence.json"
INTAKE_ONLY_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_no_promotion_gate.json"
OPERATOR_SUMMARY_JSON: Final[Path] = LAB / "ocr_operator_next_action_summary.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_status_transitions.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_status_transitions.md"


@dataclass(frozen=True, slots=True)
class TransitionInputs:
    arrival_smoke: JsonObject
    post_arrival: JsonObject
    intake_only: JsonObject
    operator_summary: JsonObject


@dataclass(frozen=True, slots=True)
class TransitionRow:
    phase: str
    target_status: str
    allowed_next: str
    ready: bool
    write_allowed: bool

    def as_json(self) -> JsonObject:
        return {
            "phase": self.phase,
            "target_status": self.target_status,
            "allowed_next": self.allowed_next,
            "ready": self.ready,
            "write_allowed": self.write_allowed,
        }


def main() -> int:
    output = transition_report(
        TransitionInputs(
            arrival_smoke=read_json_object(ARRIVAL_SMOKE_JSON),
            post_arrival=read_json_object(POST_ARRIVAL_JSON),
            intake_only=read_json_object(INTAKE_ONLY_JSON),
            operator_summary=read_json_object(OPERATOR_SUMMARY_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def transition_report(inputs: TransitionInputs) -> JsonObject:
    require_inputs(inputs)
    rows = transition_rows()
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_EVIDENCE_ARRIVAL_STATUS_TRANSITIONS_READY",
        "current_stage": "before_required_files",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "transition_count": len(rows),
        "current_ready": False,
        "ready_after_required_files": True,
        "payload_parse_before_smoke_allowed": False,
        "promotion_write_allowed": False,
        "replacement_write_allowed": False,
        "accuracy_recompute_allowed": False,
        "runtime_write_allowed": False,
        "stops_before": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "transitions": [row.as_json() for row in rows],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def transition_rows() -> tuple[TransitionRow, ...]:
    return (
        TransitionRow("before_required_files", "USER_APPROVAL_REQUIRED", "arrival_smoke_only", False, False),
        TransitionRow(
            "after_required_files_arrive",
            "POST_ARRIVAL_DRY_RUN_SEQUENCE_READY",
            "smoke_then_blank_rejection_then_contract_validate_then_intake_replay",
            True,
            False,
        ),
        TransitionRow("after_contract_valid_intake_replay", "INTAKE_REPLAY_ONLY", "report_counts_only", True, False),
        TransitionRow(
            "promotion_or_replacement_requested",
            "SEPARATE_AUTHORIZATION_REQUIRED",
            "stop_before_promotion_replacement_accuracy_or_runtime_write",
            False,
            False,
        ),
    )


def require_inputs(inputs: TransitionInputs) -> None:
    require_text_value(inputs.arrival_smoke.get("status"), "TRAINING_PACK_EVIDENCE_ARRIVAL_SMOKE_READY", "arrival.status")
    require_bool_value(inputs.arrival_smoke.get("payload_parse_attempted"), False, "arrival.payload_parse_attempted")
    require_bool_value(inputs.arrival_smoke.get("ready_after_required_files"), True, "arrival.ready_after_required_files")
    require_text_value(
        inputs.post_arrival.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_SEQUENCE_USER_APPROVAL_REQUIRED",
        "post_arrival.status",
    )
    require_bool_value(inputs.post_arrival.get("current_ready"), False, "post_arrival.current_ready")
    require_bool_value(inputs.post_arrival.get("ready_after_required_files"), True, "post_arrival.ready_after_required_files")
    require_int_value(inputs.post_arrival.get("planned_command_count"), 8, "post_arrival.planned_command_count")
    require_text_value(
        inputs.intake_only.get("blocked_without_separate_authorization"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "intake.blocked_without_authorization",
    )
    require_text_value(
        inputs.operator_summary.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "operator.current_blocker",
    )
    for label, payload in (
        ("arrival", inputs.arrival_smoke),
        ("post_arrival", inputs.post_arrival),
        ("intake", inputs.intake_only),
        ("operator", inputs.operator_summary),
    ):
        require_safety_counters(label, payload)


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_EVIDENCE_ARRIVAL_STATUS_TRANSITIONS_READY", "status")
    require_text_value(output.get("current_stage"), "before_required_files", "current_stage")
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_text_value(output.get("stops_before"), "promotion_replacement_accuracy_recompute_or_runtime_write", "stops_before")
    require_int_value(output.get("transition_count"), 4, "transition_count")
    for key, value in bool_expectations():
        require_bool_value(output.get(key), value, key)
    require_transition_rows(output.get("transitions"))
    require_safety_counters("output", output)


def bool_expectations() -> tuple[tuple[str, bool], ...]:
    return (
        ("current_ready", False),
        ("ready_after_required_files", True),
        ("payload_parse_before_smoke_allowed", False),
        ("promotion_write_allowed", False),
        ("replacement_write_allowed", False),
        ("accuracy_recompute_allowed", False),
        ("runtime_write_allowed", False),
    )


def require_transition_rows(value: JsonValue) -> None:
    match value:
        case list() as rows:
            if len(rows) != 4:
                raise ExtendedGateError("transitions must contain four rows")
            for row in rows:
                require_transition_row(row)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("transitions must be a list")
        case unreachable:
            assert_never(unreachable)


def require_transition_row(value: JsonValue) -> None:
    match value:
        case dict() as row:
            require_bool_value(row.get("write_allowed"), False, "transition.write_allowed")
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("transition row must be a mapping")
        case unreachable:
            assert_never(unreachable)


def require_safety_counters(label: str, payload: JsonObject) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_leak")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.path_leak")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Evidence Arrival Status Transitions",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- current stage: `{output['current_stage']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- transition rows: {output['transition_count']}",
        f"- readiness: current={output['current_ready']}, after files={output['ready_after_required_files']}",
        f"- stops before: `{output['stops_before']}`",
        "- payload parse before smoke allowed: false",
        "- promotion/replacement/accuracy/runtime writes allowed: false",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
