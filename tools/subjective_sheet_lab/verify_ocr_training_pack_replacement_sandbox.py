# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_replacement_sandbox.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_training_pack_replacement_decision import replacement_decision_probes

LAB: Final[Path] = Path(__file__).resolve().parent
READINESS_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_cache_replacement_readiness.json"
CONTRACT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_contract.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_replacement_sandbox.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_replacement_sandbox.md"
SENSITIVE_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)


def main() -> int:
    output = sandbox_summary(read_json_object(READINESS_JSON), read_json_object(CONTRACT_JSON))
    require_sandbox(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def sandbox_summary(readiness: JsonObject, contract: JsonObject) -> JsonObject:
    require_text_value(
        readiness.get("status"),
        "TRAINING_PACK_RECOGNIZED_CACHE_REPLACEMENT_REQUIRES_OCR_EVIDENCE",
        "readiness.status",
    )
    require_bool_value(readiness.get("replacement_allowed"), False, "readiness.replacement_allowed")
    require_text_value(
        contract.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS",
        "contract.status",
    )
    require_bool_value(contract.get("contract_ready"), True, "contract.contract_ready")
    probe_results = replacement_decision_probes()
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_REPLACEMENT_SANDBOX_BLOCKED_BY_MISSING_EVIDENCE",
        "source_assets_ready_count": readiness["source_assets_ready_count"],
        "contract_ready": contract["contract_ready"],
        "contract_evidence_file_count": contract["evidence_file_count"],
        "contract_probe_rejected_count": contract["contract_probe_rejected_count"],
        "safe_auto_grade_status_probe_rejected_count": contract["safe_auto_grade_status_probe_rejected_count"],
        "approved_ocr_evidence_count": readiness["approved_ocr_evidence_count"],
        "replacement_allowed": False,
        "replacement_decision_probe_count": len(probe_results),
        "replacement_decision_allowed_probe_count": sum(1 for value in probe_results if value),
        "replacement_decision_blocked_probe_count": sum(1 for value in probe_results if not value),
        "replacement_attempted": False,
        "replacement_payload_created_count": 0,
        "accuracy_recompute_attempted": False,
        "accuracy_report_created_count": 0,
        "lab_only_variant_write_count": 0,
        "next_status": "USER_APPROVAL_REQUIRED",
        "required_next_artifact": "recognized_cache_payloads_with_nonzero_recognized_values",
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "sensitive_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    text = json.dumps(output, ensure_ascii=False)
    output["sensitive_field_leak_count"] = sensitive_leak_count(text)
    output["filesystem_path_leak_count"] = filesystem_path_leak_count(text)
    return output


def require_sandbox(output: JsonObject) -> None:
    require_int_value(output.get("source_assets_ready_count"), 4, "source_assets_ready_count")
    require_bool_value(output.get("contract_ready"), True, "contract_ready")
    require_int_value(output.get("contract_evidence_file_count"), 0, "contract_evidence_file_count")
    require_int_value(output.get("contract_probe_rejected_count"), 9, "contract_probe_rejected_count")
    require_int_value(
        output.get("safe_auto_grade_status_probe_rejected_count"),
        1,
        "safe_auto_grade_status_probe_rejected_count",
    )
    require_int_value(output.get("approved_ocr_evidence_count"), 0, "approved_ocr_evidence_count")
    require_bool_value(output.get("replacement_allowed"), False, "replacement_allowed")
    require_int_value(output.get("replacement_decision_probe_count"), 5, "replacement_decision_probe_count")
    require_int_value(output.get("replacement_decision_allowed_probe_count"), 1, "replacement_decision_allowed_probe_count")
    require_int_value(output.get("replacement_decision_blocked_probe_count"), 4, "replacement_decision_blocked_probe_count")
    require_bool_value(output.get("replacement_attempted"), False, "replacement_attempted")
    require_int_value(output.get("replacement_payload_created_count"), 0, "replacement_payload_created_count")
    require_bool_value(output.get("accuracy_recompute_attempted"), False, "accuracy_recompute_attempted")
    require_int_value(output.get("accuracy_report_created_count"), 0, "accuracy_report_created_count")
    require_int_value(output.get("lab_only_variant_write_count"), 0, "lab_only_variant_write_count")
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_int_value(output.get("provider_call_count"), 0, "provider_call_count")
    require_int_value(output.get("external_ocr_api_call_count"), 0, "external_ocr_api_call_count")
    require_int_value(output.get("submit_test_call_count"), 0, "submit_test_call_count")
    require_int_value(output.get("ts_submit_click_count"), 0, "ts_submit_click_count")
    require_int_value(output.get("sensitive_field_leak_count"), 0, "sensitive_field_leak_count")
    require_int_value(output.get("filesystem_path_leak_count"), 0, "filesystem_path_leak_count")


def sensitive_leak_count(text: str) -> int:
    return sum(text.count(token) for token in SENSITIVE_TOKENS)


def filesystem_path_leak_count(text: str) -> int:
    return text.count("C:\\") + text.count("C:/") + text.count("/c/")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Replacement Sandbox",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- source assets ready: {output['source_assets_ready_count']}",
        f"- contract ready: {output['contract_ready']}",
        f"- contract evidence files: {output['contract_evidence_file_count']}",
        f"- contract probes rejected: {output['contract_probe_rejected_count']}",
        f"- safe-auto-grade status probes rejected: {output['safe_auto_grade_status_probe_rejected_count']}",
        f"- approved OCR evidence: {output['approved_ocr_evidence_count']}",
        f"- replacement decision probes: {output['replacement_decision_allowed_probe_count']} allowed / "
        f"{output['replacement_decision_blocked_probe_count']} blocked",
        f"- replacement attempted: {output['replacement_attempted']}",
        f"- replacement payloads created: {output['replacement_payload_created_count']}",
        f"- accuracy recompute attempted: {output['accuracy_recompute_attempted']}",
        f"- accuracy reports created: {output['accuracy_report_created_count']}",
        f"- next status: `{output['next_status']}`",
        "- sensitive/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
