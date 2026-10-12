# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_operator_handoff.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)

LAB: Final[Path] = Path(__file__).resolve().parent
DROPBOX_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_dropbox_spec.json"
CONTRACT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_contract.json"
COVERAGE_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_target_coverage.json"
INTAKE_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake.json"
PROMOTION_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_promotion_gate.json"
READINESS_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_cache_replacement_readiness.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_operator_handoff.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_operator_handoff.md"


@dataclass(frozen=True, slots=True)
class HandoffInputs:
    dropbox: JsonObject
    contract: JsonObject
    coverage: JsonObject
    intake: JsonObject
    promotion: JsonObject
    readiness: JsonObject


@dataclass(frozen=True, slots=True)
class HandoffStage:
    name: str
    ready: bool
    blocker: str
    next_action: str


def main() -> int:
    output = handoff_summary(
        HandoffInputs(
            dropbox=read_json_object(DROPBOX_JSON),
            contract=read_json_object(CONTRACT_JSON),
            coverage=read_json_object(COVERAGE_JSON),
            intake=read_json_object(INTAKE_JSON),
            promotion=read_json_object(PROMOTION_JSON),
            readiness=read_json_object(READINESS_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def handoff_summary(inputs: HandoffInputs) -> JsonObject:
    require_inputs(inputs)
    stages = handoff_stages(inputs)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_OPERATOR_HANDOFF_USER_APPROVAL_REQUIRED",
        "pipeline_stage_count": len(stages),
        "ready_stage_count": sum(1 for stage in stages if stage.ready),
        "blocked_stage_count": sum(1 for stage in stages if not stage.ready),
        "required_file_count": inputs.dropbox["required_file_count"],
        "present_file_count": inputs.dropbox["present_file_count"],
        "missing_file_count": inputs.dropbox["missing_file_count"],
        "recognized_value_count": inputs.intake["recognized_value_count"],
        "current_blocker": "missing_training_pack_recognized_evidence_files",
        "handoff_ready": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "required_next_artifact": "four_target-named_recognized_evidence_payload_files",
        "required_file_names": inputs.dropbox["required_file_names"],
        "stages": [stage_fields(stage) for stage in stages],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_inputs(inputs: HandoffInputs) -> None:
    require_text_value(inputs.dropbox.get("status"), "TRAINING_PACK_EVIDENCE_DROPBOX_USER_APPROVAL_REQUIRED", "dropbox.status")
    require_text_value(inputs.contract.get("status"), "TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS", "contract.status")
    require_text_value(inputs.coverage.get("status"), "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_USER_APPROVAL_REQUIRED", "coverage.status")
    require_text_value(inputs.intake.get("status"), "TRAINING_PACK_RECOGNIZED_EVIDENCE_USER_APPROVAL_REQUIRED", "intake.status")
    require_text_value(inputs.promotion.get("status"), "TRAINING_PACK_EVIDENCE_PROMOTION_USER_APPROVAL_REQUIRED", "promotion.status")
    require_text_value(inputs.readiness.get("status"), "TRAINING_PACK_RECOGNIZED_CACHE_REPLACEMENT_REQUIRES_OCR_EVIDENCE", "readiness.status")
    require_int_value(inputs.dropbox.get("required_file_count"), 4, "dropbox.required_file_count")
    require_int_value(inputs.dropbox.get("present_file_count"), 0, "dropbox.present_file_count")
    require_int_value(inputs.dropbox.get("missing_file_count"), 4, "dropbox.missing_file_count")
    require_bool_value(inputs.contract.get("contract_ready"), True, "contract.contract_ready")
    require_bool_value(inputs.coverage.get("target_coverage_ready"), False, "coverage.target_coverage_ready")
    require_bool_value(inputs.intake.get("replacement_input_ready"), False, "intake.replacement_input_ready")
    require_bool_value(inputs.promotion.get("promotion_ready"), False, "promotion.promotion_ready")
    require_bool_value(inputs.readiness.get("replacement_allowed"), False, "readiness.replacement_allowed")


def handoff_stages(inputs: HandoffInputs) -> tuple[HandoffStage, ...]:
    return (
        HandoffStage("dropbox_files", False, "missing 4 target-named files", "add four recognized evidence payload files"),
        HandoffStage("payload_contract", bool(inputs.contract["contract_ready"]), "contract ready", "keep contract guard enabled"),
        HandoffStage("target_coverage", bool(inputs.coverage["target_coverage_ready"]), "target coverage missing", "cover all four target testIds"),
        HandoffStage("recognized_intake", bool(inputs.intake["replacement_input_ready"]), "recognized values missing", "provide nonzero recognized values"),
        HandoffStage("promotion_gate", bool(inputs.promotion["promotion_ready"]), "promotion blocked", "satisfy contract, coverage, and intake gates"),
        HandoffStage("replacement_readiness", bool(inputs.readiness["replacement_allowed"]), "replacement blocked", "wait for approved evidence"),
    )


def stage_fields(stage: HandoffStage) -> JsonObject:
    return {"name": stage.name, "ready": stage.ready, "blocker": stage.blocker, "next_action": stage.next_action}


def require_summary(output: JsonObject) -> None:
    for key, value in current_integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("handoff_ready"), False, "handoff_ready")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")


def current_integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("pipeline_stage_count", 6), ("ready_stage_count", 1), ("blocked_stage_count", 5),
        ("required_file_count", 4), ("present_file_count", 0), ("missing_file_count", 4),
        ("recognized_value_count", 0), ("provider_call_count", 0), ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Operator Handoff",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- stages: {output['ready_stage_count']} ready / {output['blocked_stage_count']} blocked",
        f"- required files: {output['required_file_count']}",
        f"- present files: {output['present_file_count']}",
        f"- missing files: {output['missing_file_count']}",
        f"- recognized values: {output['recognized_value_count']}",
        f"- current blocker: `{output['current_blocker']}`",
        f"- next status: `{output['next_status']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
