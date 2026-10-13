# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_example_shape.py

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
from ocr_training_pack_recognized_evidence_contract_core import validate_payload

LAB: Final[Path] = Path(__file__).resolve().parent
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_example_shape.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_example_shape.md"
SENSITIVE_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)


@dataclass(frozen=True, slots=True)
class ExampleShapeInputs:
    test_ids: list[str]


def main() -> int:
    output = example_shape_summary(ExampleShapeInputs(test_ids=target_test_ids(read_json_object(SOURCE_JSON))))
    require_example_shape_summary(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def example_shape_summary(inputs: ExampleShapeInputs) -> JsonObject:
    payloads = [example_payload(test_id) for test_id in inputs.test_ids]
    accepted_count = sum(1 for payload in payloads if validate_payload(payload).accepted)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_EXAMPLE_SHAPE_READY_USER_APPROVAL_REQUIRED",
        "target_count": len(inputs.test_ids),
        "target_test_ids": inputs.test_ids,
        "example_payload_count": len(payloads),
        "example_contract_accepted_count": accepted_count,
        "example_contract_rejected_count": len(payloads) - accepted_count,
        "example_item_count": sum(len(review_items(payload)) for payload in payloads),
        "example_review_required_count": sum(status_count(payload, "review_required") for payload in payloads),
        "example_safe_auto_grade_count": sum(status_count(payload, "safe_auto_grade") for payload in payloads),
        "required_payload_container": "review_payload",
        "required_payload_fields": ["test_id", "round", "problem_count", "items"],
        "required_item_fields": ["question_no", "status", "recognized"],
        "required_question_sequence": "1..20",
        "required_default_status": "review_required",
        "example_file_names": [example_file_name(test_id) for test_id in inputs.test_ids],
        "example_payload_write_attempted": False,
        "evidence_file_write_attempted": False,
        "replacement_allowed_without_user_approval": False,
        "next_status": "USER_APPROVAL_REQUIRED",
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


def target_test_ids(source: JsonObject) -> list[str]:
    require_text_value(
        source.get("status"),
        "TRAINING_PACK_ROUTE_UPLOAD_SOURCES_READY_CACHE_REPLAY_MISSING",
        "source.status",
    )
    targets = source.get("targets")
    if not isinstance(targets, list):
        raise ExtendedGateError("source.targets must be a list")
    return [target_test_id(item) for item in targets]


def target_test_id(value: JsonValue) -> str:
    match value:
        case dict():
            test_id = value.get("test_id")
            if isinstance(test_id, str):
                return test_id
            raise ExtendedGateError("target.test_id must be text")
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError("target must be a mapping")
        case unreachable:
            assert_never(unreachable)


def example_payload(test_id: str) -> JsonObject:
    return {
        "review_payload": {
            "test_id": test_id,
            "round": "1",
            "problem_count": 20,
            "items": [
                {"question_no": question_no, "status": "review_required", "recognized": "<ocr_value>"}
                for question_no in range(1, 21)
            ],
        },
    }


def review_items(payload: JsonObject) -> list[JsonObject]:
    review_payload = payload.get("review_payload")
    items = review_payload.get("items") if isinstance(review_payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def status_count(payload: JsonObject, status: str) -> int:
    return sum(1 for item in review_items(payload) if item.get("status") == status)


def example_file_name(test_id: str) -> str:
    return f"{test_id}_recognized_evidence.json"


def sensitive_leak_count(text: str) -> int:
    return sum(text.count(token) for token in SENSITIVE_TOKENS)


def filesystem_path_leak_count(text: str) -> int:
    return text.count("C:\\") + text.count("C:/") + text.count("/c/")


def require_example_shape_summary(output: JsonObject) -> None:
    require_text_value(
        output.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_EXAMPLE_SHAPE_READY_USER_APPROVAL_REQUIRED",
        "status",
    )
    require_int_value(output.get("target_count"), 4, "target_count")
    require_int_value(output.get("example_payload_count"), 4, "example_payload_count")
    require_int_value(output.get("example_contract_accepted_count"), 4, "example_contract_accepted_count")
    require_int_value(output.get("example_contract_rejected_count"), 0, "example_contract_rejected_count")
    require_int_value(output.get("example_item_count"), 80, "example_item_count")
    require_int_value(output.get("example_review_required_count"), 80, "example_review_required_count")
    require_int_value(output.get("example_safe_auto_grade_count"), 0, "example_safe_auto_grade_count")
    require_bool_value(output.get("example_payload_write_attempted"), False, "example_payload_write_attempted")
    require_bool_value(output.get("evidence_file_write_attempted"), False, "evidence_file_write_attempted")
    require_bool_value(
        output.get("replacement_allowed_without_user_approval"),
        False,
        "replacement_allowed_without_user_approval",
    )
    require_text_value(output.get("next_status"), "USER_APPROVAL_REQUIRED", "next_status")
    require_int_value(output.get("provider_call_count"), 0, "provider_call_count")
    require_int_value(output.get("external_ocr_api_call_count"), 0, "external_ocr_api_call_count")
    require_int_value(output.get("submit_test_call_count"), 0, "submit_test_call_count")
    require_int_value(output.get("ts_submit_click_count"), 0, "ts_submit_click_count")
    require_int_value(output.get("sensitive_field_leak_count"), 0, "sensitive_field_leak_count")
    require_int_value(output.get("filesystem_path_leak_count"), 0, "filesystem_path_leak_count")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Training Pack Recognized Evidence Example Shape",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- status: `{output['status']}`",
        f"- target tests: {output['target_count']}",
        f"- example payloads: {output['example_payload_count']}",
        f"- contract accepted examples: {output['example_contract_accepted_count']}",
        f"- example items: {output['example_item_count']}",
        f"- review-required example items: {output['example_review_required_count']}",
        f"- safe-auto-grade example items: {output['example_safe_auto_grade_count']}",
        f"- required payload container: `{output['required_payload_container']}`",
        f"- required payload fields: {', '.join(str(field) for field in output['required_payload_fields'])}",
        f"- required item fields: {', '.join(str(field) for field in output['required_item_fields'])}",
        f"- write attempted: {output['example_payload_write_attempted']}",
        f"- evidence file write attempted: {output['evidence_file_write_attempted']}",
        f"- replacement allowed without user approval: {output['replacement_allowed_without_user_approval']}",
        f"- next status: `{output['next_status']}`",
        "- sensitive/path leak count: 0",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
