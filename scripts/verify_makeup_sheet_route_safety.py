from __future__ import annotations

import copy
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


def run_route_case(*, candidates: list[dict], fail_carryover_save: bool) -> tuple:
    with tempfile.TemporaryDirectory(prefix="verify-makeup-sheet-route-") as tmpdir:
        base = Path(tmpdir)
        carryover_path = base / "makeup_carryover.json"
        absence_lock_path = base / "absent.json"
        initial_carryover = {"by_absence": {}, "manual": {}}
        initial_absent = {"by_date": {}, "by_student": {}, "by_slot": {}}
        carryover_path.write_text(json.dumps(initial_carryover), encoding="utf-8")
        absence_lock_path.write_text(json.dumps(initial_absent), encoding="utf-8")
        saves: list[dict] = []
        notifications: list[list[str]] = []
        cleared_pairs: list[set[tuple[str, str]]] = []

        originals = {
            "MAKEUP_CARRYOVER_PATH": route.MAKEUP_CARRYOVER_PATH,
            "ABS_PATH": route.ABS_PATH,
            "read": route.read_additive_sheet_candidates,
            "load_absent": route.load_absent,
            "save_absent": route.save_absent,
            "save_atomic": route.save_atomic,
            "enqueue": route.enqueue_current_schedule_changes,
            "clear": route._clear_assignments_for_new_absences,
        }
        route.MAKEUP_CARRYOVER_PATH = carryover_path
        route.ABS_PATH = absence_lock_path
        route.read_additive_sheet_candidates = lambda _url, _date: snapshot(candidates)
        route.load_absent = lambda: copy.deepcopy(initial_absent)
        route.save_absent = lambda value, locked=False: saves.append(copy.deepcopy(value))
        route.enqueue_current_schedule_changes = lambda sids: notifications.append(list(sids))
        route._clear_assignments_for_new_absences = lambda pairs: cleared_pairs.append(set(pairs))

        def save_carryover(path: Path, value: dict) -> None:
            if fail_carryover_save:
                raise OSError("synthetic carryover save failure")
            path.write_text(json.dumps(value), encoding="utf-8")

        route.save_atomic = save_carryover
        try:
            app = Flask("verify-makeup-sheet-route")
            app.register_blueprint(route.bp_api_makeup_carryover)
            client = app.test_client()
            response = client.post(
                "/api/makeup-sheet-sync",
                json={"sheetUrl": "https://docs.google.com/spreadsheets/d/test/edit", "date": "2026-08-23"},
            )
            stored = json.loads(carryover_path.read_text("utf-8"))
            return response, stored, saves, notifications, cleared_pairs, initial_absent
        finally:
            route.MAKEUP_CARRYOVER_PATH = originals["MAKEUP_CARRYOVER_PATH"]
            route.ABS_PATH = originals["ABS_PATH"]
            route.read_additive_sheet_candidates = originals["read"]
            route.load_absent = originals["load_absent"]
            route.save_absent = originals["save_absent"]
            route.save_atomic = originals["save_atomic"]
            route.enqueue_current_schedule_changes = originals["enqueue"]
            route._clear_assignments_for_new_absences = originals["clear"]


def test_noop_route_writes_nothing() -> None:
    response, stored, saves, notifications, cleared_pairs, _initial_absent = run_route_case(
        candidates=[],
        fail_carryover_save=False,
    )
    assert response.status_code == 200
    assert response.get_json()["added"] == 0
    assert stored == {"by_absence": {}, "manual": {}}
    assert saves == []
    assert notifications == []
    assert cleared_pairs == []


def test_carryover_failure_rolls_absence_back() -> None:
    response, stored, saves, notifications, cleared_pairs, initial_absent = run_route_case(
        candidates=[{"date": "2026-08-20", "sid": "sid-new", "slot": 1, "cell": "*"}],
        fail_carryover_save=True,
    )
    assert response.status_code == 500
    assert stored == {"by_absence": {}, "manual": {}}
    assert len(saves) == 2
    assert saves[0] != initial_absent
    assert saves[1] == initial_absent
    assert notifications == []
    assert cleared_pairs == [{("2026-08-20", "sid-new")}]


def main() -> int:
    test_noop_route_writes_nothing()
    test_carryover_failure_rolls_absence_back()
    print("makeup sheet route transaction safety checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
