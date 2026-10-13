"""Basic authentication for concrete administrator API routes on every network."""
from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Final

from flask import Flask, current_app, g, jsonify, make_response, request

from core.admin_basic_auth import ADMIN_AUTH_CHALLENGE, verify_admin_authorization
from core.student_public_surface import StudentPublicSurface
from core.student_public_surface_paths import strict_sid


_STUDENT_ROUTE_METHODS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("/api/auth/login", "POST"),
        ("/api/auth/me", "GET"),
        ("/api/auth/me", "HEAD"),
        ("/api/auth/schedules", "GET"),
        ("/api/auth/schedules", "HEAD"),
        ("/api/auth/switch", "POST"),
        ("/api/auth/change", "POST"),
        ("/api/student/bootstrap", "GET"),
        ("/api/student/bootstrap", "HEAD"),
        ("/api/get-url", "GET"),
        ("/api/get-url", "HEAD"),
        ("/api/watch", "POST"),
        ("/api/watch-status", "POST"),
        ("/api/feedback", "POST"),
        ("/api/announce-ack", "POST"),
        ("/api/announce-submit", "POST"),
        ("/api/kollus/lms-callback", "GET"),
        ("/api/kollus/lms-callback", "POST"),
        ("/api/ping", "GET"),
        ("/api/ping", "HEAD"),
    }
)
_SID_QUERY_ROUTE_METHODS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("/api/announcements", "GET"),
        ("/api/announce-status", "GET"),
        ("/api/announce-status", "HEAD"),
        ("/api/watch/latest", "GET"),
        ("/api/watch/latest", "HEAD"),
    }
)


def _mode() -> str:
    value = current_app.config.get("ADMIN_API_GUARD", os.environ.get("ADMIN_API_GUARD", "enforce"))
    normalized = value.strip().lower() if isinstance(value, str) else ""
    return normalized if normalized in {"off", "log", "enforce"} else "enforce"


def _student_request_exempt() -> bool:
    # The public adapter sets this only after its host/session/SID/CSRF checks.
    if getattr(g, "student_app_public_request", False) is True:
        return True
    rule = request.url_rule
    if rule is None or rule.rule != request.path:
        return False
    pair = (request.path, request.method)
    if pair in _STUDENT_ROUTE_METHODS:
        return True
    if pair in _SID_QUERY_ROUTE_METHODS:
        sids = request.args.getlist("sid")
        return len(sids) == 1 and strict_sid(sids[0]) is not None
    if request.path.startswith("/api/mobile/"):
        adapter = current_app.extensions.get("student_public_surface")
        return isinstance(adapter, StudentPublicSurface) and pair in adapter.registered_api
    return False


def install_admin_api_guard(app: Flask, *, excluded_blueprints: Iterable[str] = ()) -> None:
    """Install after the existing public-surface and external-admin hooks.

    ``off`` affects only this hook. ``log`` observes unauthenticated GETs while
    denying other administrator methods. Native student handlers retain their
    existing session, network, callback-secret, and payload checks.
    Explicitly excluded blueprints retain their pre-existing guards unchanged.
    """
    if "admin_api_guard" in app.extensions:
        return
    excluded = frozenset(excluded_blueprints)

    @app.before_request
    def require_admin_api_auth():
        rule = request.url_rule
        # A static catch-all may match an unknown /api/ URL. Preserve its 404,
        # and preserve Flask's own routing errors instead of issuing a 401.
        if (
            request.routing_exception is not None
            or rule is None
            or not rule.rule.startswith("/api/")
        ):
            return None
        if request.blueprint in excluded:
            return None
        mode = _mode()
        if mode == "off" or _student_request_exempt():
            return None
        verifier = current_app.config.get("ACADEMY_ADMIN_AUTHORIZER")
        if not callable(verifier):
            verifier = verify_admin_authorization
        if verifier(request.headers.get("Authorization")):
            return None
        if mode == "log" and request.method == "GET":
            current_app.logger.warning(
                "[ADMIN-API-GUARD] would-deny method=%s route=%s endpoint=%s",
                request.method,
                rule.rule,
                request.endpoint,
            )
            return None
        response = make_response(jsonify({"ok": False, "code": "admin_auth_required"}), 401)
        response.headers.update({"WWW-Authenticate": ADMIN_AUTH_CHALLENGE, "Cache-Control": "no-store"})
        return response

    app.extensions["admin_api_guard"] = require_admin_api_auth


__all__ = ("install_admin_api_guard",)
