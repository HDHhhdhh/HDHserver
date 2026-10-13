from __future__ import annotations

import copy
from contextlib import contextmanager
import datetime as dt
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
        "months": [
            {"month": "2026-07", "candidateCount": 0},
            {"month": "2026-08", "candidateCount": len(candidates)},
        ],
        "monthErrors": [],
        "matchedRows": 1,
        "sheetStudentCount": 1,
        "maxSheetRow": 127,
        "unmatchedStarredRows": 0,
        "ambiguousStarredRows": 0,
        "unmatchedStarredDetails": [],
        "candidates": candidates,
    }


def run_route_case(
    *,
    candidates: list[dict],
    fail_transaction: bool,
    configured_sheet_url: str = "",
    excluded_candidates: list[dict] | None = None,
) -> tuple:
    with tempfile.TemporaryDirectory(prefix="verify-makeup-sheet-route-") as tmpdir:
        base = Path(tmpdir)
        carryover_path = base / "makeup_carryover.json"
        absence_path = base / "absent.json"
        config_path = base / "makeup_sheet_sync.json"
        config = {}
        if configured_sheet_url:
            config["sheetUrl"] = configured_sheet_url
        if excluded_candidates:
            config["excludedCandidates"] = excluded_candidates
        if config:
            config_path.write_text(json.dumps(config), encoding="utf-8")
        initial_carryover = {"by_absence": {}, "manual": {}}
        initial_absent = {"by_date": {}, "by_student": {}, "by_slot": {}}
        carryover_path.write_text(json.dumps(initial_carryover), encoding="utf-8")
        absence_path.write_text(json.dumps(initial_absent), encoding="utf-8")
        notifications: list[list[str]] = []
        commits: list[dict] = []
        reads: list[dict] = []

        originals = {
            "MAKEUP_CARRYOVER_PATH": route.MAKEUP_CARRYOVER_PATH,
            "MAKEUP_SHEET_SYNC_CONFIG_PATH": route.MAKEUP_SHEET_SYNC_CONFIG_PATH,
            "ABS_PATH": route.ABS_PATH,
            "read": route.read_additive_sheet_candidate_window,
            "load_absent": route.load_absent,
            "enqueue": route.enqueue_current_schedule_changes,
            "scope": route.absence_write_scope,
            "commit": route.commit_new_absences_locked,
        }
        route.MAKEUP_CARRYOVER_PATH = carryover_path
        route.MAKEUP_SHEET_SYNC_CONFIG_PATH = config_path
        route.ABS_PATH = absence_path

        def fake_read(url, date, *, months_back=1):
            reads.append({"url": url, "date": date, "monthsBack": months_back})
            return snapshot(candidates)

        route.read_additive_sheet_candidate_window = fake_read
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
            return response, stored_carryover, stored_absent, notifications, commits, reads
        finally:
            route.MAKEUP_CARRYOVER_PATH = originals["MAKEUP_CARRYOVER_PATH"]
            route.MAKEUP_SHEET_SYNC_CONFIG_PATH = originals["MAKEUP_SHEET_SYNC_CONFIG_PATH"]
            route.ABS_PATH = originals["ABS_PATH"]
            route.read_additive_sheet_candidate_window = originals["read"]
            route.load_absent = originals["load_absent"]
            route.enqueue_current_schedule_changes = originals["enqueue"]
            route.absence_write_scope = originals["scope"]
            route.commit_new_absences_locked = originals["commit"]


def test_noop_route_writes_nothing() -> None:
    response, stored_carryover, stored_absent, notifications, commits, reads = run_route_case(
        candidates=[],
        fail_transaction=False,
    )
    assert response.status_code == 200
    assert response.get_json()["added"] == 0
    assert stored_carryover == {"by_absence": {}, "manual": {}}
    assert stored_absent == {"by_date": {}, "by_student": {}, "by_slot": {}}
    assert notifications == []
    assert commits == []
    assert reads == [{
        "url": "https://docs.google.com/spreadsheets/d/test/edit",
        "date": "2026-08-23",
        "monthsBack": 1,
    }]


