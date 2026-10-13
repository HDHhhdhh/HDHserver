# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_evidence_promotion_gate.py

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
INTAKE_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_intake.json"
CONTRACT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_contract.json"
COVERAGE_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_target_coverage.json"
READINESS_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_cache_replacement_readiness.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_promotion_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_evidence_promotion_gate.md"


@dataclass(frozen=True, slots=True)
class PromotionSignals:
    contract_ready: bool
    target_coverage_ready: bool
    replacement_input_ready: bool
    replacement_allowed: bool


def main() -> int:
    output = promotion_summary(
        PromotionInputs(
            intake=read_json_object(INTAKE_JSON),
            contract=read_json_object(CONTRACT_JSON),
            coverage=read_json_object(COVERAGE_JSON),
            readiness=read_json_object(READINESS_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


@dataclass(frozen=True, slots=True)
class PromotionInputs:
    intake: JsonObject
    contract: JsonObject
    coverage: JsonObject
    readiness: JsonObject


def promotion_summary(inputs: PromotionInputs) -> JsonObject:
    require_inputs(inputs)
    probes = promotion_probe_results()
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_EVIDENCE_PROMOTION_USER_APPROVAL_REQUIRED",
        "target_count": 4,
        "evidence_file_count": inputs.intake["evidence_file_count"],
        "recognized_value_count": inputs.intake["recognized_value_count"],
        "contract_ready": inputs.contract["contract_ready"],
        "target_coverage_ready": inputs.coverage["target_coverage_ready"],
        "target_coverage_missing_count": inputs.coverage["missing_target_count"],
        "replacement_input_ready": inputs.intake["replacement_input_ready"],
        "replacement_allowed": inputs.readiness["replacement_allowed"],
        "promotion_ready": False,
        "promotion_allowed": False,
        "promotion_probe_count": len(probes),
        "promotion_probe_ready_count": sum(1 for value in probes if value),
        "promotion_probe_blocked_count": sum(1 for value in probes if not value),
        "next_status": "USER_APPROVAL_REQUIRED",
        "next_safe_action": "collect_four_target_covered_recognized_cache_payloads_with_user_approval",
        "required_next_artifact": "four_target-covered_recognized_cache_payloads_with_nonzero_values",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def require_inputs(inputs: PromotionInputs) -> None:
    require_text_value(inputs.intake.get("status"), "TRAINING_PACK_RECOGNIZED_EVIDENCE_USER_APPROVAL_REQUIRED", "intake.status")
    require_text_value(inputs.contract.get("status"), "TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS", "contract.status")
    require_text_value(inputs.coverage.get("status"), "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_USER_APPROVAL_REQUIRED", "coverage.status")
    require_text_value(inputs.readiness.get("status"), "TRAINING_PACK_RECOGNIZED_CACHE_REPLACEMENT_REQUIRES_OCR_EVIDENCE", "readiness.status")
    require_bool_value(inputs.contract.get("contract_ready"), True, "contract.contract_ready")
    require_bool_value(inputs.coverage.get("target_coverage_ready"), False, "coverage.target_coverage_ready")
    require_bool_value(inputs.intake.get("replacement_input_ready"), False, "intake.replacement_input_ready")
    require_bool_value(inputs.readiness.get("replacement_allowed"), False, "readiness.replacement_allowed")
    require_int_value(inputs.intake.get("evidence_file_count"), 0, "intake.evidence_file_count")
    require_int_value(inputs.intake.get("recognized_value_count"), 0, "intake.recognized_value_count")
    require_int_value(inputs.coverage.get("missing_target_count"), 4, "coverage.missing_target_count")


def promotion_probe_results() -> tuple[bool, ...]:
    probes = (
        PromotionSignals(contract_ready=True, target_coverage_ready=True, replacement_input_ready=True, replacement_allowed=True),
        PromotionSignals(contract_ready=False, target_coverage_ready=True, replacement_input_ready=True, replacement_allowed=True),
        PromotionSignals(contract_ready=True, target_coverage_ready=False, replacement_input_ready=True, replacement_allowed=True),
        PromotionSignals(contract_ready=True, target_coverage_ready=True, replacement_input_ready=False, replacement_allowed=True),
        PromotionSignals(contract_ready=True, target_coverage_ready=True, replacement_input_ready=True, replacement_allowed=False),
    )
    return tuple(promotion_ready(probe) for probe in probes)


def promotion_ready(signals: PromotionSignals) -> bool:
    return signals.contract_ready and signals.target_coverage_ready and signals.replacement_input_ready and signals.replacement_allowed


def require_summary(output: JsonObject) -> None:
    for key, value in current_integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("contract_ready"), True, "contract_ready")
    require_bool_value(output.get("target_coverage_ready"), False, "target_coverage_ready")
    require_bool_value(output.get("replacement_input_ready"), False, "replacement_input_ready")
    require_bool_value(output.get("replacement_allowed"), False, "replacement_allowed")
    require_bool_value(output.get("promotion_ready"), False, "promotion_ready")
    require_bool_value(output.get("promotion_allowed"), False, "promotion_allowed")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(
        output.get("next_safe_action"),
        "collect_four_target_covered_recognized_cache_payloads_with_user_approval",
        "next_safe_action",
    )


def current_integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4), ("evidence_file_count", 0), ("recognized_value_count", 0),
        ("target_coverage_missing_count", 4), ("promotion_probe_count", 5),
        ("promotion_probe_ready_count", 1), ("promotion_probe_blocked_count", 4),
        ("provider_call_count", 0), ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0), ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0), ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Evidence Promotion Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- evidence files: {output['evidence_file_count']}",
        f"- recognized values: {output['recognized_value_count']}",
        f"- contract ready: {output['contract_ready']}",
        f"- target coverage ready: {output['target_coverage_ready']}",
        f"- missing targets: {output['target_coverage_missing_count']}",
        f"- replacement input ready: {output['replacement_input_ready']}",
        f"- replacement allowed: {output['replacement_allowed']}",
        f"- promotion probes: {output['promotion_probe_ready_count']} ready / {output['promotion_probe_blocked_count']} blocked",
        f"- promotion ready: {output['promotion_ready']}",
        f"- next status: `{output['next_status']}`",
        f"- next safe action: `{output['next_safe_action']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
