"""Temp-only public student-data and announcement session-binding checks."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch

from flask import Blueprint, Flask, g, jsonify
from werkzeug.security import generate_password_hash

from core.student_account_repository import StudentAccountRepository
from core.student_activation_codes import StudentActivationCodeRepository
from core.student_app_auth_contract import StudentAuthDependencies
from core.student_app_config import load_student_app_config
from core.student_login_throttle import StudentLoginThrottleRepository
from core.student_public_surface import SessionIdentity, install_student_public_surface
from core.student_public_session_resolver import build_default_resolvers
from core.student_sessions import StudentSessionRepository


DATE = "2026-08-03"
MODULE_NAMES = (
    "routes.api_basic",
    "routes.api_announcements",
    "routes.api_watch",
    "routes.api_fs",
    "core.absent",
    "core.log_repository",
    "core.paths",
)


def _check(state: dict[str, int], condition: bool, label: str) -> None:
    state["assertions"] += 1
    if not condition:
        raise AssertionError(label)


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@contextmanager
def _isolated_routes(root: Path):
    previous = {name: sys.modules.get(name) for name in MODULE_NAMES}
    core_package = importlib.import_module("core")
    routes_package = importlib.import_module("routes")
    paths = types.ModuleType("core.paths")
    paths.BASE = root
    names = {
        "STU_PATH": "students.json", "VID_PATH": "videos.json", "PRG_PATH": "progress.json",
        "UPD_PATH": "updates.json", "ASN_PATH": "assigns.json", "MAT_PATH": "materials.json",
        "CAL_PATH": "calendar.json", "EXTRA_PATH": "extra.json", "LOGS_PATH": "logs.json",
        "CLINIC_PATH": "clinic.json", "TODAY_ORDER_PATH": "today_order.json",
        "WEEKEND_SLOTS_PATH": "weekend_slots.json", "WATCH_PATH": "watch.json",
        "TESTS_CFG_PATH": "tests-config.json", "ABS_PATH": "absent.json",
        "ANN_STATUS_PATH": "announcement_status.json", "ANNS_PATH": "announcements.json",
        "PAGE_FOLDERS_PATH": "page-folders.json",
    }
    for attr, filename in names.items():
        setattr(paths, attr, root / filename)
    paths.FILES_DIR = root / "files"
    for name in MODULE_NAMES:
        sys.modules.pop(name, None)
    sys.modules["core.paths"] = paths
    setattr(core_package, "paths", paths)
    try:
        yield (
            importlib.import_module("routes.api_basic"),
            importlib.import_module("routes.api_announcements"),
            importlib.import_module("routes.api_watch"),
            importlib.import_module("routes.api_fs"),
            paths,
        )
    finally:
        for name in MODULE_NAMES:
            sys.modules.pop(name, None)
        for name, module in previous.items():
            if module is not None:
                sys.modules[name] = module
        for package, attr, full_name in (
            (core_package, "paths", "core.paths"), (core_package, "absent", "core.absent"),
            (core_package, "log_repository", "core.log_repository"),
            (routes_package, "api_basic", "routes.api_basic"),
            (routes_package, "api_announcements", "routes.api_announcements"),
            (routes_package, "api_watch", "routes.api_watch"),
            (routes_package, "api_fs", "routes.api_fs"),
        ):
            old = previous.get(full_name)
            if old is None:
                package.__dict__.pop(attr, None)
            else:
                setattr(package, attr, old)


def _fixtures(paths) -> dict[str, dict]:
    students = [
        {"id": "sid-a", "name": "가학생", "curriculum": "수학A", "subCurriculum": "기본", "day1": "월1"},
        {"id": "sid-b", "name": "나학생", "curriculum": "수학B", "subCurriculum": "기본", "day1": "월2"},
    ]
    logs = {
        "sid-a": {"homeworkTable": [{"book": "A교재", "this": "1-5", "fileUrl": "/files/private-a.pdf"}],
                  "assignedTests": [{"label": "A시험", "curriculum": "수학A", "status": "assigned",
                                     "answerUrl": "https://secret.example/a", "nested": {"solutionUrl": "https://secret.example/nested"}}]},
        "sid-b": {"homeworkTable": [{"book": "B교재", "this": "6-9"}],
                  "assignedTests": [{"label": "B시험", "curriculum": "수학B", "status": "assigned"}]},
    }
    data = {
        paths.STU_PATH: students,
        paths.VID_PATH: [
            {"mid": "mid-a", "title": "A영상", "curriculum": "수학A", "subCurriculum": "기본", "url": "https://secret.example/video-a"},
            {"mid": "mid-b", "title": "B영상", "curriculum": "수학B", "subCurriculum": "기본", "url": "https://secret.example/video-b"},
        ],
        paths.PRG_PATH: {DATE: {"sid-a": {"tests": {"A시험": "assigned"}}, "sid-b": {"tests": {"B시험": "assigned"}}}},
        paths.UPD_PATH: {DATE: {"sid-a": ["mid-a"], "sid-b": ["mid-b"]}},
        paths.ASN_PATH: {"sid-a": {"materials": ["mat-a"]}, "sid-b": {"materials": ["mat-b"]}},
        paths.MAT_PATH: {
            "mat-a": {"id": "mat-a", "title": "A자료", "url": "/files/material-a.pdf", "nested": {"path": "/files/nested-a.pdf"}},
            "mat-b": {"id": "mat-b", "title": "B자료", "url": "/files/material-b.pdf"},
        },
        paths.ABS_PATH: {"by_date": {}, "by_student": {}},
        paths.WATCH_PATH: {
            "2026-07-01": {"sid-a": {"mid-a": {"last": 5, "dur": 100, "updatedAt": 10}}, "sid-b": {"mid-b": {"last": 7, "dur": 80, "updatedAt": 10}}},
            "2026-07-02": {"sid-a": {"mid-a": {"last": 55, "dur": 100, "updatedAt": 20}}},
        },
        paths.ANNS_PATH: [
            {"id": "ann-a", "title": "A공지", "content": "A", "targetSids": ["sid-a"],
             "createdAt": "2026-01-01T00:00:00Z", "expiresAt": "2099-01-01T00:00:00Z",
             "images": [{"path": "announcements/visible-a.png", "url": "/files/announcements/visible-a.png"}]},
            {"id": "ann-b", "title": "B공지", "content": "B", "targetSids": ["sid-b"],
             "createdAt": "2026-01-01T00:00:00Z", "expiresAt": "2099-01-01T00:00:00Z",
             "images": [{"path": "announcements/foreign-b.png", "url": "/files/announcements/foreign-b.png"}]},
            {"id": "survey-a", "title": "A설문", "content": "S", "targetSids": ["sid-a"],
             "createdAt": "2026-01-01T00:00:00Z", "expiresAt": "2099-01-01T00:00:00Z",
             "survey": {"status": "public", "questions": [{"id": "q1", "text": "선택", "type": "single", "options": [{"id": "yes", "text": "예"}, {"id": "no", "text": "아니오"}]}]}},
            {"id": "future-a", "title": "예약 공지", "content": "F", "targetSids": ["sid-a"],
             "createdAt": "2099-02-01T00:00:00Z", "expiresAt": "2099-03-01T00:00:00Z",
             "images": [{"path": "announcements/future-a.png", "url": "/files/announcements/future-a.png"}]},
            {"id": "draft-a", "title": "초안 설문", "content": "D", "targetSids": ["sid-a"],
             "createdAt": "2026-01-01T00:00:00Z", "expiresAt": "2099-01-01T00:00:00Z",
             "images": [{"path": "announcements/draft-a.png", "url": "/files/announcements/draft-a.png"}],
             "survey": {"status": "draft", "questions": [{"id": "q1", "text": "초안", "type": "short"}]}},
            {"id": "closed-a", "title": "마감 설문", "content": "C", "targetSids": ["sid-a"],
             "createdAt": "2026-01-01T00:00:00Z", "expiresAt": "2099-01-01T00:00:00Z",
             "images": [{"path": "announcements/closed-a.png", "url": "/files/announcements/closed-a.png"}],
             "survey": {"status": "closed", "questions": [{"id": "q1", "text": "마감", "type": "short"}]}},
            {"id": "expired-a", "title": "만료 공지", "content": "E", "targetSids": ["sid-a"],
             "createdAt": "2025-01-01T00:00:00Z", "expiresAt": "2025-01-02T00:00:00Z",
             "images": [{"path": "announcements/expired-a.png", "url": "/files/announcements/expired-a.png"}]},
        ],
        paths.ANN_STATUS_PATH: {
            "sid-a": {
                "ann-a": {"acked": False}, "future-a": {"acked": False},
                "draft-a": {"acked": False}, "closed-a": {"acked": False},
            },
            "sid-b": {"ann-b": {"acked": True}},
        },
    }
    for attr in names_for_empty(paths):
        data.setdefault(attr, {})
    for path, value in data.items():
        _write(path, value)
    for filename in (
        "visible-a.png", "foreign-b.png", "future-a.png", "draft-a.png",
        "closed-a.png", "expired-a.png", "orphan.png",
    ):
        image = paths.FILES_DIR / "announcements" / filename
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(f"synthetic:{filename}".encode("ascii"))
    return logs


def names_for_empty(paths):
    return (paths.CAL_PATH, paths.EXTRA_PATH, paths.LOGS_PATH, paths.CLINIC_PATH,
            paths.TODAY_ORDER_PATH, paths.WEEKEND_SLOTS_PATH, paths.TESTS_CFG_PATH)


def _build_app(api_basic, announcements, watch, fs, logs):
    active = {"sid": "sid-a"}
    config = load_student_app_config({"STUDENT_APP_PUBLIC_ENABLED": "true", "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com"})
    config = replace(config, public_api_route_methods=config.public_api_route_methods | frozenset({("/api/context-probe", "GET"), ("/api/context-probe", "POST")}))
    app = Flask(__name__)
    install_student_public_surface(
        app, config=config,
        session_resolver=lambda token: SessionIdentity(active["sid"], ("sid-a", "sid-b")) if token == "session-token" else None,
        csrf_validator=lambda token, csrf: token == "session-token" and csrf == "csrf-token",
    )
    probe = Blueprint("student_data_probe", __name__)

    @probe.route("/api/context-probe", methods=["GET", "POST"])
    def context_probe():
        session = g.student_app_session
        return jsonify({"public": g.student_app_public_request, "activeSid": g.student_app_active_sid,
                        "allowedSids": list(g.student_app_allowed_sids), "csrfValidated": g.student_app_csrf_validated,
                        "sessionMatches": session.active_sid == g.student_app_active_sid and session.allowed_sids == g.student_app_allowed_sids,
                        "hasSecret": any(hasattr(g, key) for key in ("student_app_session_token", "student_app_csrf_token"))})

    class Logs:
        def read_entry(self, date, sid):
            return types.SimpleNamespace(entry=logs.get(sid, {}))

        def read_json_map(self):
            return {DATE: logs}

    api_basic.get_log_repository = lambda: Logs()
    app.register_blueprint(probe)
    app.register_blueprint(api_basic.bp_api_basic)
    app.register_blueprint(announcements.bp_api_announcements)
    app.register_blueprint(watch.bp_api_watch)
    app.register_blueprint(fs.bp_api_fs)
    app.config.update(TESTING=True)
    return app, config, active


def _default_resolver_contract(state: dict[str, int], root: Path) -> None:
    accounts_path, students_path, db_path = root / "resolver-accounts.json", root / "resolver-students.json", root / "resolver.sqlite"
    _write(students_path, [{"id": "sid-a", "name": "가학생"}, {"id": "sid-b", "name": "나학생"}])
    _write(accounts_path, {"resolver-id": {"sids": ["sid-a"], "pw_hash": generate_password_hash("safe-password"), "disabled": False}})
    config = load_student_app_config({"STUDENT_APP_PUBLIC_ENABLED": "true", "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com"})
    deps = StudentAuthDependencies(config, StudentAccountRepository(accounts_path, students_path), StudentSessionRepository(db_path), StudentActivationCodeRepository(db_path), StudentLoginThrottleRepository(db_path), students_path)
    resolve, _csrf = build_default_resolvers(config, SessionIdentity, lambda _config: deps)
    created = deps.sessions.create("resolver-id", "sid-a", ["sid-a"])
    _check(state, resolve(created["token"]) == SessionIdentity("sid-a", ("sid-a",)), "default resolver rejected a current active account/session")
    deps.accounts.admin_set_disabled("resolver-id", True)
    _check(state, resolve(created["token"]) is None and deps.sessions.resolve(created["token"]) is None, "disabled account did not revoke public session authority")
    deps.accounts.admin_set_disabled("resolver-id", False)
    stale = deps.sessions.create("resolver-id", "sid-a", ["sid-a"])
    _write(accounts_path, {"resolver-id": {"sids": ["sid-b"], "pw_hash": generate_password_hash("safe-password"), "disabled": False}})
    _check(state, resolve(stale["token"]) is None and deps.sessions.resolve(stale["token"]) is None, "removed account SID retained public session authority")


def run_checks() -> dict[str, object]:
    state = {"assertions": 0}
    app_was_loaded = "app" in sys.modules
    with tempfile.TemporaryDirectory(prefix="student-data-check-") as raw, patch.dict(
        os.environ,
        {"DATA_MIRROR_DIR": str(Path(raw) / "mirror"), "DATA_MIRROR_SNAPSHOTS": "0"},
    ):
        with _isolated_routes(Path(raw)) as (api_basic, announcements, watch, fs, paths):
            logs = _fixtures(paths)
            app, config, active = _build_app(api_basic, announcements, watch, fs, logs)
            client = app.test_client()
            client.set_cookie(config.session_cookie_name, "session-token", domain="app.5a-math.com", path="/")
            edge = {"CF-Connecting-IP": "203.0.113.10"}
            write_headers = edge | {"Origin": "https://app.5a-math.com", "X-CSRF-Token": "csrf-token"}

            external = client.get(f"/api/student/bootstrap?date={DATE}", base_url="https://app.5a-math.com", headers=edge)
            body = external.get_json()
            dumped = json.dumps(body, ensure_ascii=False)
            _check(state, external.status_code == 200 and body["student"]["id"] == "sid-a" and "sid-b" not in dumped, "public bootstrap was not bound to active SID")
            _check(state, body["academyAccessAllowed"] is False and body["testSubmissionBlocked"] is True, "external policy flags mismatch")
            _check(state, body["assignedTests"] and body["homeworkBooks"] == ["A교재"] and body["materials"]["mat-a"]["title"] == "A자료", "public bootstrap lost progress/homework shape")
            _check(state, "secret.example" not in dumped and "/files/material-a.pdf" not in dumped and "/files/private-a.pdf" not in dumped, "external recursive link sanitizer leaked a restricted URL")
            _check(state, body["watch"] == {"ok": True, "sid": "sid-a", "date": "", "watch": {"mid-a": {"last": 55, "dur": 100, "completed": False, "updatedAt": 20}}}, "public watch projection differs from /api/watch/latest shape")
            _check(state, client.get("/api/watch", base_url="https://app.5a-math.com", headers=edge).status_code == 404, "public watch GET exposed the raw multi-SID store")

            inside = client.get(f"/api/student/bootstrap?sid=sid-a&date={DATE}", base_url="https://app.5a-math.com", headers={"CF-Connecting-IP": "192.168.1.20"}).get_json()
            _check(state, inside["academyAccessAllowed"] is True and inside["testSubmissionBlocked"] is False and inside["assignedTests"][0]["answerUrl"].startswith("https://secret.example"), "academy public response lost answer precedence")
            forged = client.get(f"/api/student/bootstrap?date={DATE}", base_url="https://app.5a-math.com", headers={"CF-Connecting-IP": "192.168.1.20"}, environ_overrides={"REMOTE_ADDR": "198.51.100.9"}).get_json()
            _check(state, forged["academyAccessAllowed"] is False and "secret.example" not in json.dumps(forged), "untrusted peer forged academy IP")

            active["sid"] = "sid-b"
            switched = client.get(f"/api/student/bootstrap?date={DATE}", base_url="https://app.5a-math.com", headers=edge).get_json()
            _check(state, switched["student"]["id"] == "sid-b" and switched["watch"]["sid"] == "sid-b" and "mid-a" not in switched["watch"]["watch"], "session switch retained prior SID data")
            _check(state, client.get(f"/api/student/bootstrap?sid=sid-a&date={DATE}", base_url="https://app.5a-math.com", headers=edge).status_code == 403, "mismatched bootstrap SID was accepted")
            active["sid"] = "sid-a"

            _check(state, client.get(f"/api/student/bootstrap?sid=sid-a&sid=sid-b&date={DATE}", base_url="https://app.5a-math.com", headers=edge).status_code == 403, "duplicate query SID bypassed binding")
            _check(state, client.get("/api/student/bootstrap", base_url="https://app.5a-math.com.evil", headers=edge).status_code == 404, "non-exact public host reached student data")
            anonymous = app.test_client().get(f"/api/student/bootstrap?date={DATE}", base_url="https://app.5a-math.com", headers=edge)
            _check(state, anonymous.status_code == 401, "missing public session reached bootstrap")

            get_context = client.get("/api/context-probe", base_url="https://app.5a-math.com", headers=edge).get_json()
            post_context = client.post("/api/context-probe", json={}, base_url="https://app.5a-math.com", headers=write_headers).get_json()
            _check(state, get_context == {"public": True, "activeSid": "sid-a", "allowedSids": ["sid-a", "sid-b"], "csrfValidated": False, "sessionMatches": True, "hasSecret": False}, "safe GET context mismatch")
            _check(state, post_context["csrfValidated"] is True and post_context["hasSecret"] is False, "safe POST CSRF context mismatch")
            _check(state, client.post("/api/context-probe", json={}, base_url="https://app.5a-math.com", headers=edge | {"Origin": "https://app.5a-math.com"}).status_code == 403, "missing CSRF reached handler")

            fail_closed = Flask("student_data_no_csrf_validator")
            install_student_public_surface(fail_closed, config=config, session_resolver=lambda _token: SessionIdentity("sid-a", ("sid-a",)))
            unsafe = Blueprint("student_data_unsafe", __name__)
            unsafe.post("/api/announce-ack")(lambda: jsonify({"reached": True}))
            fail_closed.register_blueprint(unsafe)
            no_validator_client = fail_closed.test_client()
            no_validator_client.set_cookie(config.session_cookie_name, "session-token", domain="app.5a-math.com", path="/")
            no_validator = no_validator_client.post("/api/announce-ack", json={}, base_url="https://app.5a-math.com", headers=write_headers)
            _check(state, no_validator.status_code == 403 and no_validator.get_json()["code"] == "csrf_invalid", "missing CSRF validator did not fail closed")

            visible = client.get("/api/announcements", base_url="https://app.5a-math.com", headers=edge).get_json()
            _check(state, {row["id"] for row in visible} == {"ann-a", "survey-a"}, "public announcement GET exposed another SID")
            own_status = client.get("/api/announce-status", base_url="https://app.5a-math.com", headers=edge).get_json()
            _check(state, set(own_status) == {"ann-a"}, "public announcement status exposed another SID")
            _check(state, client.get("/api/announcements?sid=sid-b", base_url="https://app.5a-math.com", headers=edge).status_code == 403, "announcement query SID bypassed session")
            _check(state, client.post("/api/announce-ack", json={"id": "ann-a"}, base_url="https://app.5a-math.com", headers=write_headers).status_code == 200, "public ack did not infer session SID")
            _check(state, client.post("/api/announce-submit", json={"id": "ann-a", "reply": "확인"}, base_url="https://app.5a-math.com", headers=write_headers).status_code == 200, "public reply did not infer session SID")
            _check(state, client.post("/api/announce-submit", json={"id": "survey-a", "surveyAnswers": {"q1": "yes"}}, base_url="https://app.5a-math.com", headers=write_headers).status_code == 200, "public survey did not infer session SID")
            for hidden_id in ("ann-b", "future-a", "draft-a", "closed-a", "expired-a"):
                before_hidden = paths.ANN_STATUS_PATH.read_bytes()
                hidden_ack = client.post("/api/announce-ack", json={"id": hidden_id}, base_url="https://app.5a-math.com", headers=write_headers)
                hidden_reply = client.post("/api/announce-submit", json={"id": hidden_id, "reply": "hidden"}, base_url="https://app.5a-math.com", headers=write_headers)
                hidden_survey = client.post("/api/announce-submit", json={"id": hidden_id, "surveyAnswers": {"q1": "hidden"}}, base_url="https://app.5a-math.com", headers=write_headers)
                _check(state, hidden_ack.status_code == 404 and hidden_reply.status_code == 404 and hidden_survey.status_code == 404, f"hidden announcement accepted a write: {hidden_id}")
                _check(state, paths.ANN_STATUS_PATH.read_bytes() == before_hidden, f"hidden announcement mutated status: {hidden_id}")

            visible_image = client.get("/files/announcements/visible-a.png", base_url="https://app.5a-math.com", headers=edge)
            _check(state, visible_image.status_code == 200 and visible_image.data == b"synthetic:visible-a.png", "visible announcement image was blocked")
            visible_image.close()
            for filename in ("foreign-b.png", "future-a.png", "draft-a.png", "closed-a.png", "expired-a.png", "orphan.png"):
                response = client.get(f"/files/announcements/{filename}", base_url="https://app.5a-math.com", headers=edge)
                _check(state, response.status_code == 404, f"non-visible announcement image was exposed: {filename}")
                response.close()
            before_status = paths.ANN_STATUS_PATH.read_bytes()
            mismatch = client.post("/api/announce-ack", json={"sid": "sid-b", "id": "ann-b"}, base_url="https://app.5a-math.com", headers=write_headers)
            _check(state, mismatch.status_code == 403 and paths.ANN_STATUS_PATH.read_bytes() == before_status, "body SID mismatch wrote announcement status")

            local = client.get(f"/api/student/bootstrap?sid=sid-a&date={DATE}", base_url="http://127.0.0.1", environ_overrides={"REMOTE_ADDR": "192.168.1.30"}).get_json()
            _check(state, "watch" not in local and "testSubmissionBlocked" not in local and local["assignedTests"][0]["answerUrl"], "local bootstrap shape/answer behavior changed")
            local_watch = client.get("/api/watch", base_url="http://127.0.0.1").get_json()
            _check(state, "sid-a" in local_watch["2026-07-01"] and "sid-b" in local_watch["2026-07-01"], "local raw watch GET changed")
            local_announcements = client.get("/api/announcements", base_url="http://127.0.0.1").get_json()
            _check(state, {row["id"] for row in local_announcements} == {"ann-a", "ann-b", "survey-a", "future-a", "draft-a", "closed-a"}, "local admin announcement list changed")
            local_orphan = client.get("/files/announcements/orphan.png", base_url="http://127.0.0.1")
            _check(state, local_orphan.status_code == 200 and local_orphan.data == b"synthetic:orphan.png", "local announcement file behavior changed")
            local_orphan.close()
            _check(state, client.post("/api/announce-ack", json={"id": "ann-a"}, base_url="http://127.0.0.1").status_code == 400, "local missing-SID behavior changed")

    _check(state, ("app" in sys.modules) == app_was_loaded, "focused check imported the live app module")
    with tempfile.TemporaryDirectory(prefix="student-data-resolver-") as resolver_raw:
        _default_resolver_contract(state, Path(resolver_raw))
    return {"name": "student-data", "assertions": state["assertions"], "passed": True,
            "runtimeIsolation": "temporary paths module and JSON fixtures only"}


__all__ = ["run_checks"]
