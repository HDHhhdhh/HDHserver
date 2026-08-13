"""Pure parsing boundaries for the opaque student-session repository."""
from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, NoReturn, TypedDict

MAX_TEXT_LENGTH: Final = 256
MAX_TOKEN_LENGTH: Final = 512
TOKEN_ALPHABET: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


@dataclass(frozen=True, slots=True)
class StudentSessionInputError(ValueError):
    """Typed boundary failure that never includes caller secret material."""

    field: str
    reason: str

    def __str__(self) -> str:
        return f"{self.field}: {self.reason}"


class SessionCreated(TypedDict):
    """Opaque values returned exactly once at session creation/rotation."""

    session_id: int
    token: str
    csrf_token: str
    aid: str
    active_sid: str
    allowed_sids: list[str]
    created_at: float
    expires_at: float


class SessionView(TypedDict):
    """Non-secret session projection returned during resolution."""

    session_id: int
    aid: str
    active_sid: str
    allowed_sids: list[str]
    created_at: float
    expires_at: float
    last_seen: float


def _reject(field: str, reason: str) -> NoReturn:
    raise StudentSessionInputError(field, reason)


def parse_text(value: str, field: str) -> str:
    """Parse a bounded identifier without coercing arbitrary values."""
    if not isinstance(value, str):
        _reject(field, "must be text")
    text = value.strip()
    if not text:
        _reject(field, "is required")
    if len(text) > MAX_TEXT_LENGTH:
        _reject(field, "is too long")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        _reject(field, "contains control characters")
    return text


def parse_sids(value: Iterable[str]) -> list[str]:
    """Parse the exact allowlist shape used by a session row."""
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        _reject("allowed_sids", "must be an iterable of SID text values")
    try:
        items = tuple(value)
    except TypeError as exc:
        raise StudentSessionInputError("allowed_sids", "must be iterable") from exc
    if not items:
        _reject("allowed_sids", "must not be empty")
    result: list[str] = []
    for item in items:
        sid = parse_text(item, "sid")
        if sid in result:
            _reject("allowed_sids", "must contain unique SIDs")
        result.append(sid)
    return result


def parse_secret(value: str | None, field: str) -> str | None:
    """Parse an opaque URL-safe token; malformed lookup values are misses."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > MAX_TOKEN_LENGTH:
        return None
    if len(value) < 32 or any(char not in TOKEN_ALPHABET for char in value):
        return None
    return value


def parse_number(value: float | int | datetime, field: str) -> float:
    """Parse a finite non-negative timestamp value."""
    if isinstance(value, bool) or not isinstance(value, (int, float, datetime)):
        _reject(field, "must be a timestamp")
    try:
        raw = value.timestamp() if isinstance(value, datetime) else float(value)
    except (OverflowError, OSError, TypeError, ValueError) as exc:
        raise StudentSessionInputError(field, "is invalid") from exc
    if not math.isfinite(raw) or raw < 0:
        _reject(field, "must be finite and non-negative")
    return raw


def parse_ttl(value: float | int, field: str = "ttl_seconds") -> float:
    """Parse a strictly positive finite duration."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject(field, "must be a number")
    try:
        duration = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise StudentSessionInputError(field, "is invalid") from exc
    if not math.isfinite(duration) or duration <= 0:
        _reject(field, "must be finite and positive")
    return duration


def parse_timeout(value: float | int) -> float:
    """Parse SQLite timeout while preserving the repository's minimum wait."""
    return max(0.1, parse_number(value, "timeout"))


def safe_text(value: str, field: str) -> str | None:
    """Return a parsed identifier or a safe miss for lookup selectors."""
    try:
        return parse_text(value, field)
    except StudentSessionInputError:
        return None


def stored_sids(value: str) -> list[str] | None:
    """Parse a persisted JSON SID allowlist without raising on corrupt rows."""
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    try:
        return parse_sids(decoded)
    except StudentSessionInputError:
        return None


__all__ = ["SessionCreated", "SessionView", "StudentSessionInputError", "parse_number", "parse_secret", "parse_sids", "parse_text", "parse_timeout", "parse_ttl", "safe_text", "stored_sids"]
