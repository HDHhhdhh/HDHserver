from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias


JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
QUESTION_COUNT: Final[int] = 20
WARNING_CODE: Final[str] = "overwritten_answer"
ROOT_KEYS: Final[frozenset[str]] = frozenset(
    (
        "schema_version",
        "ok",
        "student_facing",
        "items",
        "provider_call_count",
        "external_ocr_api_call_count",
        "submit_test_call_count",
        "ts_submit_click_count",
        "answer_key_or_grading_field_leak_count",
        "filesystem_path_leak_count",
        "production_default",
    )
)
ITEM_KEYS: Final[frozenset[str]] = frozenset(("question_no", "warnings"))
ZERO_COUNTER_FIELDS: Final[tuple[str, ...]] = (
    "provider_call_count",
    "external_ocr_api_call_count",
    "submit_test_call_count",
    "ts_submit_click_count",
    "answer_key_or_grading_field_leak_count",
    "filesystem_path_leak_count",
)


@dataclass(frozen=True, slots=True)
class OverwrittenAmbiguityArtifactError(Exception):
    detail: str

    def __str__(self) -> str:
        return self.detail


def load_overwritten_ambiguity_warnings(path: Path | None) -> dict[int, tuple[str, ...]]:
    if path is None:
        return {}
    payload = read_json(path)
    return parse_warning_map(payload)


def ensure_overwritten_ambiguity_artifact(path: Path) -> None:
    load_overwritten_ambiguity_warnings(path)


def read_json(path: Path) -> JsonObject:
    if not path.is_file():
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact is invalid") from exc
    if not isinstance(value, dict):
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact root is invalid")
    return value


def parse_warning_map(payload: JsonObject) -> dict[int, tuple[str, ...]]:
    if frozenset(payload) != ROOT_KEYS:
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact fields are invalid")
    if payload.get("schema_version") != "overwritten_ambiguity_v1":
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact version is unsupported")
    if payload.get("ok") is not True or payload.get("student_facing") is not False:
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact safety contract is invalid")
    if payload.get("production_default") != "NO_GO" or any(not_zero_counter(payload.get(field)) for field in ZERO_COUNTER_FIELDS):
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact counters are invalid")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != QUESTION_COUNT:
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact item count is invalid")
    warnings_by_question: dict[int, tuple[str, ...]] = {}
    for item in items:
        question_no, warnings = parse_item(item)
        if question_no in warnings_by_question:
            raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact has duplicate questions")
        warnings_by_question[question_no] = warnings
    if sorted(warnings_by_question) != list(range(1, QUESTION_COUNT + 1)):
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact question set is invalid")
    return warnings_by_question


def parse_item(value: JsonValue) -> tuple[int, tuple[str, ...]]:
    if not isinstance(value, dict):
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact item is invalid")
    if frozenset(value) != ITEM_KEYS:
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact item fields are invalid")
    question_no = value.get("question_no")
    warnings = value.get("warnings")
    if not isinstance(question_no, int) or isinstance(question_no, bool) or not 1 <= question_no <= QUESTION_COUNT:
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact question is invalid")
    if not isinstance(warnings, list) or not all(isinstance(warning, str) for warning in warnings):
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact warnings are invalid")
    if any(warning != WARNING_CODE for warning in warnings):
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact warning code is invalid")
    if len(set(warnings)) != len(warnings):
        raise OverwrittenAmbiguityArtifactError("overwritten ambiguity artifact warning data is duplicated")
    return question_no, tuple(warnings)


def not_zero_counter(value: JsonValue) -> bool:
    return not isinstance(value, int) or isinstance(value, bool) or value != 0
