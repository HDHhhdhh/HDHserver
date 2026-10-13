#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# How to run: C:\\server\\venv\\Scripts\\python.exe scripts\\student_mobile_app_checks\\surface.py

"""Exact host/path/session/proxy checks for Todo 7."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Final, TypeAlias

from flask import Blueprint, Flask, g, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.student_mobile_app_checks import surface_raw_targets as raw_targets  # noqa: E402
CheckValue: TypeAlias = str | int | bool | None | list["CheckValue"] | dict[str, "CheckValue"]
CheckState: TypeAlias = list[int | str]
EVIDENCE: Final[Path] = Path(os.environ.get("STUDENT_APP_SURFACE_EVIDENCE", str(ROOT / ".omo" / "evidence" / "student-mobile-app-v2" / "task-7" / "sw-canonical-remediation-l1-surface.json")))


def _json(response) -> dict[str, CheckValue]:  # noqa: ANN001
    payload = response.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _check(state: CheckState, condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    state[0] = int(state[0]) + 1
    state.append(label)


def _pure_loc_checks(state: CheckState) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for relative in ("core/student_public_surface_adapter.py", "core/student_public_proxy.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        compile(source, relative, "exec")
        pure = sum(bool(line.strip()) and not line.lstrip().startswith("#") for line in source.splitlines())
        sizes[relative] = pure
        _check(state, pure <= 250, f"{relative} stays within 250 pure LOC")
    return sizes


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
        config = load_student_app_config(
            {
                "STUDENT_APP_PUBLIC_ENABLED": "1",
                "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
                "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1/32",
            }
        )
        app = Flask("surface-injected", static_folder=str(ROOT / "static"), static_url_path="")
        hits = {"login": 0, "session": 0, "switch": 0, "legacy": 0, "file": 0, "prefix": 0, "method": 0}
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
            hits["file"] += 1
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
            if token == "session-token":
                return SessionIdentity("sid-a", ("sid-a", "sid-b"))
            if token == "credentials-token":
                return SessionIdentity("sid-a", ("sid-a", "sid-b"), True)
            return None

        install_student_public_surface(
            app,
            config=config,
            session_resolver=resolve,
            csrf_validator=lambda token, csrf: token in {"session-token", "credentials-token"} and csrf == "csrf",
        )
        app.register_blueprint(bp_pages)
        register_student_app_domain(app, auth, AUTH_ROUTE_METHODS)
        app.register_blueprint(files)
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
        app.config.update(TESTING=True)
        client = app.test_client()
        edge = {"CF-Connecting-IP": "110.14.147.14"}
        origin_only = {"Origin": "https://app.5a-math.com"}
        origin = {"Origin": "https://app.5a-math.com", "X-CSRF-Token": "csrf"}
        raw_targets.check_public_root_boundary(client, edge, lambda condition, label: _check(state, condition, label))
        legacy_root = client.get("/", base_url="https://5a-math.com", headers=edge)
        _check(state, legacy_root.status_code == 200, "legacy root stays live while redirect approval is off")
        _check(state, client.get("/student/sid-a", base_url="https://5a-math.com", headers=edge).status_code == 200, "legacy student page keeps its original auth path")
        _check(state, client.get("/js/student.js", base_url="https://5a-math.com", headers=edge).status_code == 200, "legacy shared student asset remains available")
        for app_only_path in ("/app", "/student-app.html", "/manifest.webmanifest", "/sw.js", "/js/student-app.js", "/api/mobile/auth/session"):
            _check(state, client.get(app_only_path, base_url="https://5a-math.com", headers=edge).status_code == 404, f"legacy host blocks unfinished app path: {app_only_path}")
        _check(state, client.get("/", base_url="https://www.5a-math.com", headers=edge).status_code == 404, "unconfigured www host does not widen the legacy boundary")
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
        _check(state, client.get("/api/student/bootstrap?sid=sid-a", base_url="https://app.5a-math.com", headers=edge).status_code == 401, "bootstrap requires a cookie")
        _check(state, client.post("/api/mobile/auth/session", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "method collapse is denied")
        _check(state, client.post("/api/mobile/auth/login", base_url="https://app.5a-math.com", headers=edge | origin_only).status_code == 200 and hits["login"] == 1, "login remains unauthenticated")
        _check(state, client.get("/api/mobile/push/public-key", base_url="https://app.5a-math.com", headers=edge).status_code == 200, "Push public key is unauthenticated")
        _check(state, client.get("/api/mobile/push/status", base_url="https://app.5a-math.com", headers=edge).status_code == 401, "Push status requires a session")
        evil_login = client.post("/api/mobile/auth/login", base_url="https://app.5a-math.com", headers=edge | {"Origin": "https://evil.example"})
        _check(state, evil_login.status_code == 403 and _json(evil_login).get("code") == "origin_required", "public login rejects evil Origin generically")
        _check(state, client.post("/api/mobile/auth/switch", base_url="https://app.5a-math.com", headers=edge).status_code == 401 and hits["switch"] == 0, "missing session is denied before handler")
        client.set_cookie(config.session_cookie_name, "session-token", domain="app.5a-math.com", path="/")
        switched = client.post("/api/mobile/auth/switch", json={"sid": "sid-b"}, base_url="https://app.5a-math.com", headers=edge | origin)
        _check(state, switched.status_code == 200 and hits["switch"] == 1, "switch target reaches the handler for allowed-SID validation")
        alias_switched = client.post("/api/mobile/auth/switch", json={"targetSid": "sid-b"}, base_url="https://app.5a-math.com", headers=edge | origin)
        _check(state, alias_switched.status_code == 200 and hits["switch"] == 2, "targetSid switch alias reaches the handler")
        ambiguous = client.post("/api/mobile/auth/switch", json={"sid": "sid-a", "targetSid": "sid-b"}, base_url="https://app.5a-math.com", headers=edge | origin)
        _check(state, ambiguous.status_code == 403 and _json(ambiguous).get("code") == "sid_mismatch" and hits["switch"] == 2, "ambiguous switch targets fail closed")
        legacy_mismatch = client.post("/api/watch", json={"sid": "sid-b"}, base_url="https://app.5a-math.com", headers=edge | origin)
        _check(state, legacy_mismatch.status_code == 403 and _json(legacy_mismatch).get("code") == "sid_mismatch", "non-switch SID mismatch remains denied")
        allowed = client.post("/api/mobile/auth/switch", json={"sid": "sid-a"}, base_url="https://app.5a-math.com", headers=edge | origin)
        _check(state, allowed.status_code == 200 and hits["switch"] == 3, "matching SID reaches exact handler")
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
        _check(state, PUSH_ROUTE_METHODS <= config.public_api_route_methods, "exact Push route pairs are present in the config allowlist")
        _check(state, client.get("/student/sid-a", base_url="https://app.5a-math.com", headers=edge).status_code == 200, "current student page is allowed")
        _check(state, client.get("/student/sid-b", base_url="https://app.5a-math.com", headers=edge).status_code == 403, "foreign student page is denied")
        _check(state, client.get("/files/announcements/../secret", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "file traversal is denied")
        _check(state, client.get("/files/announcements/%2e%2e/secret", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "encoded file traversal is denied")
        _check(state, client.get("/files/announcements/%252e%252e/secret", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "double-encoded file traversal is denied")
        _check(state, client.get("/files/other.png", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "nonannouncement files are denied")
        safe_file = raw_targets.get_equivalent_encoded_announcement(client, edge)
        _check(state, safe_file.status_code == 200 and safe_file.headers["Cache-Control"] == "no-store", "equivalent safe raw encoding reaches handler")
        answer_map = client.get("/js/test_answer_link_map.json", base_url="https://app.5a-math.com", headers=edge)
        _check(state, answer_map.status_code == 200 and answer_map.headers["Cache-Control"] == "no-store", "session-bound answer map uses the sensitive surface")
        anonymous_answer = app.test_client().get("/js/test_answer_link_map.json", base_url="https://app.5a-math.com", headers=edge)
        _check(state, anonymous_answer.status_code == 401, "anonymous request reached sensitive answer map")
        _check(state, client.open("/offline.html", method="OPTIONS", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "offline OPTIONS is denied")
        _check(state, client.get("/app/", base_url="http://app.5a-math.com", headers=edge).status_code == 404, "HTTP public host is denied")
        forged_proxy = client.get(
            "/app/",
            base_url="http://legacy.example",
            headers={
                "CF-Connecting-IP": "110.14.147.14",
                "X-Forwarded-For": "127.0.0.1",
                "X-Forwarded-Host": "app.5a-math.com",
                "X-Forwarded-Proto": "https",
            },
            environ_overrides={"REMOTE_ADDR": "198.51.100.9"},
        )
        _check(state, forged_proxy.status_code == 404, "untrusted original peer cannot forge forwarded host, scheme, or address")
        forged_scheme = client.get(
            "/app/",
            base_url="http://app.5a-math.com",
            headers={"X-Forwarded-For": "127.0.0.1", "X-Forwarded-Proto": "https"},
            environ_overrides={"REMOTE_ADDR": "198.51.100.9"},
        )
        _check(state, forged_scheme.status_code == 404, "untrusted original peer cannot upgrade HTTP with X-Forwarded-Proto")
        forged_local_host = app.test_client().get(
            "/admin",
            base_url="https://app.5a-math.com",
            headers={
                "X-Forwarded-For": "127.0.0.1",
                "X-Forwarded-Host": "127.0.0.1",
                "X-Forwarded-Proto": "https",
            },
            environ_overrides={"REMOTE_ADDR": "198.51.100.9"},
        )
        _check(state, forged_local_host.status_code == 404, "forged forwarded localhost cannot select the legacy branch")
        trusted_proxy = client.get(
            "/",
            base_url="http://127.0.0.1",
            headers={
                "CF-Connecting-IP": "110.14.147.14",
                "X-Forwarded-For": "110.14.147.14",
                "X-Forwarded-Host": "app.5a-math.com",
                "X-Forwarded-Proto": "https",
            },
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        _check(
            state,
            trusted_proxy.status_code == 302 and trusted_proxy.headers.get("Location") == "/app",
            "trusted original proxy reaches the canonical public root redirect",
        )
        trusted_proxy_admin = client.get(
            "/admin",
            base_url="http://127.0.0.1",
            headers={
                "CF-Connecting-IP": "110.14.147.14",
                "X-Forwarded-For": "110.14.147.14",
                "X-Forwarded-Host": "app.5a-math.com",
                "X-Forwarded-Proto": "https",
            },
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        _check(state, trusted_proxy_admin.status_code == 404, "trusted proxy public host cannot fall through to local admin")
        untrusted = client.post(
            "/api/mobile/auth/login",
            base_url="https://app.5a-math.com",
            headers={"CF-Connecting-IP": "198.51.100.8", **origin_only},
            environ_base={"REMOTE_ADDR": "198.51.100.9"},
        )
        _check(state, untrusted.status_code == 200 and seen_ips[-1] == "198.51.100.9", "untrusted forwarding does not alter request")
        pseudo_ipv4_mobile = client.post(
            "/api/mobile/auth/login",
            base_url="https://app.5a-math.com",
            headers={
                "CF-Connecting-IP": "240.0.0.44",
                "CF-Connecting-IPv6": "2a09:bac2:46d9::44",
                **origin_only,
            },
        )
        _check(
            state,
            pseudo_ipv4_mobile.status_code == 200 and seen_ips[-1] == "2a09:bac2:46d9::44",
            "trusted Cloudflare Pseudo IPv4 mobile request restores its original IPv6 client",
        )
        mismatched_ipv6 = client.post(
            "/api/mobile/auth/login",
            base_url="https://app.5a-math.com",
            headers={
                "CF-Connecting-IP": "110.14.147.14",
                "CF-Connecting-IPv6": "2a09:bac2:46d9::44",
                **origin_only,
            },
        )
        _check(state, mismatched_ipv6.status_code == 404, "non-pseudo CF address cannot inject a second IPv6 identity")
        malformed = client.get("/app/", base_url="https://app.5a-math.com", headers={"CF-Connecting-IP": "110.14.147.14, 198.51.100.8"})
        _check(state, malformed.status_code == 404, "multi-hop CF address fails closed")
        _check(state, client.get("/app/", base_url="https://app.5a-math.com.evil", headers=edge).status_code == 404, "host suffix confusion is denied")
        _check(state, client.get("/app/", base_url="https://app.5a-math.com:443", headers=edge).status_code == 404, "host port confusion is denied")
        _check(state, client.get("/app/", base_url="https://127.0.0.1").status_code == 200, "non-public app route remains local")
        _check(state, client.get("/student/sid-a", base_url="https://127.0.0.1").status_code == 200, "non-public student route remains local")
        external_local = client.get(
            "/api/student/bootstrap?sid=sid-a",
            base_url="https://127.0.0.1",
            environ_overrides={"REMOTE_ADDR": "198.51.100.9"},
        )
        _check(state, external_local.status_code == 404, "external peer cannot select the loopback-host legacy branch")
        external_private = client.get(
            "/api/student/bootstrap?sid=sid-a",
            base_url="https://192.168.0.10",
            environ_overrides={"REMOTE_ADDR": "198.51.100.9"},
        )
        _check(state, external_private.status_code == 404, "external peer cannot select a private-host legacy branch")
        academy_local = client.get(
            "/",
            base_url="https://192.168.0.10",
            environ_overrides={"REMOTE_ADDR": "192.168.0.20"},
        )
        _check(state, academy_local.status_code == 200, "academy-local peer retains the private-host legacy branch")

        forced = app.test_client()
        forced.set_cookie(config.session_cookie_name, "credentials-token", domain="app.5a-math.com", path="/")
        protected = (
            ("GET", "/api/student/bootstrap?sid=sid-a", {}),
            ("GET", "/api/announcements?sid=sid-a", {}),
            ("GET", "/api/get-url?sid=sid-a", {}),
            ("GET", "/api/mobile/push/status", {}),
            ("POST", "/api/mobile/auth/switch", {"json": {"sid": "sid-a"}}),
            ("GET", "/student/sid-a", {}),
            ("GET", "/js/test_answer_link_map.json", {}),
            ("GET", "/files/announcements/notice.png", {}),
        )
        before_forced_hits = (hits["legacy"], hits["file"])
        for method, path, kwargs in protected:
            response = forced.open(path, method=method, base_url="https://app.5a-math.com", headers=edge, **kwargs)
            payload = _json(response)
            _check(
                state,
                response.status_code == 403
                and payload.get("code") == "credentials_required"
                and payload.get("state") == "credentials_required",
                f"credentials-required session is centrally blocked before protected handler: {path}",
            )
        _check(state, (hits["legacy"], hits["file"]) == before_forced_hits, "credentials gate runs before bridge handlers")
        _check(state, forced.get("/api/mobile/auth/session", base_url="https://app.5a-math.com", headers=edge).status_code == 200, "credentials-required session may inspect auth state")
        for path in ("/api/mobile/auth/credentials", "/api/mobile/auth/logout"):
            response = forced.post(path, base_url="https://app.5a-math.com", headers=edge | origin)
            _check(state, response.status_code == 200, f"credentials-required session may call {path}")


def _approved_legacy_redirect_checks(state: CheckState) -> None:
    from core.student_app_config import load_student_app_config
    from core.student_public_surface import SessionIdentity, install_student_public_surface
    from routes.pages import bp_pages

    config = load_student_app_config(
        {
            "STUDENT_APP_PUBLIC_ENABLED": "1",
            "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
            "STUDENT_APP_LEGACY_HOST": "5a-math.com",
            "STUDENT_APP_LEGACY_REDIRECT_ENABLED": "1",
            "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1/32",
        }
    )
    app = Flask("surface-legacy-redirect", static_folder=str(ROOT / "static"), static_url_path="")
    install_student_public_surface(
        app,
        config=config,
        session_resolver=lambda _token: SessionIdentity("sid-a", ("sid-a",)),
    )
    app.register_blueprint(bp_pages)
    app.config.update(TESTING=True)
    client = app.test_client()
    edge = {"CF-Connecting-IP": "110.14.147.14"}
    for method in ("GET", "HEAD"):
        response = client.open("/", method=method, base_url="https://5a-math.com", headers=edge)
        _check(
            state,
            response.status_code == 302
            and response.headers.get("Location") == "https://app.5a-math.com/app"
            and response.headers.get("Cache-Control") == "no-store",
            f"approved legacy {method} redirects to the absolute canonical app URL",
        )
    query = client.get("/?next=https://evil.example", base_url="https://5a-math.com", headers=edge)
    _check(state, query.status_code == 200 and query.headers.get("Location") is None, "legacy redirect never forwards or consumes a query string")
    _check(state, client.get("/student/sid-a", base_url="https://5a-math.com", headers=edge).status_code == 200, "approved root redirect does not rewrite legacy deep links")
    _check(state, client.get("/app", base_url="https://5a-math.com", headers=edge).status_code == 404, "approved redirect does not expose app assets on the legacy origin")


def _disabled_surface_checks(state: CheckState) -> None:
    from core.student_app_config import load_student_app_config
    from core.student_public_surface import SessionIdentity, install_student_public_surface
    from routes.pages import bp_pages

    with tempfile.TemporaryDirectory(prefix="student-surface-disabled-"):
        config = load_student_app_config(
            {
                "STUDENT_APP_PUBLIC_ENABLED": "0",
                "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
                "STUDENT_APP_LEGACY_REDIRECT_ENABLED": "1",
                "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1/32",
            }
        )
        app = Flask("surface-disabled", static_folder=str(ROOT / "static"), static_url_path="")
        install_student_public_surface(
            app,
            config=config,
            session_resolver=lambda _token: SessionIdentity("sid-a", ("sid-a",)),
        )
        app.register_blueprint(bp_pages)
        app.config.update(TESTING=True)
        client = app.test_client()
        edge = {"CF-Connecting-IP": "110.14.147.14"}
        _check(state, client.get("/app/", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "default-off public host is denied")
        _check(state, client.get("/", base_url="https://5a-math.com", headers=edge).status_code == 200, "legacy root cannot redirect while the app is disabled")
        _check(state, client.get("/", base_url="https://127.0.0.1").status_code == 200, "default-off local root remains available")
        _check(state, client.get("/student-app.html", base_url="https://127.0.0.1").status_code == 200, "local raw shell remains direct static")


def _actual_bridge_checks(state: CheckState) -> None:
    from unittest.mock import patch

    from core.student_public_surface import SessionIdentity, StudentPublicSurface
    from scripts.student_mobile_app_checks import academy_gates, student_data

    app_was_loaded = "app" in sys.modules
    with tempfile.TemporaryDirectory(prefix="student-surface-bridges-") as raw, patch.dict(
        os.environ,
        {"DATA_MIRROR_DIR": str(Path(raw) / "mirror"), "DATA_MIRROR_SNAPSHOTS": "0"},
    ):
        student_root = Path(raw) / "student-data"
        with student_data._isolated_routes(student_root) as (api_basic, announcements, watch, fs, paths):
            logs = student_data._fixtures(paths)
            app, config, _active = student_data._build_app(api_basic, announcements, watch, fs, logs)
            client = app.test_client()
            client.set_cookie(config.session_cookie_name, "session-token", domain="app.5a-math.com", path="/")
            edge = {"CF-Connecting-IP": "203.0.113.10"}
            ready_responses = (
                client.get(f"/api/student/bootstrap?date={student_data.DATE}", base_url="https://app.5a-math.com", headers=edge),
                client.get("/api/announcements", base_url="https://app.5a-math.com", headers=edge),
                client.get("/files/announcements/visible-a.png", base_url="https://app.5a-math.com", headers=edge),
            )
            _check(state, all(response.status_code == 200 for response in ready_responses), "real bootstrap/announcement/file handlers remain reachable for a ready session")
            for response in ready_responses:
                response.close()

            adapter = app.extensions.get("student_public_surface")
            if not isinstance(adapter, StudentPublicSurface):
                raise AssertionError("student-data app omitted the public surface adapter")
            adapter.session_resolver = lambda token: SessionIdentity("sid-a", ("sid-a",), True) if token == "session-token" else None
            before = {
                path: path.read_bytes()
                for path in (paths.STU_PATH, paths.ANNS_PATH, paths.ANN_STATUS_PATH)
            }
            for path in (
                f"/api/student/bootstrap?date={student_data.DATE}",
                "/api/announcements",
                "/files/announcements/visible-a.png",
            ):
                response = client.get(path, base_url="https://app.5a-math.com", headers=edge)
                payload = _json(response)
                _check(
                    state,
                    response.status_code == 403
                    and payload.get("code") == "credentials_required"
                    and payload.get("state") == "credentials_required",
                    f"real protected bridge is blocked before its handler: {path}",
                )
                response.close()
            _check(state, all(path.read_bytes() == content for path, content in before.items()), "blocked real bridges leave temp stores unchanged")

        academy_root = Path(raw) / "academy-gates"
        with academy_gates._isolated_routes(academy_root) as modules:
            academy_gates._fixture(modules[-1])
            app, config = academy_gates._app(academy_root, modules)
            client = app.test_client()
            client.set_cookie(config.session_cookie_name, "session", domain="app.5a-math.com", path="/")
            academy = {"CF-Connecting-IP": "192.168.1.20"}
            ready = client.get(
                "/api/get-url?mid=mid-1234&sid=sid-a",
                base_url="https://app.5a-math.com",
                headers=academy,
            )
            _check(state, ready.status_code == 200, "real get-url handler remains reachable for an academy ready session")
            adapter = app.extensions.get("student_public_surface")
            if not isinstance(adapter, StudentPublicSurface):
                raise AssertionError("academy-gates app omitted the public surface adapter")
            adapter.session_resolver = lambda token: SessionIdentity("sid-a", ("sid-a",), True) if token == "session" else None
            blocked = client.get(
                "/api/get-url?mid=mid-1234&sid=sid-a",
                base_url="https://app.5a-math.com",
                headers=academy,
            )
            payload = _json(blocked)
            _check(
                state,
                blocked.status_code == 403
                and payload.get("code") == "credentials_required"
                and payload.get("state") == "credentials_required",
                "real get-url bridge is blocked before signed URL issuance",
            )
    _check(state, ("app" in sys.modules) == app_was_loaded, "actual bridge fixture did not import the live app module")


def run_checks() -> dict[str, CheckValue]:
    state: CheckState = [0]
    pure_loc = _pure_loc_checks(state)
    _injected_checks(state)
    from scripts.student_mobile_app_checks.surface_auth_ip import run_auth_throttle_ip_check

    run_auth_throttle_ip_check(state)
    _approved_legacy_redirect_checks(state)
    _disabled_surface_checks(state)
    _actual_bridge_checks(state)
    result: dict[str, CheckValue] = {
        "name": "surface",
        "assertions": int(state[0]),
        "passed": True,
        "pure_loc": pure_loc,
        "scenarios": [value for value in state[1:] if isinstance(value, str)],
        "mutant_guards": [
            "prefix: fake /api/app/v1/login handler remained unhit at 404",
            "method: fake POST /api/mobile/auth/session handler remained unhit at 404",
            "host: suffix/port host probes remained 404",
            "proxy: ProxyFix originals bound host, scheme, and peer trust before forwarded results",
            "legacy host: external peers could not select loopback/private host branches",
            "credentials: protected bootstrap/announcement/file/get-url/page/static/push bridges returned central JSON 403",
            "real bridges: temp-path production blueprints passed ready sessions and blocked credentials-required sessions",
            "csrf: missing/bad CSRF remained 403 before fake legacy handler",
            "sid: foreign student page remained 403",
            "raw target: normalized double slash and conflicting WSGI target values remained 404",
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
