from __future__ import annotations

import json
from typing import Final, TypeAlias, assert_never

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

TARGET_IDS: Final[tuple[str, ...]] = (
    "t_unit_mijeok1_01_lv3_r1",
    "t_training_pack_mijeok1_non_frequent_r1",
    "t_training_pack_mijeok1_non_frequent_r2",
    "t_training_pack_gongsu2_non_frequent_r1",
    "t_training_pack_gongsu2_non_frequent_r2",
)
ALLOWED_STATUSES: Final[frozenset[str]] = frozenset(
    (
        "needs_visual_mode_audit",
        "draft_all_choice_number_candidate",
        "draft_mixed_mode_candidate",
    )
)
FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    (
        "answerKey",
        "answerKeys",
        "expected",
        "expected_answer",
        "canonical_answer",
        "accepted_answers",
        "correct",
        "incorrect",
        "score",
        "grading",
        "grade",
        "wrong",
        "pct",
    )
)
LOCAL_PATH_TOKENS: Final[tuple[str, ...]] = (
    "C:\\",
    "C:/",
    "\\server-ocr\\",
    "/server-ocr/",
    "crop_benchmark_inputs",
    "phase2c_route_uploads",
    "gemini_outputs",
)


class AnswerModeDraftVerificationError(Exception):
    pass


def verify_draft(draft: JsonObject, tests_config_text: str) -> JsonObject:
    verify_safety_metadata(draft)
    assert_no_forbidden_fields(draft)
    assert_no_student_facing_paths(draft)
    tests = require_array(draft.get("tests"), "tests")
    rows = [_verify_test(require_object(raw_test, f"tests[{index}]"), tests_config_text) for index, raw_test in enumerate(tests)]
    seen = {str(row["test_id"]) for row in rows}
    missing = [test_id for test_id in TARGET_IDS if test_id not in seen]
    unexpected = sorted(seen.difference(TARGET_IDS))
    if missing or unexpected:
        raise AnswerModeDraftVerificationError(f"target mismatch missing={missing} unexpected={unexpected}")

    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "target_count": len(rows),
        "fully_classified_draft_count": sum(1 for row in rows if row["needs_visual_mode_audit_count"] == 0),
        "needs_visual_mode_audit_count": sum(1 for row in rows if row["needs_visual_mode_audit_count"] != 0),
        "ready_for_runtime_integration_count": sum(1 for row in rows if row["ready_for_runtime_integration"] is True),
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "tests": rows,
    }


def verify_safety_metadata(draft: JsonObject) -> None:
    required_zero_counts = (
        "provider_call_count",
        "external_ocr_api_call_count",
        "submit_test_call_count",
        "ts_submit_click_count",
    )
    for key in required_zero_counts:
        if draft.get(key) != 0:
            raise AnswerModeDraftVerificationError(f"{key} must be 0")
    if draft.get("student_facing") is not False:
        raise AnswerModeDraftVerificationError("student_facing must be false")
    if draft.get("production_default") != "NO_GO":
        raise AnswerModeDraftVerificationError("production_default must stay NO_GO")


def _verify_test(test: JsonObject, tests_config_text: str) -> JsonObject:
    test_id = require_string(test.get("test_id"), "test_id")
    if test_id not in TARGET_IDS:
        raise AnswerModeDraftVerificationError(f"unexpected test_id: {test_id}")
    if f'"id": "{test_id}"' not in tests_config_text:
        raise AnswerModeDraftVerificationError(f"test_id not found in tests-config.json: {test_id}")

    question_count = require_int(test.get("question_count"), f"{test_id}.question_count")
    if question_count != 20:
        raise AnswerModeDraftVerificationError(f"{test_id} question_count must be 20")
    status = require_string(test.get("status"), f"{test_id}.status")
    if status not in ALLOWED_STATUSES:
        raise AnswerModeDraftVerificationError(f"{test_id} invalid status: {status}")
    ready = test.get("ready_for_runtime_integration")
    if not isinstance(ready, bool):
        raise AnswerModeDraftVerificationError(f"{test_id}.ready_for_runtime_integration must be boolean")

    choice = _question_list(test, "choice_number_questions")
    value = _question_list(test, "answer_value_questions")
    audit = _question_list(test, "needs_visual_mode_audit_questions")
    _verify_question_partition(test_id, choice, value, audit)
    if ready:
        raise AnswerModeDraftVerificationError(f"{test_id} draft must not be runtime-ready yet")
    if status == "needs_visual_mode_audit" and not audit:
        raise AnswerModeDraftVerificationError(f"{test_id} status requires needs_visual_mode_audit questions")

    return {
        "test_id": test_id,
        "category": require_string(test.get("category"), f"{test_id}.category"),
        "round": require_int(test.get("round"), f"{test_id}.round"),
        "status": status,
        "confidence": require_string(test.get("confidence"), f"{test_id}.confidence"),
        "ready_for_runtime_integration": ready,
        "choice_number_count": len(choice),
        "answer_value_count": len(value),
        "needs_visual_mode_audit_count": len(audit),
        "question_coverage_count": len(set(choice + value + audit)),
    }


