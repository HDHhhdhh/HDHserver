# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_person03_second_pass_live_handoff.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from ocr_provider_free_extended_gate_common import JsonObject, JsonValue, read_json_object, require_int_value

LAB: Final[Path] = Path(__file__).resolve().parent
PERSON_REQUEST_JSON: Final[Path] = LAB / "ocr_person_second_pass_request_manifests.json"
BATCH_REQUEST_JSON: Final[Path] = LAB / "ocr_second_pass_batch_request_manifest.json"
REPORT_JSON: Final[Path] = LAB / "ocr_person03_second_pass_live_handoff.json"
REPORT_MD: Final[Path] = LAB / "ocr_person03_second_pass_live_handoff.md"

REQUIRED_AUTHORIZATION: Final[str] = (
    "person_03의 학생 답안지 사진이 Google/Gemini 외부 provider로 전송된다는 점과 "
    "학생 자료 외부 전송 위험을 이해했다. 로컬 QA 목적의 Gemini OCR provider 호출을 "
    "1회 승인한다. fresh provider call budget은 총 1회다. /api/submit-test는 호출하지 "
    "않는다. #tsSubmit은 클릭하지 않는다. API key/.env는 출력하지 않는다. 기존 "
    "person_03_same_contact recognized/cache는 덮어쓰지 않고 별도 variant/cache 경로를 사용한다."
)


@dataclass(frozen=True, slots=True)
class LiveHandoffError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    person_request = read_json_object(PERSON_REQUEST_JSON)
    batch_request = read_json_object(BATCH_REQUEST_JSON)
    output = summary(person_request, batch_request)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def summary(person_request: JsonObject, batch_request: JsonObject) -> JsonObject:
    require_common_zero_counts(person_request, "person_request")
    require_common_zero_counts(batch_request, "batch_request")
    require_text(person_request.get("status"), "USER_APPROVAL_REQUIRED", "person_request.status")
    require_text(batch_request.get("status"), "USER_APPROVAL_REQUIRED", "batch_request.status")
    require_int_value(person_request.get("request_item_count"), 2, "person_request.request_item_count")
    require_int_value(batch_request.get("batch_item_count"), 2, "batch_request.batch_item_count")
    require_int_value(person_request.get("future_provider_call_budget_required"), 1, "person_request.future_provider_call_budget_required")
    require_int_value(batch_request.get("provider_call_budget_required_for_future_run"), 1, "batch_request.provider_call_budget_required_for_future_run")
    require_int_value(person_request.get("auto_confirm_allowed_count"), 0, "person_request.auto_confirm_allowed_count")
    require_int_value(batch_request.get("auto_confirm_allowed_count"), 0, "batch_request.auto_confirm_allowed_count")
    questions = person_03_questions(person_request)
    return {
        "ok": True,
        "student_facing": False,
        "status": "USER_APPROVAL_REQUIRED",
        "runner_mode": "dry_run_handoff_only",
        "target_case_id": "person_03",
        "request_question_numbers": list(questions),
        "request_item_count": len(questions),
        "required_authorization": REQUIRED_AUTHORIZATION,
        "declared_provider_call_budget_required": 1,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "old_ocr_test_sheet_call_count": 0,
        "production_default": "NO_GO",
        "live_call_allowed_now": False,
        "preflight_file_modified": False,
        "protected_file_modified": False,
        "recognized_cache_overwrite_allowed": False,
        "variant_cache_required": True,
        "auto_confirm_allowed_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def require_common_zero_counts(payload: JsonObject, label: str) -> None:
    if payload.get("ok") is not True:
        raise LiveHandoffError(f"{label}.ok must be true")
    if payload.get("student_facing") is not False:
        raise LiveHandoffError(f"{label}.student_facing must be false")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")


def person_03_questions(report: JsonObject) -> tuple[int, ...]:
    cases = require_array(report.get("cases"), "person_request.cases")
    for raw_case in cases:
        case = require_object(raw_case, "person_request.cases[]")
        if case.get("case_id") == "person_03":
            require_text(case.get("status"), "USER_APPROVAL_REQUIRED", "person_03.status")
            items = require_array(case.get("request_items"), "person_03.request_items")
            questions = tuple(require_question_no(item, "person_03.request_items[]") for item in items)
            if questions != (16, 17):
                raise LiveHandoffError(f"person_03 request questions expected (16, 17), got {questions}")
            return questions
    raise LiveHandoffError("person_03 request case not found")


def require_question_no(value: JsonValue, label: str) -> int:
    item = require_object(value, label)
    question_no = item.get("question_no")
    match question_no:
        case int() if not isinstance(question_no, bool):
            return question_no
        case None | bool() | float() | str() | list() | dict():
            raise LiveHandoffError(f"{label}.question_no must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise LiveHandoffError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise LiveHandoffError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_text(value: JsonValue, expected: str, label: str) -> None:
    match value:
        case str() if value == expected:
            return
        case str():
            raise LiveHandoffError(f"{label} expected {expected}, got {value}")
        case None | bool() | int() | float() | list() | dict():
            raise LiveHandoffError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR person_03 Second-Pass Live Handoff",
        "",
        "- Status: `USER_APPROVAL_REQUIRED`",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- production default: `NO-GO`",
        f"- target case: `{output['target_case_id']}`",
        f"- request questions: {output['request_question_numbers']}",
        f"- declared provider call budget required: {output['declared_provider_call_budget_required']}",
        "- recognized/cache overwrite allowed: false",
        "- variant/cache output required: true",
        "- answer-key/grading/path leak count: 0",
        "",
        "## Required Authorization",
        "",
        str(output["required_authorization"]),
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
