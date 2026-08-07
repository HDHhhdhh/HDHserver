#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# How to run: C:\\server\\venv\\Scripts\\python.exe scripts\\student_mobile_app_checks\\auth.py

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable
import json
from pathlib import Path
import sys
import tempfile
from typing import Iterator, TypeAlias

from flask import Flask, Response
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_activation_codes import StudentActivationCodeRepository  # noqa: E402
from core.student_app_auth_service import StudentAuthDependencies  # noqa: E402
from core.student_app_auth_store import create_account  # noqa: E402
from core.student_app_config import load_student_app_config  # noqa: E402
from core.student_account_repository import StudentAccountRepository  # noqa: E402
from core.student_login_throttle import StudentLoginThrottleRepository  # noqa: E402
from core.student_sessions import StudentSessionRepository  # noqa: E402
from routes.api_student_app_auth import create_blueprint  # noqa: E402
from scripts.student_mobile_app_checks.auth_session import run_session_expiry_flow, write_auth_evidence  # noqa: E402

CheckValue: TypeAlias = str | int | bool | None | list["CheckValue"] | dict[str, "CheckValue"]


@contextmanager
def fixture(canary: str | None = None, *, clock: Callable[[], float | int] | None = None) -> Iterator[tuple[Flask, Path, Path, Path]]:
    with tempfile.TemporaryDirectory(prefix="student-auth-check-") as raw:
        directory = Path(raw)
        students_path, accounts_path, db_path = directory / "students.json", directory / "auth_accounts.json", directory / "app.sqlite"
        students = [
            {"id": "alice-1", "name": "Alice", "school": "A", "grade": "1", "curriculum": "Math"},
            {"id": "bob-1", "name": "Bob", "school": "A", "grade": "1", "curriculum": "Math"},
            {"id": "bob-2", "name": "Bob", "school": "B", "grade": "1", "curriculum": "Science"},
            {"id": "cara-1", "name": "Cara", "school": "A", "grade": "2", "curriculum": "Math"},
            {"id": "custom-1", "name": "Dora", "school": "A", "grade": "3", "curriculum": "Science"},
        ]
        accounts = {
            "Alice": {"sids": ["alice-1"], "pw_hash": generate_password_hash("1234"), "disabled": False, "unknown": "keep"},
            "custom-id": {"sids": ["custom-1"], "pw_hash": generate_password_hash("custom-pass"), "disabled": False},
            "Multi": {"sids": ["alice-1", "custom-1"], "pw_hash": generate_password_hash("multi-pass"), "disabled": False},
            "Disabled": {"sids": ["cara-1"], "pw_hash": generate_password_hash("safe-pass"), "disabled": True},
            "_meta": {"version": 9},
        }
        students_path.write_text(json.dumps(students, ensure_ascii=False), encoding="utf-8")
        accounts_path.write_text(json.dumps(accounts, ensure_ascii=False), encoding="utf-8")
        environment = {"STUDENT_APP_PUBLIC_HOST": "app.5a-math.com"}
        if canary is not None:
            environment["STUDENT_APP_CANARY_SIDS"] = canary
        config = load_student_app_config(environment)
        dependencies = StudentAuthDependencies(
            config=config,
            accounts=StudentAccountRepository(accounts_path, students_path),
            sessions=StudentSessionRepository(db_path, clock=clock),
            activations=StudentActivationCodeRepository(db_path),
            throttle=StudentLoginThrottleRepository(db_path),
            students_path=students_path,
        )
        app = Flask("student-auth-check")
        app.register_blueprint(create_blueprint(dependencies))
        app.config.update(TESTING=True)
        yield app, students_path, accounts_path, db_path


