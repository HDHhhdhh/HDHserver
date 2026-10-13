# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by provider-free OCR report verifiers.

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import assert_never

from ocr_preflight_environment_matrix_model import ROOT, JsonValue
from ocr_preflight_environment_matrix_output import parse_json


def read_report(path: Path) -> Mapping[str, JsonValue]:
    parsed = parse_json(path.read_text(encoding="utf-8"))
    match parsed:
        case dict() as data:
            return data
        case None | bool() | int() | float() | str() | list():
            message = f"{path.relative_to(ROOT)} is not a JSON object"
            raise TypeError(message)
        case unreachable:
            assert_never(unreachable)


def bool_field(data: Mapping[str, JsonValue], field: str) -> bool:
    match data.get(field):
        case bool() as value:
            return value
        case None | int() | float() | str() | list() | dict():
            return False
        case unreachable:
            assert_never(unreachable)


def nullable_int_field(data: Mapping[str, JsonValue], field: str) -> int | None:
    match data.get(field):
        case bool():
            return None
        case int() as value:
            return value
        case None | float() | str() | list() | dict():
            return None
        case unreachable:
            assert_never(unreachable)


def int_field(data: Mapping[str, JsonValue], field: str) -> int:
    value = nullable_int_field(data, field)
    if value is None:
        return 0
    return value


def str_field(data: Mapping[str, JsonValue], field: str) -> str:
    match data.get(field):
        case str() as value:
            return value
        case None | bool() | int() | float() | list() | dict():
            return ""
        case unreachable:
            assert_never(unreachable)
