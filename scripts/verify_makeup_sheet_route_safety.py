from __future__ import annotations

import copy
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes.api_makeup_carryover as route


def snapshot(candidates: list[dict]) -> dict:
    return {
        "month": "2026-08",
        "matchedRows": 1,
        "sheetStudentCount": 1,
        "maxSheetRow": 127,
        "candidates": candidates,
    }


def run_route_case(*, candidates: list[dict], fail_transaction: bool) -> tuple:
    with tempfile.TemporaryDirectory(prefix="verify-makeup-sheet-route-") as tmpdir:
        base = Path(tmpdir)
        carryover_path = base / "makeup_carryover.json"
        absence_path = base / "absent.json"
        initial_carryover = {"by_absence": {}, "manual": {}}
        initial_absent = {"by_date": {}, "by_student": {}, "by_slot": {}}
        carryover_path.write_text(json.dumps(initial_carryover), encoding="utf-8")
        absence_path.write_text(json.dumps(initial_absent), encoding="utf-8")
        notifications: list[list[str]] = []
        commits: list[dict] = []

        originals = {
            "MAKEUP_CARRYOVER_PATH": route.MAKEUP_CARRYOVER_PATH,
            "ABS_PATH": route.ABS_PATH,
            "read": route.read_additive_sheet_candidates,
            "load_absent": route.load_absent,
            "enqueue": route.enqueue_current_schedule_changes,
            "scope": route.absence_write_scope,
            "commit": route.commit_new_absences_locked,
        }
        route.MAKEUP_CARRYOVER_PATH = carryover_path
        route.ABS_PATH = absence_path
        route.read_additive_sheet_candidates = lambda _url, _date: snapshot(candidates)
        route.load_absent = lambda: copy.deepcopy(initial_absent)
        route.enqueue_current_schedule_changes = lambda sids: notifications.append(list(sids))

        @contextmanager
        def fake_scope(**kwargs):
            assert kwargs["absent_path"] == absence_path
            assert kwargs["carryover_path"] == carryover_path
            yield base / "journal"

        def fake_commit(pairs, **kwargs):
            commits.append({
                "pairs": set(pairs),
                "absentAfter": copy.deepcopy(kwargs["absent_after"]),
                "carryoverAfter": copy.deepcopy(kwargs["carryover_after"]),
                "kind": kwargs["kind"],
            })
            if fail_transaction:
                raise OSError("synthetic atomic transaction failure")
            carryover_path.write_text(
                json.dumps(kwargs["carryover_after"]),
                encoding="utf-8",
            )
            absence_path.write_text(
                json.dumps(kwargs["absent_after"]),
                encoding="utf-8",
            )

        route.absence_write_scope = fake_scope
        route.commit_new_absences_locked = fake_commit
        try:
            app = Flask("verify-makeup-sheet-route")
            app.register_blueprint(route.bp_api_makeup_carryover)
            client = app.test_client()
            response = client.post(
                "/api/makeup-sheet-sync",
                json={"sheetUrl": "https://docs.google.com/spreadsheets/d/test/edit", "date": "2026-08-23"},
            )
            stored_carryover = json.loads(carryover_path.read_text("utf-8"))
            stored_absent = json.loads(absence_path.read_text("utf-8"))
            return response, stored_carryover, stored_absent, notifications, commits
        finally:
            route.MAKEUP_CARRYOVER_PATH = originals["MAKEUP_CARRYOVER_PATH"]
            route.ABS_PATH = originals["ABS_PATH"]
            route.read_additive_sheet_candidates = originals["read"]
            route.load_absent = originals["load_absent"]
            route.enqueue_current_schedule_changes = originals["enqueue"]
            route.absence_write_scope = originals["scope"]
            route.commit_new_absences_locked = originals["commit"]


def test_noop_route_writes_nothing() -> None:
    response, stored_carryover, stored_absent, notifications, commits = run_route_case(
        candidates=[],
        fail_transaction=False,
    )
    assert response.status_code == 200
    assert response.get_json()["added"] == 0
    assert stored_carryover == {"by_absence": {}, "manual": {}}
    assert stored_absent == {"by_date": {}, "by_student": {}, "by_slot": {}}
    assert notifications == []
    assert commits == []


def test_transaction_failure_leaves_route_state_unchanged() -> None:
    response, stored_carryover, stored_absent, notifications, commits = run_route_case(
        candidates=[{"date": "2026-08-20", "sid": "sid-new", "slot": 1, "cell": "*"}],
        fail_transaction=True,
    )
    assert response.status_code == 500
    assert stored_carryover == {"by_absence": {}, "manual": {}}
    assert stored_absent == {"by_date": {}, "by_student": {}, "by_slot": {}}
    assert notifications == []
    assert commits[0]["pairs"] == {("2026-08-20", "sid-new")}
    assert commits[0]["kind"] == "makeup-sheet-api"


def test_success_notifies_only_after_atomic_commit() -> None:
    response, stored_carryover, stored_absent, notifications, commits = run_route_case(
        candidates=[{"date": "2026-08-20", "sid": "sid-new", "slot": 1, "cell": "*"}],
        fail_transaction=False,
    )
    assert response.status_code == 200
    assert response.get_json()["added"] == 1
    assert stored_carryover == commits[0]["carryoverAfter"]
    assert stored_absent == commits[0]["absentAfter"]
    assert notifications == [["sid-new"]]


def main() -> int:
    test_noop_route_writes_nothing()
    test_transaction_failure_leaves_route_state_unchanged()
    test_success_notifies_only_after_atomic_commit()
    print("makeup sheet route atomic transaction checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
