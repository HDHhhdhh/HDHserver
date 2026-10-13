"""Temp-only contract checks for Basic-authenticated student-account administration."""
from __future__ import annotations

import base64
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeAlias

from flask import Flask, Response
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_account_audit import StudentAccountAuditRepository  # noqa: E402
from routes.api_student_accounts import create_blueprint  # noqa: E402
from core.student_account_admin_service import StudentAccountAdminDependencies  # noqa: E402
from core.student_account_repository import StudentAccountRepository  # noqa: E402
from core.student_activation_codes import StudentActivationCodeRepository  # noqa: E402
from core.student_app_config import load_student_app_config  # noqa: E402
from core.student_push_repository import StudentPushRepository  # noqa: E402
from core.student_sessions import StudentSessionRepository  # noqa: E402
from scripts.student_mobile_app_checks.admin_auth_contract import (  # noqa: E402
    add_test_authorization,
    run_admin_auth_contract,
    test_authorizer,
)

CheckValue: TypeAlias = str | int | float | bool | None | list["CheckValue"] | dict[str, "CheckValue"]


def _check(count: list[int], condition: bool, label: str) -> None:
    count[0] += 1
    if not condition:
        raise AssertionError(label)


def _json(response: Response) -> dict[str, Any]:
    value = response.get_json()
    if not isinstance(value, dict):
        raise AssertionError("response is not a JSON object")
    return value


def _request(client: Any, method: str, path: str, **kwargs: Any) -> Response:
    kwargs.setdefault("base_url", "http://admin.local")
    kwargs.setdefault("environ_overrides", {"REMOTE_ADDR": "10.2.3.4"})
    add_test_authorization(kwargs)
    return client.open(path, method=method, **kwargs)


def _subscription_keys() -> tuple[str, str]:
    p256dh = base64.urlsafe_b64encode(b"p" * 65).decode().rstrip("=")
    auth = base64.urlsafe_b64encode(b"a" * 16).decode().rstrip("=")
    return p256dh, auth


def _account(path: Path, aid: str) -> dict[str, Any]:
    value = json.loads(path.read_text("utf-8"))[aid]
    if not isinstance(value, dict):
        raise AssertionError("stored account is not an object")
    return value


def _lazy_gate_checks(count: list[int], root: Path, config: Any) -> None:
    private = root / "lazy"
    accounts, students, database = private / "accounts.json", private / "students.json", private / "app.sqlite"
    app = Flask("student-account-admin-gates")
    app.register_blueprint(create_blueprint(config=config, accounts_path=accounts, students_path=students, db_path=database, admin_authorizer=test_authorizer))
    client = app.test_client()
    public = client.get("/api/student-accounts", base_url="https://app.5a-math.com", environ_overrides={"REMOTE_ADDR": "10.0.0.8"})
    _check(count, public.status_code == 404, "exact public host is hidden")
    direct = client.get("/api/student-accounts", base_url="http://admin.local", environ_overrides={"REMOTE_ADDR": "203.0.113.7"})
    spoof = client.get("/api/student-accounts", base_url="http://admin.local", headers={"X-Forwarded-For": "10.0.0.8"}, environ_overrides={"REMOTE_ADDR": "203.0.113.7"})
    _check(count, direct.status_code == 401 and _json(direct).get("code") == "admin_auth_required", "off-network request without credentials is challenged")
    _check(count, spoof.status_code == 401 and _json(spoof).get("code") == "admin_auth_required", "forwarded IP does not replace Basic authentication")
    missing = client.get("/api/student-accounts", base_url="http://admin.local", environ_overrides={"REMOTE_ADDR": "10.2.3.4"})
    bad = client.get("/api/student-accounts", base_url="http://admin.local", headers={"Authorization": "Basic Zm9vOmJhcg=="}, environ_overrides={"REMOTE_ADDR": "10.2.3.4"})
    _check(count, missing.status_code == 401 and _json(missing).get("code") == "admin_auth_required" and missing.headers.get("WWW-Authenticate"), "academy request without admin credentials is challenged")
    _check(count, bad.status_code == 401 and _json(bad).get("code") == "admin_auth_required", "bad admin credentials are rejected")
    _check(count, not any(path.exists() for path in (accounts, students, database, private)), "denied requests do not construct repositories")