def test_transaction_failure_leaves_route_state_unchanged() -> None:
    response, stored_carryover, stored_absent, notifications, commits, reads = run_route_case(
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
    response, stored_carryover, stored_absent, notifications, commits, reads = run_route_case(
        candidates=[{"date": "2026-08-20", "sid": "sid-new", "slot": 1, "cell": "*"}],
        fail_transaction=False,
    )
    assert response.status_code == 200
    assert response.get_json()["added"] == 1
    assert stored_carryover == commits[0]["carryoverAfter"]
    assert stored_absent == commits[0]["absentAfter"]
    assert notifications == [["sid-new"]]


def test_server_config_url_is_authoritative() -> None:
    configured = "https://docs.google.com/spreadsheets/d/server-config/edit?gid=0"
    response, _carryover, _absent, _notifications, _commits, reads = run_route_case(
        candidates=[],
        fail_transaction=False,
        configured_sheet_url=configured,
    )
    assert response.status_code == 200
    assert response.get_json()["sheetSource"] == "server-config"
    assert reads == [{"url": configured, "date": "2026-08-23", "monthsBack": 1}]

def test_configured_candidate_exclusion_is_date_scoped() -> None:
    response, _carryover, _absent, notifications, commits, _reads = run_route_case(
        candidates=[
            {"date": "2026-08-19", "sid": "sid-excluded", "slot": 2, "cell": "*"},
            {"date": "2026-08-20", "sid": "sid-included", "slot": 1, "cell": "*"},
        ],
        fail_transaction=False,
        excluded_candidates=[{"date": "2026-08-19", "sid": "sid-excluded"}],
    )
    assert response.status_code == 200
    assert response.get_json()["excludedCount"] == 1
    assert commits[0]["pairs"] == {("2026-08-20", "sid-included")}
    assert notifications == [["sid-included"]]


def test_sync_date_rejects_far_future_year_inference() -> None:
    today = dt.date(2026, 8, 24)
    assert route._sheet_sync_date("2026-07-01", today=today) == "2026-07-01"
    try:
        route._sheet_sync_date("2099-01-15", today=today)
    except RuntimeError as exc:
        assert "운영 범위" in str(exc)
    else:
        raise AssertionError("far-future sheet year inference must be rejected")

def test_config_endpoint_preserves_unknown_fields() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-makeup-sheet-config-") as tmpdir:
        config_path = Path(tmpdir) / "makeup_sheet_sync.json"
        initial = {
            "enabled": True,
            "sheetUrl": "https://docs.google.com/spreadsheets/d/old-sheet/edit?gid=0",
            "unknown": {"keep": True},
        }
        config_path.write_text(json.dumps(initial), encoding="utf-8")
        original = route.MAKEUP_SHEET_SYNC_CONFIG_PATH
        route.MAKEUP_SHEET_SYNC_CONFIG_PATH = config_path
        try:
            app = Flask("verify-makeup-sheet-config")
            app.register_blueprint(route.bp_api_makeup_carryover)
            client = app.test_client()
            before = client.get("/api/makeup-sheet-sync/config")
            assert before.status_code == 200
            assert before.get_json()["sheetUrl"] == initial["sheetUrl"]

            next_url = "https://docs.google.com/spreadsheets/d/new-sheet/edit?gid=7"
            saved = client.post("/api/makeup-sheet-sync/config", json={"sheetUrl": next_url})
            assert saved.status_code == 200
            assert saved.get_json()["sheetUrl"] == next_url
            stored = json.loads(config_path.read_text("utf-8"))
            assert stored["sheetUrl"] == next_url
            assert stored["enabled"] is True
            assert stored["unknown"] == {"keep": True}

            snapshot = config_path.read_bytes()
            invalid = client.post("/api/makeup-sheet-sync/config", json={"sheetUrl": "https://example.com/not-sheet"})
            assert invalid.status_code == 400
            assert config_path.read_bytes() == snapshot
        finally:
            route.MAKEUP_SHEET_SYNC_CONFIG_PATH = original


def test_sheet_read_failure_is_returned_as_actionable_json() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-makeup-sheet-error-") as tmpdir:
        config_path = Path(tmpdir) / "makeup_sheet_sync.json"
        config_path.write_text(
            json.dumps({
                "sheetUrl": "https://docs.google.com/spreadsheets/d/private-sheet/edit?gid=0",
            }),
            encoding="utf-8",
        )
        original_config = route.MAKEUP_SHEET_SYNC_CONFIG_PATH
        original_read = route.read_additive_sheet_candidate_window
        route.MAKEUP_SHEET_SYNC_CONFIG_PATH = config_path
        route.read_additive_sheet_candidate_window = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "현재 시트는 서버에서 읽을 수 없는 '제한됨' 상태입니다. "
                "Google Sheets 공유의 일반 액세스를 '링크가 있는 모든 사용자 - 뷰어'로 "
                "바꾼 뒤 다시 시도해주세요. 웹에 게시할 필요는 없습니다."
            )
        )
        try:
            app = Flask("verify-makeup-sheet-json-error")
            app.register_blueprint(route.bp_api_makeup_carryover)
            response = app.test_client().post(
                "/api/makeup-sheet-sync",
                json={"date": "2026-08-23"},
            )
            payload = response.get_json()
            assert response.status_code == 400
            assert response.headers["Cache-Control"] == "no-store"
            assert payload["ok"] is False
            assert payload["error"] == "sheet_read_failed"
            assert "링크가 있는 모든 사용자 - 뷰어" in payload["message"]
            assert "웹에 게시할 필요는 없습니다" in payload["message"]
        finally:
            route.MAKEUP_SHEET_SYNC_CONFIG_PATH = original_config
            route.read_additive_sheet_candidate_window = original_read

def main() -> int:
    test_noop_route_writes_nothing()
    test_transaction_failure_leaves_route_state_unchanged()
    test_success_notifies_only_after_atomic_commit()
    test_server_config_url_is_authoritative()
    test_configured_candidate_exclusion_is_date_scoped()
    test_sync_date_rejects_far_future_year_inference()
    test_config_endpoint_preserves_unknown_fields()
    test_sheet_read_failure_is_returned_as_actionable_json()
    print("makeup sheet route atomic transaction checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
