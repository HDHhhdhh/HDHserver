"""Pure typed boundaries for the student activation-code repository."""
from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, NoReturn, TypeAlias, TypedDict

MAX_TEXT_LENGTH: Final = 256
MAX_ATTEMPTS: Final = 5
CODE_LENGTH: Final = 6
DEFAULT_TTL_SECONDS: Final = 24 * 60 * 60
ActivationScalar: TypeAlias = str | int | float | bytes | None
StoredActivationRow: TypeAlias = tuple[int, str, list[str], str, float, int]


class ActivationRedemption(TypedDict):
    """Non-secret activation result; the submitted code is never returned."""

    activation_id: int
    identity_key: str
    sids: list[str]
    attempts: int
    used_at: float


@dataclass(frozen=True, slots=True)
class StudentActivationInputError(ValueError):
    """Typed caller-boundary failure that never includes secret material."""

    field: str
    reason: str

    def __str__(self) -> str:
        return f"{self.field}: {self.reason}"


@dataclass(frozen=True, slots=True)
class StudentActivationStateError(ValueError):
    """Typed failure for malformed persisted activation state."""

    field: str
    reason: str

    def __str__(self) -> str:
        return f"stored {self.field}: {self.reason}"


def _reject(field: str, reason: str) -> NoReturn:
    raise StudentActivationInputError(field, reason)


def _state_reject(field: str, reason: str) -> NoReturn:
    raise StudentActivationStateError(field, reason)


def parse_text(value: str, field: str) -> str:
    """Parse a bounded textual identity/SID without coercion."""
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
    """Parse an exact, non-empty unique SID collection."""
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        _reject("sids", "must be an iterable of SID text values")
    try:
        items = tuple(value)
    except TypeError as exc:
        raise StudentActivationInputError("sids", "must be iterable") from exc
    if not items:
        _reject("sids", "must not be empty")
    result: list[str] = []
    for item in items:
        sid = parse_text(item, "sid")
        if sid in result:
            _reject("sids", "must contain unique SIDs")
        result.append(sid)
    return result


def parse_code(value: str) -> str:
    """Parse the exact six-digit activation code shape."""
    if not isinstance(value, str) or len(value) != CODE_LENGTH or not value.isascii() or not value.isdigit():
        _reject("code", "must be six ASCII digits")
    return value


def safe_text(value: str, field: str) -> str | None:
    """Return a normalized lookup selector or a safe miss."""
    try:
        return parse_text(value, field)
    except StudentActivationInputError:
        return None


def safe_code(value: str) -> str | None:
    """Return a valid lookup code or a safe miss."""
    try:
        return parse_code(value)
    except StudentActivationInputError:
        return None


def parse_number(value: float | int | datetime, field: str) -> float:
    """Parse a finite non-negative timestamp without string conversion."""
    if isinstance(value, bool) or not isinstance(value, (int, float, datetime)):
        _reject(field, "must be a timestamp")
    try:
        raw = value.timestamp() if isinstance(value, datetime) else float(value)
    except (OverflowError, OSError, TypeError, ValueError) as exc:
        raise StudentActivationInputError(field, "is invalid") from exc
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
        raise StudentActivationInputError(field, "is invalid") from exc
    if not math.isfinite(duration) or duration <= 0:
        _reject(field, "must be finite and positive")
    return duration


def parse_timeout(value: float | int) -> float:
    """Parse a finite non-negative SQLite timeout."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject("timeout", "must be a number")
    try:
        timeout = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise StudentActivationInputError("timeout", "is invalid") from exc
    if not math.isfinite(timeout) or timeout < 0:
        _reject("timeout", "must be finite and non-negative")
    return max(0.1, timeout)


def parse_attempts(value: ActivationScalar) -> int:
    """Parse the persisted mismatch counter without coercion."""
    if type(value) is not int or not 0 <= value <= MAX_ATTEMPTS:
        _state_reject("attempts", "must be an integer from zero through five")
    return value


def parse_stored_number(value: ActivationScalar, field: str) -> float:
    """Parse a persisted numeric timestamp without accepting text numerals."""
    if type(value) not in (int, float):
        _state_reject(field, "must be a finite non-negative number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        _state_reject(field, "must be a finite non-negative number")
    return parsed


def parse_stored_used(value: ActivationScalar) -> int:
    """Parse the persisted one-use flag."""
    if type(value) is not int or value not in (0, 1):
        _state_reject("used", "must be zero or one")
    return value


def parse_stored_digest(value: ActivationScalar, field: str) -> str:
    """Parse a lowercase SHA-256 digest stored in a protected column."""
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        _state_reject(field, "must be a SHA-256 digest")
    return value


def parse_stored_sids(value: ActivationScalar) -> list[str]:
    """Parse and validate the JSON SID binding stored with a code."""
    if not isinstance(value, str):
        _state_reject("sids_json", "must be JSON text")
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StudentActivationStateError("sids_json", "is invalid JSON") from exc
    try:
        return parse_sids(decoded)
    except StudentActivationInputError as exc:
        raise StudentActivationStateError("sids_json", "does not contain valid SIDs") from exc


def parse_stored_row(row: sqlite3.Row) -> StoredActivationRow:
    """Parse an active SQLite row before any lifecycle mutation occurs."""
    if type(row["id"]) is not int:
        raise StudentActivationStateError("id", "must be an integer")
    identity = parse_stored_digest(row["identity_key"], "identity_key")
    sids = parse_stored_sids(row["sids_json"])
    digest = parse_stored_digest(row["code_digest"], "code_digest")
    created = parse_stored_number(row["created_at"], "created_at")
    expires = parse_stored_number(row["expires_at"], "expires_at")
    used = parse_stored_used(row["used"])
    attempts = parse_attempts(row["attempts"])
    if expires <= created or used != 0:
        raise StudentActivationStateError("row", "has an invalid active lifecycle")
    return int(row["id"]), identity, sids, digest, expires, attempts


def state_usable(expires_at: float, attempts: int, now: float) -> bool:
    """Return whether expiry and mismatch limits still permit redemption."""
    return expires_at > now and attempts < MAX_ATTEMPTS


__all__ = [
    "ActivationScalar",
    "ActivationRedemption",
    "CODE_LENGTH",
    "DEFAULT_TTL_SECONDS",
    "MAX_ATTEMPTS",
    "StoredActivationRow",
    "StudentActivationInputError",
    "StudentActivationStateError",
    "parse_attempts",
    "parse_code",
    "parse_number",
    "parse_sids",
    "parse_stored_digest",
    "parse_stored_number",
    "parse_stored_sids",
    "parse_stored_used",
    "parse_stored_row",
    "parse_text",
    "parse_timeout",
    "parse_ttl",
    "safe_code",
    "safe_text",
    "state_usable",
]