def _fixture(root: Path) -> tuple[Flask, Path, Path, StudentAccountAdminDependencies]:
    students_path, accounts_path, db_path = root / "students.json", root / "accounts.json", root / "app.sqlite"
    students = [
        {"id": "minsu-a1", "name": "김민수", "school": "A고", "grade": "1"},
        {"id": "minsu-a2", "name": "김민수", "school": "A고", "grade": "1"},
        {"id": "minsu-b1", "name": "김민수", "school": "B고", "grade": "2"},
        {"id": "seo-1", "name": "이서준", "school": "C고", "grade": "3"},
    ]
    old_hash, disabled_hash = generate_password_hash("old-password"), generate_password_hash("disabled-password")
    accounts = {
        "custom-a": {"sids": ["minsu-a1", "minsu-a2"], "pw_hash": old_hash, "disabled": False, "must_change_credentials": False, "unknown": {"keep": True}},
        "disabled-a": {"sids": ["seo-1"], "pw_hash": disabled_hash, "disabled": True, "must_change_credentials": False},
        "stale-a": {"sids": ["gone-1"], "pw_hash": generate_password_hash("stale-password"), "disabled": False},
    }
    students_path.write_text(json.dumps(students, ensure_ascii=False), encoding="utf-8")
    accounts_path.write_text(json.dumps(accounts, ensure_ascii=False), encoding="utf-8")
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE unrelated_sentinel(value TEXT NOT NULL)")
    db.execute("INSERT INTO unrelated_sentinel VALUES ('keep')")
    db.commit(); db.close()
    now = lambda: 1000.0
    dependencies = StudentAccountAdminDependencies(
        accounts=StudentAccountRepository(accounts_path, students_path),
        sessions=StudentSessionRepository(db_path, clock=now),
        push=StudentPushRepository(db_path, clock=now),
        activations=StudentActivationCodeRepository(db_path, clock=now),
        audit=StudentAccountAuditRepository(db_path, clock=now),
        clock=now,
    )
    config = load_student_app_config({"STUDENT_APP_PUBLIC_HOST": "app.5a-math.com"})
    app = Flask("student-account-admin")
    app.register_blueprint(create_blueprint(dependencies, config=config, admin_authorizer=test_authorizer))
    return app, accounts_path, db_path, dependencies


def _list_and_reset(count: list[int], app: Flask, accounts_path: Path, deps: StudentAccountAdminDependencies) -> None:
    sessions, push = deps.sessions, deps.push
    sessions.create("custom-a", "minsu-a1", ["minsu-a1", "minsu-a2"], ttl_seconds=500, now=1000)
    sessions.create("custom-a", "minsu-a1", ["minsu-a1", "minsu-a2"], ttl_seconds=1, now=900)
    p256dh, auth = _subscription_keys()
    push.upsert("custom-a", "minsu-a1", "device-1", "https://fcm.googleapis.com/fcm/send/secret-endpoint", p256dh, auth, now=1000)
    client = app.test_client()
    listed = _request(client, "GET", "/api/student-accounts")
    external = _request(client, "GET", "/api/student-accounts", environ_overrides={"REMOTE_ADDR": "203.0.113.7"})
    body, raw = _json(listed), listed.get_data(as_text=True)
    _check(count, listed.status_code == 200 and isinstance(body.get("groups"), list) and len(body["groups"]) == 3, "roster groups are listed")
    _check(count, external.status_code == 200 and len(_json(external).get("groups", [])) == 3, "valid Basic credentials open account administration off-network")
    group = next(item for item in body["groups"] if item.get("account", {}).get("aid") == "custom-a")
    _check(count, group["account"]["status"] == "active" and group["account"]["activeSessionCount"] == 1 and group["account"]["activePushSubscriptionCount"] == 1 and group["activationCodeRequired"] is True, "list reports counts and marks every duplicate group for group-bound activation")
    missing_group = next(item for item in body["groups"] if item["identity"]["sids"] == ["minsu-b1"])
    _check(count, missing_group["account"] is None and missing_group["activationCodeRequired"] is True, "duplicate unlinked group requires code")
    forbidden = ("pw_hash", "old-password", "secret-endpoint", p256dh, auth, '"activationCode":')
    _check(count, all(secret not in raw for secret in forbidden), "list omits hashes, codes, endpoints, and keys")
    reset = _request(client, "POST", "/api/student-accounts/custom-a/reset")
    record = _account(accounts_path, "custom-a")
    _check(count, reset.status_code == 200 and check_password_hash(record["pw_hash"], "1234") and record["must_change_credentials"] is True, "reset installs exact 1234 and forces change")
    db = sqlite3.connect(sessions.db_path); unrevoked = db.execute("SELECT COUNT(*) FROM student_app_sessions WHERE aid='custom-a' AND revoked_at IS NULL").fetchone(); db.close()
    _check(count, record["unknown"] == {"keep": True} and sessions.active_count("custom-a", now=1000) == 0 and unrevoked == (0,), "reset preserves unknown fields and revokes every session")


