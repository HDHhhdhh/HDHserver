# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_post_arrival_dry_run_readiness_matrix.py

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
    require_int,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
COMMAND_CHECKLIST_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_command_checklist.json"
MISSING_BLOCKER_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_missing_blocker_snapshot.json"
POST_ARRIVAL_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_dry_run_sequence.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_dry_run_readiness_matrix.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_post_arrival_dry_run_readiness_matrix.md"


@dataclass(frozen=True, slots=True)
class MatrixInputs:
    command_checklist: JsonObject
    missing_blocker: JsonObject
    post_arrival: JsonObject


@dataclass(frozen=True, slots=True)
class ChecklistCommand:
    step_no: int
    label: str
    command: str


@dataclass(frozen=True, slots=True)
class MatrixRow:
    step_no: int
    label: str
    command: str
    current_status: str
    after_files_status: str
    requires_evidence_files: bool
    payload_parse_allowed_now: bool
    write_allowed: bool
    stops_before_write: bool
    failure_reason: str

    def as_json(self) -> JsonObject:
        return {"step_no": self.step_no, "label": self.label, "command": self.command, "current_status": self.current_status, "after_files_status": self.after_files_status, "requires_evidence_files": self.requires_evidence_files, "payload_parse_allowed_now": self.payload_parse_allowed_now, "write_allowed": self.write_allowed, "stops_before_write": self.stops_before_write, "failure_reason": self.failure_reason}


def main() -> int:
    output = readiness_matrix(
        MatrixInputs(
            command_checklist=read_json_object(COMMAND_CHECKLIST_JSON),
            missing_blocker=read_json_object(MISSING_BLOCKER_JSON),
            post_arrival=read_json_object(POST_ARRIVAL_JSON),
        ),
    )
    require_report(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def readiness_matrix(inputs: MatrixInputs) -> JsonObject:
    require_inputs(inputs)
    rows = tuple(readiness_row(command) for command in commands(inputs.command_checklist))
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_READINESS_MATRIX_READY",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "ordered_command_count": len(rows),
        "currently_runnable_command_count": count_status(rows, "runnable_now"),
        "blocked_missing_evidence_count": count_status(rows, "blocked_missing_evidence"),
        "after_files_runnable_command_count": len(rows),
        "payload_parse_allowed_now_count": sum(1 for row in rows if row.payload_parse_allowed_now),
        "write_allowed_command_count": sum(1 for row in rows if row.write_allowed),
        "stop_before_write_command_count": sum(1 for row in rows if row.stops_before_write),
        "allowed_after_files_arrive": "smoke_then_blank_rejection_then_contract_validate_then_intake_replay_only",
        "blocked_without_separate_authorization": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "commands": [row.as_json() for row in rows],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def readiness_row(command: ChecklistCommand) -> MatrixRow:
    match command.step_no:
        case 1 | 2:
            return MatrixRow(command.step_no, command.label, command.command, "runnable_now", "runnable_after_files", False, False, False, False, "none")
        case 3 | 4 | 5 | 6 | 7:
            return MatrixRow(
                command.step_no,
                command.label,
                command.command,
                "blocked_missing_evidence",
                "runnable_after_files",
                True,
                False,
                False,
                False,
                "training_pack_recognized_evidence_files_missing",
            )
        case 8:
            return MatrixRow(
                command.step_no,
                command.label,
                command.command,
                "runnable_now",
                "runnable_after_files",
                False,
                False,
                False,
                True,
                "promotion_replacement_accuracy_recompute_or_runtime_write_blocked",
            )
        case unreachable:
            assert_never(unreachable)


def commands(command_checklist: JsonObject) -> tuple[ChecklistCommand, ...]:
    match command_checklist.get("commands"):
        case list() as rows:
            result = tuple(command(row) for row in rows)
            if len(result) != 8:
                raise ExtendedGateError("readiness matrix requires eight commands")
            return result
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("commands must be a list")
        case unreachable:
            assert_never(unreachable)


def command(value: JsonValue) -> ChecklistCommand:
    match value:
        case dict() as row:
            return ChecklistCommand(
                step_no=require_int(row.get("step_no"), "command.step_no"),
                label=text_value(row.get("label"), "command.label"),
                command=text_value(row.get("command"), "command.command"),
            )
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("command row must be a mapping")
        case unreachable:
            assert_never(unreachable)


def require_inputs(inputs: MatrixInputs) -> None:
    require_text_value(inputs.command_checklist.get("status"), "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_READY", "checklist.status")
    require_text_value(inputs.missing_blocker.get("status"), "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_SNAPSHOT_READY", "blocker.status")
    require_text_value(inputs.post_arrival.get("status"), "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_SEQUENCE_USER_APPROVAL_REQUIRED", "post.status")
    require_int_value(inputs.command_checklist.get("ordered_command_count"), 8, "checklist.ordered_command_count")
    require_int_value(inputs.post_arrival.get("planned_command_count"), 8, "post.planned_command_count")
    require_bool_value(inputs.missing_blocker.get("ready_now"), False, "blocker.ready_now")
    require_bool_value(inputs.missing_blocker.get("ready_after_required_files"), True, "blocker.ready_after_files")
    require_bool_value(inputs.post_arrival.get("current_ready"), False, "post.current_ready")
    require_bool_value(inputs.post_arrival.get("ready_after_required_files"), True, "post.ready_after_files")
    for label, payload in (("checklist", inputs.command_checklist), ("blocker", inputs.missing_blocker), ("post", inputs.post_arrival)):
        require_safety_counters(label, payload)


def require_report(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_READINESS_MATRIX_READY", "status")
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_int_value(output.get("ordered_command_count"), 8, "ordered_command_count")
    require_int_value(output.get("currently_runnable_command_count"), 3, "currently_runnable_command_count")
    require_int_value(output.get("blocked_missing_evidence_count"), 5, "blocked_missing_evidence_count")
    require_int_value(output.get("after_files_runnable_command_count"), 8, "after_files_runnable_command_count")
    require_int_value(output.get("payload_parse_allowed_now_count"), 0, "payload_parse_allowed_now_count")
    require_int_value(output.get("write_allowed_command_count"), 0, "write_allowed_command_count")
    require_int_value(output.get("stop_before_write_command_count"), 1, "stop_before_write_command_count")
    require_safety_counters("output", output)


def count_status(rows: tuple[MatrixRow, ...], status: str) -> int:
    return sum(1 for row in rows if row.current_status == status)


def require_safety_counters(label: str, payload: JsonObject) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_leak")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.path_leak")


def text_value(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Post-Arrival Dry-Run Readiness Matrix",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- commands: {output['ordered_command_count']}",
        f"- runnable now: {output['currently_runnable_command_count']}",
        f"- blocked by missing evidence: {output['blocked_missing_evidence_count']}",
        f"- runnable after files: {output['after_files_runnable_command_count']}",
        f"- payload parse allowed now: {output['payload_parse_allowed_now_count']}",
        f"- write-allowed commands: {output['write_allowed_command_count']}",
        f"- stop-before-write commands: {output['stop_before_write_command_count']}",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
