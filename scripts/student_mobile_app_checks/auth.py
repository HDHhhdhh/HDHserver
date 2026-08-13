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

from flask import Blueprint, Flask, Response, g, jsonify
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
from core.student_public_session_resolver import build_default_resolvers  # noqa: E402
from core.student_public_surface import SessionIdentity, install_student_public_surface, register_student_app_domain  # noqa: E402
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


def _public_surface_app(
    students_path: Path,
    accounts_path: Path,
    db_path: Path,
    *,
    canary: str | None = None,
) -> tuple[Flask, StudentAuthDependencies, dict[str, int]]:
    environment = {
        "STUDENT_APP_PUBLIC_ENABLED": "1",
        "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
        "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1/32",
    }
    if canary is not None:
        environment["STUDENT_APP_CANARY_SIDS"] = canary
    config = load_student_app_config(environment)
    dependencies = StudentAuthDependencies(
        config=config,
        accounts=StudentAccountRepository(accounts_path, students_path),
        sessions=StudentSessionRepository(db_path),
        activations=StudentActivationCodeRepository(db_path),
        throttle=StudentLoginThrottleRepository(db_path),
        students_path=students_path,
    )
    resolver, csrf_validator = build_default_resolvers(config, SessionIdentity, lambda _config: dependencies)
    app = Flask("student-auth-surface-check")
    install_student_public_surface(
        app,
        config=config,
        auth_blueprint=create_blueprint(dependencies),
        session_resolver=resolver,
        csrf_validator=csrf_validator,
    )
    hits = {"api": 0, "page": 0, "static": 0, "file": 0}
    probes = Blueprint("student_auth_surface_probes", __name__)

    def protected_api():  # noqa: ANN202
        hits["api"] += 1
        return jsonify({"ok": True, "allowedSids": list(getattr(g, "student_app_allowed_sids", ()))})

    probe_routes = frozenset(
        {
            ("/api/student/bootstrap", "GET"),
            ("/api/announcements", "GET"),
            ("/api/get-url", "GET"),
            ("/api/mobile/push/status", "GET"),
        }
    )
    for index, (path, method) in enumerate(sorted(probe_routes)):
        probes.add_url_rule(path, endpoint=f"protected_{index}", view_func=protected_api, methods=[method])
    register_student_app_domain(app, probes, probe_routes)

    @app.get("/student/<sid>")
    def protected_page(sid: str):  # noqa: ARG001, ANN202
        hits["page"] += 1
        return "student"

    @app.get("/js/test_answer_link_map.json")
    def protected_static():  # noqa: ANN202
        hits["static"] += 1
        return jsonify({"answer": "secret"})

    @app.get("/files/announcements/<path:filename>")
    def protected_file(filename: str):  # noqa: ARG001, ANN202
        hits["file"] += 1
        return "announcement"

    app.config.update(TESTING=True)
    return app, dependencies, hits


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
    with fixture() as (limited_app, _students_path, _accounts_path, limited_db):
        valid_code = StudentActivationCodeRepository(limited_db).issue("Bob||A||1", ["bob-1"])
        limited_client = limited_app.test_client()
        failures = [limited_client.post("/api/mobile/auth/login", json={"id": "Bob", "activationCode": "not-a-code"}, base_url="https://app.5a-math.com") for _ in range(5)]
        _check(state, all(item.status_code == 409 for item in failures[:4]) and failures[4].status_code == 429, "duplicate-code failures enter the identifier/IP throttle on attempt five")
        _check(state, StudentActivationCodeRepository(limited_db).redeem("Bob||A||1", valid_code) is not None, "wrong public attempts do not consume an unrelated valid group code")


