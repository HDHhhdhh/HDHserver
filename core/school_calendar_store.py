from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from core.storage import file_lock, save_atomic


class SchoolCalendarConflictError(RuntimeError):
    def __init__(self, current_revision: str) -> None:
        self.current_revision = current_revision
        super().__init__("school calendar changed")


class SchoolCalendarUnavailableError(RuntimeError):
    """Raised when the calendar store cannot be read safely."""


def school_calendar_revision(document: dict[str, Any]) -> str:
    if not isinstance(document, dict):
        raise ValueError("school calendar must be an object")
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_school_calendar_strict(path: Any) -> dict[str, Any]:
    source = pathlib.Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SchoolCalendarUnavailableError(
            f"school calendar is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise SchoolCalendarUnavailableError("school calendar must be an object")
    return value


def load_school_calendar_snapshot(path: Any) -> tuple[dict[str, Any], str]:
    with file_lock(path, timeout_sec=4.0, poll_sec=0.05):
        document = _load_school_calendar_strict(path)
        return document, school_calendar_revision(document)


def replace_school_calendar(
    path: Any,
    document: dict[str, Any],
    *,
    expected_revision: str,
) -> str:
    if not isinstance(document, dict):
        raise ValueError("school calendar must be an object")

    with file_lock(path, timeout_sec=4.0, poll_sec=0.05):
        current = _load_school_calendar_strict(path)
        current_revision = school_calendar_revision(current)
        if expected_revision != current_revision:
            raise SchoolCalendarConflictError(current_revision)
        save_atomic(pathlib.Path(path), document)
        return school_calendar_revision(document)


__all__ = [
    "SchoolCalendarConflictError",
    "SchoolCalendarUnavailableError",
    "load_school_calendar_snapshot",
    "replace_school_calendar",
    "school_calendar_revision",
]
