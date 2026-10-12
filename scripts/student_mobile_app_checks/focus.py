"""Temp-only focus-session, privacy, route, and retention checks."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path

from flask import Flask, g, request


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
IMPORT_STATE = {name: name in sys.modules for name in ("app", "core.paths")}

from core.student_app_config import load_student_app_config  # noqa: E402
from core.student_focus_repository import StudentFocusRepository  # noqa: E402
from core.student_focus_rules import KST, event_batch, select_eligibility  # noqa: E402
from routes.api_student_focus import (  # noqa: E402
    StudentFocusApiDependencies,
    create_admin_blueprint,
    create_public_blueprint,
)


MIGRATION = ROOT / "scripts" / "migrations" / "20260809_create_student_focus.sql"


def _check(state: dict[str, int], condition: bool, label: str) -> None:
    state["assertions"] += 1
    if not condition:
        raise AssertionError(label)


def _config(*, enabled: bool = True):
    return load_student_app_config({
        "STUDENT_APP_PUBLIC_ENABLED": "1",
        "STUDENT_APP_FOCUS_ENABLED": "1" if enabled else "0",
        "STUDENT_APP_PUBLIC_HOST": "app.5a-math.com",
        "STUDENT_APP_SESSION_SECURE": "1",
    })


def _schedule(start: float, *, kind: str = "regular", status: str = "scheduled") -> list[dict[str, object]]:
    moment = datetime.fromtimestamp(start, tz=KST)
    return [{
        "kind": kind, "status": status, "date": moment.date().isoformat(),
        "startAt": moment.isoformat(timespec="seconds"), "timeLabel": moment.strftime("%H:%M"), "slots": [2],
    }]


def _app(deps: StudentFocusApiDependencies, *, admin: bool = False) -> Flask:
    app = Flask(__name__)

    @app.before_request
    def inject_public_context():
        g.student_app_public_request = request.headers.get("X-Test-Public", "1") == "1"
        g.student_app_active_sid = request.headers.get("X-Test-Sid", "sid-a")
        g.student_app_csrf_validated = request.headers.get("X-Test-CSRF") == "ok"

    app.register_blueprint(create_public_blueprint(deps))
    if admin:
        app.register_blueprint(create_admin_blueprint(deps, admin_authorizer=lambda value: value == "test-admin"))
    return app


def _new_deps(raw: str, *, now: float, enabled: bool = True, schedule=None):
    state = {"now": now}
    repo = StudentFocusRepository(Path(raw) / "focus.sqlite", clock=lambda: state["now"])
    if enabled:
        repo.apply_migration(MIGRATION.read_text(encoding="utf-8"))
    source = schedule or (lambda _sid, _now: _schedule(now + 30 * 60))
    deps = StudentFocusApiDependencies(
        _config(enabled=enabled), repo, source,
        lambda: {"sid-a": {"name": "학생A", "school": "테스트고", "grade": "1"}},
        lambda: state["now"],
    )
    return deps, repo, state


def _route_happy_path(state: dict[str, int], raw: str) -> None:
    start_at = datetime(2026, 8, 10, 18, 0, tzinfo=KST).timestamp()
    deps, repo, clock = _new_deps(raw, now=start_at - 30 * 60, schedule=lambda _sid, _now: _schedule(start_at))
    app, client = _app(deps, admin=True), None
    client = app.test_client()
    current = client.get("/api/mobile/focus/current", base_url="https://app.5a-math.com").get_json()
    _check(state, current["eligibility"]["state"] == "eligible" and current["session"] is None, "focus did not open exactly 30 minutes early")
    _check(state, set(current["eligibility"]["schedule"]) == {"kind", "date", "startAt", "endAt", "timeLabel", "slots"}, "public schedule whitelist drifted")

    started_response = client.post(
        "/api/mobile/focus/start", json={}, headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com",
    )
    started = started_response.get_json()
    focus_id = started["session"]["id"]
    _check(state, started_response.status_code == 201 and started["session"]["visibility"] == "visible", "focus start contract drifted")
    resumed = client.post("/api/mobile/focus/start", json={}, headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com")
    _check(state, resumed.status_code == 200 and resumed.get_json()["resumed"] is True, "idempotent focus start did not resume")

    clock["now"] += 10 * 60
    hidden = client.post(
        "/api/mobile/focus/events", json={"sessionId": focus_id, "events": [{"seq": 1, "type": "hidden"}]},
        headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com",
    )
    _check(state, hidden.status_code == 200, "visible-to-hidden transition failed")
    clock["now"] += 2 * 60
    visible = client.post(
        "/api/mobile/focus/events", json={"sessionId": focus_id, "events": [{"seq": 2, "type": "visible"}]},
        headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com",
    )
    _check(state, visible.status_code == 200, "hidden-to-visible transition failed")
    clock["now"] += 8 * 60
    ended = client.post(
        "/api/mobile/focus/end", json={"sessionId": focus_id, "seq": 3},
        headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com",
    ).get_json()["session"]
    _check(state, ended["focusMs"] == 1_080_000 and ended["hiddenCount"] == 1, "focus/hidden aggregate drifted")
    _check(state, ended["hiddenMs"] == ended["longestHiddenMs"] == 120_000, "hidden duration aggregate drifted")
    _check(state, ended["unknownMs"] == 0 and ended["state"] == "finished", "normal focus session became unknown")

    second_schedule = select_eligibility(_schedule(start_at), sid="sid-b", now=clock["now"])["schedule"]
    second_row, _ = repo.start("sid-b", second_schedule, now=clock["now"])
    repo.end("sid-b", second_row["id"], 1, now=clock["now"])

    admin = client.get(
        "/api/admin/student-focus/summary?date=2026-08-10",
        headers={"Authorization": "test-admin", "X-Test-Public": "0"},
        base_url="http://127.0.0.1",
    )
    admin_classes = admin.get_json()["classes"]
    admin_session = admin_classes[0]["sessions"][0]
    _check(state, len(admin_classes) == 1 and len(admin_classes[0]["sessions"]) == 2, "same class window was split by student SID")
    _check(state, admin_classes[0]["classId"].startswith("fcl_") and "sid" not in admin_classes[0]["classId"], "admin class ID is not opaque")
    _check(state, admin.status_code == 200 and admin_session["focusMs"] == ended["focusMs"], "student/admin focus totals differ")
    _check(state, admin_session["hiddenMs"] == ended["hiddenMs"] and "id" not in admin_session, "admin summary leaked a session ID or changed totals")

    foreign = client.post(
        "/api/mobile/focus/events", json={"sessionId": focus_id, "events": [{"seq": 4, "type": "hidden"}]},
        headers={"X-Test-CSRF": "ok", "X-Test-Sid": "sid-b"}, base_url="https://app.5a-math.com",
    )
    _check(state, foreign.status_code == 404 and foreign.get_json()["code"] == "focus_session_not_found", "cross-SID focus lookup did not fail closed")
    after = repo.current_for_sid("sid-a")
    _check(state, after is not None and after["last_seq"] == 3, "cross-SID request mutated the focus session")
    public_dump = json.dumps(started, ensure_ascii=False)
    _check(state, all(word not in public_dump for word in ("sid-a", "scheduleKey", "token", "csrf", "appName", "url")), "public focus response leaked authority/privacy fields")


def _negative_and_cleanup(state: dict[str, int], raw: str) -> None:
    start_at = datetime(2026, 8, 11, 18, 0, tzinfo=KST).timestamp()
    too_early = select_eligibility(_schedule(start_at), sid="sid-a", now=start_at - 1801)
    exact_open = select_eligibility(_schedule(start_at), sid="sid-a", now=start_at - 1800)
    exact_close = select_eligibility(_schedule(start_at), sid="sid-a", now=start_at + 7200)
    cancelled = select_eligibility(_schedule(start_at, kind="absence", status="cancelled"), sid="sid-a", now=start_at)
    _check(state, too_early["state"] == "upcoming" and exact_open["state"] == "eligible", "focus early-start boundary drifted")
    _check(state, exact_close["state"] == "unavailable" and cancelled["state"] == "unavailable", "focus close/absence boundary drifted")
    try:
        event_batch([{"seq": index + 1, "type": "hidden" if index % 2 == 0 else "visible"} for index in range(51)])
    except Exception as exc:
        _check(state, getattr(exc, "code", "") == "focus_event_limit", "51-event batch returned the wrong failure")
    else:
        _check(state, False, "51-event batch was accepted")

    deps, repo, clock = _new_deps(raw, now=start_at, schedule=lambda _sid, _now: _schedule(start_at))
    client = _app(deps).test_client()
    started = client.post("/api/mobile/focus/start", json={}, headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com").get_json()
    focus_id = started["session"]["id"]
    privacy = client.post(
        "/api/mobile/focus/events",
        json={"sessionId": focus_id, "events": [{"seq": 1, "type": "hidden", "url": "forbidden"}]},
        headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com",
    )
    _check(state, privacy.status_code == 400, "focus event accepted a browsing URL")
    gap = client.post(
        "/api/mobile/focus/events", json={"sessionId": focus_id, "events": [{"seq": 2, "type": "hidden"}]},
        headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com",
    )
    _check(state, gap.status_code == 409 and gap.get_json()["code"] == "focus_sequence_conflict", "focus sequence gap was accepted")

    def append_same_seq():
        try:
            StudentFocusRepository(repo.db_path, clock=lambda: clock["now"]).append_events(
                "sid-a", focus_id, [{"seq": 1, "type": "hidden"}], now=clock["now"],
            )
            return "ok"
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK
            return getattr(exc, "code", "error")

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(lambda _: append_same_seq(), range(2)))
    _check(state, outcomes == ["focus_sequence_conflict", "ok"], "concurrent same-seq transition was not atomic")
    closed = client.post(
        "/api/mobile/focus/end", json={"sessionId": focus_id, "seq": 2},
        headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com",
    )
    _check(state, closed.status_code == 200, "focus session did not close after concurrent transition")
    post_end = client.post(
        "/api/mobile/focus/events", json={"sessionId": focus_id, "events": [{"seq": 3, "type": "visible"}]},
        headers={"X-Test-CSRF": "ok"}, base_url="https://app.5a-math.com",
    )
    _check(state, post_end.status_code == 409, "post-end focus event was accepted")

    with closing(sqlite3.connect(repo.db_path)) as db:
        db.execute("UPDATE student_focus_events SET server_at=1")
        db.commit()
    result = repo.cleanup(now=start_at + 40 * 86400, raw_before=start_at + 10 * 86400, limit=500)
    _check(state, result["eventsDeleted"] == 2 and repo.current_for_sid("sid-a") is not None, "raw retention removed the aggregate session")

    late_repo = StudentFocusRepository(Path(raw) / "late.sqlite", clock=lambda: start_at)
    late_repo.apply_migration(MIGRATION.read_text(encoding="utf-8"))
    late_schedule = select_eligibility(_schedule(start_at), sid="sid-late", now=start_at)["schedule"]
    late_row, _ = late_repo.start("sid-late", late_schedule, now=start_at)
    late_end = late_repo.end("sid-late", late_row["id"], 1, now=start_at + 3 * 60 * 60)
    late_summary = late_repo.summary(late_end, now=start_at + 3 * 60 * 60)
    _check(state, late_summary["state"] == "unknown" and late_summary["focusMs"] == 0, "late end was counted as confirmed focus")
    _check(state, late_summary["unknownMs"] == 7_200_000, "late end did not preserve the unknown class interval")


def _gates_and_default_off(state: dict[str, int], raw: str) -> None:
    missing = Path(raw) / "disabled.sqlite"
    deps, _repo, _clock = _new_deps(raw, now=1_786_400_000, enabled=False)
    deps.repository = StudentFocusRepository(missing)
    app, client = _app(deps, admin=True), None
    client = app.test_client()
    disabled = client.get("/api/mobile/focus/current", base_url="https://app.5a-math.com")
    _check(state, disabled.status_code == 404 and disabled.data == b"" and not missing.exists(), "focus flag OFF created/opened a database")
    admin_disabled = client.get("/api/admin/student-focus/summary?date=2026-08-11", base_url="http://127.0.0.1")
    _check(state, admin_disabled.status_code == 404 and admin_disabled.data == b"", "disabled admin focus route was not hidden")

    enabled_deps, _enabled_repo, _ = _new_deps(str(Path(raw) / "gates"), now=1_786_400_000)
    gates = _app(enabled_deps, admin=True).test_client()
    public_admin = gates.get(
        "/api/admin/student-focus/summary?date=2026-08-11",
        headers={"Authorization": "test-admin"}, base_url="https://app.5a-math.com",
    )
    _check(state, public_admin.status_code == 404 and public_admin.data == b"", "public host exposed admin focus summaries")
    outside = gates.get(
        "/api/admin/student-focus/summary?date=2026-08-11",
        headers={"Authorization": "test-admin", "X-Test-Public": "0"},
        base_url="http://academy.local", environ_overrides={"REMOTE_ADDR": "198.51.100.9"},
    )
    _check(state, outside.status_code == 403, "off-network admin focus summary was allowed")
    challenge = gates.get(
        "/api/admin/student-focus/summary?date=2026-08-11",
        headers={"X-Test-Public": "0"}, base_url="http://127.0.0.1",
    )
    _check(state, challenge.status_code == 401 and "Basic" in challenge.headers.get("WWW-Authenticate", ""), "admin focus auth challenge drifted")
    no_csrf = gates.post("/api/mobile/focus/start", json={}, base_url="https://app.5a-math.com")
    _check(state, no_csrf.status_code == 403, "focus start accepted a missing CSRF validation")


def run_checks() -> dict[str, object]:
    state = {"assertions": 0}
    with tempfile.TemporaryDirectory(prefix="student-focus-check-") as raw:
        _route_happy_path(state, str(Path(raw) / "happy"))
        _negative_and_cleanup(state, str(Path(raw) / "negative"))
        _gates_and_default_off(state, str(Path(raw) / "off"))
        db_bytes = b"".join(path.read_bytes() for path in Path(raw).rglob("*.sqlite"))
        _check(state, all(token not in db_bytes for token in (b"appName", b"notification", b"endpoint", b"csrf", b"http://", b"https://")), "focus SQLite contains forbidden privacy fields")
    _check(state, IMPORT_STATE == {name: name in sys.modules for name in IMPORT_STATE}, "focus checks imported app or core.paths")
    return {"name": "focus", "assertions": state["assertions"], "passed": True, "runtimeIsolation": "temporary SQLite and injected Flask fixtures only"}


if __name__ == "__main__":
    result = run_checks()
    print(f"focus checks passed: {result['assertions']} assertions")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


__all__ = ("run_checks",)