def _duplicate_name_collision_flow(state: list[int]) -> None:
    with fixture() as (app, _students_path, accounts_path, db_path):
        accounts = json.loads(accounts_path.read_text(encoding="utf-8"))
        accounts["Bob"] = {
            "sids": ["bob-1"],
            "pw_hash": generate_password_hash("1234"),
            "must_change_credentials": True,
            "disabled": False,
            "unknown": "keep-a",
        }
        accounts_path.write_text(json.dumps(accounts, ensure_ascii=False), encoding="utf-8")
        before = accounts_path.read_bytes()
        client = app.test_client()

        plain = client.post(
            "/api/mobile/auth/login",
            json={"id": "Bob", "password": "1234"},
            base_url="https://app.5a-math.com",
        )
        _check(
            state,
            plain.status_code == 409 and _json(plain).get("code") == "activation_code_required",
            "shared duplicate name cannot select an existing name-keyed account by password",
        )
        casefolded = client.post(
            "/api/mobile/auth/login",
            json={"id": "bOb", "password": "1234"},
            base_url="https://app.5a-math.com",
        )
        _check(
            state,
            casefolded.status_code == 409 and _json(casefolded).get("code") == "activation_code_required",
            "case-insensitive shared name cannot bypass duplicate activation",
        )
        rename = client.post(
            "/api/mobile/auth/credentials",
            json={"studentId": "StolenBob", "password": "attacker-password"},
            headers={"X-CSRF-Token": str(_json(plain).get("csrfToken") or "")},
            base_url="https://app.5a-math.com",
        )
        _check(state, rename.status_code == 401, "rejected duplicate-name login cannot rename the existing account")
        _check(state, accounts_path.read_bytes() == before, "rejected duplicate-name login leaves accounts unchanged")

        codes = StudentActivationCodeRepository(db_path)
        legacy_code = codes.issue("Bob", ["bob-2"])
        legacy = client.post(
            "/api/mobile/auth/login",
            json={"id": "Bob", "activationCode": legacy_code},
            base_url="https://app.5a-math.com",
        )
        _check(state, legacy.status_code == 409, "ambiguous legacy name-bound code is rejected")
        _check(state, codes.redeem("Bob", legacy_code) is not None, "rejected ambiguous code is not consumed")

        code_a = codes.issue("Bob||A||1", ["bob-1"])
        code_b = codes.issue("Bob||B||1", ["bob-2"])
        activated_b = client.post(
            "/api/mobile/auth/login",
            json={"id": "Bob", "activationCode": code_b},
            base_url="https://app.5a-math.com",
        )
        payload_b = _json(activated_b)
        _check(
            state,
            activated_b.status_code == 200
            and payload_b.get("state") == "credentials_required"
            and payload_b.get("sid") == "bob-2",
            "canonical B code activates only duplicate group B",
        )
        after_b = json.loads(accounts_path.read_text(encoding="utf-8"))
        linked_b = [
            (aid, record)
            for aid, record in after_b.items()
            if isinstance(record, dict) and record.get("sids") == ["bob-2"]
        ]
        _check(
            state,
            after_b.get("Bob", {}).get("sids") == ["bob-1"]
            and after_b.get("Bob", {}).get("unknown") == "keep-a",
            "B activation does not overwrite the name-keyed A account",
        )
        _check(
            state,
            len(linked_b) == 1
            and linked_b[0][0] != "Bob"
            and linked_b[0][0].startswith("pending-")
            and len(linked_b[0][0]) <= 32,
            "B activation creates an opaque group-bound pending account",
        )

        client_a = app.test_client()
        activated_a = client_a.post(
            "/api/mobile/auth/login",
            json={"id": "Bob", "activationCode": code_a},
            base_url="https://app.5a-math.com",
        )
        _check(
            state,
            activated_a.status_code == 200
            and _json(activated_a).get("sid") == "bob-1",
            "B activation does not consume A's canonical code",
        )

    with fixture() as (app, _students_path, accounts_path, db_path):
        accounts = json.loads(accounts_path.read_text(encoding="utf-8"))
        accounts["Bob"] = {
            "sids": ["bob-1"],
            "pw_hash": generate_password_hash("safe-password"),
            "must_change_credentials": False,
            "disabled": True,
        }
        accounts_path.write_text(json.dumps(accounts, ensure_ascii=False), encoding="utf-8")
        code = StudentActivationCodeRepository(db_path).issue("Bob||A||1", ["bob-1"])
        disabled = app.test_client().post(
            "/api/mobile/auth/login",
            json={"id": "Bob", "activationCode": code},
            base_url="https://app.5a-math.com",
        )
        _check(
            state,
            disabled.status_code == 401 and _json(disabled).get("code") == "invalid_credentials",
            "canonical activation rejects a disabled exact-SID account",
        )


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


