"""Academy-only administrative API for student mobile-app accounts."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from flask import Blueprint, Response, jsonify, make_response, request

from core.admin_basic_auth import ADMIN_AUTH_CHALLENGE, verify_admin_authorization
from core.student_account_admin_service import (
    StudentAccountAdminDependencies,
    StudentAccountAdminError,
    StudentAccountAdminService,
)
from core.student_account_audit import StudentAccountAuditRepository
from core.student_account_repository import StudentAccountRepository
from core.student_activation_codes import StudentActivationCodeRepository
from core.student_app_config import StudentAppConfig, load_student_app_config
from core.student_public_surface_paths import exact_host
from core.student_push_repository import StudentPushRepository
from core.student_sessions import StudentSessionRepository


def _default_dependencies(
    *,
    root: Path | None = None,
    accounts_path: Path | None = None,
    students_path: Path | None = None,
    db_path: Path | None = None,
) -> StudentAccountAdminDependencies:
    base = Path(__file__).resolve().parents[1] if root is None else Path(root)
    accounts_file = accounts_path or Path(os.environ.get("STUDENT_APP_ACCOUNTS_PATH", base / "auth_accounts.json"))
    students_file = students_path or Path(os.environ.get("STUDENT_APP_STUDENTS_PATH", base / "students.json"))
    database = db_path or Path(os.environ.get("STUDENT_APP_DB_PATH", base / "app.sqlite"))
    return StudentAccountAdminDependencies(
        accounts=StudentAccountRepository(accounts_file, students_file),
        sessions=StudentSessionRepository(database),
        push=StudentPushRepository(database),
        activations=StudentActivationCodeRepository(database),
        audit=StudentAccountAuditRepository(database),
    )


@dataclass(slots=True)  # noqa: MUTABLE_OK
class _DependencyProvider:
    dependencies: StudentAccountAdminDependencies | None
    selected_config: StudentAppConfig | None
    factory: Callable[[], StudentAccountAdminDependencies]

    def config(self) -> StudentAppConfig:
        if self.selected_config is None:
            self.selected_config = load_student_app_config()
        return self.selected_config

    def service(self) -> StudentAccountAdminService:
        if self.dependencies is None:
            self.dependencies = self.factory()
        return StudentAccountAdminService(self.dependencies)


def _error(code: str, status: int) -> tuple[Response, int]:
    response = jsonify({"ok": False, "code": code})
    response.headers["Cache-Control"] = "no-store"
    return response, status


def _success(payload: dict[str, Any]) -> Response:
    response = jsonify({"ok": True, **payload})
    response.headers["Cache-Control"] = "no-store"
    return response


def _body() -> dict[str, Any]:
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    if not request.is_json:
        raise StudentAccountAdminError("invalid_json", 400)
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise StudentAccountAdminError("invalid_json", 400)
    return value


def _empty_body() -> None:
    if _body():
        raise StudentAccountAdminError("malformed_request", 400)


def _reset_body() -> None:
    body = _body()
    if not body:
        return
    if set(body) not in ({"password"}, {"temporaryPassword"}):
        raise StudentAccountAdminError("malformed_request", 400)
    value = body.get("password", body.get("temporaryPassword"))
    if value != "1234":
        raise StudentAccountAdminError("invalid_reset_password", 400)


def _original_host() -> str:
    value = request.environ.get("werkzeug.proxy_fix.orig_http_host", request.environ.get("HTTP_HOST"))
    return value if isinstance(value, str) else request.host


def create_blueprint(
    dependencies: StudentAccountAdminDependencies | None = None,
    *,
    config: StudentAppConfig | None = None,
    root: Path | None = None,
    accounts_path: Path | None = None,
    students_path: Path | None = None,
    db_path: Path | None = None,
    admin_authorizer: Callable[[str | None], bool] | None = None,
) -> Blueprint:
    """Create a lazy, injectable blueprint that never imports runtime paths."""
    provider = _DependencyProvider(
        dependencies,
        config,
        lambda: _default_dependencies(root=root, accounts_path=accounts_path, students_path=students_path, db_path=db_path),
    )
    blueprint = Blueprint("student_accounts", __name__, url_prefix="/api/student-accounts")
    authorize = admin_authorizer or verify_admin_authorization

    @blueprint.before_request
    def gate_admin_surface() -> Response | tuple[Response, int] | None:
        if exact_host(_original_host(), provider.config().public_host):
            response = make_response("", 404)
            response.headers["Cache-Control"] = "no-store"
            return response
        if not authorize(request.headers.get("Authorization")):
            response, status = _error("admin_auth_required", 401)
            response.headers["WWW-Authenticate"] = ADMIN_AUTH_CHALLENGE
            return response, status
        return None

    def execute(operation: Callable[[StudentAccountAdminService], dict[str, Any]]) -> Response | tuple[Response, int]:
        try:
            return _success(operation(provider.service()))
        except StudentAccountAdminError as exc:
            return _error(exc.code, exc.status)
        except (OSError, sqlite3.Error, ValueError):
            return _error("operation_failed", 409)

    @blueprint.get("")
    def list_accounts() -> Response | tuple[Response, int]:
        return execute(lambda service: {"groups": service.list_groups()})

    @blueprint.post("/<aid>/reset")
    def reset(aid: str) -> Response | tuple[Response, int]:
        def operation(service: StudentAccountAdminService) -> dict[str, Any]:
            _reset_body()
            return service.reset(aid)
        return execute(operation)

    @blueprint.post("/<aid>/disable")
    def disable(aid: str) -> Response | tuple[Response, int]:
        def operation(service: StudentAccountAdminService) -> dict[str, Any]:
            _empty_body()
            return service.disable(aid)
        return execute(operation)

    @blueprint.post("/<aid>/enable")
    def enable(aid: str) -> Response | tuple[Response, int]:
        def operation(service: StudentAccountAdminService) -> dict[str, Any]:
            _empty_body()
            return service.enable(aid)
        return execute(operation)

    @blueprint.post("/<aid>/revoke-sessions")
    def revoke_sessions(aid: str) -> Response | tuple[Response, int]:
        def operation(service: StudentAccountAdminService) -> dict[str, Any]:
            _empty_body()
            return service.revoke_sessions(aid)
        return execute(operation)

    @blueprint.post("/<aid>/activation-code")
    def activation_code(aid: str) -> Response | tuple[Response, int]:
        def operation(service: StudentAccountAdminService) -> dict[str, Any]:
            body = _body()
            if set(body) != {"sids"}:
                raise StudentAccountAdminError("invalid_sids", 400)
            return service.issue_activation_code(aid, body["sids"])
        return execute(operation)

    return blueprint


create_student_accounts_blueprint = create_blueprint
bp_api_student_accounts = create_blueprint()


__all__ = ["bp_api_student_accounts", "create_blueprint", "create_student_accounts_blueprint"]