def _state_actions(count: list[int], app: Flask, accounts_path: Path, deps: StudentAccountAdminDependencies) -> None:
    sessions, push, client = deps.sessions, deps.push, app.test_client()
    p256dh, auth = _subscription_keys()
    sessions.create("custom-a", "minsu-a1", ["minsu-a1", "minsu-a2"], now=1000)
    push.upsert("custom-a", "minsu-a2", "device-2", "https://fcm.googleapis.com/fcm/send/second", p256dh, auth, now=1000)
    disabled = _request(client, "POST", "/api/student-accounts/custom-a/disable")
    _check(count, disabled.status_code == 200 and _account(accounts_path, "custom-a")["disabled"] is True, "disable changes account state")
    _check(count, sessions.active_count("custom-a", now=1000) == 0 and push.active_count("custom-a") == 0, "disable revokes sessions and push")
    reset_disabled = _request(client, "POST", "/api/student-accounts/custom-a/reset")
    _check(count, reset_disabled.status_code == 409 and _json(reset_disabled).get("code") == "account_disabled", "disabled reset is typed conflict")
    before_hash = _account(accounts_path, "custom-a")["pw_hash"]
    enabled = _request(client, "POST", "/api/student-accounts/custom-a/enable")
    _check(count, enabled.status_code == 200 and _account(accounts_path, "custom-a")["pw_hash"] == before_hash, "enable preserves credential hash")
    sessions.create("custom-a", "minsu-a1", ["minsu-a1", "minsu-a2"], now=1000)
    push.upsert("custom-a", "minsu-a1", "device-3", "https://fcm.googleapis.com/fcm/send/third", p256dh, auth, now=1000)
    revoked = _request(client, "POST", "/api/student-accounts/custom-a/revoke-sessions")
    _check(count, revoked.status_code == 200 and sessions.active_count("custom-a", now=1000) == 0 and push.active_count("custom-a") == 1, "session-only revoke leaves push active")


