"""Typed Web Push boundary parsing and vetted VAPID key validation."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, TypeAlias, TypedDict
from urllib.parse import urlparse, urlsplit, urlunsplit


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

_BASE64URL_RE: Final = re.compile(r"^[A-Za-z0-9_-]+$")
_ANNOUNCEMENT_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAILTO_RE: Final = re.compile(r"^mailto:[^@\s/]+@[^@\s/]+$")
_DNS_LABEL_RE: Final = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PUSH_ENDPOINT_ALLOWLIST_ENV: Final = "STUDENT_APP_PUSH_ENDPOINT_ALLOWLIST"
_DEFAULT_PUSH_ENDPOINT_PATTERNS: Final = (
    "fcm.googleapis.com",
    "*.push.services.mozilla.com",
    "*.push.apple.com",
    "*.notify.windows.com",
)


class SubscriptionKeys(TypedDict):
    p256dh: str
    auth: str


class SubscriptionInfo(TypedDict):
    endpoint: str
    keys: SubscriptionKeys


class VapidKeyValidator(Protocol):
    """Callable seam for tests; production uses ``validate_vapid_private_key``."""

    def __call__(self, pem: bytes) -> None: ...


@dataclass(frozen=True, slots=True)
class StudentPushInputError(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class StudentPushConfigurationError(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class StudentPushDependencyError(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class StudentPushKeyError(ValueError):
    reason: str

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class ParsedSubscription:
    endpoint: str
    p256dh: str
    auth: str

    def as_pywebpush(self) -> SubscriptionInfo:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_runtime_destination(path: Path | str, label: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    repository = Path(__file__).resolve().parents[1]
    if _is_under(resolved, repository) and not _is_under(resolved, repository / "instance"):
        raise StudentPushConfigurationError(f"{label} must be runtime data outside tracked source")
    return resolved


def validate_private_key_path(path: Path | str) -> Path:
    """Resolve a private-key path and reject tracked source directories."""

    return _validate_runtime_destination(path, "VAPID private-key path")


def validate_public_output_path(path: Path | str) -> Path:
    """Resolve a public-key output path and reject tracked source directories."""

    return _validate_runtime_destination(path, "VAPID public-key output")


def _decode_base64url(value: str, label: str) -> bytes:
    if not value or "=" in value or not _BASE64URL_RE.fullmatch(value):
        raise StudentPushInputError(f"{label} is not unpadded base64url")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise StudentPushInputError(f"{label} is not valid base64url") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if canonical != value:
        raise StudentPushInputError(f"{label} is not canonical base64url")
    return decoded


def _normalized_dns_host(value: str) -> str:
    raw = value.strip().rstrip(".").casefold()
    try:
        host = raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise StudentPushInputError("subscription endpoint host is invalid") from exc
    if not host or len(host) > 253 or host == "localhost" or host.endswith(".localhost"):
        raise StudentPushInputError("subscription endpoint host is invalid")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        pass
    else:
        raise StudentPushInputError("subscription endpoint host is invalid")
    labels = host.split(".")
    if len(labels) < 2 or any(_DNS_LABEL_RE.fullmatch(label) is None for label in labels):
        raise StudentPushInputError("subscription endpoint host is invalid")
    return host


def _push_endpoint_patterns() -> tuple[str, ...]:
    configured = str(os.environ.get(_PUSH_ENDPOINT_ALLOWLIST_ENV) or "").strip()
    if not configured:
        return _DEFAULT_PUSH_ENDPOINT_PATTERNS
    raw_patterns = [item.strip().casefold() for item in configured.split(",") if item.strip()]
    if not raw_patterns or len(raw_patterns) > 32 or len(configured) > 4096:
        raise StudentPushConfigurationError("subscription endpoint policy is invalid")
    patterns = list(_DEFAULT_PUSH_ENDPOINT_PATTERNS)
    for raw in raw_patterns:
        wildcard = raw.startswith("*.")
        if "*" in raw[2 if wildcard else 0 :]:
            raise StudentPushConfigurationError("subscription endpoint policy is invalid")
        try:
            host = _normalized_dns_host(raw[2:] if wildcard else raw)
        except StudentPushInputError as exc:
            raise StudentPushConfigurationError("subscription endpoint policy is invalid") from exc
        if host.count(".") < 2:
            raise StudentPushConfigurationError("subscription endpoint policy is invalid")
        patterns.append(f"*.{host}" if wildcard else host)
    return tuple(dict.fromkeys(patterns))


def _host_allowed(host: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if host != suffix and host.endswith(f".{suffix}"):
                return True
        elif host == pattern:
            return True
    return False


def validate_push_endpoint(value: str) -> str:
    """Return one canonical HTTPS URL for an explicitly trusted Push provider."""

    if not isinstance(value, str) or value != value.strip() or len(value) > 2048:
        raise StudentPushInputError("subscription endpoint is invalid")
    if any(ord(char) < 0x21 or ord(char) == 0x7F for char in value):
        raise StudentPushInputError("subscription endpoint is invalid")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise StudentPushInputError("subscription endpoint is invalid") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or "#" in value
        or port not in (None, 443)
        or parsed.netloc.endswith(":")
    ):
        raise StudentPushInputError("subscription endpoint is invalid")
    host = _normalized_dns_host(hostname)
    if not _host_allowed(host, _push_endpoint_patterns()):
        raise StudentPushInputError("subscription endpoint is not an approved Web Push provider")
    return urlunsplit(("https", host, parsed.path, parsed.query, ""))


def parse_subscription(raw: Mapping[str, JsonValue] | JsonValue) -> ParsedSubscription:
    """Parse strict HTTPS and PushSubscription key bytes at the trust boundary."""

    if not isinstance(raw, Mapping):
        raise StudentPushInputError("subscription shape is invalid")
    endpoint = raw.get("endpoint")
    keys_raw = raw.get("keys")
    if not isinstance(endpoint, str) or not isinstance(keys_raw, Mapping):
        raise StudentPushInputError("subscription shape is invalid")
    endpoint = validate_push_endpoint(endpoint)
    p256dh = keys_raw.get("p256dh")
    auth = keys_raw.get("auth")
    if not isinstance(p256dh, str) or not isinstance(auth, str):
        raise StudentPushInputError("subscription keys are invalid")
    p256dh_bytes = _decode_base64url(p256dh, "p256dh")
    auth_bytes = _decode_base64url(auth, "auth")
    if len(p256dh_bytes) != 65 or p256dh_bytes[0] != 0x04:
        raise StudentPushInputError("p256dh must be an uncompressed P-256 point")
    if len(auth_bytes) != 16:
        raise StudentPushInputError("auth must be exactly 16 bytes")
    return ParsedSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth)


def valid_announcement_id(value: str) -> bool:
    """Return whether an announcement ID is safe for the push topic/payload."""

    return isinstance(value, str) and _ANNOUNCEMENT_ID_RE.fullmatch(value) is not None


def valid_vapid_subject(value: str) -> bool:
    """Return whether a VAPID subject is a safe mailto or HTTPS URL."""

    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return _MAILTO_RE.fullmatch(value) is not None or (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and not any(char.isspace() for char in value)
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
    )


def vapid_public_key_from_pem(pem: bytes) -> str:
    """Derive an unpadded URL-safe VAPID public key through cryptography."""

    try:
        from cryptography.exceptions import UnsupportedAlgorithm
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ModuleNotFoundError as exc:
        raise StudentPushDependencyError("cryptography is required for VAPID key validation") from exc
    try:
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise StudentPushKeyError("PEM private key is not a P-256 key")
        raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
        raise StudentPushKeyError("PEM private key is invalid") from exc
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def validate_vapid_private_key(pem: bytes) -> None:
    """Vet PEM bytes with the installed cryptography provider before transport."""

    vapid_public_key_from_pem(pem)


__all__ = [
    "JsonValue",
    "ParsedSubscription",
    "StudentPushConfigurationError",
    "StudentPushDependencyError",
    "StudentPushInputError",
    "StudentPushKeyError",
    "SubscriptionInfo",
    "SubscriptionKeys",
    "VapidKeyValidator",
    "parse_subscription",
    "valid_announcement_id",
    "valid_vapid_subject",
    "validate_private_key_path",
    "validate_push_endpoint",
    "validate_public_output_path",
    "validate_vapid_private_key",
    "vapid_public_key_from_pem",
]
