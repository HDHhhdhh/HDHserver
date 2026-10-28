"""Thin Flask adapter for the pure student-app surface policy."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, TypeAlias

from flask import Blueprint, Flask, Response, current_app, g, jsonify, make_response, redirect, request

from .network_access import ip_allowed
from .student_app_config import PUBLIC_SENSITIVE_STATIC_PATHS, StudentAppConfig, load_student_app_config
from .student_legacy_surface_adapter import legacy_surface_response
from .student_public_session_resolver import build_default_resolvers
from .student_public_proxy import (
    effective_scheme,
    local_request_allowed,
    proxy_header_values,
    public_host_matches,
    resolve_proxy_client,
)
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
from .student_public_surface_paths import resolve_raw_request_target, strict_sid


_SID_QUERY_NAMES: Final[tuple[str, ...]] = ("sid",)
_SID_BODY_NAMES: Final[tuple[str, ...]] = ("sid", "activeSid", "targetSid", "studentSid")
_SWITCH_ROUTE: Final[RouteMethod] = ("/api/mobile/auth/switch", "POST")
_SWITCH_TARGET_BODY_NAMES: Final[frozenset[str]] = frozenset({"sid", "targetSid"})
_CREDENTIALS_REQUIRED_EXEMPT: Final[frozenset[RouteMethod]] = frozenset(
    {
        ("/api/mobile/auth/session", "GET"),
        ("/api/mobile/auth/credentials", "POST"),
        ("/api/mobile/auth/logout", "POST"),
    }
)
CSRFValidator: TypeAlias = Callable[[str, str | None], bool]


class StudentPublicSurfaceRegistrationError(RuntimeError):
    """Raised when a domain is registered before the public surface hook."""


def _json_response(code: str, status: int, *, state: str | None = None) -> Response:
    payload = {"ok": False, "code": code}
    if state is not None:
        payload["state"] = state
    response = make_response(jsonify(payload), status)
    response.headers["Cache-Control"] = "no-store"
    return response


def _sid_values(*, exempt_body_names: frozenset[str] = frozenset()) -> tuple[tuple[str, ...], bool]:
    """Parse only explicit SID fields; missing fields stay missing."""
    values: list[str] = []
    exempt_count = 0
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
            elif name in exempt_body_names:
                exempt_count += 1
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
    if exempt_count > 1:
        invalid = True
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

    @staticmethod
    def _handler_registered(path: str, method: str) -> bool:
        """Require a declared API pair to have a concrete Flask handler."""
        return request.url_rule is not None and method in request.url_rule.methods

    def _session(self, decision: SurfaceDecision) -> SessionIdentity | None:
        token = request.cookies.get(self.config.session_cookie_name)
        session = self.session_resolver(token) if isinstance(token, str) else None
        if decision.requires_session and session is None:
            return None
        return session

    def before_request(self) -> Response | None:
        """Apply host, proxy, method, session, origin, and SID boundaries."""
        public_host = public_host_matches(request.environ, self.config.public_host, self.config.trusted_proxy_networks)
        if public_host_matches(request.environ, self.config.legacy_host, self.config.trusted_proxy_networks):
            return legacy_surface_response(request, self.config)
        if not public_host:
            return None if local_request_allowed(request.environ, ip_allowed) else make_response("", 404)
        if not self.config.public_enabled or effective_scheme(request.environ, self.config.trusted_proxy_networks).lower() != "https":
            return make_response("", 404)
        resolution = resolve_proxy_client(
            request.environ,
            proxy_header_values(request.headers),
            self.config.trusted_proxy_networks,
        )
        if not resolution.valid:
            return make_response("", 404)
        g.student_app_client_ip = resolution.client_ip
        raw_uri = resolve_raw_request_target(request.environ, request.full_path.removesuffix("?"))
        if raw_uri is None:
            return make_response("", 404)
        decision = classify_public_path(request.path, request.method, frozenset(self.registered_api), raw_uri)
        if not decision.allowed:
            return make_response("", 404)
        if decision.api and not self._handler_registered(request.path, request.method.upper()):
            return make_response("", 404)
        if decision.kind == "root":
            response = redirect("/app", code=302)
            response.headers["Cache-Control"] = "no-store"
            return response
        session = self._session(decision)
        if decision.requires_session and session is None:
            return _json_response("unauthenticated", 401) if decision.api or decision.kind == "file" else make_response("", 401)
        route_method = (request.path, request.method.upper())
        if (
            decision.requires_session
            and session is not None
            and session.credentials_required
            and route_method not in _CREDENTIALS_REQUIRED_EXEMPT
        ):
            return _json_response("credentials_required", 403, state="credentials_required")
        if decision.sid is not None and (session is None or decision.sid != session.active_sid):
            return _json_response("sid_mismatch", 403) if decision.api else make_response("", 403)
        exempt_body_names = _SWITCH_TARGET_BODY_NAMES if route_method == _SWITCH_ROUTE else frozenset()
        sid_values, invalid_sid = _sid_values(exempt_body_names=exempt_body_names)
        if invalid_sid or sid_values:
            if session is None or invalid_sid or any(sid != session.active_sid for sid in sid_values):
                return _json_response("sid_mismatch", 403) if decision.api else make_response("", 403)
        csrf_validated = False
        if decision.api and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if (request.path == "/api/mobile/auth/login" and origin not in {None, f"https://{self.config.public_host}"}) or (
                request.path != "/api/mobile/auth/login" and origin != f"https://{self.config.public_host}"
            ):
                return _json_response("origin_required", 403)
            if request.path != "/api/mobile/auth/login":
                csrf_token = request.headers.get("X-CSRF-Token")
                if not isinstance(csrf_token, str) or not csrf_token:
                    return _json_response("csrf_required", 403)
                token = request.cookies.get(self.config.session_cookie_name)
                validator = self.csrf_validator
                if not isinstance(token, str) or validator is None or not validator(token, csrf_token):
                    return _json_response("csrf_invalid", 403)
                csrf_validated = True
        # Downstream handlers receive only resolved, non-secret authority.
        # Never expose the opaque cookie or raw CSRF token through ``g``.
        g.student_app_public_request = True
        g.student_app_session = (
            SessionIdentity(session.active_sid, session.allowed_sids, session.credentials_required)
            if session is not None
            else None
        )
        g.student_app_active_sid = session.active_sid if session is not None else None
        g.student_app_allowed_sids = session.allowed_sids if session is not None else ()
        g.student_app_csrf_validated = csrf_validated
        return None

    def after_request(self, response: Response) -> Response:
        """Apply exact public cache/content headers without touching local responses."""
        if not public_host_matches(request.environ, self.config.public_host, self.config.trusted_proxy_networks):
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
        elif path in PUBLIC_SENSITIVE_STATIC_PATHS:
            response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        elif (path, request.method.upper()) in self.registered_api or path.startswith(("/files/announcements/", "/api/mobile/")):
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
        resolver, default_csrf_validator = build_default_resolvers(chosen, SessionIdentity)
    else:
        resolver, default_csrf_validator = session_resolver, None
    adapter = StudentPublicSurface(chosen, resolver, csrf_validator if csrf_validator is not None else default_csrf_validator)
    adapter.register_api(chosen.public_api_route_methods | AUTH_ROUTE_METHODS | PUSH_ROUTE_METHODS)
    app.extensions["student_public_surface"] = adapter
    app.config.update(
        {
            "STUDENT_APP_PUBLIC_HOST": chosen.public_host,
            "STUDENT_APP_PUBLIC_ENABLED": chosen.public_enabled,
            "STUDENT_APP_DASHBOARD_ENABLED": chosen.dashboard_enabled,
            "STUDENT_APP_HOMEWORK_ENABLED": chosen.homework_enabled,
            "STUDENT_APP_REMINDERS_ENABLED": chosen.reminders_enabled,
            "STUDENT_APP_FOCUS_ENABLED": chosen.focus_enabled,
        }
    )
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
