from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import api_arrive_time, api_logs, log_repository_provider  # noqa: E402
from core.log_repository import LogRepository  # noqa: E402
import core.log_repository as log_repository_module  # noqa: E402


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


def _verify_signature_cached_legacy_reads() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-log-read-cache-") as tmp:
        with log_repository_module._LOG_JSON_READ_CACHE_LOCK:
            log_repository_module._LOG_JSON_READ_CACHE.clear()
        root = Path(tmp)
        logs_path = root / "logs.json"
        database_path = root / "app.sqlite"
        logs_path.write_text(
            json.dumps({DATE: {SID_ONE: {"notes": "첫 값", "nested": {"keep": 1}}}}, ensure_ascii=False),
            "utf-8",
        )
        repository = LogRepository(logs_path=logs_path, db_path=str(database_path))
        raw_reader = log_repository_module._read_log_json_for_cache
        with mock.patch(
            "core.log_repository._read_log_json_for_cache",
            wraps=raw_reader,
        ) as reader:
            first = repository.read_logs(DATE)
            second = repository.read_logs(DATE)
            assert reader.call_count == 1, "unchanged logs.json must be parsed once"
            assert first == second

            first[DATE][SID_ONE]["nested"]["keep"] = 99
            third = repository.read_logs(DATE)
            assert third[DATE][SID_ONE]["nested"]["keep"] == 1
            assert reader.call_count == 1, "callers must not mutate the cached snapshot"

            logs_path.write_text(
                json.dumps({DATE: {SID_ONE: {"notes": "바뀐 값과 길이"}}}, ensure_ascii=False),
                "utf-8",
            )
            refreshed = repository.read_logs(DATE)
            assert refreshed[DATE][SID_ONE]["notes"] == "바뀐 값과 길이"
            assert reader.call_count == 2, "a changed file signature must invalidate the cache"

            with mock.patch.object(
                repository,
                "_connect",
                side_effect=RuntimeError("synthetic sqlite outage"),
            ):
                fallback_first = repository.read_logs()
                fallback_first[DATE][SID_ONE]["notes"] = "caller mutation"
                fallback_second = repository.read_logs()
            assert fallback_second[DATE][SID_ONE]["notes"] == "바뀐 값과 길이"
            assert reader.call_count == 2, "fallback defensive copies must reuse the stable parse"

        unstable_path = root / "unstable-logs.json"
        signatures = [
            (1, 1, 1, 1),
            (2, 2, 2, 2),
            (3, 3, 3, 3),
            (3, 3, 3, 3),
            (3, 3, 3, 3),
        ]
        snapshots = [
            ({"version": 1}, "available"),
            ({"version": 2}, "available"),
            ({"version": 3}, "available"),
        ]
        with mock.patch(
            "core.log_repository._log_json_signature",
            side_effect=signatures,
        ), mock.patch(
            "core.log_repository._read_log_json_for_cache",
            side_effect=snapshots,
        ) as unstable_reader:
            first_unstable, _ = log_repository_module._cached_log_json_for_read(unstable_path)
            second_stable, _ = log_repository_module._cached_log_json_for_read(unstable_path)
        assert first_unstable == {"version": 2}
        assert second_stable == {"version": 3}
        assert unstable_reader.call_count == 3, "an unstable replacement must not be cached"

        with log_repository_module._LOG_JSON_READ_CACHE_LOCK:
            log_repository_module._LOG_JSON_READ_CACHE.clear()
        for index in range(17):
            cache_path = root / f"logs-{index}.json"
            cache_path.write_text("{}", encoding="utf-8")
            log_repository_module._cached_log_json_for_read(cache_path)
        with log_repository_module._LOG_JSON_READ_CACHE_LOCK:
            assert len(log_repository_module._LOG_JSON_READ_CACHE) == 16
            log_repository_module._LOG_JSON_READ_CACHE.clear()


