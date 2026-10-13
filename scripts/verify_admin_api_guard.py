"""Temp-only Flask routing and persistence contracts for the admin API guard."""
from __future__ import annotations

import ast
import base64
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from flask import Blueprint, Flask, g, jsonify, make_response, request
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.admin_api_guard import install_admin_api_guard
from core.admin_basic_auth import (
    ADMIN_AUTH_CHALLENGE,
    ADMIN_PASSWORD_HASH_ENV,
    ADMIN_USERNAME_ENV,
    external_admin_api_auth_required,
    verify_admin_authorization,
)
from core.student_app_config import load_student_app_config
from core.student_public_surface import SessionIdentity, StudentPublicSurface, install_student_public_surface


_UNSET = object()
_USERNAME = "검증관리자"
_PASSWORD = "temporary-test-password"
_AUTH = "Basic " + base64.b64encode(f"{_USERNAME}:{_PASSWORD}".encode("utf-8")).decode("ascii")
_PUBLIC_ORIGIN = "https://students.example.test"
_MOBILE_PAIRS = (
    ("/api/mobile/auth/login", "POST"),
    ("/api/mobile/auth/session", "GET"),
    ("/api/mobile/auth/credentials", "POST"),
    ("/api/mobile/auth/switch", "POST"),
    ("/api/mobile/auth/logout", "POST"),
    ("/api/mobile/push/public-key", "GET"),
    ("/api/mobile/push/status", "GET"),
    ("/api/mobile/push/subscribe", "POST"),
    ("/api/mobile/push/unsubscribe", "POST"),
    ("/api/mobile/push/bypass", "POST"),
    ("/api/mobile/push/preferences", "GET"),
    ("/api/mobile/push/preferences", "POST"),
    ("/api/mobile/student/homework", "GET"),
    ("/api/mobile/student/board", "GET"),
    ("/api/mobile/focus/current", "GET"),
    ("/api/mobile/focus/start", "POST"),
    ("/api/mobile/focus/events", "POST"),
    ("/api/mobile/focus/end", "POST"),
)
_NATIVE_ROUTES = {
    "/api/auth/login": ("POST",),
    "/api/auth/me": ("GET",),
    "/api/auth/schedules": ("GET",),
    "/api/auth/switch": ("POST",),
    "/api/auth/change": ("POST",),
    "/api/student/bootstrap": ("GET",),
    "/api/get-url": ("GET",),
    "/api/watch": ("GET", "POST"),
    "/api/watch/latest": ("GET",),
    "/api/watch-status": ("POST",),
    "/api/feedback": ("POST",),
    "/api/announcements": ("GET", "POST"),
    "/api/announce-status": ("GET",),
    "/api/announce-ack": ("POST",),
    "/api/announce-submit": ("POST",),
    "/api/kollus/lms-callback": ("GET", "POST"),
    "/api/ping": ("GET",),
}


def _fingerprint(path: Path) -> tuple[bytes, int, int, str]:
    raw = path.read_bytes()
    stat = path.stat()
    return raw, stat.st_mtime_ns, stat.st_size, hashlib.sha256(raw).hexdigest()


def _declared_pairs(path: Path, prefix: str = "") -> set[tuple[str, str]]:
    """Bind the literal fixture routes to source without importing the app."""
    found: set[tuple[str, str]] = set()
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            verb = decorator.func.attr
            if verb not in {"get", "post", "put", "patch", "delete", "route"} or not decorator.args:
                continue
            target = decorator.args[0]
            if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
                continue
            methods = {verb.upper()}
            if verb == "route":
                methods = {"GET"}
                for keyword in decorator.keywords:
                    if keyword.arg == "methods":
                        methods = set(ast.literal_eval(keyword.value))
            found.update((prefix + target.value, method) for method in methods)
    return found


class AdminApiGuardContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="admin-api-guard-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture_count = 0
        environment = patch.dict(os.environ, {"ADMIN_API_GUARD": "enforce"})
        environment.start()
        self.addCleanup(environment.stop)

    def fixture(self, *, mode=_UNSET, external=False, surface=False, guarded=True, mobile=True, excluded_blueprints=()):
        self.fixture_count += 1
        root = self.root / str(self.fixture_count)
        static = root / "static"
        static.mkdir(parents=True)
        (static / "fixture.txt").write_text("synthetic static", encoding="utf-8")
        store = root / "students.json"
        store.write_bytes(b'[{"id":"sid-a","unknown":"keep"}]\n')
        app = Flask(f"admin-api-guard-{self.fixture_count}", static_folder=str(static), static_url_path="")
        app.config.update(TESTING=True, ACADEMY_ADMIN_AUTHORIZER=lambda value: value == _AUTH)
        if mode is not _UNSET:
            app.config["ADMIN_API_GUARD"] = mode
        hits: list[tuple[str, str]] = []
        config = load_student_app_config(
            {
                "STUDENT_APP_PUBLIC_ENABLED": "1" if surface else "0",
                "STUDENT_APP_PUBLIC_HOST": "students.example.test",
                "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1/32",
            }
        )
        resolver = lambda token: SessionIdentity("sid-a", ("sid-a", "sid-b")) if token == "fixture-session" else None
        if surface:
            adapter = install_student_public_surface(
                app,
                config=config,
                session_resolver=resolver,
                csrf_validator=lambda token, csrf: token == "fixture-session" and csrf == "fixture-csrf",
            )
        else:
            adapter = StudentPublicSurface(config, resolver)
            app.extensions["student_public_surface"] = adapter
        adapter.register_api(frozenset(_MOBILE_PAIRS))
        if surface:
            adapter.register_api(frozenset({("/api/announcements", "GET"), ("/api/watch", "GET"), ("/api/watch", "POST")}))

        @app.before_request
        def fixture_public_flag():
            if "FIXTURE_PUBLIC_FLAG" in app.config:
                g.student_app_public_request = app.config["FIXTURE_PUBLIC_FLAG"]

        if external:
            @app.before_request
            def original_external_guard():
                if not external_admin_api_auth_required(
                    request.path,
                    request,
                    method=request.method,
                    public_request=getattr(g, "student_app_public_request", False) is True,
                    student_scoped=bool(str(request.args.get("sid") or "").strip()),
                ):
                    return None
                verifier = app.config.get("ACADEMY_ADMIN_AUTHORIZER")
                if not callable(verifier):
                    verifier = verify_admin_authorization
                if verifier(request.headers.get("Authorization")):
                    return None
                response = make_response(jsonify({"ok": False, "code": "admin_auth_required"}), 401)
                response.headers.update({"WWW-Authenticate": ADMIN_AUTH_CHALLENGE, "Cache-Control": "no-store"})
                return response

        if guarded:
            install_admin_api_guard(app, excluded_blueprints=excluded_blueprints)

        def add_probe(path: str, methods: tuple[str, ...]) -> None:
            def probe(**_kwargs):
                hits.append((request.path, request.method))
                if path in {"/api/auth/me", "/api/auth/schedules", "/api/auth/switch", "/api/auth/change"}:
                    if request.headers.get("Authorization") != "Bearer fixture-student":
                        return jsonify({"ok": False, "code": "native_token_required"}), 401
                if path == "/api/student/bootstrap" and not request.args.get("sid"):
                    return jsonify({"ok": False, "code": "native_sid_required"}), 400
                if path == "/api/get-url" and not request.args.get("mid"):
                    return jsonify({"ok": False, "code": "native_mid_required"}), 400
                if path == "/api/kollus/lms-callback" and request.values.get("fixtureSecret") != "allowed":
                    return jsonify({"ok": False, "code": "native_callback_secret_required"}), 403
                if path == "/api/watch" and request.method == "GET" and getattr(g, "student_app_public_request", False) is True:
                    return jsonify({"ok": False, "code": "native_not_found"}), 404
                if path.startswith("/api/mobile/") and path not in {"/api/mobile/auth/login", "/api/mobile/push/public-key"}:
                    if request.cookies.get(config.session_cookie_name) != "fixture-session":
                        return jsonify({"ok": False, "code": "native_session_required"}), 401
                if request.method not in {"GET", "HEAD"} or (
                    request.method == "HEAD" and path in {"/api/watch", "/api/announcements", "/api/kollus/lms-callback"}
                ):
                    store.write_bytes(b'[{"id":"sid-a","changed":true}]\n')
                return jsonify({"ok": True, "path": request.path})
            app.add_url_rule(path, endpoint=f"probe_{len(list(app.url_map.iter_rules()))}", view_func=probe, methods=list(methods))

        for path, methods in _NATIVE_ROUTES.items():
            add_probe(path, methods)
        for path in ("/api/students", "/api/videos", "/api/progress", "/api/logs", "/api/tests-config", "/api/private"):
            add_probe(path, ("GET", "POST", "PUT", "PATCH", "DELETE"))
        add_probe("/api/students/<sid>", ("DELETE",))
        add_probe("/api/only-get", ("GET",))
        add_probe("/api/admin/folder/", ("GET",))
        if mobile:
            for path in sorted({path for path, _method in _MOBILE_PAIRS} | {"/api/mobile/private"}):
                add_probe(path, ("GET", "POST"))
        return app, store, hits, adapter

    def denied(self, app, store, path, *, method="GET", **kwargs):
        before = _fingerprint(store)
        response = app.test_client().open(path, method=method, **kwargs)
        self.assertEqual(response.status_code, 401, (method, path, response.get_data(as_text=True)))
        if method != "HEAD":
            self.assertEqual(response.get_json(), {"ok": False, "code": "admin_auth_required"})
        self.assertEqual(response.headers.get("WWW-Authenticate"), ADMIN_AUTH_CHALLENGE)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(_fingerprint(store), before, (method, path, "denial changed bytes or mtime"))
        return response

    def test_default_enforce_and_unauthorized_writes_do_not_touch_storage(self):
        app, store, hits, _ = self.fixture()
        for method in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                self.denied(app, store, "/api/students", method=method, json=[] if method == "POST" else None)
        self.denied(app, store, "/api/students/sid-a", method="DELETE")
        self.assertEqual(hits, [])

    def test_unguarded_negative_control_and_authenticated_writes(self):
        for guarded, headers in ((False, {}), (True, {"Authorization": _AUTH})):
            app, store, hits, _ = self.fixture(guarded=guarded)
            before = _fingerprint(store)
            response = app.test_client().post("/api/students", json=[], headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertNotEqual(_fingerprint(store), before)
            self.assertEqual(hits, [("/api/students", "POST")])

    def test_roster_reads_do_not_gain_student_scope_from_sid_or_claimed_flags(self):
        app, store, _, _ = self.fixture()
        for path in ("/api/students", "/api/videos", "/api/progress", "/api/logs", "/api/tests-config", "/api/watch"):
            self.denied(app, store, path, query_string={"sid": "sid-a"})
        self.denied(app, store, "/api/students", method="POST", json={"student_app_public_request": True})
        self.denied(app, store, "/api/students", headers={"X-Student-App-Public-Request": "true"})
        for flag in (1, "true", [True]):
            app.config["FIXTURE_PUBLIC_FLAG"] = flag
            self.denied(app, store, "/api/students")
        app.config["FIXTURE_PUBLIC_FLAG"] = True
        self.assertEqual(app.test_client().get("/api/students").status_code, 200)

    def test_student_auth_methods_reach_their_native_token_gate(self):
        app, store, hits, _ = self.fixture()
        client = app.test_client()
        for path, methods in (("/api/auth/me", ("GET", "HEAD")), ("/api/auth/schedules", ("GET", "HEAD")), ("/api/auth/switch", ("POST",)), ("/api/auth/change", ("POST",))):
            for method in methods:
                response = client.open(path, method=method)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn("WWW-Authenticate", response.headers)
                if method != "HEAD":
                    self.assertEqual(response.get_json()["code"], "native_token_required")
                self.assertEqual(client.open(path, method=method, headers={"Authorization": "Bearer fixture-student"}).status_code, 200)
        self.assertEqual(client.post("/api/auth/login").status_code, 200)
        self.assertTrue(hits)
        self.denied(app, store, "/api/auth/me", method="OPTIONS")

    def test_native_student_validation_and_callback_secret_remain_in_charge(self):
        app, _, _, _ = self.fixture()
        client = app.test_client()
        for path, code in (("/api/student/bootstrap", "native_sid_required"), ("/api/get-url", "native_mid_required")):
            response = client.get(path)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["code"], code)
        self.assertEqual(client.get("/api/student/bootstrap?sid=sid-a").status_code, 200)
        self.assertEqual(client.get("/api/get-url?mid=fixture-mid").status_code, 200)
        for path in ("/api/watch", "/api/watch-status", "/api/feedback", "/api/announce-ack", "/api/announce-submit"):
            self.assertEqual(client.post(path, json={"sid": "sid-a"}).status_code, 200)
        for method in ("GET", "POST"):
            response = client.open("/api/kollus/lms-callback", method=method)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json()["code"], "native_callback_secret_required")
            self.assertEqual(client.open("/api/kollus/lms-callback?fixtureSecret=allowed", method=method, environ_overrides={"REMOTE_ADDR": "203.0.113.8"}).status_code, 200)
        self.assertEqual(client.get("/api/ping").status_code, 200)

    def test_student_query_reads_require_one_strict_sid(self):
        app, store, _, _ = self.fixture()
        invalid = ([], [("sid", "")], [("sid", "sid-a,sid-b")], [("sid", "sid-a"), ("sid", "sid-a")], [("sid", " sid-a")], [("sid", "sid-a/")], [("sid", "sid%2Fa")], [("sid", "sid\\a")], [("sid", "sid\x00a")])
        for path in ("/api/announcements", "/api/announce-status", "/api/watch/latest"):
            for query in invalid:
                with self.subTest(path=path, query=query):
                    self.denied(app, store, path, query_string=query)
            self.assertEqual(app.test_client().get(path, query_string={"sid": "학생123"}).status_code, 200)
        for path in ("/api/announce-status", "/api/watch/latest"):
            self.assertEqual(app.test_client().head(path, query_string={"sid": "sid-a"}).status_code, 200)
        self.denied(app, store, "/api/announcements?sid=sid-a", method="POST", json={"sid": "sid-a"})
        self.denied(app, store, "/api/announcements?sid=sid-a", method="HEAD")
        self.denied(app, store, "/api/watch?sid=sid-a", method="HEAD")
        self.denied(app, store, "/api/kollus/lms-callback?fixtureSecret=allowed", method="HEAD")

    def test_mobile_exceptions_require_actual_adapter_exact_registration_and_handler(self):
        app, store, _, adapter = self.fixture()
        client = app.test_client()
        client.set_cookie(adapter.config.session_cookie_name, "fixture-session")
        for path, method in _MOBILE_PAIRS:
            with self.subTest(path=path, method=method):
                self.assertEqual(client.open(path, method=method).status_code, 200)
        self.denied(app, store, "/api/mobile/private", method="POST")
        self.denied(app, store, "/api/mobile/auth/session", method="POST")
        self.denied(app, store, "/api/mobile/auth/login", method="GET")
        self.denied(app, store, "/api/mobile/auth/session", method="HEAD")
        adapter.registered_api.discard(("/api/mobile/auth/login", "POST"))
        self.denied(app, store, "/api/mobile/auth/login", method="POST")
        app.extensions["student_public_surface"] = {"registered_api": set(_MOBILE_PAIRS)}
        self.denied(app, store, "/api/mobile/auth/session")
        missing, _, _, _ = self.fixture(mobile=False)
        self.assertEqual(missing.test_client().get("/api/mobile/auth/session").status_code, 404)

    def test_public_surface_runs_first_and_retains_session_sid_origin_csrf_checks(self):
        app, store, hits, adapter = self.fixture(surface=True, external=True)
        client = app.test_client()
        edge = {"CF-Connecting-IP": "203.0.113.8"}
        before = _fingerprint(store)
        response = client.get("/api/mobile/auth/session", base_url=_PUBLIC_ORIGIN, headers=edge)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "unauthenticated")
        client.set_cookie(adapter.config.session_cookie_name, "fixture-session", domain="students.example.test")
        for path, method, extra, code in (
            ("/api/mobile/auth/switch", "POST", {}, "origin_required"),
            ("/api/mobile/auth/switch", "POST", {"Origin": _PUBLIC_ORIGIN}, "csrf_required"),
            ("/api/mobile/auth/switch", "POST", {"Origin": _PUBLIC_ORIGIN, "X-CSRF-Token": "wrong"}, "csrf_invalid"),
            ("/api/announcements?sid=sid-b", "GET", {}, "sid_mismatch"),
            ("/api/announcements?sid=sid-a&sid=sid-b", "GET", {}, "sid_mismatch"),
        ):
            response = client.open(path, method=method, base_url=_PUBLIC_ORIGIN, headers=edge | extra)
            self.assertEqual(response.status_code, 403, (path, response.get_data(as_text=True)))
            self.assertEqual(response.get_json()["code"], code)
        for path, method in (("/api/students", "GET"), ("/api/mobile/private", "POST"), ("/api/mobile/auth/session", "POST"), ("/api/mobile/auth/session", "HEAD")):
            self.assertEqual(client.open(path, method=method, base_url=_PUBLIC_ORIGIN, headers=edge | {"Authorization": _AUTH}).status_code, 404)
        self.assertEqual(_fingerprint(store), before)
        self.assertEqual(hits, [])
        self.assertEqual(client.get("/api/announcements", base_url=_PUBLIC_ORIGIN, headers=edge).status_code, 200)
        self.assertEqual(client.get("/api/announcements?sid=sid-a&sid=sid-a", base_url=_PUBLIC_ORIGIN, headers=edge).status_code, 200)
        self.assertEqual(client.get("/api/watch", base_url=_PUBLIC_ORIGIN, headers=edge).status_code, 404)
        response = client.post("/api/mobile/auth/switch", base_url=_PUBLIC_ORIGIN, headers=edge | {"Origin": _PUBLIC_ORIGIN, "X-CSRF-Token": "fixture-csrf"}, json={"targetSid": "sid-b"})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(_fingerprint(store), before)

    def test_static_catchall_routing_errors_and_redirects_are_preserved(self):
        app, store, _, _ = self.fixture()
        before = _fingerprint(store)
        for path, method, status in (("/api/unknown", "GET", 404), ("/api/unknown", "POST", 405), ("/api/only-get", "POST", 405), ("/api/admin/folder", "GET", 308), ("/fixture.txt", "GET", 200), ("/missing.html", "GET", 404)):
            response = app.test_client().open(path, method=method)
            self.assertEqual(response.status_code, status, (path, method))
            self.assertNotIn("WWW-Authenticate", response.headers)
            response.close()
        self.assertEqual(_fingerprint(store), before)
        no_static = Flask("admin-api-no-static", static_folder=None)
        install_admin_api_guard(no_static)
        self.assertEqual(no_static.test_client().get("/api/unknown").status_code, 404)

    def test_dynamic_api_rule_cannot_impersonate_literal_student_exception(self):
        app = Flask("admin-api-dynamic", static_folder=None)
        app.config["ACADEMY_ADMIN_AUTHORIZER"] = lambda _value: False
        install_admin_api_guard(app)
        app.add_url_rule("/api/<path:name>", view_func=lambda name: jsonify({"name": name}), methods=["GET", "POST"])
        self.assertEqual(app.test_client().get("/api/auth/me").status_code, 401)
        self.assertEqual(app.test_client().post("/api/watch").status_code, 401)

    def test_log_observes_get_but_always_blocks_other_admin_methods(self):
        app, store, _, _ = self.fixture(mode="log")
        with self.assertLogs(app.logger, level="WARNING") as captured:
            self.assertEqual(app.test_client().get("/api/students").status_code, 200)
        self.assertIn("[ADMIN-API-GUARD] would-deny", captured.output[0])
        self.assertIn("route=/api/students", captured.output[0])
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            self.denied(app, store, "/api/students", method=method)
        self.denied(app, store, "/api/announcements?sid=sid-a", method="HEAD")

    def test_off_rolls_back_local_guard_without_weakening_external_guard(self):
        remote = {"REMOTE_ADDR": "203.0.113.8"}
        for mode in ("off", "log", "enforce"):
            app, store, hits, _ = self.fixture(mode=mode, external=True)
            self.denied(app, store, "/api/students", environ_overrides=remote)
            self.denied(app, store, "/api/students", method="POST", environ_overrides=remote)
            self.assertEqual(hits, [])
            self.assertEqual(app.test_client().post("/api/students", headers={"Authorization": _AUTH}, environ_overrides=remote).status_code, 200)
        app, store, _, _ = self.fixture(mode="off", external=True)
        before = _fingerprint(store)
        self.assertEqual(app.test_client().post("/api/students").status_code, 200)
        self.assertNotEqual(_fingerprint(store), before)

    def test_invalid_modes_fail_closed_and_config_overrides_environment(self):
        for mode in ("", "unexpected", None, True, 0):
            app, store, _, _ = self.fixture(mode=mode)
            self.denied(app, store, "/api/students")
        with patch.dict(os.environ, {"ADMIN_API_GUARD": "unexpected"}):
            app, store, _, _ = self.fixture()
            self.denied(app, store, "/api/students")
        with patch.dict(os.environ, {"ADMIN_API_GUARD": "off"}):
            app, store, _, _ = self.fixture(mode="enforce")
            self.denied(app, store, "/api/students")
        with patch.dict(os.environ, {"ADMIN_API_GUARD": "log"}):
            app, _, _, _ = self.fixture()
            with self.assertLogs(app.logger, level="WARNING"):
                self.assertEqual(app.test_client().get("/api/students").status_code, 200)
        with patch.dict(os.environ):
            os.environ.pop("ADMIN_API_GUARD", None)
            app, store, _, _ = self.fixture()
            self.denied(app, store, "/api/students")

    def test_local_and_academy_networks_still_require_basic_for_admin_apis(self):
        app, store, _, _ = self.fixture(external=True)
        for remote in ("127.0.0.1", "110.14.147.14"):
            self.denied(app, store, "/api/students", method="POST", environ_overrides={"REMOTE_ADDR": remote})

    def test_authorizer_override_and_missing_hash_configuration_fail_closed(self):
        app, store, _, _ = self.fixture(external=True)
        seen = []
        def override(value):
            seen.append(value)
            return value == "fixture-override"
        app.config["ACADEMY_ADMIN_AUTHORIZER"] = override
        self.assertEqual(app.test_client().post("/api/students", headers={"Authorization": "fixture-override"}, environ_overrides={"REMOTE_ADDR": "203.0.113.8"}).status_code, 200)
        self.assertEqual(seen, ["fixture-override", "fixture-override"])
        app.config["ACADEMY_ADMIN_AUTHORIZER"] = None
        with patch.dict(os.environ, {ADMIN_USERNAME_ENV: "", ADMIN_PASSWORD_HASH_ENV: ""}):
            self.denied(app, store, "/api/students", method="POST", headers={"Authorization": _AUTH})

    def test_valid_remote_basic_uses_existing_hash_verifier_without_network_rejection(self):
        values = {ADMIN_USERNAME_ENV: _USERNAME, ADMIN_PASSWORD_HASH_ENV: generate_password_hash(_PASSWORD, method="pbkdf2:sha256:1000")}
        app, store, _, _ = self.fixture(external=True)
        app.config["ACADEMY_ADMIN_AUTHORIZER"] = None
        with patch.dict(os.environ, values):
            self.denied(app, store, "/api/students", method="POST", headers={"Authorization": "Basic !!!"}, environ_overrides={"REMOTE_ADDR": "203.0.113.8"})
            self.assertEqual(app.test_client().post("/api/students", headers={"Authorization": _AUTH}, environ_overrides={"REMOTE_ADDR": "203.0.113.8"}).status_code, 200)

    def test_repeated_install_is_idempotent(self):
        app, _, _, _ = self.fixture(mode="log")
        install_admin_api_guard(app)
        with self.assertLogs(app.logger, level="WARNING") as captured:
            self.assertEqual(app.test_client().get("/api/students").status_code, 200)
        self.assertEqual(len(captured.output), 1)

    def test_frozen_blueprint_exclusions_preserve_local_native_and_external_guards(self):
        excluded = {"owned_student_feature", "owned_other_feature"}
        app, store, _, _ = self.fixture(external=True, excluded_blueprints=excluded)
        excluded.clear()
        excluded.add("unrelated_feature")
        for name in ("owned_student_feature", "owned_other_feature", "unrelated_feature"):
            blueprint = Blueprint(name, __name__)
            def probe(name=name):
                if request.headers.get("X-Fixture-Native-Session") != "allowed":
                    return jsonify({"ok": False, "code": "native_feature_session_required"}), 403
                if request.method == "POST":
                    store.write_bytes(f'{{"fixtureFeature":"{name}"}}\n'.encode("utf-8"))
                return jsonify({"ok": True})
            blueprint.add_url_rule(f"/api/owned/{name}", view_func=probe, methods=["GET", "POST"])
            app.register_blueprint(blueprint)
        client = app.test_client()
        for name in ("owned_student_feature", "owned_other_feature"):
            path = f"/api/owned/{name}"
            before = _fingerprint(store)
            rejected = client.post(path)
            self.assertEqual(rejected.status_code, 403)
            self.assertEqual(rejected.get_json()["code"], "native_feature_session_required")
            self.assertNotIn("WWW-Authenticate", rejected.headers)
            self.assertEqual(_fingerprint(store), before)
            self.assertEqual(client.post(path, headers={"X-Fixture-Native-Session": "allowed"}).status_code, 200)
            self.assertNotEqual(_fingerprint(store), before)
            self.denied(app, store, path, method="POST", headers={"X-Fixture-Native-Session": "allowed"}, environ_overrides={"REMOTE_ADDR": "203.0.113.8"})
            self.assertEqual(client.post(path, headers={"X-Fixture-Native-Session": "allowed", "Authorization": _AUTH}, environ_overrides={"REMOTE_ADDR": "203.0.113.8"}).status_code, 200)
        self.denied(app, store, "/api/owned/unrelated_feature", method="POST", headers={"X-Fixture-Native-Session": "allowed"})
        self.denied(app, store, "/api/students", method="POST")

    def test_native_fixture_routes_are_declared_by_the_current_source(self):
        declared: set[tuple[str, str]] = set()
        for filename, prefix in (("api_auth.py", "/api/auth"), ("api_student_bootstrap.py", ""), ("api_watch.py", ""), ("api_announcements.py", ""), ("api_kollus.py", ""), ("api_basic.py", "")):
            declared.update(_declared_pairs(ROOT / "routes" / filename, prefix))
        for path, methods in _NATIVE_ROUTES.items():
            for method in methods:
                self.assertIn((path, method), declared)


if __name__ == "__main__":
    unittest.main(verbosity=2)
