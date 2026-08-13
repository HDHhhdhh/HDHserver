"""Temp-only contracts for academy administrator HTTP Basic authentication."""
from __future__ import annotations

import base64
import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Callable

from flask import Flask
from werkzeug.security import generate_password_hash

from core.admin_basic_auth import (
    ADMIN_AUTH_CHALLENGE,
    ADMIN_PASSWORD_HASH_ENV,
    ADMIN_USERNAME_ENV,
    verify_admin_authorization,
)
from routes.pages import bp_pages


TEST_USERNAME = "검증관리자"
TEST_PASSWORD = "temporary-test-password"
TEST_AUTHORIZATION = "Basic " + base64.b64encode(f"{TEST_USERNAME}:{TEST_PASSWORD}".encode("utf-8")).decode("ascii")


def test_authorizer(authorization: str | None) -> bool:
    return authorization == TEST_AUTHORIZATION


def add_test_authorization(kwargs: MutableMapping[str, Any]) -> None:
    headers = dict(kwargs.get("headers") or {})
    headers.setdefault("Authorization", TEST_AUTHORIZATION)
    kwargs["headers"] = headers


def _request(client: Any, path: str, authorization: str | None = None, remote: str = "127.0.0.1") -> Any:
    headers = {} if authorization is None else {"Authorization": authorization}
    return client.get(path, base_url="http://127.0.0.1:8003", headers=headers, environ_overrides={"REMOTE_ADDR": remote})


def run_admin_auth_contract(count: list[int], check: Callable[[list[int], bool, str], None], root: Path) -> None:
    values = {
        ADMIN_USERNAME_ENV: TEST_USERNAME,
        ADMIN_PASSWORD_HASH_ENV: generate_password_hash(TEST_PASSWORD),
    }
    check(count, verify_admin_authorization(TEST_AUTHORIZATION, values), "UTF-8 administrator credentials verify against a hash")
    bad_password = "Basic " + base64.b64encode(f"{TEST_USERNAME}:wrong".encode()).decode()
    bad_username = "Basic " + base64.b64encode(f"other:{TEST_PASSWORD}".encode()).decode()
    check(count, not verify_admin_authorization(bad_password, values), "wrong administrator password is rejected")
    check(count, not verify_admin_authorization(bad_username, values), "wrong administrator username is rejected")
    check(count, not verify_admin_authorization("Basic !!!", values), "malformed Basic credentials are rejected")
    check(count, not verify_admin_authorization(TEST_AUTHORIZATION, {}), "missing administrator configuration fails closed")

    app = Flask("admin-page-auth", static_folder=str(root / "static"), static_url_path="")
    app.config["ACADEMY_ADMIN_AUTHORIZER"] = test_authorizer
    app.register_blueprint(bp_pages)
    client = app.test_client()
    missing = _request(client, "/admin")
    bad = _request(client, "/admin", "Basic Zm9vOmJhcg==")
    valid = _request(client, "/admin", TEST_AUTHORIZATION)
    static_bypass = _request(client, "/admin.html")
    case_bypasses = [_request(client, path) for path in ("/ADMIN.HTML", "/All.HTML", "/VIDEO-MANAGE.HTML", "/admin.html.")]
    ntfs_bypasses = [_request(client, path) for path in (
        "/ADMIN~1.HTM", "/ALL~1.HTM", "/FILE-M~1.HTM", "/SCHOOL~1.HTM", "/TESTS~1.HTM", "/VIDEO-~1.HTM",
        "/admin.html::$DATA", "/admin.html%3A%3A%24DATA",
    )]
    related_page = _request(client, "/students")
    demo = _request(client, "/demo/rh3123")
    off_network = _request(client, "/admin", TEST_AUTHORIZATION, "203.0.113.8")
    check(count, missing.status_code == 401 and missing.headers.get("WWW-Authenticate") == ADMIN_AUTH_CHALLENGE, "admin page challenges missing credentials")
    check(count, bad.status_code == 401, "admin page rejects bad credentials")
    check(count, valid.status_code == 200, "valid credentials open the admin page")
    check(count, static_bypass.status_code == 401 and related_page.status_code == 401, "direct static and related admin pages cannot bypass authentication")
    check(count, all(response.status_code == 401 for response in case_bypasses), "Windows case and trailing-dot aliases cannot bypass authentication")
    expected_ntfs = 401 if os.name == "nt" else 404
    check(count, all(response.status_code == expected_ntfs for response in ntfs_bypasses), "NTFS 8.3 and alternate-stream aliases cannot bypass authentication")
    check(count, demo.status_code == 200, "demo admin route remains transparent")
    check(count, off_network.status_code == 403, "administrator credentials do not bypass the academy network gate")


__all__ = ("TEST_AUTHORIZATION", "add_test_authorization", "run_admin_auth_contract", "test_authorizer")
