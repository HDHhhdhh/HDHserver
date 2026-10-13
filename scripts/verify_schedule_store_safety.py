"""Bad stored schedule snapshots must never become empty replacement maps."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import api_schedule_overrides as schedules


class ScheduleStoreTests(unittest.TestCase):
    def test_corrupt_or_wrong_shape_blocks_write_without_hooks(self):
        for store, method, body, broken_values in (
            ("EXTRA_PATH", "patch", {"date": "2026-10-15", "sids": ["student0"]}, (b"[]", b"null", b"{broken", b'{"2026-10-15":{"keep":"unknown"}}')),
            ("WEEKEND_SLOTS_PATH", "post", {"2026-10-15": {"student0": [1]}}, (b"[]", b"null", b"{broken", b'{"2026-10-15":["keep"]}')),
        ):
            for broken in broken_values:
                with self.subTest(store=store, broken=broken), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    path = root / "schedule.json"
                    path.write_bytes(broken)
                    roster = root / "students.json"
                    roster.write_text('[{"id":"student0"}]', "utf-8")
                    before = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
                    calls = []
                    app = Flask("schedule-store-fixture")
                    schedules.configure_schedule_override_assignment_hooks(app, initialize_today=lambda **kwargs: calls.append("initialize"), reconcile=lambda *args, **kwargs: calls.append("reconcile"))
                    app.register_blueprint(schedules.bp_api_schedule_overrides)
                    with patch.object(schedules, store, path), patch.object(schedules, "STU_PATH", roster), patch.object(schedules, "enqueue_current_schedule_changes", side_effect=lambda *args: calls.append("notify")):
                        url = "/api/extra-attend" if store == "EXTRA_PATH" else "/api/weekend-slots"
                        response = getattr(app.test_client(), method)(url, json=body)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.get_json(), {"ok": False, "error": "schedule_store_unavailable"})
                    self.assertEqual((path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()), before)
                    self.assertEqual(calls, [])

    def test_targeted_read_permission_failure_returns_503_without_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "extra.json"
            path.write_text('{"2026-10-15":["keep"]}', "utf-8")
            before = path.read_bytes()
            original = Path.read_text

            def denied(target, *args, **kwargs):
                if target == path:
                    raise PermissionError("fixture schedule denied")
                return original(target, *args, **kwargs)

            app = Flask("schedule-read-fixture")
            app.register_blueprint(schedules.bp_api_schedule_overrides)
            with patch.object(schedules, "EXTRA_PATH", path), patch.object(Path, "read_text", denied):
                response = app.test_client().get("/api/extra-attend")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(path.read_bytes(), before)

    def test_roster_permission_failure_is_unavailable_not_ghost_denial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, roster = root / "weekend.json", root / "students.json"
            path.write_text('{"keep":{"other":[2]}}', "utf-8")
            roster.write_text('[{"id":"student0"}]', "utf-8")
            before = (path.stat().st_mtime_ns, path.read_bytes())
            original = Path.read_text
            calls = []

            def denied(target, *args, **kwargs):
                if target == roster:
                    raise PermissionError("fixture roster denied")
                return original(target, *args, **kwargs)

            app = Flask("weekend-roster-read-fixture")
            schedules.configure_schedule_override_assignment_hooks(app, initialize_today=lambda **kwargs: calls.append("initialize"), reconcile=lambda *args, **kwargs: calls.append("reconcile"))
            app.register_blueprint(schedules.bp_api_schedule_overrides)
            with patch.object(schedules, "WEEKEND_SLOTS_PATH", path), patch.object(schedules, "STU_PATH", roster), patch.object(Path, "read_text", denied), patch.object(schedules, "enqueue_current_schedule_changes", side_effect=lambda *args: calls.append("notify")):
                response = app.test_client().post("/api/weekend-slots", json={"2026-10-15": {"student0": [1]}})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json(), {"ok": False, "error": "student roster unavailable"})
            self.assertEqual((path.stat().st_mtime_ns, path.read_bytes()), before)
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
