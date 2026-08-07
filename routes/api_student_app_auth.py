"""Public PWA cookie-auth blueprint; registration is intentionally owned by Todo 7."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from flask import Blueprint, Response, g, jsonify, request

from core.student_app_auth_factory import build_dependencies
from core.student_app_auth_service import (
    AuthExchange,
    StudentAuthDependencies,
    StudentAuthFailure,
    StudentAuthService,
    signed_out_response,
)
from core.student_app_config import StudentAppConfig


@dataclass(slots=True)  # noqa: MUTABLE_OK
class _DependencyProvider:
    """Lazily cache defaults so importing/registering the blueprint is pure."""

    dependencies: StudentAuthDependencies | None = None
    factory: Callable[[], StudentAuthDependencies] | None = None

    def get(self) -> StudentAuthDependencies:
        if self.dependencies is None:
            self.dependencies = build_dependencies() if self.factory is None else self.factory()
        return self.dependencies


def _body() -> Mapping[str, str]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, str)}


def _value(data: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = data.get(name)
        if value is not None:
            return value
    return ""


def _resolved_client_ip() -> str:
    """Use the public-surface resolver's explicit client-IP context when present."""
    value = getattr(g, "student_app_client_ip", None)
    return value if isinstance(value, str) and value else (request.remote_addr or "127.0.0.1")


def _error(exc: StudentAuthFailure) -> tuple[Response, int]:
    payload: dict[str, str | bool] = {"ok": False, "code": exc.code}
    if exc.state != "error":
        payload["state"] = exc.state
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    if exc.retry_after > 0:
        response.headers["Retry-After"] = str(exc.retry_after)
    return response, exc.status


def _cookie(response: Response, exchange: AuthExchange, dependencies: StudentAuthDependencies, *, clear: bool = False) -> Response:
    settings = dependencies.config.cookie
    if exchange.token is not None:
        response.set_cookie(
            settings.name,
            exchange.token,
            max_age=settings.max_age,
            path=settings.path,
            secure=settings.secure,
            httponly=settings.httponly,
            samesite=settings.samesite,
        )
    elif clear:
        response.set_cookie(
            settings.name,
            "",
            max_age=0,
            expires=0,
            path=settings.path,
            secure=settings.secure,
            httponly=settings.httponly,
            samesite=settings.samesite,
        )
    return response


def _finish(exchange: AuthExchange, dependencies: StudentAuthDependencies, *, clear: bool = False) -> Response:
    response = jsonify(exchange.response)
    response.headers["Cache-Control"] = "no-store"
    return _cookie(response, exchange, dependencies, clear=clear)


def create_blueprint(
    dependencies: StudentAuthDependencies | None = None,
    *,
    config: StudentAppConfig | None = None,
    root: Path | None = None,
    accounts_path: Path | None = None,
    students_path: Path | None = None,
    db_path: Path | None = None,
) -> Blueprint:
    """Create a testable blueprint with optional temporary repositories."""
    provider = _DependencyProvider(dependencies)
    if dependencies is None and (config is not None or root is not None or accounts_path is not None or students_path is not None or db_path is not None):
        provider.factory = lambda: build_dependencies(config, root=root, accounts_path=accounts_path, students_path=students_path, db_path=db_path)
    blueprint = Blueprint("student_app_auth", __name__, url_prefix="/api/mobile/auth")

    def service() -> tuple[StudentAuthService, StudentAuthDependencies]:
        selected = provider.get()
        return StudentAuthService(selected), selected

    @blueprint.post("/login")
    def login() -> tuple[Response, int] | Response:
        data = _body()
        try:
            current, selected = service()
            exchange = current.login(_value(data, "id", "accountId", "studentId", "name"), _value(data, "password", "pw"), _value(data, "activationCode", "code"), _resolved_client_ip())
            return _finish(exchange, selected)
        except StudentAuthFailure as exc:
            return _error(exc)

    @blueprint.get("/session")
    def session() -> tuple[Response, int] | Response:
        token = request.cookies.get(provider.get().config.cookie.name)
        if not token:
            return _finish(signed_out_response(), provider.get())
        try:
            current, selected = service()
            return _finish(current.session(token), selected)
        except StudentAuthFailure as exc:
            return _error(exc)

    @blueprint.post("/credentials")
    def credentials() -> tuple[Response, int] | Response:
        selected = provider.get()
        token = request.cookies.get(selected.config.cookie.name)
        if not token:
            return _error(StudentAuthFailure("unauthenticated", 401))
        try:
            current, _selected = service()
            data = _body()
            exchange = current.credentials(token, request.headers.get("X-CSRF-Token"), _value(data, "studentId", "id", "accountId"), _value(data, "password", "newPassword"))
            return _finish(exchange, selected)
        except StudentAuthFailure as exc:
            return _error(exc)

    @blueprint.post("/switch")
    def switch() -> tuple[Response, int] | Response:
        selected = provider.get()
        token = request.cookies.get(selected.config.cookie.name)
        if not token:
            return _error(StudentAuthFailure("unauthenticated", 401))
        try:
            current, _selected = service()
            target = _value(_body(), "sid", "targetSid")
            return _finish(current.switch(token, request.headers.get("X-CSRF-Token"), target), selected)
        except StudentAuthFailure as exc:
            return _error(exc)

    @blueprint.post("/logout")
    def logout() -> tuple[Response, int] | Response:
        selected = provider.get()
        token = request.cookies.get(selected.config.cookie.name)
        if not token:
            return _error(StudentAuthFailure("unauthenticated", 401))
        try:
            current, _selected = service()
            return _finish(current.logout(token, request.headers.get("X-CSRF-Token")), selected, clear=True)
        except StudentAuthFailure as exc:
            return _error(exc)

    return blueprint


create_student_app_auth_blueprint = create_blueprint
bp_api_student_app_auth = create_blueprint()


__all__ = ["bp_api_student_app_auth", "create_blueprint", "create_student_app_auth_blueprint"]
