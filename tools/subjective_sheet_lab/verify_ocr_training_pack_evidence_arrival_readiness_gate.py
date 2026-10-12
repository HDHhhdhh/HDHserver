# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_evidence_arrival_readiness_gate.py

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
POST_DROPBOX_ACCEPTANCE_JSON: Final[Path] = LAB / "ocr_training_pack_post_dropbox_acceptance_gate.json"
PREVIEW_DIFF_JSON: Final[Path] = LAB / "ocr_training_pack_promotion_preview_diff_gate.json"
PROMOTION_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_promotion_gate.json"
REPLACEMENT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_cache_replacement_readiness.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_readiness_gate.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_evidence_arrival_readiness_gate.md"


@dataclass(frozen=True, slots=True)
class ArrivalInputs:
    acceptance: JsonObject
    preview_diff: JsonObject
    promotion: JsonObject
    replacement: JsonObject


def main() -> int:
    output = arrival_readiness_summary(
        ArrivalInputs(
            acceptance=read_json_object(POST_DROPBOX_ACCEPTANCE_JSON),
            preview_diff=read_json_object(PREVIEW_DIFF_JSON),
            promotion=read_json_object(PROMOTION_JSON),
            replacement=read_json_object(REPLACEMENT_JSON),
        ),
    )
    require_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def arrival_readiness_summary(inputs: ArrivalInputs) -> JsonObject:
    require_inputs(inputs)
    current_blocked_count = sum(
        (
            not bool_value(inputs.acceptance, "acceptance_ready_now"),
            not bool_value(inputs.preview_diff, "current_diff_ready"),
            not bool_value(inputs.promotion, "promotion_allowed"),
            not bool_value(inputs.replacement, "replacement_allowed"),
        ),
    )
    post_file_ready_count = sum(
        (
            bool_value(inputs.acceptance, "acceptance_ready_after_required_files"),
            bool_value(inputs.preview_diff, "post_file_diff_ready"),
            int_value(inputs.promotion, "promotion_probe_ready_count") == 1,
            int_value(inputs.replacement, "readiness_ready_probe_count") == 1,
        ),
    )
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_EVIDENCE_ARRIVAL_READINESS_USER_APPROVAL_REQUIRED",
        "target_count": 4,
        "current_evidence_payload_count": int_value(inputs.preview_diff, "actual_payload_count"),
        "current_missing_payload_count": int_value(inputs.preview_diff, "actual_missing_preview_count"),
        "current_blocked_check_count": current_blocked_count,
        "post_file_ready_check_count": post_file_ready_count,
        "post_file_required_check_count": 4,
        "post_file_arrival_ready": post_file_ready_count == 4,
        "current_arrival_ready": False,
        "promotion_write_attempted": False,
        "replacement_write_attempted": False,
        "accuracy_recompute_attempted": False,
        "next_status": "USER_APPROVAL_REQUIRED",
        "next_safe_action": "collect_four_target_named_contract_valid_recognized_evidence_payloads_with_user_approval",
        "required_next_artifact": "four_target_named_contract_valid_recognized_evidence_payloads",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def require_inputs(inputs: ArrivalInputs) -> None:
    require_text_value(inputs.acceptance.get("status"), "TRAINING_PACK_POST_DROPBOX_ACCEPTANCE_GATE_READY", "acceptance.status")
    require_text_value(
        inputs.preview_diff.get("status"),
        "TRAINING_PACK_PROMOTION_PREVIEW_DIFF_USER_APPROVAL_REQUIRED",
        "preview_diff.status",
    )
    require_text_value(
        inputs.promotion.get("status"),
        "TRAINING_PACK_EVIDENCE_PROMOTION_USER_APPROVAL_REQUIRED",
        "promotion.status",
    )
    require_text_value(
        inputs.replacement.get("status"),
        "TRAINING_PACK_RECOGNIZED_CACHE_REPLACEMENT_REQUIRES_OCR_EVIDENCE",
        "replacement.status",
    )
    require_int_value(inputs.preview_diff.get("actual_payload_count"), 0, "preview_diff.actual_payload_count")
    require_int_value(inputs.preview_diff.get("actual_missing_preview_count"), 4, "preview_diff.actual_missing_preview_count")
    require_bool_value(inputs.acceptance.get("acceptance_ready_now"), False, "acceptance.acceptance_ready_now")
    require_bool_value(inputs.preview_diff.get("current_diff_ready"), False, "preview_diff.current_diff_ready")
    require_bool_value(inputs.promotion.get("promotion_allowed"), False, "promotion.promotion_allowed")
    require_bool_value(inputs.replacement.get("replacement_allowed"), False, "replacement.replacement_allowed")


def int_value(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ExtendedGateError(f"{key} must be an integer")
    return value


def bool_value(payload: JsonObject, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ExtendedGateError(f"{key} must be boolean")
    return value


def require_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_EVIDENCE_ARRIVAL_READINESS_USER_APPROVAL_REQUIRED", "status")
    for key, value in integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("post_file_arrival_ready"), True, "post_file_arrival_ready")
    require_bool_value(output.get("current_arrival_ready"), False, "current_arrival_ready")
    require_bool_value(output.get("promotion_write_attempted"), False, "promotion_write_attempted")
    require_bool_value(output.get("replacement_write_attempted"), False, "replacement_write_attempted")
    require_bool_value(output.get("accuracy_recompute_attempted"), False, "accuracy_recompute_attempted")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_text_value(
        output.get("next_safe_action"),
        "collect_four_target_named_contract_valid_recognized_evidence_payloads_with_user_approval",
        "next_safe_action",
    )


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4),
        ("current_evidence_payload_count", 0),
        ("current_missing_payload_count", 4),
        ("current_blocked_check_count", 4),
        ("post_file_ready_check_count", 4),
        ("post_file_required_check_count", 4),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Evidence Arrival Readiness Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- submit route calls: 0",
        "- submit button clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- target payloads: {output['target_count']}",
        f"- current evidence payloads: {output['current_evidence_payload_count']}",
        f"- current missing payloads: {output['current_missing_payload_count']}",
        f"- current blocked checks: {output['current_blocked_check_count']}",
        f"- post-file ready checks: {output['post_file_ready_check_count']} / {output['post_file_required_check_count']}",
        f"- post-file arrival ready: {output['post_file_arrival_ready']}",
        f"- current arrival ready: {output['current_arrival_ready']}",
        f"- promotion write attempted: {output['promotion_write_attempted']}",
        f"- replacement write attempted: {output['replacement_write_attempted']}",
        f"- accuracy recompute attempted: {output['accuracy_recompute_attempted']}",
        f"- next status: `{output['next_status']}`",
        f"- next safe action: `{output['next_safe_action']}`",
        "- answer-key/grading/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
