"""Temp-only academy/public boundary checks for sensitive student actions."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import replace
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
from urllib.parse import parse_qs, urlparse

from flask import Flask, g, request

from core.progress_rules import PROGRESS_MANUAL_META_KEY
from core.student_app_config import load_student_app_config
from core.student_public_surface import SessionIdentity, install_student_public_surface


MODULES = (
    "routes.api_basic", "routes.api_watch", "routes.api_kollus", "routes.api_tests",
    "routes.api_announcements", "routes.api_fs", "routes.pages", "core.paths",
)
DATE = "2026-08-08"


def _check(state: list[int], condition: bool, label: str) -> None:
    state[0] += 1
    if not condition:
        raise AssertionError(label)


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@contextmanager
def _isolated_routes(root: Path):
    previous = {name: sys.modules.get(name) for name in MODULES}
    core_package, routes_package = importlib.import_module("core"), importlib.import_module("routes")
    paths = types.ModuleType("core.paths")
    paths.BASE = root
    for attr, filename in {
        "STU_PATH": "students.json", "VID_PATH": "videos.json", "WATCH_PATH": "watch.json",
        "PRG_PATH": "progress.json", "LOGS_PATH": "logs.json", "TESTS_PATH": "tests.json",
        "TESTS_CFG_PATH": "tests-config.json", "MAT_PATH": "materials.json",
        "ASN_PATH": "assigns.json", "PAGE_FOLDERS_PATH": "page-folders.json",
        "ANNS_PATH": "announcements.json", "ANN_STATUS_PATH": "announcement_status.json",
    }.items():
        setattr(paths, attr, root / filename)
    paths.FILES_DIR = root / "files"
    for name in MODULES:
        sys.modules.pop(name, None)
    sys.modules["core.paths"] = paths
    setattr(core_package, "paths", paths)
    try:
        watch = importlib.import_module("routes.api_watch")
        kollus = importlib.import_module("routes.api_kollus")
        tests = importlib.import_module("routes.api_tests")
        importlib.import_module("routes.api_announcements")
        fs = importlib.import_module("routes.api_fs")
        pages = importlib.import_module("routes.pages")
        basic = types.ModuleType("routes.api_basic")

        basic._progress_lock = nullcontext
        basic._load_progress_strict = lambda path=paths.PRG_PATH: json.loads(Path(path).read_text("utf-8"))
        basic._save_progress_strict = lambda data, path=paths.PRG_PATH: _write(Path(path), data)
        basic._notification_progress_snapshot = lambda _progress, _sid: None
        basic._notification_progress_commit = lambda _before, _after, _sid: 0
        sys.modules["routes.api_basic"] = basic
        setattr(routes_package, "api_basic", basic)
        yield watch, kollus, tests, fs, pages, paths
    finally:
        for name in MODULES:
            sys.modules.pop(name, None)
        for name, module in previous.items():
            if module is not None:
                sys.modules[name] = module
        for package, attr, name in (
            (core_package, "paths", "core.paths"), (routes_package, "api_basic", "routes.api_basic"),
            (routes_package, "api_watch", "routes.api_watch"), (routes_package, "api_kollus", "routes.api_kollus"),
            (routes_package, "api_tests", "routes.api_tests"), (routes_package, "api_fs", "routes.api_fs"),
            (routes_package, "api_announcements", "routes.api_announcements"),
            (routes_package, "pages", "routes.pages"),
        ):
            old = previous.get(name)
            if old is None:
                package.__dict__.pop(attr, None)
            else:
                setattr(package, attr, old)


def _fixture(paths) -> dict:
    config = {
        "version": 1,
        "aux": [{"answerUrl": "https://secret.example/top", "label": "keep"}],
        "categories": {"UNIT": {"label": "단원", "tests": [{
            "id": "t1", "name": "안전 시험", "problems": 1,
            "answerKeys": {"1": ["1"]},
            "sourceFiles": {"problemFileId": "visible-problem", "solutionFileId": "secret-file"},
            "nested": [{"solutionUrl": "https://secret.example/solution", "title": "keep"},
                       {"deeper": {"answers": ["1"], "visible": True}},
                       {"solutionFile": "synthetic-secret-solution-file"},
                       {"answerPath": "synthetic-secret-answer-path"},
                       {"solutionHref": "synthetic-secret-solution-href"},
                       {"Correct-File": "synthetic-secret-correct-file"},
                       {"expected_path": "synthetic-secret-expected-path"},
                       {"AcceptedHref": "synthetic-secret-accepted-href"},
                       {"canonical_file": "synthetic-secret-canonical-file"}],
        }]}}
    }
    values = {
        paths.STU_PATH: [{"id": "sid-a", "name": "가학생"}],
        paths.VID_PATH: [{"mid": "mid-1234", "title": "영상"}],
        paths.WATCH_PATH: {}, paths.TESTS_PATH: {}, paths.LOGS_PATH: {},
        paths.TESTS_CFG_PATH: config, paths.MAT_PATH: {}, paths.ASN_PATH: {}, paths.PAGE_FOLDERS_PATH: {},
        paths.ANNS_PATH: [{
            "id": "notice", "title": "공지", "content": "내용", "targetSids": ["sid-a"],
            "createdAt": "2026-01-01T00:00:00Z", "expiresAt": "2099-01-01T00:00:00Z",
            "images": [{"path": "announcements/notice.png", "url": "/files/announcements/notice.png"}],
        }],
        paths.ANN_STATUS_PATH: {},
        paths.PRG_PATH: {DATE: {"sid-a": {"mid-white": "none", "mid-skip": "skip",
            PROGRESS_MANUAL_META_KEY: {"mid-white": True, "mid-skip": True}}}},
    }
    for path, value in values.items():
        _write(path, value)
    announcement = paths.FILES_DIR / "announcements" / "notice.png"
    announcement.parent.mkdir(parents=True)
    announcement.write_bytes(b"announcement")
    private = paths.FILES_DIR / "answers" / "secret.pdf"
    private.parent.mkdir(parents=True)
    private.write_bytes(b"secret")
    static = paths.BASE / "static" / "js"
    static.mkdir(parents=True)
    (static / "test_answer_link_map.json").write_text('{"t1":"secret"}', encoding="utf-8")
    return config


def _app(root: Path, modules):
    watch, kollus, tests, fs, pages, _paths = modules
    config = load_student_app_config({
        "STUDENT_APP_PUBLIC_ENABLED": "1", "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
        "STUDENT_APP_TRUSTED_PROXIES": "127.0.0.1/32",
    })
    # Todo 10 owns the central exact sensitive-static classification.
    config = replace(config, public_sensitive_static_paths=frozenset({"/js/test_answer_link_map.json"}))
    app = Flask("academy-gates", static_folder=str(root / "static"), static_url_path="")
    install_student_public_surface(
        app, config=config,
        session_resolver=lambda token: SessionIdentity("sid-a", ("sid-a",)) if token == "session" else None,
        csrf_validator=lambda token, csrf: token == "session" and csrf == "csrf",
    )
    for blueprint in (pages.bp_pages, watch.bp_api_watch, kollus.bp_api_kollus, tests.bp_api_tests, fs.bp_api_fs):
        app.register_blueprint(blueprint)
    app.config.update(TESTING=True)
    return app, config


def _forbidden_keys(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = "".join(char for char in str(key).casefold() if char.isalnum())
            if normalized.startswith(("answer", "solution", "correct", "expected", "accepted", "canonical")):
                found.add(str(key))
            found.update(_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_keys(child))
    return found


def _handler_defense(state: list[int], modules) -> None:
    watch, kollus, tests, _fs, _pages, _paths = modules
    direct = Flask("academy-handler-defense")

    @direct.before_request
    def _public_context():
        g.student_app_public_request = True
        g.student_app_active_sid = "sid-a" if request.headers.get("X-No-Session") != "1" else None
        g.student_app_client_ip = request.headers.get("X-Resolved-IP", "203.0.113.20")

    for blueprint in (watch.bp_api_watch, kollus.bp_api_kollus, tests.bp_api_tests):
        direct.register_blueprint(blueprint)
    client = direct.test_client()
    academy = {"X-Resolved-IP": "192.168.1.20"}
    watch_body = {"date": DATE, "sid": "sid-b", "mid": "mid-1234", "status": "done"}
    _check(state, client.get("/api/get-url?mid=mid-1234&sid=sid-b", headers=academy).status_code == 403, "get-url handler accepted SID mismatch")
    _check(state, client.post("/api/watch-status", json=watch_body, headers=academy).status_code == 403, "watch handler accepted SID mismatch")
    _check(state, client.get("/api/get-url?mid=mid-1234&sid=sid-a").status_code == 403, "get-url handler accepted external network")
    _check(state, client.get("/api/tests-config", headers={"X-No-Session": "1"}).status_code == 401, "tests-config handler accepted missing session context")
    for route in ("/api/submit-test", "/api/ocr-test-sheet", "/api/ocr-test-sheet-review"):
        _check(state, client.post(route, json={"sid": "sid-a"}, headers=academy).status_code == 404, f"retired route is still registered: {route}")
    _check(state, client.post("/api/tests", json={"sid": "sid-a"}, headers=academy).status_code == 405, "test catalog still accepts writes")


def _kollus_url_contract(state: list[int], modules) -> None:
    _watch, kollus, _tests, _fs, _pages, _paths = modules
    source = Path(kollus.__file__).read_text(encoding="utf-8")
    secret = "academy-gates-kollus-callback-secret"
    fixed_now = 1_787_487_150
    original_callback_secret = kollus._callback_secret
    original_time = kollus.time.time
    kollus._callback_secret = lambda: secret
    kollus.time.time = lambda: fixed_now
    try:
        signed_url = kollus.kollus_signed_url("mid-1234", "192.168.1.20", "sid-a")
        parsed = urlparse(signed_url)
        token = (parse_qs(parsed.query).get("uservalue0") or [""])[0]
        decoded_sid, token_valid = kollus._decode_callback_token(token, "mid-1234", secret)
        _check(
            state,
            parsed.scheme == "https"
            and parsed.netloc == "v.kr.kollus.com"
            and parsed.path == "/mid-1234"
            and token.startswith("v1.")
            and token != "sid-a"
            and secret not in signed_url,
            "Kollus URL must carry an opaque signed student binding token",
        )
        _check(
            state,
            decoded_sid == "sid-a" and token_valid is True,
            "Kollus signed student binding token did not verify",
        )
        _wrong_mid_sid, wrong_mid_valid = kollus._decode_callback_token(token, "mid-other", secret)
        _check(
            state,
            wrong_mid_valid is False,
            "Kollus student binding signature is not scoped to the media MID",
        )
    finally:
        kollus._callback_secret = original_callback_secret
        kollus.time.time = original_time
    _check(
        state,
        "jwt.encode" not in source and "KOLLUS_POLICY_KEY" not in source and "KOLLUS_SERVICE_KEY" not in source,
        "Kollus URL builder retained unused hard-coded signing material",
    )


def _run_matrix(state: list[int], root: Path, modules) -> None:
    _watch, _kollus, tests, _fs, _pages, paths = modules
    original_config = _fixture(paths)
    app, config = _app(root, modules)
    client = app.test_client()
    client.set_cookie(config.session_cookie_name, "session", domain="app.5a-math.com", path="/")
    external = {"CF-Connecting-IP": "203.0.113.20"}
    academy = {"CF-Connecting-IP": "192.168.1.20"}
    write_external = external | {"Origin": "https://app.5a-math.com", "X-CSRF-Token": "csrf"}
    write_academy = academy | {"Origin": "https://app.5a-math.com", "X-CSRF-Token": "csrf"}

    _check(state, client.get("/api/get-url?mid=mid-1234&sid=sid-a", base_url="https://app.5a-math.com", headers=external).status_code == 403, "external signed video URL was not blocked")
    _check(state, client.get("/api/get-url?mid=mid-1234&sid=sid-a", base_url="https://app.5a-math.com", headers=academy).status_code == 200, "academy session could not obtain signed video URL")
    _check(state, client.get("/api/get-url?mid=mid-1234&sid=sid-b", base_url="https://app.5a-math.com", headers=academy).status_code == 403, "signed URL accepted caller SID mismatch")
    forged = client.get("/api/get-url?mid=mid-1234&sid=sid-a", base_url="https://app.5a-math.com", headers=academy, environ_overrides={"REMOTE_ADDR": "198.51.100.9"})
    _check(state, forged.status_code == 403, "untrusted peer forged academy CF address")

    before_tests = paths.TESTS_PATH.read_bytes()
    for route in ("/api/submit-test", "/api/ocr-test-sheet", "/api/ocr-test-sheet-review"):
        response = client.post(route, json={"sid": "sid-a"}, base_url="https://app.5a-math.com", headers=write_academy)
        _check(state, response.status_code == 404 and paths.TESTS_PATH.read_bytes() == before_tests, f"retired route is still exposed: {route}")
    _check(state, client.post("/api/tests", json={"sid": "sid-a"}, base_url="https://app.5a-math.com", headers=write_academy).status_code == 404 and paths.TESTS_PATH.read_bytes() == before_tests, "public test catalog write route is still exposed")

    watch_body = {"date": DATE, "sid": "sid-a", "mid": "mid-1234", "last": 20, "dur": 100}
    _check(state, client.post("/api/watch", json=watch_body, base_url="https://app.5a-math.com", headers=write_external).status_code == 403, "external watch write was not blocked")
    _check(state, client.post("/api/watch-status", json={"date": DATE, "sid": "sid-a", "mid": "mid-white", "status": "done"}, base_url="https://app.5a-math.com", headers=write_external).status_code == 403, "external watch status was not blocked")
    _check(state, client.post("/api/watch", json=watch_body, base_url="https://app.5a-math.com", headers=write_academy).status_code == 200, "academy watch write failed")
    for mid, expected in (("mid-white", "none"), ("mid-skip", "skip")):
        response = client.post("/api/watch-status", json={"date": DATE, "sid": "sid-a", "mid": mid, "status": "done"}, base_url="https://app.5a-math.com", headers=write_academy)
        _check(state, response.status_code == 200 and response.get_json()["progress"][mid] == expected, f"manual {expected} was overwritten by watch status")

    outside_catalog = client.get("/api/tests-config", base_url="https://app.5a-math.com", headers=external).get_json()
    outside_dump = json.dumps(outside_catalog, ensure_ascii=False)
    outside_test = outside_catalog["categories"]["UNIT"]["tests"][0]
    _check(state, not _forbidden_keys(outside_catalog) and "synthetic-secret-" not in outside_dump, "external catalog leaked recursive answer fields")
    _check(state, outside_test["nested"][0]["title"] == "keep" and outside_test["sourceFiles"]["problemFileId"] == "visible-problem", "external catalog sanitizer removed benign metadata")
    inside_catalog = client.get("/api/tests-config", base_url="https://app.5a-math.com", headers=academy).get_json()
    _check(state, inside_catalog == original_config, "academy catalog lost existing answer precedence")

    announcement = client.get("/files/announcements/notice.png", base_url="https://app.5a-math.com", headers=external)
    _check(state, announcement.status_code == 200, "authenticated announcement image was blocked")
    announcement.close()
    _check(state, client.get("/files/answers/secret.pdf", base_url="https://app.5a-math.com", headers=academy).status_code == 404, "public arbitrary answer file was exposed")
    _check(state, client.get("/files/announcements/%252e%252e/answers/secret.pdf", base_url="https://app.5a-math.com", headers=external).status_code == 404, "encoded file traversal was exposed")

    _handler_defense(state, modules)

    answer_external = client.get("/js/test_answer_link_map.json", base_url="https://app.5a-math.com", headers=external)
    answer_academy = client.get("/js/test_answer_link_map.json", base_url="https://app.5a-math.com", headers=academy)
    _check(state, answer_external.status_code == 404 and answer_academy.status_code == 200, "answer map network gate mismatch")
    answer_external.close()
    answer_academy.close()
    _check(state, app.test_client().get("/js/test_answer_link_map.json", base_url="https://app.5a-math.com", headers=academy).status_code == 401, "answer map accepted anonymous public request")

    local_file = client.get("/files/answers/secret.pdf", base_url="http://127.0.0.1")
    _check(state, local_file.status_code == 200, "local file route changed")
    local_file.close()
    _check(state, client.get("/api/tests-config", base_url="http://127.0.0.1", environ_overrides={"REMOTE_ADDR": "192.168.1.20"}).get_json() == original_config, "local academy catalog changed")
    registered_rules = {rule.rule for rule in app.url_map.iter_rules()}
    for route in ("/api/submit-test", "/api/ocr-test-sheet", "/api/ocr-test-sheet-review"):
        _check(state, route not in registered_rules, f"local retired route is still registered: {route}")
        response = client.post(route, json={"sid": "sid-a"}, base_url="http://127.0.0.1")
        _check(state, response.status_code in {404, 405}, f"local retired route is unexpectedly callable: {route}")
    _check(state, client.post("/api/tests", json={"sid": "sid-a"}, base_url="http://127.0.0.1").status_code == 405, "local test catalog still accepts writes")


def run_checks() -> dict[str, object]:
    state = [0]
    app_was_loaded = "app" in sys.modules
    with tempfile.TemporaryDirectory(prefix="academy-gates-") as raw:
        root = Path(raw)
        with _isolated_routes(root) as modules:
            _run_matrix(state, root, modules)
            _kollus_url_contract(state, modules)
    _check(state, ("app" in sys.modules) == app_was_loaded, "focused check imported the live app")
    return {"name": "academy-gates", "assertions": state[0], "passed": True,
            "runtimeIsolation": "temporary core.paths module and files only"}


__all__ = ["run_checks"]
