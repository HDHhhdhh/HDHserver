"""Temp HTTP/startup wiring; maintenance never needs a model or live app import."""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask
from core.student_test_ocr_maintenance import StudentTestOcrMaintenance
from core.student_test_ocr_repository import StudentTestOcrRepository
import routes.api_student_test_ocr as routes

ROOT = Path(__file__).resolve().parents[1]
KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime(2026, 10, 4, tzinfo=KST)


class WiringChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-maintenance-wiring-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "app.sqlite"
        self.assets = self.root / "assets"
        self.config = SimpleNamespace(
            enabled=False, maintenance_enabled=False, maintenance_interval_seconds=300.0,
            db_path=self.db, asset_root=self.assets,
        )
        self.addCleanup(routes.close_student_test_ocr_maintenance)
        self.addCleanup(patch.stopall)
        patch.object(routes, "load_student_test_ocr_config", lambda: self.config).start()
        patch.object(routes, "_now", lambda: NOW).start()
        patch.object(routes, "_build_runtime", side_effect=AssertionError("OCR model runtime forbidden")).start()

    def create_schema(self):
        repository = StudentTestOcrRepository(self.db)
        repository.apply_migration((ROOT / "scripts/migrations/20260828_create_student_test_ocr.sql").read_text(encoding="utf-8"))
        return repository

    def client(self, inspector=None):
        app = Flask(__name__)
        app.config["ACADEMY_ADMIN_AUTHORIZER"] = lambda value: value == "Basic test"
        if inspector is not None:
            app.config["STUDENT_TEST_OCR_MAINTENANCE"] = inspector
        app.register_blueprint(routes.bp_api_student_test_ocr)
        return app.test_client()

    def test_off_does_not_open_database_or_create_thread(self):
        with patch.object(routes, "StudentTestOcrRepository", side_effect=AssertionError("DB must not open")), \
                patch.object(routes, "StudentTestOcrMaintenance", side_effect=AssertionError("thread must not start")):
            self.assertFalse(routes.configure_student_test_ocr_maintenance())
        self.assertFalse(self.db.exists() or self.assets.exists())

    def test_enabled_missing_schema_never_creates_or_migrates(self):
        self.config.maintenance_enabled = True
        self.assertFalse(routes.configure_student_test_ocr_maintenance())
        self.assertFalse(self.db.exists() or self.assets.exists())

    def test_ocr_off_startup_is_model_independent_and_idempotent(self):
        self.create_schema()
        self.config.maintenance_enabled = True
        observed = threading.Event()
        # Observe actual periodic work through an external repository method.
        native_overdue = StudentTestOcrRepository.list_overdue_pending
        def overdue(repository, **kwargs):
            observed.set()
            return native_overdue(repository, **kwargs)
        with patch.object(StudentTestOcrRepository, "list_overdue_pending", overdue), \
                patch.object(StudentTestOcrMaintenance, "start", autospec=True,
                             side_effect=StudentTestOcrMaintenance.start) as start:
            self.assertTrue(routes.configure_student_test_ocr_maintenance())
            self.assertTrue(routes.configure_student_test_ocr_maintenance())
            self.assertTrue(observed.wait(3))
            self.assertEqual(start.call_count, 1)
        response = self.client().get("/api/student-test-ocr/admin/maintenance",
                                     headers={"Authorization": "Basic test"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["enabled"])
        self.assertNotIn("answer", json.dumps(response.json).lower())

    def test_admin_auth_precedes_all_database_reads(self):
        with patch.object(routes, "StudentTestOcrRepository", side_effect=AssertionError("unauthorized DB access")):
            response = self.client().get("/api/student-test-ocr/admin/maintenance")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.headers.get("WWW-Authenticate"))
        self.assertTrue(response.headers["Cache-Control"].startswith("no-store"))

    def test_reconfiguration_waits_for_old_tick_before_new_database_work(self):
        old_repo = self.create_schema()
        old_repo.begin_submission(
            submission_id="s", idempotency_key="s", request_hash="s", sid="student",
            test_id="unit", round_no="1", assignment_date="2026-10-03",
            answer_modes=["answer_value"] * 20, now=NOW.isoformat(),
        )
        self.assets.mkdir()
        (self.assets / "capture.jpg").write_bytes(b"expired fixture")
        old_repo.register_asset(asset_id="a", submission_id="s", question_no=1, kind="student_crop",
                                relative_path="capture.jpg", expires_at=NOW.isoformat(), created_at=NOW.isoformat())
        new_db = self.root / "new.sqlite"
        StudentTestOcrRepository(new_db).apply_migration(
            (ROOT / "scripts/migrations/20260828_create_student_test_ocr.sql").read_text(encoding="utf-8"))
        entered, release, new_work, configured = (threading.Event() for _ in range(4))
        from core import student_test_ocr_assets as assets_module
        native_unlink = assets_module._unlink_registered_asset
        native_query = StudentTestOcrRepository.expired_assets
        errors = []
        def unlink(root, relative):
            entered.set()
            if not release.wait(5):
                raise AssertionError("release timeout")
            native_unlink(root, relative)
        def query(repository, **kwargs):
            if Path(repository.db_path) == new_db:
                new_work.set()
            return native_query(repository, **kwargs)
        def configure():
            try:
                routes.configure_student_test_ocr_maintenance()
                configured.set()
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=configure)
        self.config.maintenance_enabled = True
        with patch.object(assets_module, "_unlink_registered_asset", unlink), \
                patch.object(StudentTestOcrRepository, "expired_assets", query):
            try:
                self.assertTrue(routes.configure_student_test_ocr_maintenance())
                self.assertTrue(entered.wait(3))
                self.config.db_path = new_db
                self.config.asset_root = self.root / "new-assets"
                worker.start()
                self.assertFalse(new_work.wait(0.15))
                self.assertFalse(configured.is_set())
            finally:
                release.set()
                if worker.ident is not None:
                    worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(configured.is_set() and new_work.wait(3))
        self.assertIsNotNone(old_repo.get_asset("a")["deleted_at"])

    def test_admin_off_inspection_does_not_delete_or_start(self):
        repository = self.create_schema()
        repository.begin_submission(
            submission_id="s", idempotency_key="s", request_hash="s", sid="student",
            test_id="unit", round_no="1", assignment_date="2026-10-03",
            answer_modes=["answer_value"] * 20, now=NOW.isoformat(),
        )
        self.assets.mkdir()
        target = self.assets / "capture.jpg"
        target.write_bytes(b"preserve expired file")
        repository.register_asset(asset_id="a", submission_id="s", question_no=1, kind="student_crop",
                                  relative_path="capture.jpg", expires_at=NOW.isoformat(), created_at=NOW.isoformat())
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        with patch.object(StudentTestOcrMaintenance, "start", side_effect=AssertionError("GET started thread")), \
                patch.object(StudentTestOcrMaintenance, "run_once", side_effect=AssertionError("GET deleted file")):
            response = self.client().get("/api/student-test-ocr/admin/maintenance",
                                         headers={"Authorization": "Basic test"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["enabled"] or response.json["executionEnabled"])
        self.assertTrue(response.headers["Cache-Control"].startswith("no-store"))
        self.assertTrue(target.exists())
        self.assertIsNone(repository.get_asset("a")["deleted_at"])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_first_tick_pending_uses_read_only_current_inspection(self):
        repository = self.create_schema()
        inspector = StudentTestOcrMaintenance(repository, self.assets, lambda: NOW)
        with patch.object(routes, "_MAINTENANCE", (("test",), inspector)), \
                patch.object(inspector, "run_once", side_effect=AssertionError("GET executed deletion")):
            response = self.client().get("/api/student-test-ocr/admin/maintenance",
                                         headers={"Authorization": "Basic test"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["enabled"])
        self.assertEqual(response.json["checkedAt"], NOW.isoformat(timespec="seconds"))
        self.assertFalse(response.json["executionEnabled"])
        self.assertFalse(self.assets.exists())

    def test_read_only_cli_uses_explicit_temp_paths(self):
        self.create_schema()
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/check_student_test_ocr_maintenance.py"),
             "--db", str(self.db), "--asset-root", str(self.assets)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output["ok"])
        self.assertFalse(output["executionEnabled"] or self.assets.exists())
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_app_wires_only_after_server_guard(self):
        module = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        factory = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
        calls = [node for node in ast.walk(factory) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        guard = next(node for node in calls if node.func.id == "refuse_concurrent_live_server")
        startup = next(node for node in calls if node.func.id == "configure_student_test_ocr_maintenance")
        self.assertGreater(startup.lineno, guard.lineno)


if __name__ == "__main__":
    unittest.main()
