#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# How to run: C:\\server\\venv\\Scripts\\python.exe scripts\\student_mobile_app_checks\\surface.py

"""Exact host/path/session/proxy checks for Todo 7."""

from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from collections.abc import Iterator
from typing import Final, TypeAlias

from flask import Blueprint, Flask, g, jsonify

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CheckValue: TypeAlias = str | int | bool | None | list["CheckValue"] | dict[str, "CheckValue"]
CheckState: TypeAlias = list[int | str]
EVIDENCE: Final[Path] = Path(os.environ.get("STUDENT_APP_SURFACE_EVIDENCE", str(ROOT / ".omo" / "evidence" / "student-mobile-app-v2" / "task-7" / "sw-canonical-remediation-l1-surface.json")))


@contextmanager
def _env(values: dict[str, str]) -> Iterator[None]:
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _json(response) -> dict[str, CheckValue]:  # noqa: ANN001
    payload = response.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _check(state: CheckState, condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    state[0] = int(state[0]) + 1
    state.append(label)


def _injected_checks(state: CheckState) -> None:
    from core.student_app_config import load_student_app_config
    from core.student_public_surface import (
        AUTH_ROUTE_METHODS,
        PUSH_ROUTE_METHODS,
        SessionIdentity,
        install_student_public_surface,
        register_student_app_domain,
    )
    from routes.pages import bp_pages

    with tempfile.TemporaryDirectory(prefix="student-surface-") as raw:
        root = Path(raw)
        config = load_student_app_config(
            {
                "STUDENT_APP_PUBLIC_ENABLED": "1",
                "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
                "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1/32",
            }
        )
        app = Flask("surface-injected", static_folder=str(ROOT / "static"), static_url_path="")
        hits = {"login": 0, "session": 0, "switch": 0, "legacy": 0, "prefix": 0, "method": 0}
        seen_ips: list[str] = []
        auth = Blueprint("surface_auth", __name__)
        files = Blueprint("surface_files", __name__)

        @auth.post("/api/mobile/auth/login")
        def login():
            hits["login"] += 1
            seen_ips.append(getattr(g, "student_app_client_ip", ""))
            return jsonify({"ok": True})

        @auth.post("/api/mobile/auth/switch")
        def switch():
            hits["switch"] += 1
            return jsonify({"ok": True})

        @auth.post("/api/mobile/auth/session")
        def method_mutant_probe():
            hits["method"] += 1
            return jsonify({"ok": True})

        @auth.get("/api/mobile/auth/session")
        def session_probe():
            hits["session"] += 1
            return jsonify({"ok": True})

        @auth.post("/api/app/v1/login")
        def prefix_mutant_probe():
            hits["prefix"] += 1
            return jsonify({"ok": True})

        @files.get("/files/announcements/<path:filename>")
        def announcement(filename: str):  # noqa: ARG001
            return "ok"

        known = {
            ("/api/mobile/auth/login", "POST"),
            ("/api/mobile/auth/session", "GET"),
            ("/api/mobile/auth/switch", "POST"),
        }
        for index, (path, method) in enumerate(sorted(config.public_api_route_methods)):
            if (path, method) in known:
                continue

            def legacy_probe(index: int = index, path: str = path, method: str = method):  # noqa: ARG001
                hits["legacy"] += 1
                return jsonify({"ok": True, "route": path, "method": method})

            auth.add_url_rule(path, endpoint=f"legacy_{index}", view_func=legacy_probe, methods=[method])

        def resolve(token: str) -> SessionIdentity | None:
            return SessionIdentity("sid-a", ("sid-a", "sid-b")) if token == "session-token" else None

        install_student_public_surface(
            app,
            config=config,
            session_resolver=resolve,
            csrf_validator=lambda token, csrf: token == "session-token" and csrf == "csrf",
        )
        app.register_blueprint(bp_pages)
        register_student_app_domain(app, auth, AUTH_ROUTE_METHODS)
        app.register_blueprint(files)
        app.config.update(TESTING=True)
        client = app.test_client()
        edge = {"CF-Connecting-IP": "110.14.147.14"}
        origin_only = {"Origin": "https://app.5a-math.com"}
        origin = {"Origin": "https://app.5a-math.com", "X-CSRF-Token": "csrf"}
        _check(state, client.get("/", base_url="https://app.5a-math.com", headers=edge).status_code == 302, "public root redirects")
        _check(state, client.get("/", base_url="https://app.5a-math.com", headers=edge).headers["Location"] == "/app", "redirect stays same-origin")
        _check(state, (app_root := client.get("/app", base_url="https://app.5a-math.com", headers=edge)).status_code == 200 and app_root.headers["Cache-Control"] == "no-store", "canonical app root is public")
        _check(state, client.get("/student-app.html", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "raw student shell alias is denied")
        manifest = client.get("/manifest.webmanifest", base_url="https://app.5a-math.com", headers=edge)
        _check(state, manifest.status_code == 200 and manifest.headers["Content-Type"].startswith("application/manifest+json"), "manifest allowed with exact type")
        _check(state, manifest.headers["Cache-Control"] == "no-cache, max-age=0, must-revalidate", "manifest is non-stale")
        asset = client.get("/js/student-app.js", base_url="https://app.5a-math.com", headers=edge)
        _check(state, asset.status_code == 200 and asset.headers["Cache-Control"] == "public, max-age=0, must-revalidate", "shell asset is revalidated")
        offline = client.get("/offline.html", base_url="https://app.5a-math.com", headers=edge)
        _check(state, offline.status_code == 200 and offline.headers.get("ETag"), "offline help has content ETag")
        _check(state, client.get("/admin", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "admin is denied")
        _check(state, client.get("/app/js/student-app.js", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "app asset alias is denied")
        _check(state, client.get("/api/mobile/auth/session", base_url="https://app.5a-math.com", headers=edge).status_code == 401, "session discovery requires a cookie")
        _check(state, client.post("/api/mobile/auth/session", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "method collapse is denied")
        _check(state, client.post("/api/mobile/auth/login", base_url="https://app.5a-math.com", headers=edge | origin_only).status_code == 200 and hits["login"] == 1, "login is the only unauthenticated API")
        evil_login = client.post("/api/mobile/auth/login", base_url="https://app.5a-math.com", headers=edge | {"Origin": "https://evil.example"})
        _check(state, evil_login.status_code == 403 and _json(evil_login).get("code") == "origin_required", "public login rejects evil Origin generically")
        _check(state, client.post("/api/mobile/auth/switch", base_url="https://app.5a-math.com", headers=edge).status_code == 401 and hits["switch"] == 0, "missing session is denied before handler")
        client.set_cookie(config.session_cookie_name, "session-token", domain="app.5a-math.com", path="/")
        _check(state, client.post("/api/mobile/auth/switch", json={"sid": "sid-b"}, base_url="https://app.5a-math.com", headers=edge | origin).status_code == 403, "SID mismatch is denied")
        allowed = client.post("/api/mobile/auth/switch", json={"sid": "sid-a"}, base_url="https://app.5a-math.com", headers=edge | origin)
        _check(state, allowed.status_code == 200 and hits["switch"] == 1, "matching SID reaches exact handler")
        bootstrap = client.get("/api/student/bootstrap?sid=sid-a", base_url="https://app.5a-math.com", headers=edge)
        _check(state, bootstrap.status_code == 200 and hits["legacy"] >= 1, "declared legacy GET reaches handler")
        csrf_missing = client.post("/api/watch", json={"sid": "sid-a"}, base_url="https://app.5a-math.com", headers=edge | origin_only)
        _check(state, csrf_missing.status_code == 403 and _json(csrf_missing).get("code") == "csrf_required", "unsafe legacy API requires CSRF")
        csrf_bad = client.post("/api/watch", json={"sid": "sid-a"}, base_url="https://app.5a-math.com", headers=edge | origin | {"X-CSRF-Token": "bad"})
        _check(state, csrf_bad.status_code == 403 and _json(csrf_bad).get("code") == "csrf_invalid", "unsafe legacy API rejects bad CSRF")
        csrf_ok = client.post("/api/watch", json={"sid": "sid-a"}, base_url="https://app.5a-math.com", headers=edge | origin)
        _check(state, csrf_ok.status_code == 200 and hits["legacy"] >= 2, "unsafe legacy API reaches handler with CSRF")
        _check(state, client.post("/api/tests-config", json={"sid": "sid-a"}, base_url="https://app.5a-math.com", headers=edge | origin).status_code == 404, "declared path disallowed method is denied")
        prefix_negative = client.post("/api/app/v1/login", base_url="https://app.5a-math.com", headers=edge)
        _check(state, prefix_negative.status_code == 404 and hits["prefix"] == 0, "prefix mutant is denied")
        method_negative = client.post("/api/mobile/auth/session", base_url="https://app.5a-math.com", headers=edge)
        _check(state, method_negative.status_code == 404 and hits["method"] == 0, "method mutant is denied")
        for path, method in sorted(config.public_api_route_methods):
            if path == "/api/watch" and method == "POST":
                continue
            headers = edge | origin if method in {"POST", "PUT", "PATCH", "DELETE"} else edge
            kwargs = {"headers": headers, "base_url": "https://app.5a-math.com"}
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                kwargs["json"] = {"sid": "sid-a"}
            response = client.open(path, method=method, **kwargs)
            _check(state, response.status_code == 200, f"declared pair reaches handler: {method} {path}")
        for path, method in sorted(PUSH_ROUTE_METHODS):
            _check(state, client.open(path, method=method, base_url="https://app.5a-math.com", headers=edge).status_code == 404, f"future push pair is not exposed: {method} {path}")
        _check(state, client.get("/student/sid-a", base_url="https://app.5a-math.com", headers=edge).status_code == 200, "current student page is allowed")
        _check(state, client.get("/student/sid-b", base_url="https://app.5a-math.com", headers=edge).status_code == 403, "foreign student page is denied")
        _check(state, client.get("/files/announcements/../secret", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "file traversal is denied")
        _check(state, client.get("/files/announcements/%2e%2e/secret", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "encoded file traversal is denied")
        _check(state, client.get("/files/announcements/%252e%252e/secret", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "double-encoded file traversal is denied")
        _check(state, client.get("/files/other.png", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "nonannouncement files are denied")
        safe_file = client.get("/files/announcements/notice.pdf", base_url="https://app.5a-math.com", headers=edge)
        _check(state, safe_file.status_code == 200 and safe_file.headers["Cache-Control"] == "no-store", "safe announcement file reaches handler")
        _check(state, client.get("/js/test_answer_link_map.json", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "answer map is outside public surface")
        _check(state, client.open("/offline.html", method="OPTIONS", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "offline OPTIONS is denied")
        _check(state, client.get("/app/", base_url="http://app.5a-math.com", headers=edge).status_code == 404, "HTTP public host is denied")
        untrusted = client.post(
            "/api/mobile/auth/login",
            base_url="https://app.5a-math.com",
            headers={"CF-Connecting-IP": "198.51.100.8", **origin_only},
            environ_base={"REMOTE_ADDR": "198.51.100.9"},
        )
        _check(state, untrusted.status_code == 200 and seen_ips[-1] == "198.51.100.9", "untrusted forwarding does not alter request")
        malformed = client.get("/app/", base_url="https://app.5a-math.com", headers={"CF-Connecting-IP": "110.14.147.14, 198.51.100.8"})
        _check(state, malformed.status_code == 404, "multi-hop CF address fails closed")
        _check(state, client.get("/app/", base_url="https://app.5a-math.com.evil", headers=edge).status_code == 404, "host suffix confusion is denied")
        _check(state, client.get("/app/", base_url="https://app.5a-math.com:443", headers=edge).status_code == 404, "host port confusion is denied")
        _check(state, client.get("/app/", base_url="https://127.0.0.1").status_code == 200, "non-public app route remains local")
        _check(state, client.get("/student/sid-a", base_url="https://127.0.0.1").status_code == 200, "non-public student route remains local")


def _actual_app_checks(state: CheckState) -> None:
    with tempfile.TemporaryDirectory(prefix="student-surface-app-") as raw:
        root = Path(raw)
        environment = {
            "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
            "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1/32",
            "STUDENT_APP_DB_PATH": str(root / "app.sqlite"),
            "STUDENT_APP_ACCOUNTS_PATH": str(root / "auth_accounts.json"),
            "STUDENT_APP_STUDENTS_PATH": str(root / "students.json"),
        }
        module = importlib.import_module("app")
        with _env(environment | {"STUDENT_APP_PUBLIC_ENABLED": "0"}):
            disabled = module.create_app()
            client = disabled.test_client()
            edge = {"CF-Connecting-IP": "110.14.147.14"}
            _check(state, client.get("/app/", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "default-off public host is denied")
            legacy_baseline = client.get("/", base_url="https://127.0.0.1")
            _check(state, legacy_baseline.status_code == 200, "default-off local root remains available")
        with _env(environment | {"STUDENT_APP_PUBLIC_ENABLED": "1"}):
            app = module.create_app()
            client = app.test_client()
            edge = {"CF-Connecting-IP": "110.14.147.14"}
            _check(state, (canonical := client.get("/app", base_url="https://app.5a-math.com", headers=edge)).status_code == 200 and canonical.headers["Cache-Control"] == "no-store", "actual canonical app root works")
            public = client.get("/app/", base_url="https://app.5a-math.com", headers=edge)
            _check(state, public.status_code == 200 and public.headers["Cache-Control"] == "no-store", "actual app shell is no-store")
            _check(state, client.get("/student-app.html", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "actual app denies raw shell alias")
            _check(state, client.get("/admin", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "actual app denies admin")
            _check(state, client.post("/api/app/v1/login", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "app-v1 alias is denied")
            _check(state, (local := client.get("/", base_url="https://127.0.0.1")).status_code == 200 and local.data == legacy_baseline.data and local.content_type == legacy_baseline.content_type, "local root shape remains legacy")
            _check(state, client.get("/student-app.html", base_url="https://127.0.0.1").status_code == 200, "local raw shell remains direct static")


def run_checks() -> dict[str, CheckValue]:
    state: CheckState = [0]
    _injected_checks(state)
    from scripts.student_mobile_app_checks.surface_auth_ip import run_auth_throttle_ip_check

    run_auth_throttle_ip_check(state)
    _actual_app_checks(state)
    result: dict[str, CheckValue] = {
        "name": "surface",
        "assertions": int(state[0]),
        "passed": True,
        "scenarios": [value for value in state[1:] if isinstance(value, str)],
        "mutant_guards": [
            "prefix: fake /api/app/v1/login handler remained unhit at 404",
            "method: fake POST /api/mobile/auth/session handler remained unhit at 404",
            "host: suffix/port host probes remained 404",
            "proxy: forged multi-hop CF header remained 404 and untrusted IP stayed peer",
            "csrf: missing/bad CSRF remained 403 before fake legacy handler",
            "sid: foreign student page remained 403",
        ],
        "invocation": "python scripts/student_mobile_app_checks/surface.py",
        "runtime_diff": {},
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:  # noqa: BROAD_EXCEPT_OK
    try:
        result = run_checks()
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK
        print(f"surface: FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(f"surface: PASS ({result['assertions']} assertions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
