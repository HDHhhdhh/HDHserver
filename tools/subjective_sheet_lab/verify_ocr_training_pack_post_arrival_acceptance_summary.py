# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_post_arrival_acceptance_summary.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
MISSING_BLOCKER_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_missing_blocker_snapshot.json"
READINESS_MATRIX_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_dry_run_readiness_matrix.json"
ACCEPTANCE_BUNDLE_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_acceptance_bundle_gate.json"
CONTRACT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_contract.json"
COVERAGE_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_target_coverage.json"
INTAKE_REPLAY_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake_replay.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_post_arrival_acceptance_summary.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_post_arrival_acceptance_summary.md"


@dataclass(frozen=True, slots=True)
class AcceptanceInputs:
    missing_blocker: JsonObject
    readiness_matrix: JsonObject
    acceptance_bundle: JsonObject
    contract: JsonObject
    coverage: JsonObject
    intake_replay: JsonObject


def main() -> int:
    output = acceptance_summary(
        AcceptanceInputs(
            missing_blocker=read_json_object(MISSING_BLOCKER_JSON),
            readiness_matrix=read_json_object(READINESS_MATRIX_JSON),
            acceptance_bundle=read_json_object(ACCEPTANCE_BUNDLE_JSON),
            contract=read_json_object(CONTRACT_JSON),
            coverage=read_json_object(COVERAGE_JSON),
            intake_replay=read_json_object(INTAKE_REPLAY_JSON),
        ),
    )
    require_report(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def acceptance_summary(inputs: AcceptanceInputs) -> JsonObject:
    require_inputs(inputs)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_POST_ARRIVAL_ACCEPTANCE_SUMMARY_USER_ACTION_REQUIRED",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "acceptance_ready_now": False,
        "acceptance_ready_after_required_files": True,
        "required_file_count": 4,
        "present_file_count": 0,
        "missing_file_count": 4,
        "accepted_file_count": 0,
        "rejected_file_count": 0,
        "pending_file_count": 4,
        "contract_payload_parse_allowed_now": False,
        "required_review_item_count_per_payload": 20,
        "required_question_sequence": "1-20",
        "allowed_after_files_arrive": "smoke_then_blank_rejection_then_contract_validate_then_target_coverage_then_intake_replay_only",
        "blocked_without_separate_authorization": "promotion_replacement_accuracy_recompute_or_runtime_write",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: AcceptanceInputs) -> None:
    require_text_value(
        inputs.missing_blocker.get("status"),
        "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_SNAPSHOT_READY",
        "missing_blocker.status",
    )
    require_text_value(
        inputs.readiness_matrix.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_DRY_RUN_READINESS_MATRIX_READY",
        "readiness_matrix.status",
    )
    require_text_value(
        inputs.acceptance_bundle.get("status"),
        "TRAINING_PACK_EVIDENCE_ACCEPTANCE_BUNDLE_USER_APPROVAL_REQUIRED",
        "acceptance_bundle.status",
    )
    require_text_value(
        inputs.contract.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS",
        "contract.status",
    )
    require_text_value(
        inputs.coverage.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_USER_APPROVAL_REQUIRED",
        "coverage.status",
    )
    require_text_value(
        inputs.intake_replay.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED",
        "intake_replay.status",
    )
    for key, value in required_input_counts():
        source, field = key.split(".", maxsplit=1)
        require_int_value(getattr(inputs, source).get(field), value, key)
    require_bool_value(inputs.contract.get("contract_ready"), True, "contract.contract_ready")
    require_bool_value(inputs.coverage.get("target_coverage_ready"), False, "coverage.target_coverage_ready")
    require_bool_value(inputs.intake_replay.get("intake_replay_ready"), False, "intake_replay.intake_replay_ready")
    for label, payload in safety_inputs(inputs):
        require_safety_counters(label, payload)


def required_input_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("missing_blocker.required_file_count", 4),
        ("missing_blocker.present_file_count", 0),
        ("missing_blocker.missing_file_count", 4),
        ("readiness_matrix.payload_parse_allowed_now_count", 0),
        ("readiness_matrix.write_allowed_command_count", 0),
        ("acceptance_bundle.current_payload_count", 0),
        ("acceptance_bundle.current_missing_payload_count", 4),
        ("contract.evidence_file_count", 0),
        ("contract.live_evidence_accepted_count", 0),
        ("contract.live_evidence_rejected_count", 0),
        ("coverage.covered_target_count", 0),
        ("coverage.missing_target_count", 4),
        ("intake_replay.accepted_file_count", 0),
        ("intake_replay.rejected_file_count", 0),
        ("intake_replay.missing_required_file_count", 4),
    )


def safety_inputs(inputs: AcceptanceInputs) -> tuple[tuple[str, JsonObject], ...]:
    return (
        ("missing_blocker", inputs.missing_blocker),
        ("readiness_matrix", inputs.readiness_matrix),
        ("acceptance_bundle", inputs.acceptance_bundle),
        ("contract", inputs.contract),
        ("coverage", inputs.coverage),
        ("intake_replay", inputs.intake_replay),
    )


def require_report(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_POST_ARRIVAL_ACCEPTANCE_SUMMARY_USER_ACTION_REQUIRED",
        "status",
    )
    require_text_value(output.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "current_blocker")
    for key, value in output_counts():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("acceptance_ready_now"), False, "acceptance_ready_now")
    require_bool_value(output.get("acceptance_ready_after_required_files"), True, "acceptance_ready_after_required_files")
    require_bool_value(output.get("contract_payload_parse_allowed_now"), False, "contract_payload_parse_allowed_now")
    require_safety_counters("output", output)


def output_counts() -> tuple[tuple[str, int], ...]:
    return (
        ("required_file_count", 4),
        ("present_file_count", 0),
        ("missing_file_count", 4),
        ("accepted_file_count", 0),
        ("rejected_file_count", 0),
        ("pending_file_count", 4),
        ("required_review_item_count_per_payload", 20),
    )


def require_safety_counters(label: str, payload: JsonObject) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_leak")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.path_leak")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Post-Arrival Acceptance Summary",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        f"- status: `{output['status']}`",
        f"- current blocker: `{output['current_blocker']}`",
        f"- acceptance ready now: {output['acceptance_ready_now']}",
        f"- acceptance ready after files: {output['acceptance_ready_after_required_files']}",
        f"- required files: {output['required_file_count']}",
        f"- present files: {output['present_file_count']}",
        f"- missing files: {output['missing_file_count']}",
        f"- pending files: {output['pending_file_count']}",
        f"- required review items per payload: {output['required_review_item_count_per_payload']}",
        f"- required question sequence: `{output['required_question_sequence']}`",
        f"- allowed after files arrive: `{output['allowed_after_files_arrive']}`",
        f"- blocked without separate authorization: `{output['blocked_without_separate_authorization']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
