"""Temp-only Flask contracts for the Phase 2 homework boundaries."""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, g

from core.student_app_config import load_student_app_config
from core.student_homework_repository import StudentHomeworkRepository
from core.student_homework_service import KST, prepare_batch
from routes.api_student_homework import StudentHomeworkApiDependencies, create_blueprints


MIGRATION = ROOT / "scripts" / "migrations" / "20260809_create_student_homework.sql"
NOW = dt.datetime(2026, 8, 9, 12, 0, tzinfo=KST)


def _config():
    return load_student_app_config({
        "STUDENT_APP_PUBLIC_ENABLED": "1",
        "STUDENT_APP_HOMEWORK_ENABLED": "1",
        "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
        "STUDENT_APP_SESSION_SECURE": "0",
    })


class _LogPatch:
    def __init__(self):
        self.mode = "success"
        self.calls = []

    def __call__(self, date_key, sid, entry, base):
        self.calls.append((date_key, sid, entry, base))
        if self.mode == "error":
            raise OSError("injected")
        if self.mode == "conflict":
            return SimpleNamespace(
                sqlite_ok=False,
                json_ok=False,
                sqlite_base_conflict=False,
                json_conflict_entry={"homeworkTable": [{"foreign": True}]},
            )
        return SimpleNamespace(
            sqlite_ok=True,
            json_ok=True,
            sqlite_base_conflict=False,
            json_conflict_entry=None,
            merged=entry,
        )


class _DurableThenConflict:
    def __init__(self):
        self.entry = None

    def __call__(self, _date_key, _sid, entry, _base):
        if self.entry is None:
            self.entry = entry
            return SimpleNamespace(
                sqlite_ok=False,
                json_ok=False,
                sqlite_base_conflict=False,
                json_conflict_entry=None,
            )
        return SimpleNamespace(
            sqlite_ok=False,
            json_ok=False,
            sqlite_base_conflict=True,
            sqlite_conflict_entry=self.entry,
            json_conflict_entry=self.entry,
        )


class _SqliteThenJsonRecovery:
    def __init__(self):
        self.entry = None

    def __call__(self, _date_key, _sid, entry, _base):
        if self.entry is None:
            self.entry = entry
            return SimpleNamespace(
                sqlite_ok=True,
                json_ok=False,
                sqlite_base_conflict=False,
                sqlite_conflict_entry=None,
                json_conflict_entry=None,
            )
        return SimpleNamespace(
            sqlite_ok=False,
            json_ok=True,
            sqlite_base_conflict=True,
            sqlite_conflict_entry=self.entry,
            json_conflict_entry=None,
        )


class _JsonThenSqliteRecovery:
    def __init__(self):
        self.entry = None

    def __call__(self, _date_key, _sid, entry, _base):
        if self.entry is None:
            self.entry = entry
            return SimpleNamespace(
                sqlite_ok=False,
                json_ok=True,
                sqlite_base_conflict=False,
                sqlite_conflict_entry=None,
                json_conflict_entry=None,
            )
        return SimpleNamespace(
            sqlite_ok=True,
            json_ok=False,
            sqlite_base_conflict=False,
            sqlite_conflict_entry=None,
            json_conflict_entry=self.entry,
        )


class _FailingHomework:
    def __init__(self, repository):
        self.repository = repository
        self.fail = True

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def apply_batch(self, *args, **kwargs):
        if self.fail:
            raise OSError("injected")
        return self.repository.apply_batch(*args, **kwargs)


def _deps(database: Path, logs_path: Path, patcher, repository=None):
    repo = repository or StudentHomeworkRepository(database)
    return StudentHomeworkApiDependencies(_config(), repo, logs_path, patcher, lambda: NOW)


def _migrate(repository):
    repository.apply_migration(MIGRATION.read_text(encoding="utf-8"))


def _public_app(dependencies):
    app = Flask("homework-public")
    public, _admin = create_blueprints(dependencies, admin_authorizer=lambda _value: True)
    app.register_blueprint(public)

    @app.before_request
    def bind_session():
        g.student_app_public_request = True
        g.student_app_active_sid = "sid-a"

    return app


def _admin_app(dependencies, *, authorization="ok"):
    app = Flask("homework-admin")
    _public, admin = create_blueprints(
        dependencies,
        admin_authorizer=lambda value: value == authorization,
    )
    app.register_blueprint(admin)
    return app


