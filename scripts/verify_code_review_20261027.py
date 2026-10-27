"""Five isolated regressions; never import app or runtime core.paths."""
from __future__ import annotations

import ast
import concurrent.futures
import contextlib
import hashlib
import json
import pathlib
import re
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest
from functools import wraps
from unittest.mock import patch

from flask import Flask, abort, current_app, g, jsonify, make_response, request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.storage import file_lock, load, save_atomic


def source_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = [d for d in node.decorator_list if isinstance(d, ast.Name)]
    exec(compile(tree, path, "exec"), namespace)
    return namespace


class ReviewRegressions(unittest.TestCase):
    def test_005_canary_issuance_matches_session_resolver(self):
        from core.student_app_auth_service import StudentAuthService, StudentAuthFailure
        from core.student_public_session_resolver import build_default_resolvers
        from core.student_sessions import StudentSessionRepository
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            students = root / "students.json"
            students.write_text(json.dumps([{"id": "s1", "curriculum": "A"}, {"id": "s2", "curriculum": "B"}]), encoding="utf-8")
            sessions = StudentSessionRepository(root / "sessions.sqlite")
            accounts = types.SimpleNamespace(get=lambda aid: {"sids": ["s1", "s2"]})
            for canary in (frozenset({"other"}), frozenset({"s1"}), frozenset({"s1", "s2"})):
                config = types.SimpleNamespace(canary_sids=canary, allows_canary_sid=lambda sid, c=canary: sid in c)
                deps = types.SimpleNamespace(config=config, sessions=sessions, accounts=accounts, students_path=students)
                service = StudentAuthService(deps)
                resolver, _ = build_default_resolvers(config, lambda active, allowed, required: (active, allowed), lambda c: deps)
                if canary != frozenset({"s1", "s2"}):
                    with self.assertRaises(StudentAuthFailure) as failure:
                        service._new_session("account", ("s1", "s2"), False)
                    self.assertEqual(failure.exception.code, "unavailable")
                else:
                    exchange = service._new_session("account", ("s1", "s2"), False)
                    self.assertTrue(exchange.response["ok"])
                    self.assertEqual(resolver(exchange.token), ("s1", ("s1", "s2")))

    def test_004_deleted_tree_cleans_only_its_references(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            for directory in ("course/nested", "course2"):
                (root / directory).mkdir(parents=True)
                (root / directory / "handout.txt").write_text("fixture", encoding="utf-8")
            mats = {"gone": {"url": "/files/course/nested/handout.txt"},
                    "keep": {"url": "/files/course2/handout.txt"}}
            assigns = {"s1": ["gone", "/files/course/nested/handout.txt", "course/nested/handout.txt",
                              "DIR:course", "DIR:course/nested", "keep", "DIR:course2"]}
            saved = []
            ns = dict(pathlib=pathlib, os=os, shutil=shutil, FILES_ROOT=root, FILES_DIR=root,
                      request=request, jsonify=jsonify,
                      _load_mats_and_assigns=lambda: (mats, assigns),
                      _save_mats_and_assigns=lambda m, a: saved.append((m, a)))
            source_functions("routes/api_fs.py", {"_safe_join", "_reject_root_path", "_rel_from_abs", "_rel_from_url", "api_fs_delete"}, ns)
            app = Flask(__name__)
            app.add_url_rule("/api/fs/delete", view_func=ns["api_fs_delete"], methods=["POST"])
            with app.test_client() as client:
                response = client.post("/api/fs/delete", json={"paths": ["./course", "../unsafe"]})
                self.assertFalse(response.json["ok"])
                self.assertEqual(len(response.json["errors"]), 1)
                self.assertFalse((root / "course").exists())
                self.assertTrue((root / "course2/handout.txt").exists())
                self.assertEqual(mats, {"keep": {"url": "/files/course2/handout.txt"}})
                self.assertEqual(assigns["s1"], ["keep", "DIR:course2"])
                self.assertEqual(len(saved), 1)
                def fail_metadata(m, a):
                    raise OSError("metadata unavailable")
                ns["_save_mats_and_assigns"] = fail_metadata
                response = client.post("/api/fs/delete", json={"paths": ["course2"]})
                self.assertFalse(response.json["ok"])
                self.assertEqual(response.json["errors"][0]["phase"], "metadata")

    def test_003_roster_updates_preserve_other_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "students.json"
            save_atomic(path, [{"id": "s1", "first": "old", "second": "old"}])
            racing = False
            attempts = 0
            first_read = threading.Event()
            second_attempt = threading.Event()
            counter_lock = threading.Lock()
            @contextlib.contextmanager
            def observed_lock(target):
                nonlocal attempts
                if racing:
                    with counter_lock:
                        attempts += 1
                        if attempts == 2:
                            second_attempt.set()
                with file_lock(target):
                    yield
            def observed_load(target):
                value = load(target)
                if racing and not first_read.is_set():
                    first_read.set()
                    self.assertTrue(second_attempt.wait(timeout=5))
                return value
            ns = dict(wraps=wraps, file_lock=observed_lock, STU_PATH=path, load=observed_load,
                      save_atomic=save_atomic, request=request, jsonify=jsonify, abort=abort,
                      List=list, re=re, json=json, hashlib=hashlib,
                      _student_uses_able_curriculum=lambda s: False,
                      AUTO_VIDEO_ASSIGN_FIELD="autoVideoAssignCount",
                      student_schedule_changed_sids=lambda a, b: [],
                      enqueue_current_schedule_changes=lambda s: None)
            source_functions("routes/api_basic.py", {"_student_roster_locked", "_student_roster_revision", "api_students", "api_update_student_field"}, ns)
            app = Flask(__name__)
            app.add_url_rule("/api/update", view_func=ns["api_update_student_field"], methods=["POST"])
            app.add_url_rule("/api/students", view_func=ns["api_students"], methods=["GET", "POST"])
            with app.test_client() as client:
                revision = client.get("/api/students").headers["X-Students-Revision"]
            racing = True
            barrier = threading.Barrier(2)
            def update(field):
                with app.test_client() as client:
                    barrier.wait(timeout=5)
                    return client.post("/api/update", json={"id": "s1", "field": field, "value": "new"}).status_code
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                self.assertEqual(list(pool.map(update, ("first", "second"))), [200, 200])
            racing = False
            self.assertEqual(load(path), [{"id": "s1", "first": "new", "second": "new"}])
            with app.test_client() as client:
                self.assertEqual(client.post("/api/students", json=[], headers={"X-Students-Revision": revision}).status_code, 409)
                self.assertEqual(client.post("/api/students", json=[]).status_code, 409)
                revision = client.get("/api/students").headers["X-Students-Revision"]
                self.assertEqual(client.post("/api/students", json=load(path), headers={"X-Students-Revision": revision}).status_code, 204)

    def test_002_concurrent_log_winner_is_authoritative(self):
        # Load the real repository without importing runtime path initialization.
        module = types.ModuleType("review_log_repository")
        module.LOGS_PATH = pathlib.Path("unused.json")
        tree = ast.parse((ROOT / "core/log_repository.py").read_text(encoding="utf-8-sig"))
        tree.body = [n for n in tree.body if not isinstance(n, ast.ImportFrom) or n.module != "core.paths"]
        with patch.dict(sys.modules, {module.__name__: module}):
            exec(compile(tree, "core/log_repository.py", "exec"), module.__dict__)
        from core.log_rules import merge_log_entry_safe, log_entry_conflicts_with_base
        with tempfile.TemporaryDirectory() as temp:
            logs = pathlib.Path(temp) / "logs.json"
            repo = module.LogRepository(logs_path=logs, db_path=str(pathlib.Path(temp) / "app.sqlite"),
                                        merge_entry=merge_log_entry_safe, entry_conflicts=log_entry_conflicts_with_base)
            date, sid = "2026-10-27", "s1"
            repo.patch_entry(date, sid, {"notes": "base"}, {})
            barrier = threading.Barrier(2)
            def save(note):
                barrier.wait(timeout=5)
                return repo.patch_entry(date, sid, {"notes": note}, {"notes": "base"})
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results = list(pool.map(save, ("A", "B")))
            winners = [r for r in results if r.sqlite_ok]
            self.assertEqual(len(winners), 1)
            self.assertTrue(next(r for r in results if not r.sqlite_ok).sqlite_base_conflict)
            self.assertIsNone(next(r for r in results if not r.sqlite_ok).json_conflict_entry)
            self.assertEqual(load(logs)[date][sid]["notes"], winners[0].merged["notes"])
            self.assertEqual(repo.read_entry(date, sid).entry["notes"], winners[0].merged["notes"])

    def test_001_admin_api_boundary(self):
        from core.admin_basic_auth import ADMIN_AUTH_CHALLENGE
        ns = dict(Response=object, request=request, current_app=current_app, g=g,
                  abort=abort, make_response=make_response,
                  ADMIN_AUTH_CHALLENGE=ADMIN_AUTH_CHALLENGE,
                  _ADMIN_PAGE_PATHS=set(), _is_admin_static_alias=lambda: False,
                  admin_network_allowed=lambda req: req.remote_addr == "127.0.0.1",
                  verify_admin_authorization=lambda value: value == "Basic admin")
        source_functions("routes/pages.py", {"_admin_route_key", "_admin_auth_required", "_gate_admin_pages"}, ns)
        app = Flask(__name__)
        @app.before_request
        def public_context():
            if request.path == "/api/student/bootstrap":
                g.student_app_public_request = True
        app.before_request(ns["_gate_admin_pages"])
        app.add_url_rule("/api/students", endpoint="roster", view_func=lambda: jsonify(["private"]), methods=["GET", "POST", "DELETE"])
        app.add_url_rule("/api/student/bootstrap", endpoint="self", view_func=lambda: jsonify({"sid": "self"}))
        with app.test_client() as client:
            for host in ("legacy.example", "localhost", "public.example"):
                for method in ("GET", "POST", "DELETE"):
                    for headers in ({}, {"Cookie": "student=session"}):
                        self.assertEqual(client.open("/api/students", method=method, base_url=f"http://{host}", headers=headers).status_code, 401)
                self.assertEqual(client.get("/api/students", base_url=f"http://{host}", headers={"Authorization": "Basic admin"}).status_code, 200)
            self.assertEqual(client.get("/api/students", environ_overrides={"REMOTE_ADDR": "203.0.113.1"}, headers={"Authorization": "Basic admin"}).status_code, 403)
            self.assertEqual(client.get("/api/student/bootstrap").json, {"sid": "self"})


if __name__ == "__main__":
    unittest.main()