def _current_account_surface_flow(state: list[int]) -> None:
    with fixture() as (_fixture_app, students_path, accounts_path, db_path):
        app, dependencies, hits = _public_surface_app(students_path, accounts_path, db_path)
        client = app.test_client()
        edge = {"CF-Connecting-IP": "110.14.147.14"}
        login = client.post(
            "/api/mobile/auth/login",
            json={"id": "custom-id", "password": "custom-pass"},
            headers=edge,
            base_url="https://app.5a-math.com",
        )
        _check(state, login.status_code == 200 and _json(login).get("state") == "ready", "surface fixture creates a ready session")
        accounts = json.loads(accounts_path.read_text(encoding="utf-8"))
        accounts["custom-id"]["must_change_credentials"] = True
        accounts_path.write_text(json.dumps(accounts, ensure_ascii=False), encoding="utf-8")

        protected_paths = (
            "/api/student/bootstrap?sid=custom-1",
            "/api/announcements?sid=custom-1",
            "/api/get-url?sid=custom-1",
            "/api/mobile/push/status",
            "/student/custom-1",
            "/js/test_answer_link_map.json",
            "/files/announcements/notice.png",
        )
        before = dict(hits)
        for path in protected_paths:
            response = client.get(path, base_url="https://app.5a-math.com", headers=edge)
            payload = _json(response)
            _check(
                state,
                response.status_code == 403
                and payload.get("code") == "credentials_required"
                and payload.get("state") == "credentials_required",
                f"current credentials-required state blocks protected surface: {path}",
            )
        _check(state, hits == before, "central credentials gate runs before every protected bridge handler")

        session = client.get("/api/mobile/auth/session", base_url="https://app.5a-math.com", headers=edge)
        session_payload = _json(session)
        _check(state, session.status_code == 200 and session_payload.get("state") == "credentials_required", "auth session remains available while credentials are required")
        csrf = str(session_payload.get("csrfToken") or "")

        logout_client = app.test_client()
        logout_login = logout_client.post(
            "/api/mobile/auth/login",
            json={"id": "custom-id", "password": "custom-pass"},
            headers=edge,
            base_url="https://app.5a-math.com",
        )
        logout_payload = _json(logout_login)
        logged_out = logout_client.post(
            "/api/mobile/auth/logout",
            headers=edge | {"Origin": "https://app.5a-math.com", "X-CSRF-Token": str(logout_payload.get("csrfToken") or "")},
            base_url="https://app.5a-math.com",
        )
        _check(state, logout_payload.get("state") == "credentials_required" and logged_out.status_code == 200, "credentials-required session may log out")

        changed = client.post(
            "/api/mobile/auth/credentials",
            json={"studentId": "custom-id", "password": "custom-safer-pass"},
            headers=edge | {"Origin": "https://app.5a-math.com", "X-CSRF-Token": csrf},
            base_url="https://app.5a-math.com",
        )
        changed_payload = _json(changed)
        _check(state, changed.status_code == 200 and changed_payload.get("state") == "ready", "credentials-required session may complete credential replacement")
        ready_bootstrap = client.get("/api/student/bootstrap?sid=custom-1", base_url="https://app.5a-math.com", headers=edge)
        _check(state, ready_bootstrap.status_code == 200 and hits["api"] == before["api"] + 1, "protected bootstrap resumes after credential replacement")

        ready_token = client.get_cookie("student_app_session", domain="app.5a-math.com", path="/")
        disabled_accounts = json.loads(accounts_path.read_text(encoding="utf-8"))
        disabled_accounts["custom-id"]["disabled"] = True
        accounts_path.write_text(json.dumps(disabled_accounts, ensure_ascii=False), encoding="utf-8")
        disabled = client.get("/api/student/bootstrap?sid=custom-1", base_url="https://app.5a-math.com", headers=edge)
        _check(state, disabled.status_code == 401 and _json(disabled).get("code") == "unauthenticated", "current disabled account fails closed on the next protected request")
        if ready_token is None:
            raise AssertionError("ready session cookie missing before disabled-account check")
        _check(state, dependencies.sessions.resolve(ready_token.value) is None, "disabled account revokes the existing session token")


