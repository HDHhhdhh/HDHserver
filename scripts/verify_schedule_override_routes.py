from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import time
from copy import deepcopy
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import api_schedule_overrides  # noqa: E402
from core.json_store import JsonStore  # noqa: E402


def _write_store(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def _fingerprint(path: Path) -> tuple[int, str]:
    content = path.read_bytes()
    return len(content), hashlib.sha256(content).hexdigest()


def main() -> int:
    route_source = (ROOT / "routes" / "api_schedule_overrides.py").read_text("utf-8")
    basic_source = (ROOT / "routes" / "api_basic.py").read_text("utf-8")
    app_source = (ROOT / "app.py").read_text("utf-8")
    assert '@bp_api_schedule_overrides.route("/api/extra-attend", methods=["GET", "PATCH"])' in route_source
    assert '@bp_api_schedule_overrides.route("/api/weekend-slots", methods=["GET", "POST"])' in route_source
    assert '"/api/extra-attend"' not in basic_source
    assert '"/api/weekend-slots"' not in basic_source
    assert "app.register_blueprint(bp_api_schedule_overrides)" in app_source

    with tempfile.TemporaryDirectory(prefix="verify-schedule-overrides-") as tmp:
        root = Path(tmp)
        extra_path = root / "extra_attend.json"
        weekend_path = root / "weekend_slots.json"
        students_path = root / "students.json"
        initial_extra = {
            "2026-06-07": ["keep", "remove-me"],
            "2026-06-10": ["untouched"],
        }
        initial_weekend = {
            "2026-06-06": {"keep": [3], "remove-me": [2]},
            "legacy": {"untouched": "raw"},
        }
        students = [
            {"id": sid, "name": f"Student {sid}"}
            for sid in ("s1", "remove-me", "raw", "must-not-write")
        ]
        _write_store(extra_path, initial_extra)
        _write_store(weekend_path, initial_weekend)
        _write_store(students_path, students)

        original = {
            "EXTRA_PATH": api_schedule_overrides.EXTRA_PATH,
            "WEEKEND_SLOTS_PATH": api_schedule_overrides.WEEKEND_SLOTS_PATH,
            "STU_PATH": api_schedule_overrides.STU_PATH,
            "today": api_schedule_overrides._today_kst_iso,
            "enqueue": api_schedule_overrides.enqueue_current_schedule_changes,
            "load": api_schedule_overrides.load,
            "save_atomic": api_schedule_overrides.save_atomic,
            "read_data_locked": JsonStore.read_data_locked,
        }
        initializer_calls: list[dict] = []
        initializer_state = {"failures_remaining": 0}
        reconcile_calls: list[tuple[tuple, dict]] = []
        notification_calls: list[set[str]] = []

        def initialize_today(**kwargs):
            initializer_calls.append(deepcopy(kwargs))
            if initializer_state["failures_remaining"]:
                initializer_state["failures_remaining"] -= 1
                raise OSError("injected post-commit initializer failure")
            return {}

        def reconcile(*args, **kwargs):
            reconcile_calls.append((deepcopy(args), deepcopy(kwargs)))
            return False

        try:
            api_schedule_overrides.EXTRA_PATH = extra_path
            api_schedule_overrides.WEEKEND_SLOTS_PATH = weekend_path
            api_schedule_overrides.STU_PATH = students_path
            api_schedule_overrides._today_kst_iso = lambda: "2026-06-06"
            api_schedule_overrides.enqueue_current_schedule_changes = (
                lambda sids: notification_calls.append(set(sids)) or 0
            )

            app = Flask("verify-schedule-override-routes")
            app.config["TESTING"] = False
            api_schedule_overrides.configure_schedule_override_assignment_hooks(
                app,
                initialize_today=initialize_today,
                reconcile=reconcile,
            )
            app.register_blueprint(api_schedule_overrides.bp_api_schedule_overrides)
            client = app.test_client()

            route_rows = sorted(
                (
                    rule.rule,
                    rule.endpoint,
                    sorted(rule.methods - {"HEAD", "OPTIONS"}),
                )
                for rule in app.url_map.iter_rules()
                if rule.rule in {"/api/extra-attend", "/api/weekend-slots"}
            )
            assert route_rows == [
                (
                    "/api/extra-attend",
                    "api_schedule_overrides.api_extra_attend",
                    ["GET", "PATCH"],
                ),
                (
                    "/api/weekend-slots",
                    "api_schedule_overrides.api_weekend_slots",
                    ["GET", "POST"],
                ),
            ]
            assert client.get("/api/extra-attend").get_json() == initial_extra
            assert client.get("/api/weekend-slots").get_json() == initial_weekend

            extra_before_failures = _fingerprint(extra_path)
            extra_failures = (
                client.post("/api/extra-attend", json={}),
                client.patch("/api/extra-attend", json=[]),
                client.patch(
                    "/api/extra-attend",
                    json={"date": "2026-02-30", "sids": ["s1"]},
                ),
                client.patch(
                    "/api/extra-attend",
                    json={"date": "2026-06-06", "sids": "s1"},
                ),
                client.patch(
                    "/api/extra-attend",
                    json={"date": "2026-06-06", "sids": ["ghost-outside-test"]},
                ),
            )
            assert [response.status_code for response in extra_failures] == [405, 400, 400, 400, 403]
            assert _fingerprint(extra_path) == extra_before_failures
            assert initializer_calls == []
            assert notification_calls == []

            saved_extra = client.patch(
                "/api/extra-attend",
                json={
                    "dates": {
                        "2026-06-06": ["s1", "s1", 2, ""],
                        "2026-06-07": [],
                    }
                },
            )
            expected_extra = {
                "2026-06-06": ["s1", "2"],
                "2026-06-10": ["untouched"],
            }
            assert saved_extra.status_code == 200
            assert saved_extra.get_json() == {
                "ok": True,
                "dates": {
                    "2026-06-06": ["s1", "2"],
                    "2026-06-07": [],
                },
                "changedDates": ["2026-06-06", "2026-06-07"],
            }
            assert json.loads(extra_path.read_text("utf-8")) == expected_extra
            assert initializer_calls == [
                {"date_key": "2026-06-06", "extra": expected_extra},
            ]
            assert notification_calls[-1] == {"s1", "2", "keep", "remove-me"}

            idempotent_before = _fingerprint(extra_path)
            idempotent = client.patch(
                "/api/extra-attend",
                json={"date": "2026-06-06", "sids": ["s1", "2"]},
            )
            assert idempotent.status_code == 200
            assert idempotent.get_json()["changedDates"] == []
            assert _fingerprint(extra_path) == idempotent_before
            assert initializer_calls[-1] == {
                "date_key": "2026-06-06",
                "extra": expected_extra,
            }
            assert len(initializer_calls) == 2
            assert notification_calls[-1] == set()

            real_read = JsonStore.read_data_locked
            first_loaded = threading.Event()
            release_first = threading.Event()
            writer_results: dict[str, int] = {}

            def delayed_read(store):
                value = real_read(store)
                if store.path == extra_path and threading.current_thread().name == "extra-writer-one":
                    first_loaded.set()
                    assert release_first.wait(3), "timed out releasing the first extra writer"
                return value

            def write_extra(label: str, date_key: str, sid: str) -> None:
                with app.test_client() as thread_client:
                    response = thread_client.patch(
                        "/api/extra-attend",
                        json={"date": date_key, "sids": [sid]},
                    )
                    writer_results[label] = response.status_code

            JsonStore.read_data_locked = delayed_read
            first = threading.Thread(
                target=write_extra,
                args=("first", "2026-06-08", "writer-a"),
                name="extra-writer-one",
            )
            second = threading.Thread(
                target=write_extra,
                args=("second", "2026-06-09", "writer-b"),
                name="extra-writer-two",
            )
            first.start()
            assert first_loaded.wait(3), "first extra writer did not enter the locked read"
            second.start()
            time.sleep(0.15)
            assert second.is_alive(), "second extra writer bypassed the file lock"
            release_first.set()
            first.join(5)
            second.join(5)
            assert not first.is_alive() and not second.is_alive()
            assert writer_results == {"first": 200, "second": 200}
            concurrent_extra = json.loads(extra_path.read_text("utf-8"))
            assert concurrent_extra["2026-06-08"] == ["writer-a"]
            assert concurrent_extra["2026-06-09"] == ["writer-b"]
            assert concurrent_extra["2026-06-10"] == ["untouched"]
            JsonStore.read_data_locked = real_read

            weekend_before_failures = _fingerprint(weekend_path)
            students_before_failures = _fingerprint(students_path)
            assert client.patch("/api/weekend-slots", json={}).status_code == 405
            notification_calls.clear()
            reconcile_calls.clear()
            malformed = client.post(
                "/api/weekend-slots",
                data="{broken",
                content_type="application/json",
            )
            strict_failures = (
                malformed,
                client.post("/api/weekend-slots", json=[]),
                client.post("/api/weekend-slots", json={}),
                client.post(
                    "/api/weekend-slots",
                    json={"2026-02-30": {"s1": [1]}},
                ),
                client.post(
                    "/api/weekend-slots",
                    json={"not-a-date": {"s1": [1]}},
                ),
                client.post(
                    "/api/weekend-slots",
                    json={"2026-06-06": ["s1"]},
                ),
                client.post(
                    "/api/weekend-slots",
                    json={"2026-06-06": {}},
                ),
                client.post(
                    "/api/weekend-slots",
                    json={"2026-06-06": {"ghost-outside-test": [1]}},
                ),
                client.post(
                    "/api/weekend-slots",
                    json={"2026-06-06": {"s1": [1], "unknown": [2]}},
                ),
            )
            assert [response.status_code for response in strict_failures] == [
                400,
                400,
                400,
                400,
                400,
                400,
                400,
                403,
                404,
            ]
            assert _fingerprint(weekend_path) == weekend_before_failures
            assert _fingerprint(students_path) == students_before_failures
            assert notification_calls == []
            assert reconcile_calls == []
            assert len(initializer_calls) == 2

            saved_weekend = client.post(
                "/api/weekend-slots",
                json={
                    "2026-06-06": {
                        "s1": ["1", 2],
                        "remove-me": None,
                        "raw": "3",
                    },
                },
            )
            expected_weekend = {
                "2026-06-06": {
                    "keep": [3],
                    "s1": [1, 2],
                    "raw": 3,
                },
                "legacy": {"untouched": "raw"},
            }
            assert saved_weekend.status_code == 204
            assert json.loads(weekend_path.read_text("utf-8")) == expected_weekend
            assert initializer_calls == [
                {"date_key": "2026-06-06", "extra": expected_extra},
                {"date_key": "2026-06-06", "extra": expected_extra},
                {
                    "date_key": "2026-06-06",
                    "weekend_slots": expected_weekend,
                },
            ]
            assert notification_calls == [
                {"s1", "remove-me", "raw"},
            ]
            assert {args[:2] for args, _kwargs in reconcile_calls} == {
                ("2026-06-06", "s1"),
                ("2026-06-06", "remove-me"),
                ("2026-06-06", "raw"),
            }
            assert all(
                kwargs.get("weekend_slots") == expected_weekend
                for _args, kwargs in reconcile_calls
            )

            future_weekend = client.post(
                "/api/weekend-slots",
                json={"2026-06-07": {"s1": [1]}},
            )
            assert future_weekend.status_code == 204
            assert len(initializer_calls) == 3
            assert json.loads(weekend_path.read_text("utf-8"))[
                "2026-06-07"
            ] == {"s1": [1]}

            save_before_failure = _fingerprint(weekend_path)
            real_save = api_schedule_overrides.save_atomic

            def fail_save(_path, _value, **_kwargs):
                raise OSError("injected schedule save failure")

            api_schedule_overrides.save_atomic = fail_save
            failed_save = client.post(
                "/api/weekend-slots",
                json={"2026-06-06": {"must-not-write": [1]}},
            )
            assert failed_save.status_code == 500
            assert _fingerprint(weekend_path) == save_before_failure
            api_schedule_overrides.save_atomic = real_save

            retry_payload = {
                "date": "2026-06-06",
                "sids": ["s1", "2", "retry-after-commit"],
            }
            initializer_state["failures_remaining"] = 1
            calls_before_retry_case = len(initializer_calls)
            notifications_before_retry_case = len(notification_calls)
            first_attempt = client.patch(
                "/api/extra-attend",
                json=retry_payload,
            )
            expected_retry_extra = json.loads(extra_path.read_text("utf-8"))
            committed_fingerprint = _fingerprint(extra_path)
            assert first_attempt.status_code == 500
            assert expected_retry_extra["2026-06-06"] == [
                "s1",
                "2",
                "retry-after-commit",
            ]
            assert len(initializer_calls) == calls_before_retry_case + 1
            assert len(notification_calls) == notifications_before_retry_case

            identical_retry = client.patch(
                "/api/extra-attend",
                json=retry_payload,
            )
            assert identical_retry.status_code == 200
            assert identical_retry.get_json()["changedDates"] == []
            assert _fingerprint(extra_path) == committed_fingerprint
            assert initializer_calls[-2:] == [
                {
                    "date_key": "2026-06-06",
                    "extra": expected_retry_extra,
                },
                {
                    "date_key": "2026-06-06",
                    "extra": expected_retry_extra,
                },
            ]
            assert notification_calls[-1] == set()

            weekend_retry_payload = {
                "2026-06-06": {"s1": [3]},
            }
            initializer_state["failures_remaining"] = 1
            weekend_calls_before = len(initializer_calls)
            weekend_notifications_before = len(notification_calls)
            weekend_reconcile_before = len(reconcile_calls)
            weekend_first = client.post(
                "/api/weekend-slots",
                json=weekend_retry_payload,
            )
            committed_weekend = json.loads(
                weekend_path.read_text("utf-8")
            )
            assert weekend_first.status_code == 500
            assert committed_weekend["2026-06-06"]["s1"] == [3]
            assert len(initializer_calls) == weekend_calls_before + 1
            assert len(notification_calls) == weekend_notifications_before
            assert len(reconcile_calls) == weekend_reconcile_before

            weekend_identical_retry = client.post(
                "/api/weekend-slots",
                json=weekend_retry_payload,
            )
            assert weekend_identical_retry.status_code == 204
            assert initializer_calls[-2:] == [
                {
                    "date_key": "2026-06-06",
                    "weekend_slots": committed_weekend,
                },
                {
                    "date_key": "2026-06-06",
                    "weekend_slots": committed_weekend,
                },
            ]
            assert notification_calls[-1] == {"s1"}
            assert reconcile_calls[-1][0][:2] == (
                "2026-06-06",
                "s1",
            )
        finally:
            JsonStore.read_data_locked = original["read_data_locked"]
            api_schedule_overrides.EXTRA_PATH = original["EXTRA_PATH"]
            api_schedule_overrides.WEEKEND_SLOTS_PATH = original["WEEKEND_SLOTS_PATH"]
            api_schedule_overrides.STU_PATH = original["STU_PATH"]
            api_schedule_overrides._today_kst_iso = original["today"]
            api_schedule_overrides.enqueue_current_schedule_changes = original["enqueue"]
            api_schedule_overrides.load = original["load"]
            api_schedule_overrides.save_atomic = original["save_atomic"]

    print(
        "schedule override route checks passed: dedicated blueprint, literal store oracle, "
        "date-scoped extra merge, real lock exclusion, post-commit identical retry, "
        "callbacks, hash-identical failures, and strict weekend "
        "body/date/ghost/known-student validation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