def _activation_and_errors(count: list[int], app: Flask, db_path: Path, deps: StudentAccountAdminDependencies) -> None:
    client = app.test_client()
    first = _request(client, "POST", "/api/student-accounts/김민수/activation-code", json={"sids": ["minsu-b1"]})
    first_body = _json(first); first_code = first_body.get("activationCode")
    _check(count, first.status_code == 200 and isinstance(first_code, str) and len(first_code) == 6 and first_code.isdigit() and first_body.get("expiresAt") == 87400.0, "six-digit 24h code is returned once")
    second = _request(client, "POST", "/api/student-accounts/김민수/activation-code", json={"sids": ["minsu-b1"]})
    second_code = _json(second).get("activationCode")
    relisted = _request(client, "GET", "/api/student-accounts").get_data(as_text=True)
    _check(count, first_code not in relisted and str(second_code) not in relisted and '"activationCode":' not in relisted, "issued code never reappears in account listing")
    identity_key = "김민수||B고||2"
    _check(count, isinstance(second_code, str) and deps.activations.redeem(identity_key, first_code, now=1000) is None, "new issue invalidates old active code for the exact identity group")
    _check(count, deps.activations.redeem(identity_key, second_code, now=1000) is not None and deps.activations.redeem(identity_key, second_code, now=1000) is None, "new group-bound code is one-use")
    linked = _request(client, "POST", "/api/student-accounts/custom-a/activation-code", json={"sids": ["minsu-a1", "minsu-a2"]})
    _check(count, linked.status_code == 200 and deps.activations.redeem("김민수||A고||1", _json(linked).get("activationCode"), now=1000) is not None, "linked duplicate group can issue through its account id")
    cases = (
        (_request(client, "POST", "/api/student-accounts/missing/reset"), 404, "account_not_found"),
        (_request(client, "POST", "/api/student-accounts/stale-a/reset"), 409, "stale_account"),
        (_request(client, "POST", "/api/student-accounts/김민수/activation-code", json={"sids": "minsu-b1"}), 400, "invalid_sids"),
        (_request(client, "POST", "/api/student-accounts/김민수/activation-code", json={"sids": ["minsu-a1"]}), 409, "sid_set_mismatch"),
        (_request(client, "POST", "/api/student-accounts/disabled-a/activation-code", json={"sids": ["seo-1"]}), 409, "activation_code_not_required"),
        (_request(client, "POST", "/api/student-accounts/custom-a/reset", data="{", content_type="application/json"), 400, "invalid_json"),
    )
    _check(count, all(response.status_code == status and _json(response).get("code") == code and "activationCode" not in _json(response) for response, status, code in cases), "malformed, missing, stale, and conflicting inputs are typed without code leaks")
    db = sqlite3.connect(db_path)
    rows = db.execute("SELECT action,target_aid_digest,metadata_json FROM student_account_audit").fetchall()
    digests = db.execute("SELECT code_digest FROM student_activation_codes").fetchall()
    audit_rows = json.dumps(rows, ensure_ascii=False)
    sentinel = db.execute("SELECT value FROM unrelated_sentinel").fetchone(); integrity = db.execute("PRAGMA integrity_check").fetchone(); db.close()
    _check(count, first_code not in audit_rows and second_code not in audit_rows and "minsu-b1" not in audit_rows and "김민수" not in audit_rows, "audit stores no raw code, SID, or target identity")
    _check(count, all(len(str(row[0])) == 64 and row[0] not in {first_code, second_code} for row in digests), "activation storage persists digest only")
    actions = {row[0] for row in rows}
    _check(count, {"account.reset", "account.disable", "account.enable", "sessions.revoke", "activation_code_issue"} <= actions, "every admin mutation emits a redacted audit action")
    _check(count, sentinel == ("keep",) and integrity == ("ok",), "unrelated SQLite sentinel and integrity survive")


def _shared_name_bridge(count: list[int], root: Path, config: Any) -> None:
    private = root / "shared-name"
    private.mkdir()
    students_path, accounts_path, db_path = private / "students.json", private / "accounts.json", private / "app.sqlite"
    students_path.write_text(json.dumps([
        {"id": "group-a", "name": "김민수", "school": "A고", "grade": "1"},
        {"id": "group-b", "name": "김민수", "school": "B고", "grade": "2"},
    ], ensure_ascii=False), encoding="utf-8")
    accounts_path.write_text(json.dumps({"김민수": {"sids": ["group-a"], "pw_hash": generate_password_hash("1234"), "disabled": False, "must_change_credentials": True}}, ensure_ascii=False), encoding="utf-8")
    now = lambda: 1000.0
    deps = StudentAccountAdminDependencies(
        accounts=StudentAccountRepository(accounts_path, students_path), sessions=StudentSessionRepository(db_path, clock=now),
        push=StudentPushRepository(db_path, clock=now), activations=StudentActivationCodeRepository(db_path, clock=now),
        audit=StudentAccountAuditRepository(db_path, clock=now), clock=now,
    )
    app = Flask("student-account-shared-name")
    app.register_blueprint(create_blueprint(deps, config=config, admin_authorizer=test_authorizer))
    client = app.test_client()
    listed = _json(_request(client, "GET", "/api/student-accounts"))["groups"]
    _check(count, all(group["activationCodeRequired"] is True for group in listed), "linked and unlinked duplicate groups both require group-bound activation")
    issued = _request(client, "POST", "/api/student-accounts/김민수/activation-code", json={"sids": ["group-b"]})
    code = _json(issued).get("activationCode")
    _check(count, issued.status_code == 200 and isinstance(code, str), "shared-name account for group A does not block group B issuance")
    _check(count, deps.activations.redeem("김민수", code, now=1000) is None, "shared name cannot redeem a group-bound code")
    _check(count, deps.activations.redeem("김민수||B고||2", code, now=1000) is not None, "code redeems only for the exact SID identity group")


