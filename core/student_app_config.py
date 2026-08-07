"""Side-effect-free configuration for the public student application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

from .student_app_config_parsing import (
    DEFAULT_PUBLIC_HOST,
    DEFAULT_SESSION_COOKIE_MAX_AGE,
    DEFAULT_SESSION_COOKIE_NAME,
    DEFAULT_SESSION_COOKIE_SAMESITE,
    DEFAULT_TRUSTED_PROXY_CIDRS,
    IPNetwork,
    StudentAppConfigError,
    StudentAppConfigurationError,
    _DNS_LABEL_RE,
    _FALSE_VALUES,
    _SID_RE,
    _TRUE_VALUES,
    _COOKIE_NAME_RE,
    _bool_value,
    _first_bool,
    _invalid,
    _is_ip_literal,
    _normalize_host,
    _parse_canary_sids,
    _parse_cookie_max_age,
    _parse_cookie_name,
    _parse_cookie_secure,
    _parse_proxy_networks,
    _parse_samesite,
    _parse_vapid,
    _raw,
)

# Keep the exception's import and pickle identity rooted at this public module.
StudentAppConfigurationError.__module__ = __name__


PUBLIC_PAGE_ROUTES: Final[frozenset[str]] = frozenset({"/app", "/app/", "/student/<sid>"})
PUBLIC_STATIC_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/manifest.webmanifest",
        "/manifest.json",
        "/sw.js",
        "/css/student-app.css",
        "/js/student-app.js",
        "/js/student.js",
        "/icons/icon-192.png",
        "/icons/icon-512.png",
    }
)
PUBLIC_SENSITIVE_STATIC_PATHS: Final[frozenset[str]] = frozenset(
    {"/js/test_answer_link_map.json", "/js/test_answer_link_map.js"}
)
PUBLIC_API_ROUTE_METHODS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("/api/mobile/auth/login", "POST"),
        ("/api/mobile/auth/session", "GET"),
        ("/api/mobile/auth/credentials", "POST"),
        ("/api/mobile/auth/switch", "POST"),
        ("/api/mobile/auth/logout", "POST"),
        ("/api/student/bootstrap", "GET"),
        ("/api/watch/latest", "GET"),
        ("/api/watch", "GET"),
        ("/api/watch", "POST"),
        ("/api/watch-status", "POST"),
        ("/api/feedback", "POST"),
        ("/api/get-url", "GET"),
        ("/api/announcements", "GET"),
        ("/api/announce-status", "GET"),
        ("/api/announce-ack", "POST"),
        ("/api/announce-submit", "POST"),
        ("/api/tests-config", "GET"),
        ("/api/submit-test", "POST"),
    }
)


@dataclass(frozen=True, slots=True)
class StudentAppCookieSettings:
    """Immutable cookie attributes emitted by public auth routes."""

    name: str
    path: str
    secure: bool
    httponly: bool
    samesite: str
    max_age: int
    domain: None = None


@dataclass(frozen=True, slots=True)
class StudentAppConfig:
    """Parsed public-app settings; construction performs no I/O."""

    public_enabled: bool
    public_host: str
    trusted_proxy_networks: tuple[IPNetwork, ...]
    session_cookie_name: str
    session_cookie_secure: bool
    session_cookie_samesite: str
    session_cookie_path: str
    session_cookie_max_age: int
    canary_sids: frozenset[str]
    vapid_subject: str | None
    vapid_private_key_path: Path | None
    public_page_routes: frozenset[str] = PUBLIC_PAGE_ROUTES
    public_static_paths: frozenset[str] = PUBLIC_STATIC_PATHS
    public_sensitive_static_paths: frozenset[str] = PUBLIC_SENSITIVE_STATIC_PATHS
    public_api_route_methods: frozenset[tuple[str, str]] = PUBLIC_API_ROUTE_METHODS

    @property
    def trusted_proxy_cidrs(self) -> tuple[str, ...]:
        """Return canonical proxy networks suitable for a redacted dump."""
        return tuple(str(network) for network in self.trusted_proxy_networks)

    @property
    def cookie(self) -> StudentAppCookieSettings:
        """Return immutable attributes for the session cookie."""
        return StudentAppCookieSettings(
            name=self.session_cookie_name,
            path=self.session_cookie_path,
            secure=self.session_cookie_secure,
            httponly=True,
            samesite=self.session_cookie_samesite,
            max_age=self.session_cookie_max_age,
        )

    @property
    def canary_restricted(self) -> bool:
        """Whether rollout is restricted to the configured SID set."""
        return bool(self.canary_sids)

    def allows_canary_sid(self, sid: str) -> bool:
        """Return whether ``sid`` is allowed by the optional canary gate."""
        return not self.canary_sids or sid in self.canary_sids

    def redacted_dict(self) -> dict[str, str | bool | int | tuple[str, ...]]:
        """Serialize safe diagnostics without secrets or key paths."""
        return {
            "public_enabled": self.public_enabled,
            "public_host": self.public_host,
            "trusted_proxy_cidrs": self.trusted_proxy_cidrs,
            "session_cookie_name": self.session_cookie_name,
            "session_cookie_secure": self.session_cookie_secure,
            "session_cookie_samesite": self.session_cookie_samesite,
            "session_cookie_path": self.session_cookie_path,
            "session_cookie_max_age": self.session_cookie_max_age,
            "canary_sids": tuple(sorted(self.canary_sids)),
            "vapid_configured": self.vapid_subject is not None,
        }

    as_dict = redacted_dict


StudentAppSettings = StudentAppConfig


def load_student_app_config(environ: Mapping[str, str] | None = None) -> StudentAppConfig:
    """Parse one environment mapping into an immutable student-app config."""
    values: Mapping[str, str] = os.environ if environ is None else dict(environ)
    public_enabled = _bool_value(values, "STUDENT_APP_PUBLIC_ENABLED", False)
    public_host = _normalize_host(_raw(values, "STUDENT_APP_PUBLIC_HOST"))
    cookie_name = _parse_cookie_name(values)
    cookie_secure = _parse_cookie_secure(values)
    cookie_samesite = _parse_samesite(values)
    if cookie_samesite == "None" and not cookie_secure:
        _invalid("STUDENT_APP_SESSION_SAMESITE", "None requires a secure cookie")
    vapid_subject, vapid_private_key_path = _parse_vapid(values)
    return StudentAppConfig(
        public_enabled=public_enabled,
        public_host=public_host,
        trusted_proxy_networks=_parse_proxy_networks(values),
        session_cookie_name=cookie_name,
        session_cookie_secure=cookie_secure,
        session_cookie_samesite=cookie_samesite,
        session_cookie_path="/",
        session_cookie_max_age=_parse_cookie_max_age(values),
        canary_sids=_parse_canary_sids(values),
        vapid_subject=vapid_subject,
        vapid_private_key_path=vapid_private_key_path,
    )


load_config = load_student_app_config
from_env = load_student_app_config


__all__ = (
    "DEFAULT_PUBLIC_HOST",
    "DEFAULT_SESSION_COOKIE_MAX_AGE",
    "DEFAULT_SESSION_COOKIE_NAME",
    "DEFAULT_TRUSTED_PROXY_CIDRS",
    "IPNetwork",
    "PUBLIC_API_ROUTE_METHODS",
    "PUBLIC_PAGE_ROUTES",
    "PUBLIC_SENSITIVE_STATIC_PATHS",
    "PUBLIC_STATIC_PATHS",
    "StudentAppConfig",
    "StudentAppConfigError",
    "StudentAppConfigurationError",
    "StudentAppCookieSettings",
    "StudentAppSettings",
    "from_env",
    "load_config",
    "load_student_app_config",
)
