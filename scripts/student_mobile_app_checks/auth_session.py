"""Flask and repository regression checks for monotonic session expiry."""
from __future__ import annotations

import sqlite3
import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TypeAlias

from flask import Flask, Response

from core.student_sessions import StudentSessionRepository

FixtureValue: TypeAlias = tuple[Flask, Path, Path, Path]
FixtureFactory: TypeAlias = Callable[..., AbstractContextManager[FixtureValue]]
CheckValue: TypeAlias = str | int | bool | None | list["CheckValue"] | dict[str, "CheckValue"]


def _check(count: list[int], condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    count[0] += 1


def _json(response: Response) -> dict[str, str | bool | int | None]:
    payload = response.get_json()
    if not isinstance(payload, dict):
        raise AssertionError("response is not a JSON map")
    return {key: value for key, value in payload.items() if isinstance(key, str) and (isinstance(value, (str, bool, int)) or value is None)}


def _revoked_at(path: Path, session_id: int) -> float | None:
    db = sqlite3.connect(path)
    try:
        value = db.execute("SELECT revoked_at FROM student_app_sessions WHERE id=?", (session_id,)).fetchone()
    finally:
        db.close()
    return None if value is None else value[0]


def _repository_flow(count: list[int], fixture: FixtureFactory, now: list[float]) -> None:
    with fixture(clock=lambda: now[0]) as (_app, _students, _accounts, db_path):
        sessions = StudentSessionRepository(db_path, clock=lambda: now[0])
        created = sessions.create("custom-id", "custom-1", ["custom-1"], ttl_seconds=1, now=100)
        now[0] = 102
        _check(count, sessions.resolve(created["token"], now=102) is None, "repository expiry returns no session")
        _check(count, _revoked_at(db_path, created["session_id"]) == 102.0, "repository expiry records terminal marker")
        now[0] = 99
        _check(count, sessions.resolve(created["token"], now=99) is None, "repository expiry remains invalid after rollback")


def _flask_flow(count: list[int], fixture: FixtureFactory, now: list[float]) -> None:
    with fixture(clock=lambda: now[0]) as (app, _students, _accounts, db_path):
        sessions = StudentSessionRepository(db_path, clock=lambda: now[0])
        created = sessions.create("custom-id", "custom-1", ["custom-1"], ttl_seconds=1, now=100)
        client = app.test_client()
        client.set_cookie("student_app_session", created["token"], domain="app.5a-math.com")
        now[0] = 102
        expired = client.get("/api/mobile/auth/session", base_url="https://app.5a-math.com")
        _check(count, expired.status_code == 401, "Flask session is 401 after expiry observation")
        _check(count, "csrfToken" not in _json(expired) and "token" not in _json(expired), "expired response is generic")
        now[0] = 99
        rollback = client.get("/api/mobile/auth/session", base_url="https://app.5a-math.com")
        _check(count, rollback.status_code == 401, "Flask cookie remains 401 after clock rollback")
        _check(count, "csrfToken" not in _json(rollback) and "token" not in _json(rollback), "rollback response is generic")
        headers = {"X-CSRF-Token": created["csrf_token"]}
        protected = (
            ("/api/mobile/auth/credentials", {"studentId": "changed", "password": "safe-password"}),
            ("/api/mobile/auth/switch", {"sid": "custom-1"}),
            ("/api/mobile/auth/logout", None),
        )
        for path, payload in protected:
            response = client.post(path, json=payload, headers=headers, base_url="https://app.5a-math.com")
            body = _json(response)
            _check(count, response.status_code == 403 and body.get("code") == "csrf_invalid", f"expired session blocks {path}")


def run_session_expiry_flow(fixture: FixtureFactory) -> int:
    """Exercise repository and real Flask cookie-jar expiry monotonicity."""
    count = [0]
    now = [100.0]
    _repository_flow(count, fixture, now)
    now[0] = 100.0
    _flask_flow(count, fixture, now)
    return count[0]


def write_auth_evidence(root: Path, result: Mapping[str, CheckValue]) -> None:
    """Write the auth receipt to the owned remediation artifact path."""
    evidence = root / ".omo/evidence/student-mobile-app-v2/task-6/session-expiry-remediation-l1-green.json"
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(payload, encoding="utf-8")
    except PermissionError:
        fallback = root / ".codex-temp/student-mobile-app-v2/task-6/session-expiry-remediation-l1-green.json"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(payload, encoding="utf-8")


__all__ = ["run_session_expiry_flow", "write_auth_evidence"]