def _failure_ordering(count: list[int], accounts_path: Path, deps: StudentAccountAdminDependencies, config: Any) -> None:
    def fail_revoke(*_args: Any, **_kwargs: Any) -> int:
        raise sqlite3.OperationalError("injected storage failure")

    def request_with(sessions: Any, push: Any, suffix: str, action: str) -> Response:
        app = Flask(f"student-account-failure-{suffix}")
        broken = StudentAccountAdminDependencies(
            accounts=deps.accounts, sessions=sessions, push=push,
            activations=deps.activations, audit=deps.audit, clock=deps.clock,
        )
        app.register_blueprint(create_blueprint(broken, config=config, admin_authorizer=test_authorizer))
        return _request(app.test_client(), "POST", f"/api/student-accounts/custom-a/{action}")

    passive_push = SimpleNamespace(active_count=lambda _aid: 0, revoke_account=lambda *_args, **_kwargs: 0)
    failing_sessions = SimpleNamespace(active_count=lambda _aid, **_kwargs: 0, revoke_account=fail_revoke)
    before_hash = _account(accounts_path, "custom-a")["pw_hash"]
    reset = request_with(failing_sessions, passive_push, "session", "reset")
    _check(count, reset.status_code == 409 and _account(accounts_path, "custom-a")["pw_hash"] == before_hash, "session failure cannot partially reset credentials")

    passive_sessions = SimpleNamespace(active_count=lambda _aid, **_kwargs: 0, revoke_account=lambda *_args, **_kwargs: 0)
    failing_push = SimpleNamespace(active_count=lambda _aid: 0, revoke_account=fail_revoke)
    disabled = request_with(passive_sessions, failing_push, "push", "disable")
    _check(count, disabled.status_code == 409 and _account(accounts_path, "custom-a")["disabled"] is False, "push failure cannot partially disable account")


def _source_checks(count: list[int]) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for relative in ("routes/api_student_accounts.py", "core/student_account_admin_service.py", "core/admin_basic_auth.py", "scripts/student_mobile_app_checks/admin_auth_contract.py", "scripts/student_mobile_app_checks/admin_accounts.py"):
        source = (ROOT / relative).read_text("utf-8")
        compile(source, relative, "exec")
        pure = sum(bool(line.strip()) and not line.lstrip().startswith("#") for line in source.splitlines())
        sizes[relative] = pure
        _check(count, pure <= 250, f"{relative} stays within 250 pure LOC")
    app_source = (ROOT / "app.py").read_text("utf-8")
    _check(count, "bp_api_student_accounts" in app_source and "register_blueprint(bp_api_student_accounts)" in app_source, "app registers admin account blueprint")
    return sizes


def run_checks() -> dict[str, CheckValue]:
    count = [0]
    with tempfile.TemporaryDirectory(prefix="student-admin-accounts-") as raw:
        root = Path(raw)
        config = load_student_app_config({"STUDENT_APP_PUBLIC_HOST": "app.5a-math.com"})
        run_admin_auth_contract(count, _check, ROOT)
        _lazy_gate_checks(count, root, config)
        app, accounts_path, db_path, dependencies = _fixture(root)
        _list_and_reset(count, app, accounts_path, dependencies)
        _state_actions(count, app, accounts_path, dependencies)
        _activation_and_errors(count, app, db_path, dependencies)
        _shared_name_bridge(count, root, config)
        _failure_ordering(count, accounts_path, dependencies, config)
        sizes = _source_checks(count)
    return {"name": "admin-accounts", "assertions": count[0], "passed": True, "pure_loc": sizes, "temporary_removed": not root.exists()}


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False, sort_keys=True))