def _verify_missing_leave_summary() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-missing-leave-summary-") as tmp:
        root = Path(tmp)
        logs_path = root / "logs.json"
        database_path = root / "app.sqlite"
        date = "2026-08-28"
        logs_path.write_text(
            json.dumps(
                {
                    date: {
                        "json-done": {"done": True},
                        "sqlite-wins": {"done": True},
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
            connection.executemany(
                "INSERT INTO logs(date, sid, entry_json, updated_at) VALUES(?,?,?,?)",
                [
                    (date, "sqlite-done", json.dumps({"done": True}), "2026-08-28T20:00:00+09:00"),
                    (date, "sqlite-wins", json.dumps({"done": False}), "2026-08-28T20:01:00+09:00"),
                    (date, "missing", json.dumps({"notes": "keep"}), "2026-08-28T20:02:00+09:00"),
                ],
            )
            connection.commit()
        finally:
            connection.close()

        repository = LogRepository(
            logs_path=logs_path,
            db_path=str(database_path),
            today_key=lambda: "2026-08-30",
        )
        summary = repository.summarize_missing_leave(
            {
                "2026-08-27": {"before-baseline": "18:00"},
                date: {
                    "sqlite-done": "17:00",
                    "json-done": "17:10",
                    "sqlite-wins": "17:20",
                    "missing": "17:30",
                    "absent": "17:40",
                },
                "2026-08-29": {"selected-date": "18:00"},
                "2026-08-30": {"today": "13:00"},
            },
            {date: ["absent"]},
            since_date=date,
            exclude_date="2026-08-29",
        )
        assert summary.get("rowsAvailable") is True
        assert summary.get("total") == 2
        assert summary.get("students") == 2
        assert {row["sid"] for row in summary.get("rows", [])} == {"sqlite-wins", "missing"}
        assert summary.get("byDate") == [{"date": date, "count": 2}]


def main() -> int:
    _verify_signature_cached_legacy_reads()
    _verify_missing_leave_summary()
    route_source = (ROOT / "routes" / "api_logs.py").read_text("utf-8")
    arrive_route_source = (ROOT / "routes" / "api_arrive_time.py").read_text("utf-8")
    basic_source = (ROOT / "routes" / "api_basic.py").read_text("utf-8")
    provider_source = (ROOT / "routes" / "log_repository_provider.py").read_text("utf-8")
    app_source = (ROOT / "app.py").read_text("utf-8")

    assert '@bp_api_logs.get("/api/logs")' in route_source
    assert '@bp_api_logs.get("/api/logs/entry")' in route_source
    assert '@bp_api_logs.get("/api/logs/unarchived-summary")' in route_source
    assert '@bp_api_logs.get("/api/homework-books")' in route_source
    assert '@bp_api_logs.post("/api/logs/patch")' in route_source
    assert '@bp_api_logs.post("/api/logs/patch-batch")' in route_source
    assert '@bp_api_arrive_time.get("/api/arrive-time/missing-leave-summary")' in arrive_route_source
    assert "MISSING_LEAVE_WARNING_START_DATE = \"2026-08-29\"" in arrive_route_source
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
        arrive_time_path = root / "arrive_time.json"
        extra_attend_path = root / "extra_attend.json"
        makeup_carryover_path = root / "makeup_carryover.json"
        students_path.write_text(
            json.dumps(
                [
                    {"id": SID_ONE, "subBook1": "수학 A", "subBook2": "수학 B"},
                    {"id": SID_TWO, "subBook1": "대수 C"},
                    {"id": "student-missing-leave", "day1": "토1"},
                    {"id": "student-active-makeup", "day1": "월1"},
                    {"id": "student-moved-makeup", "day1": "월1"},
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
        arrive_time_path.write_text(
            json.dumps(
                {
                    "2026-08-29": {
                        "student-missing-leave": "17:45",
                        "student-active-makeup": "17:50",
                        "student-moved-makeup": "17:55",
                    }
                }
            ),
            "utf-8",
        )
        extra_attend_path.write_text("{}", "utf-8")
        makeup_carryover_path.write_text(
            json.dumps(
                {
                    "by_absence": {
                        "2026-08-20": {
                            "student-active-makeup|1": {
                                "scheduledMakeup": {
                                    "studentId": "student-active-makeup",
                                    "makeupDate": "2026-08-29",
                                    "makeupTimes": [1],
                                    "status": "scheduled",
                                }
                            },
                            "student-moved-makeup|1": {
                                "scheduledMakeup": {
                                    "studentId": "student-moved-makeup",
                                    "makeupDate": "2026-08-31",
                                    "makeupTimes": [1],
                                    "status": "scheduled",
                                }
                            },
                        }
                    }
                }
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
            app.register_blueprint(api_arrive_time.bp_api_arrive_time)
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

            with mock.patch.object(api_arrive_time, "ARRIVE_TIME_PATH", arrive_time_path), mock.patch.object(
                api_arrive_time,
                "STU_PATH",
                students_path,
            ), mock.patch.object(
                api_arrive_time,
                "EXTRA_PATH",
                extra_attend_path,
            ), mock.patch.object(
                api_arrive_time,
                "MAKEUP_CARRYOVER_PATH",
                makeup_carryover_path,
            ), mock.patch.object(
                api_arrive_time,
                "load_absent",
                return_value={"by_date": {}, "by_student": {}, "by_slot": {}},
            ):
                missing_leave_response = client.get(
                    "/api/arrive-time/missing-leave-summary",
                    query_string={"excludeDate": DATE},
                )
                missing_leave_payload = missing_leave_response.get_json() or {}
                assert missing_leave_response.status_code == 200
                assert missing_leave_response.headers.get("Cache-Control") == "no-store"
                assert missing_leave_payload.get("total") == 2
                assert missing_leave_payload.get("rows") == [
                    {
                        "date": "2026-08-29",
                        "sid": "student-active-makeup",
                        "arriveTime": "17:50",
                    },
                    {
                        "date": "2026-08-29",
                        "sid": "student-missing-leave",
                        "arriveTime": "17:45",
                    }
                ]
                assert all(
                    row.get("sid") != "student-moved-makeup"
                    for row in missing_leave_payload.get("rows", [])
                ), "a moved makeup residue triggered a missing-leave warning"
                excluded_missing_leave = client.get(
                    "/api/arrive-time/missing-leave-summary",
                    query_string={"excludeDate": "2026-08-29"},
                )
                assert excluded_missing_leave.status_code == 200
                assert (excluded_missing_leave.get_json() or {}).get("total") == 0

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
                client.get(
                    "/api/arrive-time/missing-leave-summary",
                    query_string={"excludeDate": "2026-02-30"},
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


def verify_snapshot_write_contract() -> None:
    from contextlib import closing
    from core.log_rules import merge_log_entry_safe, log_entry_conflicts_with_base
    from core.storage import file_lock

    with tempfile.TemporaryDirectory(prefix="verify-log-snapshot-") as tmp:
        root = Path(tmp)
        logs = root / "logs.json"
        logs.write_text(json.dumps({DATE: {SID_ONE: {"notes": "base", "legacy": {"keep": 7}}, SID_TWO: {"notes": "untouched"}}}), "utf-8")
        repo = LogRepository(logs_path=logs, db_path=str(root / "app.sqlite"),
                             merge_entry=merge_log_entry_safe, entry_conflicts=log_entry_conflicts_with_base,
                             lock_factory=lambda: file_lock(logs))
        app = Flask("log-snapshot-proof")
        app.register_blueprint(api_logs.bp_api_logs)
        with mock.patch.object(api_logs, "get_log_repository", return_value=repo):
            client = app.test_client()
            def save(entry, base=None, clear=None):
                return client.post("/api/logs/patch", json={"date": DATE, "sid": SID_ONE, "entry": entry, "base": base or {}, "__clear": clear or []})
            assert save({"notes": "base"}).status_code == 200
            with closing(repo._connect()) as con:
                repo._sqlite_upsert_entry(con, DATE, SID_ONE, {"notes": "remote"})
            before = logs.read_bytes()
            conflict = save({"notes": "mine"}, {"notes": "base"})
            assert conflict.status_code == 409 and conflict.json["retryable"] is False
            assert logs.read_bytes() == before, "SQLite conflict must not commit a JSON-only edit"
            assert repo.read_entry(DATE, SID_ONE).entry["notes"] == "remote"
            with mock.patch.object(log_repository_module, "save_atomic", side_effect=OSError("injected mirror failure")):
                cleared = save({}, {"notes": "remote"}, ["notes"])
            assert cleared.status_code == 200 and cleared.json["json"] is False
            expected = {"legacy": {"keep": 7}}
            assert cleared.json["entry"] == expected
            for observed in (repo.read_entry(DATE, SID_ONE).entry, repo.read_logs(DATE)[DATE][SID_ONE], repo.read_export_history({SID_ONE: DATE})[DATE][SID_ONE]):
                assert observed == expected, "deleted notes must not be filled from stale JSON"
            restarted = LogRepository(logs_path=logs, db_path=str(root / "app.sqlite"))
            assert restarted.read_entry(DATE, SID_ONE).entry == expected
            assert save({"notes": "new"}, {"notes": ""}).status_code == 200
            assert repo.read_entry(DATE, SID_ONE).entry["notes"] == "new"
            assert repo.read_logs(DATE)[DATE][SID_TWO] == {"notes": "untouched"}
            with mock.patch.object(repo, "_connect", side_effect=OSError("injected sqlite failure")):
                before = logs.read_bytes()
                assert save({"notes": "must not become JSON-only"}).status_code != 200
                assert logs.read_bytes() == before
            logs.write_text("{broken", "utf-8")
            assert save({"notes": "must not erase legacy history"}).status_code != 200
            assert logs.read_text("utf-8") == "{broken"
    print("log snapshot contracts passed: conflict/no-write, clear/reload/restart, retry, unknown fields and strict failures")


if __name__ == "__main__":
    verify_snapshot_write_contract()
    raise SystemExit(main())
