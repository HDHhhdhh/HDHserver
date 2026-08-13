"""Pure environment parsing helpers for the public student application."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Final, Mapping, NoReturn, TypeAlias


IPNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network

DEFAULT_PUBLIC_HOST: Final = "app.5a-math.com"
DEFAULT_LEGACY_HOST: Final = "5a-math.com"
DEFAULT_SESSION_COOKIE_NAME: Final = "student_app_session"
DEFAULT_TRUSTED_PROXY_CIDRS: Final[tuple[str, ...]] = ("127.0.0.0/8", "::1/128")
DEFAULT_SESSION_COOKIE_MAX_AGE: Final = 2_592_000
DEFAULT_SESSION_COOKIE_SAMESITE: Final = "Lax"

_TRUE_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})
_COOKIE_NAME_RE: Final = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_SID_RE: Final = re.compile(r"^[^\s,;/\\]+$")
_DNS_LABEL_RE: Final = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class StudentAppConfigurationError(Exception):
    """Raised when an environment value cannot be parsed safely."""

    __slots__ = ("field", "reason", "value")

    def __init__(self, field: str, reason: str, value: str | None = None) -> None:
        self.field = field
        self.reason = reason
        self.value = value
        super().__init__(self.__str__())

    def __str__(self) -> str:
        suffix = "" if self.value is None else f" value={self.value!r}"
        return f"invalid student-app configuration field {self.field!r}: {self.reason}{suffix}"


StudentAppConfigError = StudentAppConfigurationError


def _invalid(field: str, reason: str, value: str | None = None) -> NoReturn:
    raise StudentAppConfigurationError(field, reason, value)


def _raw(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        _invalid(name, "must be text")
    return value


def _bool_value(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _raw(environ, name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    _invalid(name, "expected one of 1/0, true/false, yes/no, on/off", raw)


def _first_bool(environ: Mapping[str, str], names: tuple[str, ...], default: bool) -> bool:
    for name in names:
        if _raw(environ, name) is not None:
            return _bool_value(environ, name, default)
    return default


def _normalize_host(
    raw: str | None,
    *,
    field: str = "STUDENT_APP_PUBLIC_HOST",
    default: str = DEFAULT_PUBLIC_HOST,
) -> str:
    if raw is None:
        raw = default
    value = raw.strip()
    if not value:
        _invalid(field, "must not be empty", raw)
    if not value.isascii() or any(char.isspace() for char in value):
        _invalid(field, "must be one ASCII DNS name", raw)
    if "://" in value or "/" in value or "\\" in value or "," in value:
        _invalid(field, "must not contain a URL, path, or host list", raw)
    if value.count(":") == 1:
        value, port = value.rsplit(":", 1)
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            _invalid(field, "port must be numeric and in range", raw)
    elif ":" in value:
        _invalid(field, "IPv6 literals are not DNS host names", raw)
    if value.endswith("."):
        value = value[:-1]
    if not value or len(value) > 253:
        _invalid(field, "DNS name length is invalid", raw)
    if _is_ip_literal(value):
        _invalid(field, "IP literals are not accepted", raw)
    labels = value.split(".")
    if any(not label or len(label) > 63 or _DNS_LABEL_RE.fullmatch(label) is None for label in labels):
        _invalid(field, "must contain valid DNS labels", raw)
    return value.lower()


def _is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _parse_proxy_networks(environ: Mapping[str, str]) -> tuple[IPNetwork, ...]:
    raw = _raw(environ, "STUDENT_APP_TRUSTED_PROXIES")
    if raw is None:
        values = list(DEFAULT_TRUSTED_PROXY_CIDRS)
    elif not raw.strip():
        return ()
    else:
        values = re.split(r"[\s,;]+", raw.strip())
    networks: list[IPNetwork] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            _invalid("STUDENT_APP_TRUSTED_PROXIES", "contains an empty network", raw)
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            _invalid("STUDENT_APP_TRUSTED_PROXIES", "must contain only IP addresses or CIDRs", raw)
        canonical = str(network)
        if canonical not in seen:
            seen.add(canonical)
            networks.append(network)
    return tuple(networks)


def _parse_canary_sids(environ: Mapping[str, str]) -> frozenset[str]:
    raw = _raw(environ, "STUDENT_APP_CANARY_SIDS")
    if raw is None or not raw:
        return frozenset()
    if any(char.isspace() for char in raw):
        _invalid("STUDENT_APP_CANARY_SIDS", "SID values must not contain whitespace", raw)
    values = raw.split(",")
    if any(not value or _SID_RE.fullmatch(value) is None for value in values):
        _invalid("STUDENT_APP_CANARY_SIDS", "must be a comma-separated exact SID set", raw)
    return frozenset(values)


def _parse_cookie_name(environ: Mapping[str, str]) -> str:
    raw = _raw(environ, "STUDENT_APP_SESSION_COOKIE")
    value = DEFAULT_SESSION_COOKIE_NAME if raw is None else raw.strip()
    if not value or _COOKIE_NAME_RE.fullmatch(value) is None:
        _invalid("STUDENT_APP_SESSION_COOKIE", "must be a valid cookie token", raw)
    return value


def _parse_cookie_max_age(environ: Mapping[str, str]) -> int:
    raw = _raw(environ, "STUDENT_APP_SESSION_MAX_AGE")
    if raw is None:
        return DEFAULT_SESSION_COOKIE_MAX_AGE
    try:
        value = int(raw.strip())
    except ValueError:
        _invalid("STUDENT_APP_SESSION_MAX_AGE", "must be a positive integer", raw)
    if value <= 0:
        _invalid("STUDENT_APP_SESSION_MAX_AGE", "must be a positive integer", raw)
    return value


def _parse_samesite(environ: Mapping[str, str]) -> str:
    raw = _raw(environ, "STUDENT_APP_SESSION_SAMESITE")
    value = DEFAULT_SESSION_COOKIE_SAMESITE.lower() if raw is None else raw.strip().lower()
    normalized = {"lax": "Lax", "strict": "Strict", "none": "None"}.get(value)
    if normalized is None:
        _invalid("STUDENT_APP_SESSION_SAMESITE", "must be Lax, Strict, or None", raw)
    return normalized


def _parse_cookie_secure(environ: Mapping[str, str]) -> bool:
    override = _first_bool(
        environ,
        (
            "STUDENT_APP_TEST_INSECURE_COOKIE",
            "STUDENT_APP_ALLOW_INSECURE_COOKIE_FOR_TESTS",
            "STUDENT_APP_INSECURE_COOKIE_FOR_TESTS",
        ),
        False,
    )
    configured = _first_bool(
        environ,
        ("STUDENT_APP_SESSION_COOKIE_SECURE", "STUDENT_APP_COOKIE_SECURE"),
        True,
    )
    if override:
        return False
    if not configured:
        _invalid(
            "STUDENT_APP_SESSION_COOKIE_SECURE",
            "secure cookies may be disabled only by an explicit test override",
        )
    return True


def _parse_vapid(environ: Mapping[str, str]) -> tuple[str | None, Path | None]:
    subject = _raw(environ, "STUDENT_APP_VAPID_SUBJECT")
    key_raw = _raw(environ, "STUDENT_APP_VAPID_PRIVATE_KEY_PATH")
    if key_raw is None:
        key_raw = _raw(environ, "STUDENT_APP_VAPID_PRIVATE_KEY")
    if subject is None and key_raw is None:
        return None, None
    if subject is None or key_raw is None or not subject.strip() or not key_raw.strip():
        _invalid("STUDENT_APP_VAPID_SUBJECT", "subject and private-key path must be configured together")
    if not (subject.startswith("mailto:") or subject.startswith("https://")):
        _invalid("STUDENT_APP_VAPID_SUBJECT", "must be a mailto: or https: URL", subject)
    if "\x00" in key_raw:
        _invalid("STUDENT_APP_VAPID_PRIVATE_KEY_PATH", "must not contain NUL", key_raw)
    return subject.strip(), Path(key_raw.strip())


__all__ = (
    "DEFAULT_LEGACY_HOST",
    "DEFAULT_PUBLIC_HOST",
    "DEFAULT_SESSION_COOKIE_MAX_AGE",
    "DEFAULT_SESSION_COOKIE_NAME",
    "DEFAULT_SESSION_COOKIE_SAMESITE",
    "DEFAULT_TRUSTED_PROXY_CIDRS",
    "IPNetwork",
    "StudentAppConfigError",
    "StudentAppConfigurationError",
)
