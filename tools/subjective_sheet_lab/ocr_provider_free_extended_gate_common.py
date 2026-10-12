from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, assert_never

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ExtendedGateError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), path.name)


def assert_common_safety(label: str, payload: JsonObject) -> None:
    if payload.get("ok") is not True:
        raise ExtendedGateError(f"{label}.ok must be true")
    if payload.get("student_facing") is not False:
        raise ExtendedGateError(f"{label}.student_facing must be false")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_zero_leak(label, payload)


def require_zero_leak(label: str, payload: JsonObject) -> None:
    sensitive = payload.get("sensitive_field_leak_count")
    answer_key = payload.get("answer_key_or_grading_field_leak_count")
    filesystem = payload.get("filesystem_path_leak_count")
    if sensitive is not None:
        require_int_value(sensitive, 0, f"{label}.sensitive_field_leak_count")
        return
    require_int_value(answer_key, 0, f"{label}.answer_key_or_grading_field_leak_count")
    require_int_value(filesystem, 0, f"{label}.filesystem_path_leak_count")


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise ExtendedGateError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise ExtendedGateError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise ExtendedGateError(f"{label} expected {expected}, got {actual}")


def require_text_value(value: JsonValue, expected: str, label: str) -> None:
    match value:
        case str() if value == expected:
            return
        case str():
            raise ExtendedGateError(f"{label} expected {expected}, got {value}")
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"{label} must be text")
        case unreachable:
            assert_never(unreachable)


def require_bool_value(value: JsonValue, expected: bool, label: str) -> None:
    match value:
        case bool() if value is expected:
            return
        case bool():
            raise ExtendedGateError(f"{label} expected {expected}, got {value}")
        case None | int() | float() | str() | list() | dict():
            raise ExtendedGateError(f"{label} must be boolean")
        case unreachable:
            assert_never(unreachable)
