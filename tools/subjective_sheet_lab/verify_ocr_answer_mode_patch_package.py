from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

DRAFT_PATH: Final[Path] = Path(__file__).with_name("ocr_answer_mode_draft_targets.json")
PATCH_PATH: Final[Path] = Path(__file__).with_name("ocr_answer_mode_runtime_wiring_proposed.patch")
REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_answer_mode_patch_package_verification.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_answer_mode_patch_package_verification.md")
PREFLIGHT_CHECK_NAME: Final[str] = "ocr_draft_answer_mode_combined_policy"

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

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
    "gemini_outputs",
)


@dataclass(frozen=True, slots=True)
class ModeMapping:
    test_id: str
    choice: tuple[int, ...]
    value: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PatchPackageError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    draft = require_object(load_json(DRAFT_PATH), "draft")
    patch_text = read_patch()
    rows = draft_mappings(draft)
    verify_patch(rows, patch_text)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "target_count": len(rows),
        "server_mapping_target_count": len(rows),
        "ui_mapping_target_count": len(rows),
        "preflight_check_present": True,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "runtime_files_modified_by_this_check": False,
        "targets": [row.test_id for row in rows],
    }
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def load_json(path: Path) -> JsonValue:
    if not path.is_file():
        raise PatchPackageError(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_patch() -> str:
    if not PATCH_PATH.is_file():
        raise PatchPackageError(f"missing file: {PATCH_PATH}")
    text = PATCH_PATH.read_text(encoding="utf-8")
    assert_no_forbidden_fields(text)
    assert_no_student_facing_paths(text)
    return text


def draft_mappings(draft: JsonObject) -> tuple[ModeMapping, ...]:
    if draft.get("student_facing") is not False:
        raise PatchPackageError("draft.student_facing must be false")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        if draft.get(key) != 0:
            raise PatchPackageError(f"draft.{key} must be 0")
    if draft.get("production_default") != "NO_GO":
        raise PatchPackageError("draft.production_default must be NO_GO")
    tests = require_array(draft.get("tests"), "draft.tests")
    rows = tuple(draft_mapping(require_object(raw, f"draft.tests[{index}]")) for index, raw in enumerate(tests))
    if len(rows) != 5:
        raise PatchPackageError(f"expected 5 draft targets, got {len(rows)}")
    return rows


def draft_mapping(test: JsonObject) -> ModeMapping:
    test_id = require_string(test.get("test_id"), "test_id")
    choice = require_question_tuple(test.get("choice_number_questions"), f"{test_id}.choice_number_questions")
    value = require_question_tuple(test.get("answer_value_questions"), f"{test_id}.answer_value_questions")
    audit = require_question_tuple(test.get("needs_visual_mode_audit_questions"), f"{test_id}.needs_visual_mode_audit_questions")
    if audit:
        raise PatchPackageError(f"{test_id} still has visual-audit questions")
    verify_partition(test_id, choice, value)
    return ModeMapping(test_id=test_id, choice=choice, value=value)


def verify_patch(rows: tuple[ModeMapping, ...], patch_text: str) -> None:
    for row in rows:
        if row.test_id not in patch_text:
            raise PatchPackageError(f"missing patch target: {row.test_id}")
        for snippet in server_snippets(row) + ui_snippets(row):
            if snippet not in patch_text:
                raise PatchPackageError(f"missing patch snippet for {row.test_id}: {snippet}")
    if PREFLIGHT_CHECK_NAME not in patch_text:
        raise PatchPackageError(f"missing preflight check proposal: {PREFLIGHT_CHECK_NAME}")


def server_snippets(row: ModeMapping) -> tuple[str, str]:
    return (
        f'"choice_number": {server_frozenset(row.choice)},',
        f'"answer_value": {server_frozenset(row.value)},',
    )


def ui_snippets(row: ModeMapping) -> tuple[str, str]:
    return (
        f"choice_number: {js_set(row.choice)},",
        f"answer_value: {js_set(row.value)},",
    )


def server_frozenset(values: tuple[int, ...]) -> str:
    if not values:
        return "frozenset()"
    if values == tuple(range(1, 21)):
        return "frozenset(range(1, 21))"
    return f"frozenset(({number_list(values)}))"


def js_set(values: tuple[int, ...]) -> str:
    return f"new Set([{number_list(values)}])"


def number_list(values: tuple[int, ...]) -> str:
    return ", ".join(str(value) for value in values)


def verify_partition(test_id: str, choice: tuple[int, ...], value: tuple[int, ...]) -> None:
    questions = choice + value
    if len(questions) != 20:
        raise PatchPackageError(f"{test_id} must classify exactly 20 questions")
    if set(questions) != set(range(1, 21)):
        raise PatchPackageError(f"{test_id} must cover q001-q020")


def assert_no_forbidden_fields(text: str) -> None:
    leaked = [field for field in FORBIDDEN_FIELDS if field in text]
    if leaked:
        raise PatchPackageError(f"forbidden answer/grading field leaked in patch: {leaked}")


def assert_no_student_facing_paths(text: str) -> None:
    leaked = [token for token in LOCAL_PATH_TOKENS if token in text]
    if leaked:
        raise PatchPackageError(f"local filesystem path token leaked in patch: {leaked}")


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise PatchPackageError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_array(value: JsonValue, label: str) -> list[JsonValue]:
    match value:
        case list():
            return value
        case None | bool() | int() | float() | str() | dict():
            raise PatchPackageError(f"{label} must be a JSON array")
        case unreachable:
            assert_never(unreachable)


def require_string(value: JsonValue, label: str) -> str:
    match value:
        case str():
            return value
        case None | bool() | int() | float() | list() | dict():
            raise PatchPackageError(f"{label} must be a string")
        case unreachable:
            assert_never(unreachable)


def require_question_tuple(value: JsonValue, label: str) -> tuple[int, ...]:
    raw_values = require_array(value, label)
    questions: list[int] = []
    for index, raw_value in enumerate(raw_values):
        match raw_value:
            case int() if not isinstance(raw_value, bool) and 1 <= raw_value <= 20:
                questions.append(raw_value)
            case None | bool() | int() | float() | str() | list() | dict():
                raise PatchPackageError(f"{label}[{index}] must be q001-q020 integer")
            case unreachable:
                assert_never(unreachable)
    return tuple(questions)


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Answer Mode Patch Package Verification",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- patch targets verified: {output['target_count']}",
        "- server mapping snippets match draft targets",
        "- hidden OCR UI mapping snippets match draft targets",
        "- preflight proposal is present",
        "- answer-key/grading/path leak count: 0",
        "",
        "This verifies only the non-applied patch package. It does not modify runtime files.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