def _check(state: list[int], condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    state[0] += 1


def _json(response: Response) -> dict[str, CheckValue]:
    payload = getattr(response, "get_json")()
    if not isinstance(payload, dict):
        raise AssertionError("response is not a JSON map")
    return {key: value for key, value in payload.items() if isinstance(key, str)}


def _cookie_contract(state: list[int], header: str, max_age: str) -> None:
    _check(state, "student_app_session=" in header, "host-only session cookie name")
    _check(state, "Secure" in header, "secure cookie")
    _check(state, "HttpOnly" in header, "http-only cookie")
    _check(state, "SameSite=Lax" in header, "same-site cookie")
    _check(state, "Path=/" in header, "root cookie path")
    _check(state, f"Max-Age={max_age}" in header, "configured cookie max age")
    _check(state, "Domain=" not in header, "no cookie domain")


def _happy_flow(state: list[int], app: Flask, accounts_path: Path) -> None:
    client = app.test_client()
    response = client.post("/api/mobile/auth/login", json={"id": "Cara", "password": "1234"}, base_url="https://app.5a-math.com")
    payload = _json(response)
    _check(state, response.status_code == 200 and payload.get("state") == "credentials_required", "unique activation forces credentials")
    _check(state, "token" not in payload and "pw_hash" not in payload and "activationCode" not in payload, "login response omits secrets")
    header = response.headers.get("Set-Cookie", "")
    _cookie_contract(state, header, "2592000")
    csrf = str(payload.get("csrfToken") or "")
    session = client.get("/api/mobile/auth/session", base_url="https://app.5a-math.com")
    session_payload = _json(session)
    _check(state, session.status_code == 200 and session_payload.get("state") == "credentials_required", "session resolves forced state")
    csrf = str(session_payload.get("csrfToken") or "")
    changed = client.post("/api/mobile/auth/credentials", json={"studentId": "CaraNew", "password": "cara-safe-pass"}, headers={"X-CSRF-Token": csrf}, base_url="https://app.5a-math.com")
    changed_payload = _json(changed)
    _check(state, changed.status_code == 200 and changed_payload.get("state") == "ready", "credentials issue ready session")
    _check(state, changed_payload.get("sid") == "cara-1", "credentials keeps active SID")
    missing_csrf = client.post("/api/mobile/auth/switch", json={"sid": "cara-1"}, base_url="https://app.5a-math.com")
    _check(state, missing_csrf.status_code == 403 and _json(missing_csrf).get("code") == "csrf_required", "missing CSRF is rejected")
    after = json.loads(accounts_path.read_text(encoding="utf-8"))
    _check(state, "CaraNew" in after and after["CaraNew"].get("unknown") is None, "credential rename writes target account")
    _check(state, after.get("_meta") == {"version": 9}, "credential merge preserves top-level unknown")
    csrf_new = str(changed_payload.get("csrfToken") or "")
    stale_csrf = csrf
    old_cookie = client.get_cookie("student_app_session", domain="app.5a-math.com", path="/")
    forbidden = client.post("/api/mobile/auth/switch", json={"sid": "bob-1"}, headers={"X-CSRF-Token": csrf_new}, base_url="https://app.5a-math.com")
    _check(state, forbidden.status_code == 403 and _json(forbidden).get("code") == "forbidden_sid", "SID-outside switch denied")
    stale = client.post("/api/mobile/auth/switch", json={"sid": "cara-1"}, headers={"X-CSRF-Token": stale_csrf}, base_url="https://app.5a-math.com")
    _check(state, stale.status_code == 403 and _json(stale).get("code") == "csrf_invalid", "old CSRF token is rejected")
    logged_out = client.post("/api/mobile/auth/logout", headers={"X-CSRF-Token": csrf_new}, base_url="https://app.5a-math.com")
    _check(state, logged_out.status_code == 200 and _json(logged_out).get("state") == "signed_out", "logout revokes session")
    _check(state, "Max-Age=0" in logged_out.headers.get("Set-Cookie", ""), "logout expires cookie")
    _check(state, old_cookie is not None, "opaque cookie was issued")
    legacy = app.test_client()
    legacy_login = legacy.post("/api/mobile/auth/login", json={"id": "Alice", "password": "1234"}, base_url="https://app.5a-math.com")
    legacy_session = legacy.get("/api/mobile/auth/session", base_url="https://app.5a-math.com")
    legacy_csrf = str(_json(legacy_session).get("csrfToken") or "")
    legacy_change = legacy.post("/api/mobile/auth/credentials", json={"studentId": "AliceNew", "password": "alice-safe-pass"}, headers={"X-CSRF-Token": legacy_csrf}, base_url="https://app.5a-math.com")
    _check(state, legacy_login.status_code == 200 and legacy_change.status_code == 200, "legacy name+1234 lazy transition")
    changed_accounts = json.loads(accounts_path.read_text(encoding="utf-8"))
    _check(state, changed_accounts.get("AliceNew", {}).get("unknown") == "keep", "credential merge preserves account unknown field")
    old_client = app.test_client()
    if old_cookie is not None:
        old_client.set_cookie("student_app_session", old_cookie.value, domain="app.5a-math.com", path="/")
        stale_session = old_client.get("/api/mobile/auth/session", base_url="https://app.5a-math.com")
        _check(state, stale_session.status_code == 401, "old cookie cannot resolve")
    multi = app.test_client()
    multi_login = multi.post("/api/mobile/auth/login", json={"id": "Multi", "password": "multi-pass"}, base_url="https://app.5a-math.com")
    multi_csrf = str(_json(multi_login).get("csrfToken") or "")
    switched = multi.post("/api/mobile/auth/switch", json={"sid": "custom-1"}, headers={"X-CSRF-Token": multi_csrf}, base_url="https://app.5a-math.com")
    _check(state, switched.status_code == 200 and _json(switched).get("sid") == "custom-1", "allowed switch rotates to target SID")


def _duplicate_flow(state: list[int], app: Flask, db_path: Path) -> None:
    client = app.test_client()
    missing = client.post("/api/mobile/auth/login", json={"id": "Bob", "password": "1234"}, base_url="https://app.5a-math.com")
    _check(state, missing.status_code == 409 and _json(missing).get("code") == "activation_code_required", "duplicate has generic code-required response")
    codes = StudentActivationCodeRepository(db_path)
    code = codes.issue("Bob||A||1", ["bob-1"])
    wrong = client.post("/api/mobile/auth/login", json={"id": "Bob", "password": "1234", "activationCode": "000000"}, base_url="https://app.5a-math.com")
    _check(state, wrong.status_code == 409 and _json(wrong).get("code") == "activation_code_required", "wrong code is generic")
    valid = client.post("/api/mobile/auth/login", json={"id": "Bob", "activationCode": code}, base_url="https://app.5a-math.com")
    valid_payload = _json(valid)
    _check(state, valid.status_code == 200 and valid_payload.get("state") == "credentials_required", "duplicate issued-code activation")
    protected = client.post("/api/mobile/auth/switch", json={"sid": "bob-1"}, headers={"X-CSRF-Token": str(valid_payload.get("csrfToken") or "")}, base_url="https://app.5a-math.com")
    _check(state, protected.status_code == 403 and _json(protected).get("state") == "credentials_required", "must-change state protects switch")
    _check(state, codes.redeem("Bob||A||1", code) is None, "reused code fails closed")
    with fixture() as (expired_app, _students_path, _accounts_path, expired_db):
        expired_code = StudentActivationCodeRepository(expired_db).issue("Bob||A||1", ["bob-1"], ttl_seconds=1, now=100)
        expired = expired_app.test_client().post("/api/mobile/auth/login", json={"id": "Bob", "password": "1234", "activationCode": expired_code}, base_url="https://app.5a-math.com")
        _check(state, expired.status_code == 409 and _json(expired).get("code") == "activation_code_required", "expired activation code fails closed")


def _failure_flow(state: list[int], app: Flask) -> None:
    client = app.test_client()
    for _ in range(4):
        failed = client.post("/api/mobile/auth/login", json={"id": "ThrottleUser", "password": "bad"}, base_url="https://app.5a-math.com")
        _check(state, failed.status_code == 401, "failed login remains generic")
    fifth = client.post("/api/mobile/auth/login", json={"id": "ThrottleUser", "password": "bad"}, base_url="https://app.5a-math.com")
    _check(state, fifth.status_code == 429, "fifth failure opens throttle window")
    sixth = client.post("/api/mobile/auth/login", json={"id": "ThrottleUser", "password": "bad"}, base_url="https://app.5a-math.com")
    _check(state, sixth.status_code == 429 and _json(sixth).get("code") == "temporarily_unavailable", "sixth login is throttled")
    disabled = client.post("/api/mobile/auth/login", json={"id": "Disabled", "password": "safe-pass"}, base_url="https://app.5a-math.com", environ_base={"REMOTE_ADDR": "127.0.0.2"})
    _check(state, disabled.status_code == 401 and _json(disabled).get("code") == "invalid_credentials", "disabled login is generic")
    custom = client.post("/api/mobile/auth/login", json={"id": "custom-id", "password": "custom-pass"}, base_url="https://app.5a-math.com", environ_base={"REMOTE_ADDR": "127.0.0.2"})
    _check(state, custom.status_code == 200 and _json(custom).get("state") == "ready", "custom legacy credential is not forced")


def _canary_flow(state: list[int]) -> None:
    with fixture("only-canary") as (app, _students_path, accounts_path, _db_path):
        before = accounts_path.read_bytes()
        response = app.test_client().post("/api/mobile/auth/login", json={"id": "Cara", "password": "1234", "sids": ["cara-1"]}, base_url="https://app.5a-math.com")
        _check(state, response.status_code == 404 and _json(response).get("code") == "unavailable", "canary denies non-intersecting activation")
        _check(state, accounts_path.read_bytes() == before, "canary denial performs no account write")


def _state_and_collision_flow(state: list[int]) -> None:
    with fixture() as (app, _students_path, accounts_path, db_path):
        client = app.test_client()
        login = client.post("/api/mobile/auth/login", json={"id": "custom-id", "password": "custom-pass"}, base_url="https://app.5a-math.com")
        session = client.get("/api/mobile/auth/session", base_url="https://app.5a-math.com")
        csrf = str(_json(session).get("csrfToken") or "")
        raw = json.loads(accounts_path.read_text(encoding="utf-8"))
        raw["custom-id"]["must_change_credentials"] = True
        accounts_path.write_text(json.dumps(raw), encoding="utf-8")
        protected = client.post("/api/mobile/auth/switch", json={"sid": "custom-1"}, headers={"X-CSRF-Token": csrf}, base_url="https://app.5a-math.com")
        _check(state, login.status_code == 200 and protected.status_code == 403 and _json(protected).get("state") == "credentials_required", "reset must-change protects switch")
        raw["custom-id"]["disabled"] = True
        accounts_path.write_text(json.dumps(raw), encoding="utf-8")
        disabled_session = client.get("/api/mobile/auth/session", base_url="https://app.5a-math.com")
        _check(state, disabled_session.status_code == 401, "disabled account revokes session resolution")
    with fixture() as (app, _students_path, accounts_path, _db_path):
        create_account(accounts_path, "Collision", ["cara-1"])
        client = app.test_client()
        login = client.post("/api/mobile/auth/login", json={"id": "Cara", "password": "1234"}, base_url="https://app.5a-math.com")
        session = client.get("/api/mobile/auth/session", base_url="https://app.5a-math.com")
        csrf = str(_json(session).get("csrfToken") or "")
        before = accounts_path.read_bytes()
        collision = client.post("/api/mobile/auth/credentials", json={"studentId": "Collision", "password": "safe-password"}, headers={"X-CSRF-Token": csrf}, base_url="https://app.5a-math.com")
        _check(state, login.status_code == 200 and collision.status_code == 409 and _json(collision).get("code") == "id_collision", "ID collision is rejected")
        _check(state, accounts_path.read_bytes() == before, "ID collision leaves accounts bytes unchanged")
        import core.student_app_auth_store as store
        original_save = store.save_atomic
        store.save_atomic = lambda _path, _value: (_ for _ in ()).throw(RuntimeError("injected"))
        try:
            try:
                client.post("/api/mobile/auth/credentials", json={"studentId": "CaraNew", "password": "safe-password"}, headers={"X-CSRF-Token": csrf}, base_url="https://app.5a-math.com")
            except RuntimeError:
                state[0] += 1
            else:
                raise AssertionError("save rollback seam did not raise")
        finally:
            store.save_atomic = original_save
        _check(state, accounts_path.read_bytes() == before, "save failure leaves account bytes unchanged")


def _concurrency_flow(state: list[int]) -> None:
    import threading
    with fixture() as (_app, _students_path, accounts_path, _db_path):
        barrier = threading.Barrier(3)
        failures: list[str] = []
        def worker(identifier: str, sid: str) -> None:
            try:
                barrier.wait()
                create_account(accounts_path, identifier, [sid])
            except (RuntimeError, ValueError) as exc:
                failures.append(type(exc).__name__)
        first = threading.Thread(target=worker, args=("RaceA", "alice-1"))
        second = threading.Thread(target=worker, args=("RaceB", "cara-1"))
        first.start(); second.start(); barrier.wait(); first.join(); second.join()
        result = json.loads(accounts_path.read_text(encoding="utf-8"))
        _check(state, not failures and "RaceA" in result and "RaceB" in result, "concurrent credential/account writes serialize")
        _check(state, result.get("_meta") == {"version": 9}, "concurrency preserves unknown top-level data")


def _source_flow(state: list[int]) -> None:
    source = (ROOT / "routes/api_student_app_auth.py").read_text(encoding="utf-8")
    for marker in ("MASTER_PW", "_master_pw_ok", "Bearer ", "jwt", "localStorage"):
        _check(state, marker not in source, f"forbidden auth marker absent: {marker}")


def run_checks() -> dict[str, CheckValue]:
    state = [0]
    with fixture() as (app, _students_path, accounts_path, db_path):
        _happy_flow(state, app, accounts_path)
        _duplicate_flow(state, app, db_path)
        _failure_flow(state, app)
    _canary_flow(state)
    state[0] += run_session_expiry_flow(fixture)
    _state_and_collision_flow(state)
    _concurrency_flow(state)
    _source_flow(state)
    result: dict[str, CheckValue] = {"name": "auth", "assertions": state[0], "passed": True, "runtime_diff": {}}
    write_auth_evidence(ROOT, result)
    return result


def main() -> int:  # noqa: BROAD_EXCEPT_OK
    try:
        result = run_checks()
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK
        print(f"auth: FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(f"auth: PASS ({result['assertions']} assertions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
