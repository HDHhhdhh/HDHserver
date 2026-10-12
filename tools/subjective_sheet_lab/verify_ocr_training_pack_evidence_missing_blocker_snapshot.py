# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_evidence_missing_blocker_snapshot.py

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
ARRIVAL_SMOKE_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_smoke.json"
ARRIVAL_TRANSITIONS_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_status_transitions.json"
POST_ARRIVAL_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_dry_run_sequence.json"
OPERATOR_SUMMARY_JSON: Final[Path] = LAB / "ocr_operator_next_action_summary.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_missing_blocker_snapshot.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_evidence_missing_blocker_snapshot.md"


@dataclass(frozen=True, slots=True)
class SnapshotInputs:
    arrival_smoke: JsonObject
    arrival_transitions: JsonObject
    post_arrival: JsonObject
    operator_summary: JsonObject


def main() -> int:
    output = snapshot(
        SnapshotInputs(
            arrival_smoke=read_json_object(ARRIVAL_SMOKE_JSON),
            arrival_transitions=read_json_object(ARRIVAL_TRANSITIONS_JSON),
            post_arrival=read_json_object(POST_ARRIVAL_JSON),
            operator_summary=read_json_object(OPERATOR_SUMMARY_JSON),
        ),
    )
    require_snapshot(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def snapshot(inputs: SnapshotInputs) -> JsonObject:
    require_inputs(inputs)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_SNAPSHOT_READY",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "required_file_count": int_value(inputs.arrival_smoke.get("required_file_count"), "arrival.required_file_count"),
        "present_file_count": int_value(inputs.arrival_smoke.get("present_file_count"), "arrival.present_file_count"),
        "missing_file_count": int_value(inputs.arrival_smoke.get("missing_file_count"), "arrival.missing_file_count"),
        "ready_now": False,
        "ready_after_required_files": True,
        "safe_next_action": "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "post_arrival_sequence_ready_after_files": True,
        "payload_parse_before_arrival_smoke_allowed": False,
        "allowed_after_files_arrive": "smoke_then_blank_rejection_then_contract_validate_then_intake_replay_only",
        "blocked_without_separate_authorization": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: SnapshotInputs) -> None:
    require_text_value(inputs.arrival_smoke.get("status"), "TRAINING_PACK_EVIDENCE_ARRIVAL_SMOKE_READY", "arrival.status")
    require_text_value(
        inputs.arrival_transitions.get("status"),
        "TRAINING_PACK_EVIDENCE_ARRIVAL_STATUS_TRANSITIONS_READY",
        "transitions.status",
    )
    require_text_value(
        inputs.post_arrival.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_SEQUENCE_USER_APPROVAL_REQUIRED",
        "post_arrival.status",
    )
    require_text_value(
        inputs.operator_summary.get("status"),
        "OCR_OPERATOR_NEXT_ACTION_USER_ACTION_REQUIRED",
        "operator.status",
    )
    require_file_counts(inputs.arrival_smoke)
    require_bool_value(inputs.arrival_smoke.get("smoke_ready_now"), False, "arrival.smoke_ready_now")
    require_bool_value(inputs.arrival_smoke.get("ready_after_required_files"), True, "arrival.ready_after_files")
    require_bool_value(inputs.arrival_transitions.get("current_ready"), False, "transitions.current_ready")
    require_bool_value(inputs.arrival_transitions.get("ready_after_required_files"), True, "transitions.ready_after_files")
    require_bool_value(inputs.post_arrival.get("current_ready"), False, "post_arrival.current_ready")
    require_bool_value(inputs.post_arrival.get("ready_after_required_files"), True, "post_arrival.ready_after_files")
    require_bool_value(inputs.operator_summary.get("ready_now"), False, "operator.ready_now")
    require_bool_value(inputs.operator_summary.get("ready_after_required_files"), True, "operator.ready_after_files")
    for label, payload in (
        ("arrival", inputs.arrival_smoke),
        ("transitions", inputs.arrival_transitions),
        ("post_arrival", inputs.post_arrival),
        ("operator", inputs.operator_summary),
    ):
        require_safety_counters(label, payload)


def require_file_counts(payload: JsonObject) -> None:
    require_int_value(payload.get("required_file_count"), 4, "required_file_count")
    require_int_value(payload.get("present_file_count"), 0, "present_file_count")
    require_int_value(payload.get("missing_file_count"), 4, "missing_file_count")


def require_snapshot(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_SNAPSHOT_READY", "status")
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    require_text_value(
        output.get("safe_next_action"),
        "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "safe_next_action",
    )
    require_text_value(
        output.get("allowed_after_files_arrive"),
        "smoke_then_blank_rejection_then_contract_validate_then_intake_replay_only",
        "allowed_after_files_arrive",
    )
    require_text_value(
        output.get("blocked_without_separate_authorization"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "blocked_without_authorization",
    )
    require_file_counts(output)
    require_bool_value(output.get("ready_now"), False, "ready_now")
    require_bool_value(output.get("ready_after_required_files"), True, "ready_after_required_files")
    require_bool_value(output.get("post_arrival_sequence_ready_after_files"), True, "post_arrival_ready_after_files")
    require_bool_value(output.get("payload_parse_before_arrival_smoke_allowed"), False, "payload_parse_before_smoke")
    require_safety_counters("snapshot", output)


def require_safety_counters(label: str, payload: JsonObject) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_leak")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.path_leak")


def int_value(value: JsonValue, label: str) -> int:
    return require_int(value, label)


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Evidence Missing Blocker Snapshot",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- blocker: `{output['current_blocker']}`",
        f"- evidence files: {output['present_file_count']}/{output['required_file_count']} present",
        f"- missing files: {output['missing_file_count']}",
        f"- safe next action: `{output['safe_next_action']}`",
        f"- allowed after files arrive: `{output['allowed_after_files_arrive']}`",
        f"- blocked without separate authorization: `{output['blocked_without_separate_authorization']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