def _question_list(test: JsonObject, key: str) -> list[int]:
    raw_questions = require_array(test.get(key), key)
    questions: list[int] = []
    for index, raw_question in enumerate(raw_questions):
        question_no = require_int(raw_question, f"{key}[{index}]")
        if question_no < 1 or question_no > 20:
            raise AnswerModeDraftVerificationError(f"{key}[{index}] out of range: {question_no}")
        questions.append(question_no)
    if len(set(questions)) != len(questions):
        raise AnswerModeDraftVerificationError(f"{key} has duplicate question numbers")
    return questions


def _verify_question_partition(test_id: str, choice: list[int], value: list[int], audit: list[int]) -> None:
    all_questions = choice + value + audit
    if len(all_questions) != 20:
        raise AnswerModeDraftVerificationError(f"{test_id} must classify or audit exactly 20 questions")
    if len(set(all_questions)) != 20:
        raise AnswerModeDraftVerificationError(f"{test_id} question lists overlap")
    if set(all_questions) != set(range(1, 21)):
        raise AnswerModeDraftVerificationError(f"{test_id} must cover questions 1..20")


def assert_no_forbidden_fields(value: JsonValue, path: str = "$") -> None:
    match value:
        case dict():
            for key, child in value.items():
                if key in FORBIDDEN_FIELDS:
                    raise AnswerModeDraftVerificationError(f"forbidden answer/grading field at {path}.{key}")
                assert_no_forbidden_fields(child, f"{path}.{key}")
        case list():
            for index, child in enumerate(value):
                assert_no_forbidden_fields(child, f"{path}[{index}]")
        case None | bool() | int() | float() | str():
            return
        case unreachable:
            assert_never(unreachable)


def assert_no_student_facing_paths(value: JsonValue) -> None:
    text = json.dumps(value, ensure_ascii=False)
    leaked_tokens = [token for token in LOCAL_PATH_TOKENS if token in text]
    if leaked_tokens:
        raise AnswerModeDraftVerificationError(f"local path token leaked: {leaked_tokens}")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Answer Mode Draft Target Verification",
        "",
        "- Gemini/API calls: 0",
        "- external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- target count: {output['target_count']}",
        f"- fully classified draft count: {output['fully_classified_draft_count']}",
        f"- still needing visual mode audit: {output['needs_visual_mode_audit_count']}",
        f"- runtime-ready draft count: {output['ready_for_runtime_integration_count']}",
        "- answer-key/grading field leak count: 0",
        "- filesystem path leak count: 0",
        "",
        "## Targets",
        "",
        "| test_id | status | confidence | choice | answer_value | visual_audit | runtime_ready |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for raw_row in require_array(output.get("tests"), "output.tests"):
        row = require_object(raw_row, "output.tests[]")
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{row['test_id']}`",
                    str(row["status"]),
                    str(row["confidence"]),
                    str(row["choice_number_count"]),
                    str(row["answer_value_count"]),
                    str(row["needs_visual_mode_audit_count"]),
                    str(row["ready_for_runtime_integration"]),
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## Notes",
            "",
            "- This is a lab-only draft check, not runtime integration.",
            "- All five targets are fully classified as draft answer-mode candidates.",
            "- All targets remain blocked from runtime use until a separate review approves wiring.",
        )
    )
    return "\n".join(lines) + "\n"


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise AnswerModeDraftVerificationError(f"{label} must be a JSON object")
    return value


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise AnswerModeDraftVerificationError(f"{label} must be a JSON array")
    return value


def require_string(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise AnswerModeDraftVerificationError(f"{label} must be a string")
    return value


def require_int(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnswerModeDraftVerificationError(f"{label} must be an integer")
    return value
