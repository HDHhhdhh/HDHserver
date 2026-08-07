"""Typed parsing and fail-closed payload serialization for student push data."""
from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeAlias
from urllib.parse import urlparse


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
_BASE64URL_RE: Final = re.compile(r"^[A-Za-z0-9_-]+$")
_TOKEN_RE: Final = re.compile(r"^[A-Za-z0-9_-]+$")
_BLOCKED_KEYS: Final = ("token", "secret", "password", "csrf", "endpoint", "p256dh", "auth", "cookie", "private_key")


@dataclass(frozen=True, slots=True)
class StudentPushRepositoryInputError(ValueError):
    """Typed boundary failure for malformed or privacy-sensitive push input."""

    reason: str

    def __str__(self) -> str:
        return self.reason


def parse_endpoint(value: str) -> str:
    """Parse an HTTPS endpoint without credentials or oversized URLs."""

    endpoint = str(value)
    try:
        parsed = urlparse(endpoint)
        hostname = parsed.hostname
    except ValueError as exc:
        raise StudentPushRepositoryInputError("subscription endpoint is invalid") from exc
    if parsed.scheme.lower() != "https" or not hostname or parsed.username or parsed.password or len(endpoint) > 2048:
        raise StudentPushRepositoryInputError("subscription endpoint must be HTTPS")
    return endpoint


def parse_subscription_key(value: str) -> str:
    """Parse a URL-safe subscription key and preserve its original text."""

    text = str(value)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=+/"
    if not text or len(text) > 512 or any(char not in alphabet for char in text):
        raise StudentPushRepositoryInputError("malformed subscription key")
    try:
        base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, binascii.Error) as exc:
        raise StudentPushRepositoryInputError("malformed subscription key") from exc
    return text


def _is_subscription_key(value: str) -> bool:
    """Recognize raw Web Push auth or P-256 key material by decoded length."""

    if len(value) not in (22, 87) or _BASE64URL_RE.fullmatch(value) is None:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error):
        return False
    return len(decoded) in (16, 65)


def _is_sensitive_string(value: str, protected_values: frozenset[str]) -> bool:
    """Reject raw endpoint, credential, activation-code, or opaque-token values."""

    text = value.strip()
    if text in protected_values:
        return True
    try:
        parsed = urlparse(text)
    except ValueError:
        parsed = None
    if parsed is None and text.casefold().startswith(("http://", "https://")):
        return True
    if parsed is not None and parsed.scheme.lower() in ("http", "https") and parsed.hostname:
        return True
    if text.isdigit() and len(text) == 6:
        return True
    return (len(text) >= 40 and _TOKEN_RE.fullmatch(text) is not None) or _is_subscription_key(text)


def serialize_payload(value: Mapping[str, JsonValue], protected_values: Sequence[str] = ()) -> str:
    """Serialize a JSON payload only when nested values remain privacy-safe."""

    if not isinstance(value, Mapping):
        raise StudentPushRepositoryInputError("payload must be an object")
    protected = frozenset(str(item) for item in protected_values if str(item))

    def walk(item: JsonValue, key: str = "") -> JsonValue:
        if any(word in key.casefold() for word in _BLOCKED_KEYS):
            raise StudentPushRepositoryInputError("payload contains restricted data")
        if isinstance(item, Mapping):
            result: dict[str, JsonValue] = {}
            for name, child in item.items():
                child_key = str(name)
                if _is_sensitive_string(child_key, protected):
                    raise StudentPushRepositoryInputError("payload contains restricted data")
                result[child_key] = walk(child, child_key)
            return result
        if isinstance(item, (str, int, float, bool)) or item is None:
            if isinstance(item, str) and (len(item) > 4096 or _is_sensitive_string(item, protected)):
                raise StudentPushRepositoryInputError("payload contains restricted data")
            return item
        if isinstance(item, (list, tuple)):
            return [walk(child, key) for child in item]
        raise StudentPushRepositoryInputError("payload contains unsupported data")

    return json.dumps(walk(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["JsonValue", "StudentPushRepositoryInputError", "parse_endpoint", "parse_subscription_key", "serialize_payload"]
