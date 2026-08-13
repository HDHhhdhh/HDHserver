"""Flask response adapter for the exact legacy student origin."""

from __future__ import annotations

from flask import Request, Response, make_response, redirect

from .student_app_config import StudentAppConfig
from .student_legacy_surface import is_app_only_path
from .student_public_surface_paths import resolve_raw_request_target


def legacy_surface_response(request_ref: Request, config: StudentAppConfig) -> Response | None:
    """Serve legacy routes until both independent rollout switches are approved."""
    if is_app_only_path(request_ref.path):
        return make_response("", 404)
    if not (
        config.public_enabled
        and config.legacy_redirect_enabled
        and request_ref.method.upper() in {"GET", "HEAD"}
        and request_ref.path == "/"
    ):
        return None
    raw_uri = resolve_raw_request_target(request_ref.environ, request_ref.full_path.removesuffix("?"))
    if raw_uri != "/":
        return None
    response = redirect(f"https://{config.public_host}/app", code=302)
    response.headers["Cache-Control"] = "no-store"
    return response


__all__ = ("legacy_surface_response",)
