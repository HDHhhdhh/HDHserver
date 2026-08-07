"""Typed parsing boundaries for the student login-throttle repository."""

from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Final, NoReturn


MAX_TEXT_LENGTH: Final = 256
MAX_WINDOW_SECONDS: Final = 24 * 60 * 60
MAX_FAILURE_LIMIT: Final = 1_000


@dataclass(frozen=True, slots=True)
class StudentLoginThrottleInputError(ValueError):
    """Typed boundary failure whose text never contains caller values."""

    field: str
    reason: str

    def __str__(self) -> str:
        return f"throttle {self.field}: {self.reason}"


def _reject(field: str, reason: str) -> NoReturn:
    raise StudentLoginThrottleInputError(field, reason)


def parse_db_path(value: str | Path) -> str:
    """Accept only a path value and return its filesystem spelling."""
    if not isinstance(value, (str, Path)):
        _reject("db_path", "must be a path")
    return str(value)


def parse_timeout(value: float | int) -> float:
    """Parse a finite, non-negative SQLite timeout without text coercion."""
    if type(value) not in (int, float):
        _reject("timeout", "must be a number")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout < 0:
        _reject("timeout", "must be finite and non-negative")
    return max(0.1, timeout)


def parse_clock(value: Callable[[], float | int | datetime] | None) -> Callable[[], float | int | datetime] | None:
    """Parse an optional injected clock callable."""
    if value is not None and not callable(value):
        _reject("clock", "must be callable")
    return value


def parse_pepper(value: bytes | str) -> bytes:
    """Parse a bounded HMAC pepper without exposing its contents."""
    if type(value) is str:
        try:
            pepper = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise StudentLoginThrottleInputError("pepper", "is not valid UTF-8") from exc
    elif type(value) is bytes:
        pepper = value
    else:
        _reject("pepper", "must be bytes or text")
    if not pepper:
        _reject("pepper", "is required")
    if len(pepper) > MAX_TEXT_LENGTH:
        _reject("pepper", "is too long")
    return pepper


def parse_identifier(value: str, field: str = "identifier") -> str:
    """Parse and normalize an account identifier without arbitrary coercion."""
    if type(value) is not str:
        _reject(field, "must be text")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        _reject(field, "contains control characters")
    text = value.strip()
    if not text:
        _reject(field, "is required")
    if len(text) > MAX_TEXT_LENGTH:
        _reject(field, "is too long")
    return " ".join(text.casefold().split())


def parse_client_ip(value: str) -> str:
    """Parse a literal IPv4/IPv6 client address into canonical text."""
    if type(value) is not str:
        _reject("client_ip", "must be text")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        _reject("client_ip", "contains control characters")
    text = value.strip()
    if not text:
        _reject("client_ip", "is required")
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise StudentLoginThrottleInputError("client_ip", "must be a literal IP address") from exc
    canonical = str(address)
    if "%" in canonical:
        _reject("client_ip", "must not contain a scope")
    return canonical


def parse_now(value: float | int | datetime, field: str = "now") -> float:
    """Parse a finite non-negative clock value exactly at the boundary."""
    if isinstance(value, datetime):
        try:
            current = value.timestamp()
        except (OverflowError, OSError, ValueError) as exc:
            raise StudentLoginThrottleInputError(field, "is invalid") from exc
    elif type(value) in (int, float):
        current = float(value)
    else:
        _reject(field, "must be a timestamp")
    if not math.isfinite(current) or current < 0:
        _reject(field, "must be finite and non-negative")
    return current


def parse_window_seconds(value: int) -> int:
    """Parse a positive bounded throttle window in seconds."""
    if type(value) is not int:
        _reject("window_seconds", "must be an integer")
    if value < 1 or value > MAX_WINDOW_SECONDS:
        _reject("window_seconds", "is out of range")
    return value


def parse_max_failures(value: int) -> int:
    """Parse a positive bounded failure limit without numeric coercion."""
    if type(value) is not int:
        _reject("max_failures", "must be an integer")
    if value < 1 or value > MAX_FAILURE_LIMIT:
        _reject("max_failures", "is out of range")
    return value


__all__ = [
    "StudentLoginThrottleInputError",
    "parse_client_ip",
    "parse_clock",
    "parse_db_path",
    "parse_identifier",
    "parse_max_failures",
    "parse_now",
    "parse_pepper",
    "parse_timeout",
    "parse_window_seconds",
]
