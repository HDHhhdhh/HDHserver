from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import api_logs, log_repository_provider  # noqa: E402


DATE = "2026-08-01"
SID_ONE = "student-1"
SID_TWO = "student-2"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _store_fingerprints(root: Path) -> dict[str, tuple[int, str]]:
    out: dict[str, tuple[int, str]] = {}
    for path in sorted(root.glob("*")):
        if path.is_file():
            out[path.name] = (path.stat().st_size, _sha256(path))
    return out


def _assert_failure_is_no_write(root: Path, before: dict[str, tuple[int, str]], label: str) -> None:
    after = _store_fingerprints(root)
    assert after == before, f"{label} changed the temporary log stores"


def main() -> int:
    route_source = (ROOT / "routes" / "api_logs.py").read_text("utf-8")
    basic_source = (ROOT / "routes" / "api_basic.py").read_text("utf-8")
    provider_source = (ROOT / "routes" / "log_repository_provider.py").read_text("utf-8")
    app_source = (ROOT / "app.py").read_text("utf-8")

    assert '@bp_api_logs.get("/api/logs")' in route_source
    assert '@bp_api_logs.get("/api/logs/entry")' in route_source
    assert '@bp_api_logs.get("/api/logs/unarchived-summary")' in route_source
    assert '@bp_api_logs.get("/api/homework-books")' in route_source
    assert '@bp_api_logs.post("/api/logs/patch")' in route_source
    assert '@bp_api_logs.post("/api/logs/patch-batch")' in route_source
    assert '"/api/logs"' not in basic_source
    assert '"/api/homework-books"' not in basic_source
    assert "from routes.log_repository_provider import (" in basic_source
    assert "def get_log_repository() -> LogRepository:" in provider_source
    assert "from routes.api_logs import bp_api_logs" in app_source
    assert "app.register_blueprint(bp_api_logs)" in app_source

    with tempfile.TemporaryDirectory(prefix="verify-log-routes-") as tmp:
        root = Path(tmp)
        logs_path = root / "logs.json"
        students_path = root / "students.json"
        database_path = root / "app.sqlite"
        students_path.write_text(
            json.dumps(
                [
                    {"id": SID_ONE, "subBook1": "수학 A", "subBook2": "수학 B"},
                    {"id": SID_TWO, "subBook1": "대수 C"},
                ],
                ensure_ascii=False,
            ),
            "utf-8",
        )
        logs_path.write_text(
            json.dumps(
                {
                    DATE: {
                        SID_ONE: {"notes": "JSON 보충", "legacyOnly": "keep"},
                        SID_TWO: {
                            "done": True,
                            "homeworkTable": [{"book": "대수 C", "this": "1-2"}],
                        },
                    }
                },
                ensure_ascii=False,
            ),
            "utf-8",
        )
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                """
                CREATE TABLE logs (
                  date TEXT NOT NULL,
                  sid TEXT NOT NULL,
                  entry_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(date, sid)
                )
                """
            )
            connection.execute(
                "INSERT INTO logs(date, sid, entry_json, updated_at) VALUES(?,?,?,?)",
                (
                    DATE,
                    SID_ONE,
                    json.dumps(
                        {"notes": "SQLite 보존", "legacyOnly": "keep"},
                        ensure_ascii=False,
                    ),
                    "2026-08-01T00:00:00+09:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        original_logs_path = log_repository_provider.LOGS_PATH
        original_students_path = log_repository_provider.STU_PATH
        log_repository_provider.LOGS_PATH = logs_path
        log_repository_provider.STU_PATH = students_path
        try:
            app = Flask("verify-log-routes")
            app.register_blueprint(api_logs.bp_api_logs)
            client = app.test_client()

            patch_response = client.post(
                "/api/logs/patch",
                json={
                    "date": DATE,
                    "sid": SID_ONE,
                    "entry": {
                        "done": True,
                        "notes": "??",
                        "homeworkTable": [
                            {
                                "book": "??",
                                "this": "10-12",
                                "pct": 50,
                                "comment": "??",
                                "next": "13-15",
                            }
                        ],
                    },
                },
            )
            patch_payload = patch_response.get_json() or {}
            assert patch_response.status_code == 200
            assert patch_payload.get("ok") is True
            assert patch_payload.get("sqlite") is True
            assert patch_payload.get("json") is True
            expected_row = {
                "book": "수학 A",
                "this": "10-12",
                "pct": 50,
                "comment": "",
                "next": "13-15",
            }
            expected_summary = "[수학 A] 10-12 50% → 13-15"
            assert patch_payload["entry"].get("notes") == "SQLite 보존"
            assert patch_payload["entry"].get("legacyOnly") == "keep"
            assert patch_payload["entry"].get("homeworkTable") == [expected_row]
            assert patch_payload["entry"].get("homework") == expected_summary

            stored_json = json.loads(logs_path.read_text("utf-8"))
            stored_entry = stored_json[DATE][SID_ONE]
            assert stored_entry.get("notes") == "SQLite 보존"
            assert stored_entry.get("legacyOnly") == "keep"
            assert stored_entry.get("homeworkTable") == [expected_row]
            assert stored_entry.get("homework") == expected_summary

            connection = sqlite3.connect(database_path)
            try:
                row = connection.execute(
                    "SELECT entry_json FROM logs WHERE date=? AND sid=?",
                    (DATE, SID_ONE),
                ).fetchone()
            finally:
                connection.close()
            assert row is not None
            sqlite_entry = json.loads(row[0])
            assert sqlite_entry.get("homeworkTable") == [expected_row]
            assert sqlite_entry.get("homework") == expected_summary

            entry_response = client.get(f"/api/logs/entry?date={DATE}&sid={SID_ONE}")
            entry_payload = entry_response.get_json() or {}
            assert entry_response.status_code == 200
            assert entry_payload.get("ok") is True
            assert isinstance(entry_payload.get("source"), str) and entry_payload["source"]
            assert entry_payload.get("entry", {}).get("homeworkTable") == [expected_row]
            assert entry_payload.get("entry", {}).get("legacyOnly") == "keep"

            batch_response = client.get(f"/api/logs?date={DATE}&sids={SID_ONE},{SID_TWO}")
            batch_payload = batch_response.get_json() or {}
            assert batch_response.status_code == 200
            assert set(batch_payload.get(DATE, {})) == {SID_ONE, SID_TWO}
            assert batch_payload[DATE][SID_ONE].get("homeworkTable") == [expected_row]
            assert batch_payload[DATE][SID_TWO].get("done") is True

            export_targets = json.dumps([[SID_ONE, DATE], [SID_ONE, "2026-07-31"], [SID_TWO, DATE]])
            export_response = client.get(
                "/api/logs",
                query_string={"exportTargets": export_targets},
            )
            export_payload = export_response.get_json()
            assert export_response.status_code == 200
            assert isinstance(export_payload, dict)

            books_response = client.get("/api/homework-books")
            books_payload = books_response.get_json() or {}
            assert books_response.status_code == 200
            assert books_payload.get(SID_ONE) == ["수학 A"]
            assert books_payload.get(SID_TWO) == ["대수 C"]

            summary_response = client.get(
                "/api/logs/unarchived-summary",
                query_string={"excludeDate": "2026-07-31"},
            )
            summary_payload = summary_response.get_json() or {}
            assert summary_response.status_code == 200
            assert summary_payload.get("ok") is True
            assert summary_payload.get("rowsAvailable") is True
            assert {row["sid"] for row in summary_payload.get("rows", [])} == {SID_ONE, SID_TWO}

            before_failure = _store_fingerprints(root)
            failure_responses = [
                client.get("/api/logs?date=bad-date"),
                client.get("/api/logs?date=2026-02-30"),
                client.get(f"/api/logs/entry?date=bad-date&sid={SID_ONE}"),
                client.get(
                    f"/api/logs/entry?date=2026-02-30&sid={SID_ONE}"
                ),
                client.get(
                    "/api/logs/unarchived-summary",
                    query_string={"excludeDate": "2026-02-30"},
                ),
                client.get(
                    "/api/logs",
                    query_string={
                        "exportTargets": '[["student-1","2026-02-30"]]'
                    },
                ),
                client.post(
                    "/api/logs/patch",
                    json={
                        "date": "2026-02-30",
                        "sid": SID_ONE,
                        "entry": {"done": True},
                    },
                ),
                client.post(
                    "/api/logs/patch-batch",
                    json={
                        "patches": [
                            {
                                "date": DATE,
                                "sid": SID_ONE,
                                "entry": {"done": True},
                            },
                            {
                                "date": "2026-02-30",
                                "sid": SID_TWO,
                                "entry": {"done": True},
                            },
                        ]
                    },
                ),
                client.post(
                    "/api/logs/patch",
                    json={
                        "date": DATE,
                        "sid": "ghost-outside-test",
                        "entry": {"done": True},
                    },
                ),
                client.post(
                    "/api/logs/patch-batch",
                    json={
                        "patches": [
                            {"date": DATE, "sid": SID_ONE, "entry": {"done": True}},
                            {"date": DATE, "sid": SID_ONE, "entry": {"archived": True}},
                        ]
                    },
                ),
            ]
            assert [response.status_code for response in failure_responses] == [
                400,
                400,
                400,
                400,
                400,
                400,
                400,
                400,
                403,
                400,
            ]
            assert [response.get_json() for response in failure_responses[:8]] == [
                {"ok": False, "error": "bad date"},
                {"ok": False, "error": "bad date"},
                {"ok": False, "error": "bad query"},
                {"ok": False, "error": "bad query"},
                {"ok": False, "error": "bad date"},
                {"ok": False, "error": "bad exportTargets"},
                {"ok": False, "error": "bad date"},
                {"ok": False, "error": "bad patch item"},
            ]
            _assert_failure_is_no_write(root, before_failure, "validated route failures")
        finally:
            log_repository_provider.LOGS_PATH = original_logs_path
            log_repository_provider.STU_PATH = original_students_path

    print(
        "log route checks passed: dedicated blueprint, public repository provider, "
        "dual-store writes, placeholder repair, scoped reads, real-date validation, "
        "and no-write failures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
