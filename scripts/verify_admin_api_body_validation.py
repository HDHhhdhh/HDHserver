"""Student body validation and RMW races use actual routes and temporary stores."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.api_errors import install_api_error_handlers
from routes import api_students
from scripts.report_duplicate_student_ids import report


@contextmanager
def fixture(rows):
    with tempfile.TemporaryDirectory(prefix="student-body-") as temporary:
        root = Path(temporary)
        students = root / "students.json"
        students.write_text(json.dumps(rows, ensure_ascii=False), "utf-8")
        notifications = []
        with patch.object(api_students, "STU_PATH", students), patch.object(api_students, "PERSONS_PATH", root / "persons.json"), patch.object(api_students, "PERSON_IDENTITY_JOURNAL_PATH", root / "pending.json"), patch.object(api_students, "enqueue_current_schedule_changes", side_effect=lambda sids: notifications.extend(sids)), patch.dict(os.environ, {"DATA_MIRROR_DIR": str(root / "mirror"), "DATA_MIRROR_SNAPSHOTS": "0", "DATA_MIRROR_SYNC": "1"}):
            app = Flask("student-body-fixture")
            install_api_error_handlers(app)
            api_students.configure_student_identity_assignment_hooks(app, initialize_today=lambda **kwargs: None, reconcile_today=lambda *args, **kwargs: None)
            app.register_blueprint(api_students.bp_api_students)
            yield students, app, notifications


def fingerprint(path):
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


class StudentBodyTests(unittest.TestCase):
    def test_invalid_add_and_update_have_no_writes_or_notifications(self):
        with fixture([{"id": "student0", "name": "QA", "unknown": {"keep": 7}}]) as (path, app, notifications):
            client = app.test_client()
            before = fingerprint(path)
            invalid_add = (None, [], "name", 1, {}, {"name": ""}, {"name": "   "}, {"name": None}, {"name": []}, {"name": "!!!"})
            for body in invalid_add:
                with self.subTest(add=body):
                    response = client.post("/api/add-student", data=json.dumps(body), content_type="application/json")
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(fingerprint(path), before)
            invalid_update = ([], "field", None, {"id": "student0", "field": "name"}, *({"id": "student0", "field": field, "value": "bad"} for field in ("id", "personId", "__proto__", "x" * 41, "a.b", 7)), {"id": "student0", "field": "memo", "value": {"bad": True}}, {"id": "student0", "field": "memo", "value": ["ok", {}]}, {"id": "student0", "field": "selfStudyDays", "value": {"day1": {"nested": True}}}, {"id": "student0", "field": "whiteReviewPending", "value": "true"})
            for body in invalid_update:
                with self.subTest(update=body):
                    response = client.post("/api/update", data=json.dumps(body), content_type="application/json")
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(fingerprint(path), before)
            self.assertEqual(notifications, [])

    def test_existing_object_fields_scalar_lists_and_explicit_clear_survive(self):
        with fixture([{"id": "student0", "name": "QA", "unknown": {"keep": 7}}]) as (path, app, _):
            cases = {
                "selfStudyDays": {"day1": True, "day5": False},
                "testLevelDefaults": {"UNIT": {"공수1": "Lv.4"}, "legacy": {"unknown": {"keep": 8}}},
                "memo": None,
                "futureFlag": ["한글", 0, False, None],
            }
            for field, value in cases.items():
                self.assertEqual(app.test_client().post("/api/update", json={"id": "student0", "field": field, "value": value}).status_code, 200)
            stored = json.loads(path.read_text("utf-8"))[0]
            self.assertEqual(stored["unknown"], {"keep": 7})
            for field, value in cases.items():
                self.assertEqual(stored[field], value)

    def test_last_available_sid_and_exhaustion(self):
        rows = [{"id": f"QA{index:03d}", "name": "QA"} for index in range(999)]
        with fixture(rows) as (path, app, notifications), patch.object(api_students.random, "randint", return_value=0):
            response = app.test_client().post("/api/add-student", json={"name": "QA"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["id"], "QA999")
            before = fingerprint(path)
            self.assertEqual(app.test_client().post("/api/add-student", json={"name": "QA"}).status_code, 409)
            self.assertEqual(fingerprint(path), before)
            self.assertEqual(notifications, ["QA999"])
            self.assertEqual(report(path), {"rows": 1000, "missingIDs": 0, "duplicateIDs": {}})

    def test_two_hundred_same_name_additions_are_unique(self):
        with fixture([]) as (path, app, notifications), patch.object(api_students.random, "randint", return_value=0):
            client = app.test_client()
            added = []
            for _ in range(200):
                response = client.post("/api/add-student", json={"name": "QA"})
                self.assertEqual(response.status_code, 200)
                added.append(response.get_json()["id"])
            self.assertEqual(added, [f"QA{index:03d}" for index in range(200)])
            self.assertEqual(notifications, added)
            self.assertEqual(report(path), {"rows": 200, "missingIDs": 0, "duplicateIDs": {}})

    def test_sixteen_writers_preserve_all_hundred_rows_twenty_rounds(self):
        rows = [{"id": f"student{index}", "name": "QA", "unknown": {"keep": index}} for index in range(100)]
        with fixture(rows) as (path, app, _):
            for round_number in range(20):
                barrier = threading.Barrier(16)

                def worker(worker_number):
                    barrier.wait(timeout=10)
                    for index in range(worker_number, 100, 16):
                        response = app.test_client().post("/api/update", json={"id": f"student{index}", "field": "memo", "value": f"{round_number}:{index}"})
                        self.assertEqual(response.status_code, 200)

                with ThreadPoolExecutor(max_workers=16) as executor:
                    list(executor.map(worker, range(16)))
                stored = json.loads(path.read_text("utf-8"))
                self.assertEqual(len(stored), 100)
                for index, row in enumerate(stored):
                    self.assertEqual(row["memo"], f"{round_number}:{index}")
                    self.assertEqual(row["unknown"], {"keep": index})


if __name__ == "__main__":
    unittest.main(verbosity=2)