def _commit_body(operation_id="operation-0001", title="숙제 A"):
    row = {"book": "교재", "this": "10쪽", "teacherMeta": {"keep": True}}
    return {
        "operationId": operation_id,
        "date": "2026-08-09",
        "sid": "sid-a",
        "logPatch": {
            "entry": {"homeworkTable": [row], "notes": "유지"},
            "base": {"homeworkTable": []},
            "clearKeys": [],
            "baseHomeworkTableExact": [],
        },
        "homeworkRows": [{
            "rowIndex": 0,
            "assignmentId": None,
            "expectedRevision": None,
            "sourceRowId": "row_opaque_00000001",
            "title": title,
            "book": "교재",
            "scope": "10쪽",
            "dueAt": "2026-08-10T18:00:00+09:00",
            "status": "assigned",
        }],
        "removedAssignmentIds": [],
    }


def run_checks() -> dict:
    assertions = 0

    def check(condition, message):
        nonlocal assertions
        if not condition:
            raise AssertionError(message)
        assertions += 1

    with tempfile.TemporaryDirectory(prefix="student-homework-routes-") as raw:
        temp = Path(raw)
        database, logs_path = temp / "app.sqlite", temp / "logs.json"
        logs_path.write_text(json.dumps({"2026-08-09": {"sid-a": {"homeworkTable": []}}}), encoding="utf-8")
        patcher = _LogPatch()
        repo = StudentHomeworkRepository(database)
        _migrate(repo)
        seed_a = prepare_batch([{
            "sourceRowId": "seed-a", "rowIndex": 0, "title": "OWN-MARKER", "book": "A",
            "scope": "", "dueAt": None, "status": "assigned",
        }], sid="sid-a", source_log_date="2026-08-08", now=NOW)
        seed_b = prepare_batch([{
            "sourceRowId": "seed-b", "rowIndex": 0, "title": "FOREIGN-MARKER", "book": "B",
            "scope": "", "dueAt": None, "status": "assigned",
        }], sid="sid-b", source_log_date="2026-08-08", now=NOW)
        repo.apply_batch("sid-a", "2026-08-08", seed_a, now="2026-08-09T12:00:00+09:00")
        repo.apply_batch("sid-b", "2026-08-08", seed_b, now="2026-08-09T12:00:00+09:00")

        public_app = _public_app(_deps(database, logs_path, patcher, repo))
        with public_app.test_client() as client:
            response = client.get("/api/mobile/student/homework?status=open")
            payload = response.get_json()
            check(response.status_code == 200, "public homework list failed")
            check(response.headers.get("Cache-Control") == "no-store", "public response is cacheable")
            check(any(item["title"] == "OWN-MARKER" for item in payload["items"]), "own homework missing")
            check("FOREIGN-MARKER" not in response.get_data(as_text=True), "foreign SID leaked")
            check(all("sid" not in item and "revision" not in item for item in payload["items"]), "authority leaked")
            check(client.get("/api/mobile/student/homework?sid=sid-b").status_code == 400,
                  "route accepted a query SID")

        missing = temp / "missing.sqlite"
        unavailable_app = _public_app(_deps(missing, logs_path, patcher))
        with unavailable_app.test_client() as client:
            check(client.get("/api/mobile/student/homework").status_code == 503,
                  "uninitialized schema was not typed")
            check(not missing.exists(), "read path created an uninitialized database")

        completed_db, completed_logs = temp / "completed.sqlite", temp / "completed-logs.json"
        completed_repo = StudentHomeworkRepository(completed_db)
        _migrate(completed_repo)
        completed_id = "hw_abcdefghijklmnop"
        completed_rows = prepare_batch([{
            "assignmentId": completed_id,
            "sourceRowId": completed_id,
            "rowIndex": 0,
            "title": "완료된 숙제",
            "book": "교재",
            "scope": "",
            "dueAt": "2026-08-09T11:00:00+09:00",
            "status": "completed",
            "completedAt": "2026-08-09T11:30:00+09:00",
        }], sid="sid-a", source_log_date="2026-08-09", now=NOW)
        completed_repo.apply_batch("sid-a", "2026-08-09", completed_rows, now="2026-08-09T12:00:00+09:00")
        completed_logs.write_text(json.dumps({
            "2026-08-09": {"sid-a": {"homeworkTable": [{
                "assignmentId": completed_id, "book": "교재", "next": "완료된 숙제",
            }]}}
        }), encoding="utf-8")
        completed_app = _public_app(_deps(completed_db, completed_logs, _LogPatch(), completed_repo))
        with completed_app.test_client() as client:
            response = client.get("/api/mobile/student/homework?status=open")
            check(completed_id not in response.get_data(as_text=True),
                  "completed canonical homework was resurrected by legacy fallback")

        admin_app = _admin_app(_deps(database, logs_path, patcher, repo))
        with admin_app.test_client() as client:
            check(client.get("/api/admin/student-homework?sid=sid-a&date=2026-08-09").status_code == 401,
                  "missing admin authorization did not challenge")
            denied = client.get(
                "/api/admin/student-homework?sid=sid-a&date=2026-08-09",
                headers={"Authorization": "ok"},
                environ_overrides={"REMOTE_ADDR": "198.51.100.9"},
            )
            check(denied.status_code == 403, "external admin request was accepted")
            hidden = client.get(
                "/api/admin/student-homework?sid=sid-a&date=2026-08-09",
                base_url="https://app.5a-math.com",
                headers={"Authorization": "ok"},
            )
            check(hidden.status_code == 404, "public host exposed the admin route")
            invalid_date = client.get(
                "/api/admin/student-homework?sid=sid-a&date=not-a-date",
                headers={"Authorization": "ok"},
            )
            check(invalid_date.status_code == 400 and invalid_date.get_json()["code"] == "invalid_payload",
                  "malformed admin list date was not rejected as invalid payload")
            invalid_commit = _commit_body("operation-invalid-date")
            invalid_commit["date"] = "2026-02-30"
            invalid_response = client.post(
                "/api/admin/student-homework/commit",
                json=invalid_commit,
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(invalid_response.status_code == 400
                  and invalid_response.get_json()["code"] == "invalid_payload",
                  "malformed commit date was not rejected as invalid payload")
            check(client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body(),
                headers={"Authorization": "ok"},
            ).status_code == 403, "admin write accepted a missing Origin")
            response = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body(),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            payload = response.get_json()
            check(response.status_code == 200 and payload["state"] == "committed", "composite commit failed")
            check(payload["entry"]["homeworkTable"][0]["teacherMeta"] == {"keep": True},
                  "unknown log row metadata was lost")
            check(payload["entry"]["homeworkTable"][0]["assignmentId"].startswith("hw_"),
                  "opaque assignment link was not attached")
            committed_assignment_id = payload["entry"]["homeworkTable"][0]["assignmentId"]
            check(patcher.calls[-1][3]["__homeworkTableExact"] == [], "exact base was not forwarded")
            retry = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body(),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(retry.status_code == 200, "identical operation retry was not idempotent")
            check(len(repo.list_for_log_date("sid-a", "2026-08-09")) == 1, "retry duplicated assignment")
            mutated = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body(title="다른 숙제"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(mutated.status_code == 409 and mutated.get_json()["code"] == "idempotency_conflict",
                  "operation ID reuse was accepted")
            cancel = _commit_body("operation-cancel")
            cancel["logPatch"]["entry"]["homeworkTable"] = []
            cancel["logPatch"]["base"]["homeworkTable"] = payload["entry"]["homeworkTable"]
            cancel["logPatch"]["baseHomeworkTableExact"] = payload["entry"]["homeworkTable"]
            cancel["homeworkRows"] = []
            cancel["removedAssignmentIds"] = [committed_assignment_id]
            cancelled = client.post(
                "/api/admin/student-homework/commit",
                json=cancel,
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(cancelled.status_code == 200, "cancelled assignment did not reconcile")
            after_cancel = _commit_body("operation-after-cancel", title="새 숙제")
            after_cancel["homeworkRows"][0]["sourceRowId"] = "row_opaque_00000002"
            resumed = client.post(
                "/api/admin/student-homework/commit",
                json=after_cancel,
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(resumed.status_code == 200, "historical cancelled row blocked a later save")

        second_db = temp / "partial.sqlite"
        second_repo = StudentHomeworkRepository(second_db)
        _migrate(second_repo)
        failing_repo = _FailingHomework(second_repo)
        patch_success = _LogPatch()
        partial_app = _admin_app(_deps(second_db, logs_path, patch_success, failing_repo))
        with partial_app.test_client() as client:
            first = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-partial"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(first.status_code == 409 and first.get_json()["code"] == "partial_failure",
                  "homework failure was hidden")
            failing_repo.fail = False
            fixed = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-partial"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(fixed.status_code == 200, "partial reconciliation did not recover")
            check(len(second_repo.list_for_log_date("sid-a", "2026-08-09")) == 1,
                  "partial retry duplicated assignment")

        third_db = temp / "log-partial.sqlite"
        third_repo = StudentHomeworkRepository(third_db)
        _migrate(third_repo)
        patch_failure = _LogPatch()
        patch_failure.mode = "error"
        log_partial_app = _admin_app(_deps(third_db, logs_path, patch_failure, third_repo))
        with log_partial_app.test_client() as client:
            first = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-log-partial"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(first.status_code == 409 and first.get_json()["homework"]["ok"] is True,
                  "log failure did not preserve canonical success")
            patch_failure.mode = "success"
            fixed = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-log-partial"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(fixed.status_code == 200, "log-side partial reconciliation did not recover")

        conflict_db = temp / "conflict.sqlite"
        conflict_repo = StudentHomeworkRepository(conflict_db)
        _migrate(conflict_repo)
        conflict_patch = _LogPatch()
        conflict_patch.mode = "conflict"
        conflict_app = _admin_app(_deps(conflict_db, logs_path, conflict_patch, conflict_repo))
        with conflict_app.test_client() as client:
            response = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-conflict"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(response.status_code == 409 and response.get_json()["retryable"] is False,
                  "semantic log conflict was not terminal")
            check(conflict_repo.list_for_log_date("sid-a", "2026-08-09") == [],
                  "semantic log conflict mutated canonical homework")

        response_loss_db = temp / "response-loss.sqlite"
        response_loss_repo = StudentHomeworkRepository(response_loss_db)
        _migrate(response_loss_repo)
        durable_patch = _DurableThenConflict()
        response_loss_app = _admin_app(_deps(
            response_loss_db, logs_path, durable_patch, response_loss_repo
        ))
        with response_loss_app.test_client() as client:
            first = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-response-loss"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(first.status_code == 409 and first.get_json()["retryable"] is True,
                  "durable response loss was not retryable")
            retried = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-response-loss"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(retried.status_code == 200, "already-applied log retry became a terminal conflict")
            check(len(response_loss_repo.list_for_log_date("sid-a", "2026-08-09")) == 1,
                  "response-loss retry duplicated canonical homework")

        split_store_db = temp / "split-store.sqlite"
        split_store_repo = StudentHomeworkRepository(split_store_db)
        _migrate(split_store_repo)
        split_store_patch = _SqliteThenJsonRecovery()
        split_store_app = _admin_app(_deps(
            split_store_db, logs_path, split_store_patch, split_store_repo
        ))
        with split_store_app.test_client() as client:
            first = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-split-store"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(first.status_code == 409 and first.get_json()["retryable"] is True,
                  "split-store partial was not retryable")
            retried = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-split-store"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(retried.status_code == 200, "split-store retry did not converge")
            check(len(split_store_repo.list_for_log_date("sid-a", "2026-08-09")) == 1,
                  "split-store retry duplicated canonical homework")

        reverse_store_db = temp / "reverse-store.sqlite"
        reverse_store_repo = StudentHomeworkRepository(reverse_store_db)
        _migrate(reverse_store_repo)
        reverse_store_patch = _JsonThenSqliteRecovery()
        reverse_store_app = _admin_app(_deps(
            reverse_store_db, logs_path, reverse_store_patch, reverse_store_repo
        ))
        with reverse_store_app.test_client() as client:
            first = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-reverse-store"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(first.status_code == 409 and first.get_json()["retryable"] is True,
                  "reverse split-store partial was not retryable")
            retried = client.post(
                "/api/admin/student-homework/commit",
                json=_commit_body("operation-reverse-store"),
                headers={"Authorization": "ok", "Origin": "http://localhost"},
            )
            check(retried.status_code == 200, "reverse split-store retry did not converge")
            check(len(reverse_store_repo.list_for_log_date("sid-a", "2026-08-09")) == 1,
                  "reverse split-store retry duplicated canonical homework")

    return {"name": "homework-routes", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False))
