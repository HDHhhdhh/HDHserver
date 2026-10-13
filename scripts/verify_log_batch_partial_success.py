"""Actual batch HTTP/SQLite failure checks with paths injected before imports."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def fingerprint(path):
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    with tempfile.TemporaryDirectory(prefix="log-batch-contract-") as raw:
        directory = Path(raw)
        paths = ModuleType("core.paths")
        paths.LOGS_PATH = directory / "logs.json"
        paths.STU_PATH = directory / "students.json"
        assert "core.paths" not in sys.modules, "inject paths before importing repository/routes"
        sys.modules["core.paths"] = paths
        from core.log_repository import LogRepository
        import core.log_repository as storage
        from core.log_rules import merge_log_entry_safe, log_entry_conflicts_with_base
        from core.storage import file_lock
        from routes import api_logs

        paths.STU_PATH.write_text("[]", encoding="utf-8")
        date = "2026-10-01"
        paths.LOGS_PATH.write_text(json.dumps({date: {
            "A": {"notes": "stale JSON", "unknown": {"keep": 7}},
            "B": {"untouched": True},
        }, "2026-09-30": {"C": {"notes": "history"}}}), encoding="utf-8")
        database = directory / "app.sqlite"

        def repository():
            return LogRepository(logs_path=paths.LOGS_PATH, db_path=str(database),
                                 merge_entry=merge_log_entry_safe, entry_conflicts=log_entry_conflicts_with_base,
                                 lock_factory=lambda: file_lock(paths.LOGS_PATH))

        repo = repository()
        app = Flask("log-batch-partial-success")
        app.config["TESTING"] = True
        app.register_blueprint(api_logs.bp_api_logs)
        with patch.object(api_logs, "get_log_repository", return_value=repo):
            client = app.test_client()
            body = {"patches": [
                {"date": date, "sid": "A", "entry": {}, "__clear": ["notes"]},
                {"date": date, "sid": "B", "entry": {"done": True}},
            ]}
            before = fingerprint(paths.LOGS_PATH)
            with patch.object(storage, "save_atomic", side_effect=OSError("injected JSON failure")):
                response = client.post("/api/logs/patch-batch", json=body)
            assert response.status_code == 200
            assert response.json == {"ok": True, "sqlite": True, "json": False, "count": 2,
                                     "warning": "SQLite save succeeded, but legacy JSON log storage is out of sync."}
            assert fingerprint(paths.LOGS_PATH) == before
            with closing(sqlite3.connect(database)) as connection:
                rows = {sid: json.loads(value) for sid, value in connection.execute(
                    "SELECT sid,entry_json FROM logs WHERE date=?", (date,))}
            assert "notes" not in rows["A"]
            assert rows["A"]["unknown"] == {"keep": 7}
            assert rows["B"]["done"] is True and rows["B"]["untouched"] is True
            expected = {"unknown": {"keep": 7}}
            assert client.get(f"/api/logs/entry?date={date}&sid=A").json["entry"] == expected
            assert client.get(f"/api/logs?date={date}&sid=A").json[date]["A"] == expected
            assert repository().read_entry(date, "A").entry == expected
            assert repo.read_export_history({"A": date})[date]["A"] == expected

            retried = client.post("/api/logs/patch-batch", json=body)
            assert retried.json == {"ok": True, "sqlite": True, "json": True, "count": 2}
            synced = json.loads(paths.LOGS_PATH.read_text(encoding="utf-8"))
            assert "notes" not in synced[date]["A"]
            assert synced["2026-09-30"]["C"] == {"notes": "history"}

            before = fingerprint(paths.LOGS_PATH)
            actual_upsert = repo._sqlite_upsert_entry
            calls = 0

            def fail_second(*args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise sqlite3.OperationalError("injected second-row failure")
                return actual_upsert(*args)

            rejected = {"patches": [
                {"date": date, "sid": "D", "entry": {"notes": "must roll back"}},
                {"date": date, "sid": "E", "entry": {"notes": "must roll back"}},
            ]}
            with patch.object(repo, "_sqlite_upsert_entry", side_effect=fail_second):
                response = client.post("/api/logs/patch-batch", json=rejected)
            assert response.status_code == 409 and response.json["sqlite"] is False
            assert fingerprint(paths.LOGS_PATH) == before
            with closing(sqlite3.connect(database)) as connection:
                assert connection.execute("SELECT count(*) FROM logs WHERE sid IN ('D','E')").fetchone()[0] == 0

            paths.LOGS_PATH.write_bytes(b"{broken")
            before = fingerprint(paths.LOGS_PATH)
            with patch.object(repo, "_connect", wraps=repo._connect) as connect:
                response = client.post("/api/logs/patch-batch", json=body)
                assert response.status_code == 409 and connect.call_count == 0
            assert fingerprint(paths.LOGS_PATH) == before
    print("batch logs passed: partial success, clear/unknown/reload/restart/export, successful retry, rollback and malformed no-write")


if __name__ == "__main__":
    verify()
