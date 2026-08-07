"""Typed, fail-closed privacy parsing for student account-audit fields."""
from __future__ import annotations

import base64
import binascii
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, NoReturn, TypeAlias
from urllib.parse import urlparse


AuditScalar: TypeAlias = str | int | float | bool | None
AuditInputValue: TypeAlias = AuditScalar | list["AuditInputValue"] | tuple["AuditInputValue", ...] | dict[str, "AuditInputValue"]
JsonValue: TypeAlias = AuditScalar | list["JsonValue"] | dict[str, "JsonValue"]

MAX_DEPTH: Final = 8
MAX_NODES: Final = 256
MAX_ITEMS: Final = 64
MAX_KEY_LENGTH: Final = 128
MAX_STRING_LENGTH: Final = 1024
MAX_JSON_LENGTH: Final = 16_384
MAX_INTEGER: Final = 2**63 - 1
LABEL_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z][a-z0-9]*)*$")
TOKEN_RE: Final = re.compile(r"^[A-Za-z0-9_-]{32,}$")
JWT_RE: Final = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
BASE64URL_RE: Final = re.compile(r"^[A-Za-z0-9_-]+$")
SECRET_VALUE_RE: Final = re.compile(r"^(?:raw[-_ ]?)?(?:token|secret|auth|password|credential|private[-_ ]?key)(?:$|[-_:= ])", re.IGNORECASE)
ACTION_WORDS: Final = frozenset({
    "account", "accounts", "ack", "acknowledge", "activation", "admin", "announcement", "announcements", "api", "app",
    "archive", "attempt", "audit", "auth", "bypass", "code", "codes", "config", "conflict", "create", "delete",
    "deliver", "delivery", "disable", "enable", "enqueue", "expire", "failure", "first", "grant", "import", "issue",
    "list", "lock", "login", "logout", "maintenance", "notice", "notification", "operator", "outbox", "push", "read",
    "redeem", "reply", "reset", "retry", "revoke", "rotate", "send", "session", "sessions", "status", "student",
    "students", "subscribe", "subscription", "subscriptions", "success", "submit", "system", "test", "unsubscribe",
    "update", "use", "view", "worker",
})
ACTOR_WORDS: Final = frozenset({
    "academy", "admin", "api", "app", "background", "cli", "console", "gateway", "job", "local", "mobile", "panel",
    "public", "push", "scheduler", "server", "service", "system", "ui", "web", "worker",
})
SENSITIVE_KEYS: Final = frozenset({
    "token", "sessiontoken", "accesstoken", "refreshtoken", "idtoken", "secret", "password", "passwd", "csrf",
    "code", "activationcode", "recoverycode", "verificationcode", "endpoint", "auth", "authorization", "authkey",
    "p256dh", "cookie", "privatekey", "bearer", "credential", "vapid", "devicekey", "subscriptionkey",
})


@dataclass(frozen=True, slots=True)
class StudentAccountAuditInputError(ValueError):
    """Typed boundary failure for malformed or privacy-sensitive audit input."""

    reason: str

    def __str__(self) -> str:
        return self.reason


def _fail(reason: str) -> NoReturn:
    raise StudentAccountAuditInputError(reason)


def _subscription_key(value: str) -> bool:
    if len(value) not in (22, 87) or BASE64URL_RE.fullmatch(value) is None:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error):
        return False
    return len(decoded) in (16, 65)


def _looks_sensitive(value: str) -> bool:
    text = value.strip()
    if text.isdigit() and len(text) == 6:
        return True
    if SECRET_VALUE_RE.match(text) is not None:
        return True
    if TOKEN_RE.fullmatch(text) is not None or _subscription_key(text) or JWT_RE.fullmatch(text) is not None:
        return True
    if text.casefold().startswith(("bearer ", "basic ", "vapid ")):
        return True
    try:
        parsed = urlparse(text)
    except ValueError:
        parsed = None
    return parsed is not None and parsed.scheme.casefold() in {"http", "https", "ws", "wss"} and bool(parsed.hostname)


def _parse_label(value: str, kind: str, words: frozenset[str]) -> str:
    if not isinstance(value, str):
        _fail(f"audit {kind} must be a string")
    text = value.strip().casefold()
    parts = re.split(r"[._:-]", text)
    if not text or len(text) > 64 or _looks_sensitive(text) or LABEL_RE.fullmatch(text) is None or any(part not in words for part in parts):
        _fail(f"audit {kind} is not an allowed label")
    return text


def parse_action(value: str) -> str:
    """Parse the explicit lower-case action-label vocabulary."""
    return _parse_label(value, "action", ACTION_WORDS)


def parse_actor_surface(value: str) -> str:
    """Parse the explicit actor-surface vocabulary."""
    return _parse_label(value, "actor surface", ACTOR_WORDS)


def _sensitive_key(value: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", value.casefold())
    return compact in SENSITIVE_KEYS or compact.startswith(("endpoint", "privatekey", "p256dh", "authkey")) or compact.endswith(("token", "secret", "password", "passwd", "csrf"))


def _walk(value: AuditInputValue, key: str, depth: int, nodes: list[int]) -> JsonValue:
    if depth > MAX_DEPTH:
        _fail("audit metadata nesting is too deep")
    nodes[0] += 1
    if nodes[0] > MAX_NODES:
        _fail("audit metadata is too large")
    if isinstance(value, Mapping):
        if len(value) > MAX_ITEMS:
            _fail("audit metadata object is too large")
        result: dict[str, JsonValue] = {}
        for raw_name, child in value.items():
            if not isinstance(raw_name, str):
                _fail("audit metadata keys must be strings")
            name = raw_name
            if not name or name != name.strip() or len(name) > MAX_KEY_LENGTH or _sensitive_key(name):
                _fail("audit metadata contains restricted data")
            result[name] = _walk(child, name, depth + 1, nodes)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_ITEMS:
            _fail("audit metadata array is too large")
        return [_walk(child, key, depth + 1, nodes) for child in value]
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH or any(0xD800 <= ord(char) <= 0xDFFF for char in value) or _looks_sensitive(value):
            _fail("audit metadata contains restricted data")
        return value
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > MAX_INTEGER:
            _fail("audit metadata number is out of range")
        if 100_000 <= value <= 999_999:
            _fail("audit metadata contains restricted data")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("audit metadata number is invalid")
        return value
    _fail("audit metadata contains unsupported data")


def normalize_metadata(value: Mapping[str, AuditInputValue] | None) -> dict[str, JsonValue]:
    """Parse metadata recursively into a bounded JSON-safe projection."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        _fail("audit metadata must be an object")
    normalized = _walk(value, "", 0, [0])
    if not isinstance(normalized, dict):
        _fail("audit metadata must be an object")
    return normalized


def serialize_metadata(value: Mapping[str, AuditInputValue] | None) -> str:
    """Return deterministic JSON only after privacy and size parsing."""
    payload = json.dumps(normalize_metadata(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(payload) > MAX_JSON_LENGTH:
        _fail("audit metadata JSON is too large")
    return payload


def parse_serialized_metadata(value: str) -> dict[str, JsonValue]:
    """Parse an existing row and fail closed when legacy data is malformed."""
    if not isinstance(value, str) or len(value) > MAX_JSON_LENGTH:
        _fail("stored audit metadata is too large")
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise StudentAccountAuditInputError("stored audit metadata is invalid") from exc
    return normalize_metadata(decoded)


__all__ = [
    "AuditInputValue", "JsonValue", "StudentAccountAuditInputError", "normalize_metadata", "parse_action",
    "parse_actor_surface", "parse_serialized_metadata", "serialize_metadata",
]
