"""Lazy concrete dependency factory for the public student auth boundary."""

from __future__ import annotations

import os
from pathlib import Path

from core.student_activation_codes import StudentActivationCodeRepository
from core.student_app_auth_service import StudentAuthDependencies
from core.student_app_config import StudentAppConfig, load_student_app_config
from core.student_login_throttle import StudentLoginThrottleRepository
from core.student_account_repository import StudentAccountRepository
from core.student_sessions import StudentSessionRepository


def build_dependencies(
    config: StudentAppConfig | None = None,
    *,
    root: Path | None = None,
    accounts_path: Path | None = None,
    students_path: Path | None = None,
    db_path: Path | None = None,
) -> StudentAuthDependencies:
    """Construct injected repositories only when a caller asks for them."""
    base = Path(__file__).resolve().parents[1] if root is None else Path(root)
    account_file = accounts_path or Path(os.environ.get("STUDENT_APP_ACCOUNTS_PATH", base / "auth_accounts.json"))
    roster_file = students_path or Path(os.environ.get("STUDENT_APP_STUDENTS_PATH", base / "students.json"))
    sqlite_file = db_path or Path(os.environ.get("STUDENT_APP_DB_PATH", base / "app.sqlite"))
    chosen_config = load_student_app_config() if config is None else config
    return StudentAuthDependencies(
        config=chosen_config,
        accounts=StudentAccountRepository(account_file, roster_file),
        sessions=StudentSessionRepository(sqlite_file),
        activations=StudentActivationCodeRepository(sqlite_file),
        throttle=StudentLoginThrottleRepository(sqlite_file),
        students_path=roster_file,
    )


__all__ = ["build_dependencies"]
