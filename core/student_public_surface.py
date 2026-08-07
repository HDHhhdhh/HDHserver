"""Pure route and method policy for the public student application."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, TypeAlias

from .student_public_surface_paths import parse_student_page_sid, safe_announcement_file


RouteMethod: TypeAlias = tuple[str, str]
SessionResolver: TypeAlias = Callable[[str], "SessionIdentity | None"]

AUTH_ROUTE_METHODS: Final[frozenset[RouteMethod]] = frozenset(
    {
        ("/api/mobile/auth/login", "POST"),
        ("/api/mobile/auth/session", "GET"),
        ("/api/mobile/auth/credentials", "POST"),
        ("/api/mobile/auth/switch", "POST"),
        ("/api/mobile/auth/logout", "POST"),
    }
)
PUSH_ROUTE_METHODS: Final[frozenset[RouteMethod]] = frozenset(
    {
        ("/api/mobile/push/config", "GET"),
        ("/api/mobile/push/subscription", "PUT"),
        ("/api/mobile/push/subscription", "DELETE"),
        ("/api/mobile/push/lease", "POST"),
        ("/api/mobile/push/gate", "GET"),
    }
)
PUBLIC_API_ROUTE_METHODS: Final[frozenset[RouteMethod]] = AUTH_ROUTE_METHODS | PUSH_ROUTE_METHODS
APP_SHELL_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/app/",
        "/app/login",
        "/app/help",
        "/app/home",
        "/app/checks",
        "/app/inbox",
        "/app/materials",
        "/app/tests",
        "/app/videos",
    }
)
APP_ASSET_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/css/student-app.css",
        "/css/student.css",
        "/js/student-app.js",
        "/js/student.js",
        "/icons/student-app-192.png",
        "/icons/student-app-512.png",
        "/icons/student-app-maskable-512.png",
    }
)
APP_PUBLIC_PATHS: Final[frozenset[str]] = APP_SHELL_PATHS | APP_ASSET_PATHS | frozenset(
    {"/app", "/manifest.webmanifest", "/sw.js", "/offline.html", "/app/offline-help"}
)


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    """Minimal server-derived session identity used by boundary checks."""

    active_sid: str
    allowed_sids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SurfaceDecision:
    """Pure classification result for one host/path/method tuple."""

    allowed: bool
    kind: str
    requires_session: bool = False
    api: bool = False
    sid: str | None = None


def classify_public_path(
    path: str,
    method: str,
    registered_api: frozenset[RouteMethod],
    raw_uri: str | None = None,
) -> SurfaceDecision:
    """Classify one exact public route; undeclared methods are denied."""
    normalized_method = method.upper()
    if path == "/":
        return SurfaceDecision(True, "root") if normalized_method in {"GET", "HEAD"} else SurfaceDecision(False, "deny")
    if path == "/app":
        return SurfaceDecision(True, "page") if normalized_method in {"GET", "HEAD"} else SurfaceDecision(False, "deny")
    if path in APP_SHELL_PATHS:
        return SurfaceDecision(True, "page") if normalized_method in {"GET", "HEAD"} else SurfaceDecision(False, "deny")
    if path == "/manifest.webmanifest":
        return SurfaceDecision(True, "manifest") if normalized_method in {"GET", "HEAD"} else SurfaceDecision(False, "deny")
    if path == "/sw.js":
        return SurfaceDecision(True, "worker") if normalized_method in {"GET", "HEAD"} else SurfaceDecision(False, "deny")
    if path in {"/offline.html", "/app/offline-help"}:
        return SurfaceDecision(True, "offline") if normalized_method in {"GET", "HEAD"} else SurfaceDecision(False, "deny")
    if path in APP_ASSET_PATHS:
        return SurfaceDecision(True, "asset") if normalized_method in {"GET", "HEAD"} else SurfaceDecision(False, "deny")
    if path.startswith("/student/"):
        sid = parse_student_page_sid(path)
        if sid is None:
            return SurfaceDecision(False, "deny")
        return SurfaceDecision(True, "student-page", True, False, sid) if normalized_method in {"GET", "HEAD"} else SurfaceDecision(False, "deny")
    if safe_announcement_file(path, raw_uri):
        return SurfaceDecision(True, "file", True) if normalized_method in {"GET", "HEAD"} else SurfaceDecision(False, "deny")
    route = (path, normalized_method)
    if route in registered_api:
        requires_session = path != "/api/mobile/auth/login"
        return SurfaceDecision(True, "api", requires_session, True)
    return SurfaceDecision(False, "deny")


from .student_public_surface_adapter import (
    StudentPublicSurface,
    install_student_public_surface,
    register_student_app_domain,
)


__all__ = (
    "APP_ASSET_PATHS",
    "APP_PUBLIC_PATHS",
    "APP_SHELL_PATHS",
    "AUTH_ROUTE_METHODS",
    "PUSH_ROUTE_METHODS",
    "PUBLIC_API_ROUTE_METHODS",
    "SessionIdentity",
    "SessionResolver",
    "SurfaceDecision",
    "classify_public_path",
    "install_student_public_surface",
    "register_student_app_domain",
)