def _canary_flow(state: list[int]) -> None:
    with fixture("only-canary") as (app, _students_path, accounts_path, _db_path):
        before = accounts_path.read_bytes()
        response = app.test_client().post("/api/mobile/auth/login", json={"id": "Cara", "password": "1234", "sids": ["cara-1"]}, base_url="https://app.5a-math.com")
        _check(state, response.status_code == 404 and _json(response).get("code") == "unavailable", "canary denies non-intersecting activation")
        _check(state, accounts_path.read_bytes() == before, "canary denial performs no account write")
    with fixture() as (_fixture_app, students_path, accounts_path, db_path):
        broad_app, broad_dependencies, _broad_hits = _public_surface_app(students_path, accounts_path, db_path)
        broad_client = broad_app.test_client()
        edge = {"CF-Connecting-IP": "110.14.147.14"}
        login = broad_client.post(
            "/api/mobile/auth/login",
            json={"id": "custom-id", "password": "custom-pass"},
            headers=edge,
            base_url="https://app.5a-math.com",
        )
        cookie = broad_client.get_cookie("student_app_session", domain="app.5a-math.com", path="/")
        _check(state, login.status_code == 200 and cookie is not None, "broad rollout issues a session before canary narrowing")
        if cookie is None:
            raise AssertionError("broad rollout session cookie missing")

        narrowed_app, _narrowed_dependencies, narrowed_hits = _public_surface_app(
            students_path,
            accounts_path,
            db_path,
            canary="alice-1",
        )
        narrowed_client = narrowed_app.test_client()
        narrowed_client.set_cookie("student_app_session", cookie.value, domain="app.5a-math.com", path="/")
        denied = narrowed_client.get("/api/student/bootstrap?sid=custom-1", base_url="https://app.5a-math.com", headers=edge)
        _check(state, denied.status_code == 401 and _json(denied).get("code") == "unauthenticated", "canary narrowing fails a now-ineligible active SID closed")
        _check(state, narrowed_hits["api"] == 0, "canary-narrowed session never reaches protected data")
        _check(state, broad_dependencies.sessions.resolve(cookie.value) is None, "canary narrowing revokes the stale session token")

    with fixture() as (_fixture_app, students_path, accounts_path, db_path):
        broad_app, _broad_dependencies, _broad_hits = _public_surface_app(students_path, accounts_path, db_path)
        broad_client = broad_app.test_client()
        edge = {"CF-Connecting-IP": "110.14.147.14"}
        login = broad_client.post(
            "/api/mobile/auth/login",
            json={"id": "Multi", "password": "multi-pass"},
            headers=edge,
            base_url="https://app.5a-math.com",
        )
        cookie = broad_client.get_cookie("student_app_session", domain="app.5a-math.com", path="/")
        _check(state, login.status_code == 200 and cookie is not None, "multi-SID session exists before partial canary narrowing")
        if cookie is None:
            raise AssertionError("multi-SID session cookie missing")
        narrowed_app, dependencies, hits = _public_surface_app(students_path, accounts_path, db_path, canary="alice-1")
        narrowed_client = narrowed_app.test_client()
        narrowed_client.set_cookie("student_app_session", cookie.value, domain="app.5a-math.com", path="/")
        denied = narrowed_client.get("/api/student/bootstrap?sid=alice-1", base_url="https://app.5a-math.com", headers=edge)
        _check(state, denied.status_code == 401 and _json(denied).get("code") == "unauthenticated", "partial canary narrowing invalidates broader session authority")
        _check(state, hits["api"] == 0 and dependencies.sessions.resolve(cookie.value) is None, "partial canary narrowing revokes before protected data")


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
    with fixture() as (app, _students_path, _accounts_path, _db_path):
        _failure_flow(state, app)
    _duplicate_name_collision_flow(state)
    _current_account_surface_flow(state)
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
