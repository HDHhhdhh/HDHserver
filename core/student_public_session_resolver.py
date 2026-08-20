"""Account-aware default session resolvers for the public student surface."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable

from core.student_account_repository import AccountRepositoryError
from core.student_app_auth_contract import StudentAuthDependencies
from core.student_app_auth_store import StudentAuthStoreError, account_sids, load_students, narrow_sids
from core.student_app_config import StudentAppConfig

CSRFValidator = Callable[[str, str | None], bool]
DependencyFactory = Callable[[StudentAppConfig], StudentAuthDependencies]
IdentityFactory = Callable[[str, tuple[str, ...], bool], object]
SessionResolver = Callable[[str], object | None]


def build_default_resolvers(
    config: StudentAppConfig,
    identity_factory: IdentityFactory,
    dependency_factory: DependencyFactory | None = None,
) -> tuple[SessionResolver, CSRFValidator]:
    """Resolve only sessions still linked to an active account and current roster."""
    dependencies: StudentAuthDependencies | None = None

    def get_dependencies() -> StudentAuthDependencies:
        nonlocal dependencies
        if dependencies is None:
            if dependency_factory is None:
                from core.student_app_auth_factory import build_dependencies

                dependencies = build_dependencies(config)
            else:
                dependencies = dependency_factory(config)
        return dependencies

    def resolve(token: str) -> object | None:
        if not token:
            return None
        try:
            deps = get_dependencies()
            view = deps.sessions.resolve(token)
            if view is None:
                return None
            record = deps.accounts.get(view["aid"])
            if record is None or record.get("disabled") is True:
                deps.sessions.revoke(token)
                return None
            students = load_students(deps.students_path)
            stored = set(account_sids(record))
            allowed = tuple(sid for sid in narrow_sids(tuple(view["allowed_sids"]), students) if sid in stored)
            active = view["active_sid"]
            if not allowed or active not in allowed or any(not config.allows_canary_sid(sid) for sid in allowed):
                deps.sessions.revoke(token)
                return None
            return identity_factory(active, allowed, record.get("must_change_credentials") is True)
        except (AccountRepositoryError, StudentAuthStoreError, OSError, sqlite3.Error, ValueError):
            return None

    def validate_csrf(token: str, csrf_token: str | None) -> bool:
        if not token or not isinstance(csrf_token, str) or not csrf_token:
            return False
        try:
            return get_dependencies().sessions.resolve(token, csrf_token=csrf_token) is not None
        except (OSError, sqlite3.Error, ValueError):
            return False

    return resolve, validate_csrf


__all__ = ["build_default_resolvers"]
