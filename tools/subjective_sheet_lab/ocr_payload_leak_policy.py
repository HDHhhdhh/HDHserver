from __future__ import annotations

import json
from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "score", "wrong", "pct"))
PATH_TOKENS: Final[tuple[str, ...]] = ("C:\\", "C:/", "server-ocr", "phase2c_route_uploads", "crop_benchmark_inputs")


def forbidden_paths(value: JsonValue, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_KEYS:
                found.append(child_path)
            found.extend(forbidden_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(forbidden_paths(child, f"{path}[{index}]"))
    return found


def path_exposures(value: JsonValue) -> bool:
    text = json.dumps(value, ensure_ascii=False)
    return any(token in text for token in PATH_TOKENS)
