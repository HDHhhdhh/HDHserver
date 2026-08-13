"""Types shared by the student-app authentication route and service."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from core.student_account_repository import StudentAccountRepository
from core.student_activation_codes import StudentActivationCodeRepository
from core.student_app_auth_store import Curriculum
from core.student_app_config import StudentAppConfig
from core.student_login_throttle import StudentLoginThrottleRepository
from core.student_sessions import StudentSessionRepository


class AuthResponse(TypedDict):
    ok: bool
    state: str
    sid: str | None
    curris: list[Curriculum]
    csrfToken: str | None
    pushState: str


@dataclass(frozen=True, slots=True)
class StudentAuthDependencies:
    config: StudentAppConfig
    accounts: StudentAccountRepository
    sessions: StudentSessionRepository
    activations: StudentActivationCodeRepository
    throttle: StudentLoginThrottleRepository
    students_path: Path


@dataclass(frozen=True, slots=True)
class AuthExchange:
    response: AuthResponse
    token: str | None = None
    csrf_token: str | None = None


@dataclass(frozen=True, slots=True)
class StudentAuthFailure(Exception):
    code: str
    status: int
    state: str = "error"
    retry_after: int = 0

    def __str__(self) -> str:
        return f"student auth failure: {self.code}"


def signed_out_response() -> AuthExchange:
    return AuthExchange({"ok": True, "state": "signed_out", "sid": None, "curris": [], "csrfToken": None, "pushState": "unknown"})


__all__ = ["AuthExchange", "AuthResponse", "StudentAuthDependencies", "StudentAuthFailure", "signed_out_response"]
