"""Thin Flask adapter for the pure student-app surface policy."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, TypeAlias

from flask import Blueprint, Flask, Response, current_app, g, jsonify, make_response, redirect, request

from .student_app_auth_service import StudentAuthDependencies
from .student_app_config import StudentAppConfig, load_student_app_config
from .student_session_input import StudentSessionInputError
from .student_public_surface import (
    APP_ASSET_PATHS,
    APP_SHELL_PATHS,
    AUTH_ROUTE_METHODS,
    PUSH_ROUTE_METHODS,
    RouteMethod,
    SessionIdentity,
    SessionResolver,
    SurfaceDecision,
    classify_public_path,
)
from .student_public_surface_paths import HeaderValues, exact_host, is_local_host, resolve_client_ip, strict_sid


_SID_QUERY_NAMES: Final[tuple[str, ...]] = ("sid",)
_SID_BODY_NAMES: Final[tuple[str, ...]] = ("sid", "activeSid", "targetSid", "studentSid")
CSRFValidator: TypeAlias = Callable[[str, str | None], bool]


class StudentPublicSurfaceRegistrationError(RuntimeError):
    """Raised when a domain is registered before the public surface hook."""


def _header_values() -> HeaderValues:
    """Capture duplicate-sensitive proxy headers before trust is decided."""
    names = (
        "CF-Connecting-IP",
        "CF-Pseudo-IPv4",
        "CF-Connecting-IPv6",
        "Forwarded",
        "X-Forwarded-For",
        "X-Forwarded-Proto",
        "X-Forwarded-Host",
        "X-Real-IP",
        "True-Client-IP",
    )
    return {name.lower(): tuple(request.headers.getlist(name)) for name in names if request.headers.getlist(name)}


def _default_resolvers(config: StudentAppConfig) -> tuple[SessionResolver, CSRFValidator]:
    """Create lazy session and constant-time CSRF resolvers."""
    dependencies: StudentAuthDependencies | None = None

    def get_dependencies() -> StudentAuthDependencies:
        nonlocal dependencies
        if dependencies is None:
            from .student_app_auth_factory import build_dependencies

            dependencies = build_dependencies(config)
        return dependencies

    def resolve(token: str) -> SessionIdentity | None:
        if not token:
            return None
        try:
            view = get_dependencies().sessions.resolve(token)
        except (OSError, sqlite3.Error, StudentSessionInputError, ValueError):
            return None
        if view is None:
            return None
        active = view.get("active_sid")
        allowed = view.get("allowed_sids")
        if not isinstance(active, str) or not isinstance(allowed, list) or any(not isinstance(sid, str) for sid in allowed):
            return None
        return SessionIdentity(active, tuple(allowed))

    def validate_csrf(token: str, csrf_token: str | None) -> bool:
        if not token or not isinstance(csrf_token, str) or not csrf_token:
            return False
        try:
            return get_dependencies().sessions.resolve(token, csrf_token=csrf_token) is not None
        except (OSError, sqlite3.Error, StudentSessionInputError, ValueError):
            return False

    return resolve, validate_csrf

def _json_response(code: str, status: int) -> Response:
    response = make_response(jsonify({"ok": False, "code": code}), status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _sid_values() -> tuple[tuple[str, ...], bool]:
    """Parse only explicit SID fields; missing fields stay missing."""
    values: list[str] = []
    invalid = False
    for name in _SID_QUERY_NAMES:
        for raw in request.args.getlist(name):
            sid = strict_sid(raw)
            if sid is None:
                invalid = True
            else:
                values.append(sid)
    payload = request.get_json(silent=True)
    if isinstance(payload, Mapping):
        for name in _SID_BODY_NAMES:
            if name not in payload:
                continue
            candidate = payload[name]
            sid = strict_sid(candidate) if isinstance(candidate, str) else None
            if sid is None:
                invalid = True
            else:
                values.append(sid)
        candidates = payload.get("sids")
        if candidates is not None:
            if not isinstance(candidates, list):
                invalid = True
            else:
                for candidate in candidates:
                    sid = strict_sid(candidate) if isinstance(candidate, str) else None
                    if sid is None:
                        invalid = True
                    else:
                        values.append(sid)
    return tuple(values), invalid


@dataclass(slots=True)  # noqa: MUTABLE_OK
class StudentPublicSurface:
    """Flask adapter around the exact route classifier and session gate."""

    config: StudentAppConfig
    session_resolver: SessionResolver
    csrf_validator: CSRFValidator | None = None
    registered_api: set[RouteMethod] = field(default_factory=set)

    def register_api(self, routes: frozenset[RouteMethod]) -> None:
        """Add one explicit domain route set to the central registrar."""
        self.registered_api.update(routes)

    def _is_public_host(self) -> bool:
        host = request.environ.get("werkzeug.proxy_fix.orig_http_host", request.environ.get("HTTP_HOST"))
        if not isinstance(host, str):
            host = request.host
        return exact_host(host, self.config.public_host)

    @staticmethod
    def _raw_scheme() -> str:
        value = request.environ.get("werkzeug.proxy_fix.orig_wsgi.url_scheme", request.environ.get("wsgi.url_scheme"))
        return value if isinstance(value, str) else ""

    @staticmethod
    def _handler_registered(path: str, method: str) -> bool:
        """Require a declared API pair to have a concrete Flask handler."""
        return any(rule.rule == path and method in rule.methods for rule in current_app.url_map.iter_rules())

    def _session(self, decision: SurfaceDecision) -> SessionIdentity | None:
        token = request.cookies.get(self.config.session_cookie_name)
        session = self.session_resolver(token) if isinstance(token, str) else None
        if decision.requires_session and session is None:
            return None
        return session

    def before_request(self) -> Response | None:
        """Apply host, proxy, method, session, origin, and SID boundaries."""
        public_host = self._is_public_host()
        if not public_host:
            return None if is_local_host(request.host) else make_response("", 404)
        if not self.config.public_enabled or self._raw_scheme().lower() != "https":
            return make_response("", 404)
        peer = request.environ.get("werkzeug.proxy_fix.orig_remote_addr", request.environ.get("REMOTE_ADDR"))
        resolution = resolve_client_ip(peer, _header_values(), self.config.trusted_proxy_networks)
        if not resolution.valid:
            return make_response("", 404)
        g.student_app_client_ip = resolution.client_ip
        raw_uri = request.environ.get("RAW_URI")
        if not isinstance(raw_uri, str):
            raw_uri = request.full_path
        decision = classify_public_path(request.path, request.method, frozenset(self.registered_api), raw_uri)
        if not decision.allowed:
            return make_response("", 404)
        if decision.api and not self._handler_registered(request.path, request.method.upper()):
            return make_response("", 404)
        if decision.kind == "root":
            return redirect("/app", code=302)
        session = self._session(decision)
        if decision.requires_session and session is None:
            return _json_response("unauthenticated", 401) if decision.api or decision.kind == "file" else make_response("", 401)
        if decision.sid is not None and (session is None or decision.sid != session.active_sid):
            return _json_response("sid_mismatch", 403) if decision.api else make_response("", 403)
        sid_values, invalid_sid = _sid_values()
        if invalid_sid or sid_values:
            if session is None or invalid_sid or any(sid != session.active_sid for sid in sid_values):
                return _json_response("sid_mismatch", 403) if decision.api else make_response("", 403)
        if decision.api and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if (request.path == "/api/mobile/auth/login" and origin not in {None, f"https://{self.config.public_host}"}) or (
                request.path != "/api/mobile/auth/login" and origin != f"https://{self.config.public_host}"
            ):
                return _json_response("origin_required", 403)
            if request.path != "/api/mobile/auth/login" and self.csrf_validator is not None:
                csrf_token = request.headers.get("X-CSRF-Token")
                if not isinstance(csrf_token, str) or not csrf_token:
                    return _json_response("csrf_required", 403)
                token = request.cookies.get(self.config.session_cookie_name)
                if not isinstance(token, str) or not self.csrf_validator(token, csrf_token):
                    return _json_response("csrf_invalid", 403)
        return None

    def after_request(self, response: Response) -> Response:
        """Apply exact public cache/content headers without touching local responses."""
        if not self._is_public_host():
            return response
        path = request.path
        if path in APP_SHELL_PATHS or path == "/app" or path.startswith("/student/"):
            response.headers["Cache-Control"] = "no-store"
        elif path == "/manifest.webmanifest":
            response.headers.update({"Cache-Control": "no-cache, max-age=0, must-revalidate", "Content-Type": "application/manifest+json; charset=utf-8", "X-Content-Type-Options": "nosniff"})
        elif path == "/sw.js":
            response.headers.update({"Cache-Control": "no-cache, max-age=0, must-revalidate", "Content-Type": "text/javascript; charset=utf-8", "X-Content-Type-Options": "nosniff"})
        elif path in {"/offline.html", "/app/offline-help"}:
            response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
            response.direct_passthrough = False
            response.set_etag(hashlib.sha256(response.get_data()).hexdigest())
        elif path in APP_ASSET_PATHS:
            response.headers.update({"Cache-Control": "public, max-age=0, must-revalidate", "X-Content-Type-Options": "nosniff"})
        elif (path, request.method.upper()) in self.registered_api or path.startswith("/files/announcements/"):
            response.headers["Cache-Control"] = "no-store"
        return response


def register_student_app_domain(app: Flask, blueprint: Blueprint, routes: frozenset[RouteMethod]) -> None:
    """Register one explicit domain through the shared surface registrar."""
    adapter = app.extensions.get("student_public_surface")
    if not isinstance(adapter, StudentPublicSurface):
        raise StudentPublicSurfaceRegistrationError("student public surface registrar is not installed")
    app.register_blueprint(blueprint)
    adapter.register_api(routes)


def install_student_public_surface(
    app: Flask,
    *,
    config: StudentAppConfig | None = None,
    auth_blueprint: Blueprint | None = None,
    session_resolver: SessionResolver | None = None,
    csrf_validator: CSRFValidator | None = None,
) -> StudentPublicSurface:
    """Install the registrar and, when enabled, the current Todo-6 auth domain."""
    chosen = load_student_app_config() if config is None else config
    if session_resolver is None:
        resolver, default_csrf_validator = _default_resolvers(chosen)
    else:
        resolver, default_csrf_validator = session_resolver, None
    adapter = StudentPublicSurface(chosen, resolver, csrf_validator if csrf_validator is not None else default_csrf_validator)
    adapter.register_api(chosen.public_api_route_methods | AUTH_ROUTE_METHODS | PUSH_ROUTE_METHODS)
    app.extensions["student_public_surface"] = adapter
    app.config.update({"STUDENT_APP_PUBLIC_HOST": chosen.public_host, "STUDENT_APP_PUBLIC_ENABLED": chosen.public_enabled})
    app.before_request(adapter.before_request)
    app.after_request(adapter.after_request)
    if auth_blueprint is not None and chosen.public_enabled:
        register_student_app_domain(app, auth_blueprint, AUTH_ROUTE_METHODS)
    return adapter


__all__ = (
    "StudentPublicSurface",
    "StudentPublicSurfaceRegistrationError",
    "install_student_public_surface",
    "register_student_app_domain",
)
