"""Exercise the registered routes against real, path-injected assignment services."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import ModuleType
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.admin_api_guard import install_admin_api_guard
from core import request_consistency as consistency
from routes import api_updates as updates
from scripts.verify_student_auto_assignment_service import (
    FixtureRuntime, expected_created_updates, load_updates_with_auto_assign,
)


def fingerprint(path):
    return path.stat().st_mtime_ns, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()


with tempfile.TemporaryDirectory(prefix="draft-updates-get-") as temporary, patch.dict(os.environ, {"UPDATES_GET_ENSURE": "0"}), patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
    runtime = FixtureRuntime(Path(temporary))
    runtime.seed()
    before = {path: fingerprint(path) for path in runtime.paths.values()}
    literal = runtime.load(runtime.paths["updates"])
    initialize_calls = []
    app = Flask("draft-updates-get")
    app.config["ACADEMY_ADMIN_AUTHORIZER"] = lambda header: header == "fixture-admin"
    install_admin_api_guard(app)

    def initialize():
        initialize_calls.append(True)
        return load_updates_with_auto_assign(runtime.dependencies())

    updates.configure_updates_assignment_hooks(app, initialize_today=initialize, reconcile_self_study=lambda **kwargs: ({}, 200))
    app.register_blueprint(updates.bp_api_updates)
    headers = {"Authorization": "fixture-admin"}
    with patch.object(updates, "UPD_PATH", runtime.paths["updates"]):
        def read(_number):
            with app.test_client() as client:
                response = client.get("/api/updates", headers=headers)
            assert response.status_code == 200 and response.json == literal

        with ThreadPoolExecutor(max_workers=20) as executor:
            list(executor.map(read, range(20)))
        assert before == {path: fingerprint(path) for path in runtime.paths.values()}
        assert initialize_calls == [] and runtime.save_count == 0
        client = app.test_client()
        assert client.post("/api/updates/ensure-today", json={}).status_code == 401
        assert initialize_calls == [] and runtime.save_count == 0
        first = client.post("/api/updates/ensure-today", json={}, headers=headers)
        assert first.status_code == 200 and first.json == expected_created_updates()
        committed = fingerprint(runtime.paths["updates"])
        second = client.post("/api/updates/ensure-today", json={}, headers=headers)
        assert second.status_code == 200 and second.json == first.json
        assert fingerprint(runtime.paths["updates"]) == committed and runtime.save_count == 1
        assert client.get("/api/updates?ensure=1", headers=headers).json == first.json
        assert len(initialize_calls) == 3 and runtime.save_count == 1
        with patch.dict(os.environ, {"UPDATES_GET_ENSURE": "1"}):
            assert client.get("/api/updates", headers=headers).json == first.json
            assert len(initialize_calls) == 4
            assert client.get("/api/updates?readOnly=1&ensure=1", headers=headers).json == first.json
            assert len(initialize_calls) == 4
            assert consistency.absence_barrier_mode("/api/updates", "GET", {}) == "exclusive"
            assert consistency.absence_barrier_mode("/api/updates", "GET", {"readOnly": "yes"}) == "shared"
        assert consistency.absence_barrier_mode("/api/updates", "GET", {}) == "shared"
        assert consistency.absence_barrier_mode("/api/updates", "GET", {"ensure": "1"}) == "exclusive"
        assert consistency.absence_barrier_mode("/api/updates/ensure-today", "POST") == "exclusive"
        assert consistency.absence_barrier_mode("/api/student/bootstrap", "GET") == "exclusive"
print("Updates read/ensure: 20 parallel GETs preserve all stores; authenticated ensure is idempotent; compatibility/rollback and absence modes agree")
