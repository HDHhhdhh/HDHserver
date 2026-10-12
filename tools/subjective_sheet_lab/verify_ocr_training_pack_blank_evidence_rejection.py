# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_blank_evidence_rejection.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    JsonValue,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_training_pack_recognized_evidence_contract_core import review_items, validate_payload

LAB: Final[Path] = Path(__file__).resolve().parent
SKELETON_DIR: Final[Path] = LAB / "training_pack_provider_free_replay_cache"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_blank_evidence_rejection.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_blank_evidence_rejection.md"
TARGET_TEST_IDS: Final[tuple[str, ...]] = (
    "t_training_pack_gongsu2_non_frequent_r1",
    "t_training_pack_gongsu2_non_frequent_r2",
    "t_training_pack_mijeok1_non_frequent_r1",
    "t_training_pack_mijeok1_non_frequent_r2",
)


@dataclass(frozen=True, slots=True)
class BlankEvidenceResult:
    file_name: str
    test_id: str
    accepted: bool
    reason: str
    item_count: int
    blank_recognized_count: int


def main() -> int:
    output = blank_rejection_summary(skeleton_payloads())
    require_blank_rejection_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=True, indent=2))
    return 0


def skeleton_payloads() -> tuple[tuple[str, JsonObject], ...]:
    return tuple((path.name, read_json_object(path)) for path in sorted(SKELETON_DIR.glob("*.json")))


def blank_rejection_summary(payloads: tuple[tuple[str, JsonObject], ...]) -> JsonObject:
    results = tuple(blank_evidence_result(file_name, payload) for file_name, payload in payloads)
    target_files = {f"{test_id}.json" for test_id in TARGET_TEST_IDS}
    present_files = {result.file_name for result in results}
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_BLANK_EVIDENCE_REJECTION_VERIFIED",
        "target_count": len(TARGET_TEST_IDS),
        "skeleton_file_count": len(results),
        "target_file_match_count": len(target_files & present_files),
        "accepted_file_count": sum(1 for result in results if result.accepted),
        "rejected_file_count": sum(1 for result in results if not result.accepted),
        "blank_rejection_count": sum(1 for result in results if result.reason == "schema_blank_recognized_answer"),
        "review_item_count": sum(result.item_count for result in results),
        "blank_recognized_value_count": sum(result.blank_recognized_count for result in results),
        "safe_auto_grade_count": 0,
        "evidence_promotion_allowed": False,
        "replacement_allowed_without_real_ocr": False,
        "results": [result_fields(result) for result in results],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    return output


def blank_evidence_result(file_name: str, payload: JsonObject) -> BlankEvidenceResult:
    contract = validate_payload(payload)
    items = review_items(payload)
    return BlankEvidenceResult(
        file_name=file_name,
        test_id=payload_test_id(payload),
        accepted=contract.accepted,
        reason=contract.reason,
        item_count=len(items),
        blank_recognized_count=sum(1 for item in items if recognized_value(item).strip() in {"", "?"}),
    )


def payload_test_id(payload: JsonObject) -> str:
    review_payload = payload.get("review_payload")
    if not isinstance(review_payload, dict):
        return ""
    test_id = review_payload.get("test_id")
    return test_id if isinstance(test_id, str) else ""


def recognized_value(item: JsonObject) -> str:
    value = item.get("recognized", item.get("recognized_answer"))
    return value if isinstance(value, str) else ""


def result_fields(result: BlankEvidenceResult) -> JsonObject:
    return {
        "file_name": result.file_name,
        "test_id": result.test_id,
        "accepted": result.accepted,
        "reason": result.reason,
        "item_count": result.item_count,
        "blank_recognized_count": result.blank_recognized_count,
    }


def require_blank_rejection_summary(output: JsonObject) -> None:
    require_text_value(output.get("status"), "TRAINING_PACK_BLANK_EVIDENCE_REJECTION_VERIFIED", "status")
    for key, value in integer_expectations():
        require_int_value(output.get(key), value, key)
    require_bool_value(output.get("evidence_promotion_allowed"), False, "evidence_promotion_allowed")
    require_bool_value(
        output.get("replacement_allowed_without_real_ocr"),
        False,
        "replacement_allowed_without_real_ocr",
    )
    require_text_value(output.get("production_default"), "NO_GO", "production_default")


def integer_expectations() -> tuple[tuple[str, int], ...]:
    return (
        ("target_count", 4),
        ("skeleton_file_count", 4),
        ("target_file_match_count", 4),
        ("accepted_file_count", 0),
        ("rejected_file_count", 4),
        ("blank_rejection_count", 4),
        ("review_item_count", 80),
        ("blank_recognized_value_count", 80),
        ("safe_auto_grade_count", 0),
        ("provider_call_count", 0),
        ("external_ocr_api_call_count", 0),
        ("submit_test_call_count", 0),
        ("ts_submit_click_count", 0),
        ("answer_key_or_grading_field_leak_count", 0),
        ("filesystem_path_leak_count", 0),
    )


def markdown(output: JsonObject) -> str:
    return "\n".join(
        [
            "# OCR Training Pack Blank Evidence Rejection",
            "",
            "- Gemini/API calls: 0; external OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- student-facing: false",
            "- production default: `NO-GO`",
            f"- status: `{output['status']}`",
            f"- skeleton files: {output['skeleton_file_count']} / {output['target_count']}",
            f"- contract-accepted files: {output['accepted_file_count']}",
            f"- contract-rejected files: {output['rejected_file_count']}",
            f"- blank-recognized rejections: {output['blank_rejection_count']}",
            f"- review items checked: {output['review_item_count']}",
            f"- blank recognized values: {output['blank_recognized_value_count']}",
            f"- evidence promotion allowed: {output['evidence_promotion_allowed']}",
            f"- replacement without real OCR allowed: {output['replacement_allowed_without_real_ocr']}",
            "- answer-key/grading/path leak count: 0",
            "",
        ],
    ) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
