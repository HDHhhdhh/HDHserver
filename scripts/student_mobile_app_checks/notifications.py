"""Temp-only checks for generic student notification core contracts."""

from __future__ import annotations

import ast
import datetime as dt
import json
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_notification_events import (
    CATEGORIES,
    EVENT_TYPES,
    NotificationInputError,
    build_event_payload,
    deterministic_event_id,
    milestones_crossed,
)
from core.student_notification_outbox import NotificationConflictError, NotificationNotInitializedError
from core.student_notification_repository import StudentNotificationRepository
from core.student_notification_hooks import (
    enqueue_current_schedule_changes,
    enqueue_homework_events,
    enqueue_progress_milestones,
    schedule_snapshot_event_id,
    student_schedule_changed_sids,
)
from core.student_reminder_projection import KST, build_reminder_candidates
from core.student_account_repository import StudentAccountRepository
from core.student_app_config import load_student_app_config
from core.student_homework_repository import StudentHomeworkRepository
from core.student_notification_authority import FileNotificationAuthority
from core.student_push_repository import StudentPushRepository
from core.student_schedule_projection import project_student_schedule
from core.student_sessions import StudentSessionRepository
from core.student_push_sender import PushResultStatus, PushSendResult
from routes.api_student_homework import _add_notification_event_ids
from routes.api_student_push import StudentPushApiDependencies, create_blueprint, enqueue_announcement
from scripts.deliver_student_notification_outbox import run_once as run_delivery
from scripts.enqueue_student_reminders import run_once as run_scanner


MIGRATION = ROOT / "scripts" / "migrations" / "20260809_create_student_notifications.sql"
HOMEWORK_MIGRATION = ROOT / "scripts" / "migrations" / "20260809_create_student_homework.sql"


def _check(state: list[int], condition: bool, label: str) -> None:
    state[0] += 1
    if not condition:
        raise AssertionError(label)


def _migrate(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(MIGRATION.read_text(encoding="utf-8"))


def _count(path: Path, table: str, where: str = "", params: tuple = ()) -> int:
    with closing(sqlite3.connect(path)) as db:
        return int(db.execute(f"SELECT COUNT(*) FROM {table}{where}", params).fetchone()[0])


def _row(path: Path, sql: str, params: tuple = ()):
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql, params).fetchone()


def _event_contract(state: list[int]) -> None:
    _check(state, CATEGORIES == {"schedule", "homework", "progress", "announcement"}, "category wire set changed")
    _check(state, EVENT_TYPES == {
        "class_reminder", "schedule_changed", "homework_assigned", "homework_due",
        "progress_milestone", "announcement_published",
    }, "event type wire set changed")
    marker = "student-private-marker"
    first = deterministic_event_id("homework_due", marker, "2026-08-10T09:00:00+09:00")
    _check(state, first == deterministic_event_id("homework_due", marker, "2026-08-10T09:00:00+09:00"), "event ID is not deterministic")
    _check(state, first != deterministic_event_id("homework_due", marker, "2026-08-11T09:00:00+09:00") and marker not in first, "event ID is not opaque")
    expected_urls = {
        "class_reminder": "/app?view=home", "schedule_changed": "/app?view=home",
        "progress_milestone": "/app?view=home",
        "homework_assigned": f"/app?view=homework&item={first}",
        "homework_due": f"/app?view=homework&item={first}",
        "announcement_published": f"/app?view=board&item={first}",
    }
    for event_type, url in expected_urls.items():
        payload = build_event_payload(event_type, first)
        _check(state, set(payload) == {"type", "eventId", "url"} and payload == {
            "type": event_type, "eventId": first, "url": url,
        }, f"payload contract changed for {event_type}")
    _check(state, milestones_crossed(24, 100) == (25, 50, 75, 100), "milestone crossing lost thresholds")
    _check(state, milestones_crossed(50, 50) == () and milestones_crossed(75, 25) == (), "milestone crossing repeated or regressed")
    try:
        build_event_payload("unknown", first)
    except NotificationInputError:
        pass
    else:
        raise AssertionError("unknown event type was accepted")
    projected = [
        {"id": "hw_abcdefghijklmnop", "dueAt": "2026-08-10T18:00:00+09:00", "legacy": False},
        {"id": "hw_legacy_abcdefghijkl", "dueAt": None, "legacy": True},
    ]
    _add_notification_event_ids(projected)
    _check(state, projected[0]["notificationEventIds"] == [
        deterministic_event_id("homework_assigned", projected[0]["id"]),
        deterministic_event_id("homework_due", projected[0]["id"], projected[0]["dueAt"]),
    ] and projected[1]["notificationEventIds"] == []
           and all(projected[0]["id"] not in value for value in projected[0]["notificationEventIds"]),
           "homework notification aliases are missing, reversible, or attached to legacy rows")


def _schema_and_preferences(root: Path, state: list[int]) -> None:
    missing = root / "missing.sqlite"
    repository = StudentNotificationRepository(missing, clock=lambda: 1000.0)
    _check(state, not missing.exists() and repository.schema_ready() is False and not missing.exists(), "constructor/readiness created SQLite")
    try:
        repository.get_preferences("aid-a")
    except NotificationNotInitializedError as exc:
        _check(state, exc.code == "notification_not_initialized" and not missing.exists(), "missing schema error is not typed or created DB")
    else:
        raise AssertionError("missing schema did not fail")

    partial = root / "partial.sqlite"
    with closing(sqlite3.connect(partial)):
        pass
    repository = StudentNotificationRepository(partial)
    _check(state, repository.schema_ready() is False and not Path(str(partial) + "-wal").exists(), "partial schema mutated or passed")

    path = root / "preferences.sqlite"
    _migrate(path)
    _migrate(path)
    repository = StudentNotificationRepository(path, clock=lambda: 1000.0)
    expected_tables = {
        "student_notification_preferences", "student_notification_events",
        "student_notification_milestones", "student_notification_deliveries",
        "student_notification_schedule_state",
    }
    with closing(sqlite3.connect(path)) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    _check(state, repository.schema_ready() and expected_tables <= names, "explicit migration schema is incomplete")
    default = repository.get_preferences("aid-a")
    _check(state, default == {"categories": {name: True for name in sorted(CATEGORIES)}, "revision": 0, "updatedAt": None}, "default preference snapshot changed")
    _check(state, _count(path, "student_notification_preferences") == 0, "default preference GET wrote a row")
    _check(state, not Path(str(path) + "-wal").exists() and not Path(str(path) + "-shm").exists(), "preference GET created WAL sidecars")
    selected = {"schedule": False, "homework": True, "progress": False, "announcement": True}
    first = repository.update_preferences("aid-a", selected, expected_revision=0)
    _check(state, first["categories"] == selected and first["revision"] == 1 and first["updatedAt"] == 1000.0, "preference create failed")
    try:
        repository.update_preferences("aid-a", selected, expected_revision=0)
    except NotificationConflictError as exc:
        _check(state, exc.code == "preference_revision_conflict", "stale preference conflict code changed")
    else:
        raise AssertionError("stale preference update succeeded")
    repository.update_preferences("aid-a", {name: True for name in CATEGORIES}, expected_revision=1, now=1001.0)

    def update_one(disable: str) -> str:
        snapshot = {name: name != disable for name in CATEGORIES}
        try:
            repository.update_preferences("aid-a", snapshot, expected_revision=2, now=1002.0)
            return "saved"
        except NotificationConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(update_one, ("schedule", "homework")))
    _check(state, outcomes == ["conflict", "saved"] and repository.get_preferences("aid-a")["revision"] == 3, "parallel preference CAS was not atomic")
    _check(state, _count(path, "student_notification_preferences") == 1, "preference CAS duplicated aid row")
    try:
        repository.update_preferences("aid-a", {"schedule": True}, expected_revision=3)
    except NotificationInputError:
        pass
    else:
        raise AssertionError("partial preference snapshot was accepted")


def _outbox(root: Path, state: list[int]) -> None:
    path = root / "outbox.sqlite"
    _migrate(path)
    now = [2000.0]
    repository = StudentNotificationRepository(path, clock=lambda: now[0])
    event_id = deterministic_event_id("homework_due", "private-sid", "assignment-a", "due-a")
    first = repository.enqueue("homework_due", event_id, "private-sid")
    second = repository.enqueue("homework_due", event_id, "private-sid")
    _check(state, first["inserted"] is True and second == {"id": first["id"], "inserted": False}, "event triple did not dedupe")
    _check(state, _count(path, "student_notification_events") == 1, "event triple duplicated")
    stored = json.loads(_row(path, "SELECT payload_json FROM student_notification_events")[0])
    _check(state, set(stored) == {"type", "eventId", "url"} and "private-sid" not in json.dumps(stored), "outbox payload leaked SID or changed shape")
    parallel_id = deterministic_event_id("schedule_changed", "private-sid", "revision-a")
    with ThreadPoolExecutor(max_workers=2) as pool:
        parallel = list(pool.map(
            lambda _value: repository.enqueue(
                "schedule_changed", parallel_id, "private-sid", scheduled_at=9999.0, now=2000.0
            ),
            range(2),
        ))
    _check(state, sum(result["inserted"] is True for result in parallel) == 1 and len({result["id"] for result in parallel}) == 1,
           "parallel event enqueue did not dedupe")

    def claim():
        return repository.lease(now=2000.0, lease_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _value: claim(), range(2)))
    claimed = [lease for lease in leases if lease is not None]
    _check(state, len(claimed) == 1 and claimed[0]["payload_valid"] is True, "parallel lease duplicated or rejected canonical payload")
    lease = claimed[0]
    _check(state, lease["scheduled_at"] == 2000.0, "lease omitted its authority freshness timestamp")
    _check(state, repository.record_delivery(lease["event_row_id"], lease["lease_token"], 11), "success receipt was not recorded")
    _check(state, not repository.record_delivery(lease["event_row_id"], lease["lease_token"], 11), "success receipt duplicated")
    _check(state, repository.record_delivery(lease["event_row_id"], lease["lease_token"], 12, state="permanent_failure"), "permanent receipt failed")
    _check(state, repository.finished_subscription_ids(lease["event_row_id"]) == {11, 12}, "finished receipt set is incomplete")
    _check(state, repository.successful_subscription_ids(lease["event_row_id"]) == {11}, "successful receipt set is wrong")
    _check(state, repository.complete(lease["event_row_id"], lease["lease_token"], success=False, error="429"), "transient completion failed")
    _check(state, repository.lease(now=2059.0) is None, "retry backoff was ignored")
    retried = repository.lease(now=2060.0)
    _check(state, retried is not None and retried["attempts"] == 1 and repository.finished_subscription_ids(retried["event_row_id"]) == {11, 12}, "retry lost receipt suppression")
    _check(state, repository.complete(retried["event_row_id"], retried["lease_token"], success=True, now=2060.0), "successful retry did not finish")
    _check(state, repository.lease(now=2060.0) is None, "sent event was leased again")

    tampered_id = deterministic_event_id("class_reminder", "private-sid", "class-a")
    tampered = repository.enqueue("class_reminder", tampered_id, "private-sid", now=2400.0)
    with closing(sqlite3.connect(path)) as db:
        db.execute("UPDATE student_notification_events SET payload_json='{}' WHERE id=?", (tampered["id"],))
        db.commit()
    bad = repository.lease(now=2400.0)
    _check(state, bad is not None and bad["payload_valid"] is False and bad["payload"] == build_event_payload("class_reminder", tampered_id), "tampered payload reached lease authority")
    _check(state, repository.cancel(bad["event_row_id"], bad["lease_token"], code="payload_invalid", now=2400.0), "tampered event was not cancellable")
    _check(state, _row(path, "SELECT state,last_error FROM student_notification_events WHERE id=?", (tampered["id"],)) == ("cancelled", "payload_invalid"), "cancel state was not durable")

    late_id = deterministic_event_id("schedule_changed", "private-sid", "late-owner")
    late = repository.enqueue("schedule_changed", late_id, "private-sid", now=2500.0)
    late_lease = repository.lease(now=2500.0, lease_seconds=30.0)
    _check(state, late_lease is not None and late_lease["event_row_id"] == late["id"],
           "late-owner fixture was not leased")
    _check(state, repository.renew_lease(
        late["id"], late_lease["lease_token"], lease_seconds=180.0, now=2531.0,
    ), "unclaimed expired lease could not be renewed by its token owner")
    _check(state, repository.record_delivery(
        late["id"], late_lease["lease_token"], 31, now=2531.0,
    ) and repository.complete(
        late["id"], late_lease["lease_token"], success=True, now=2531.0,
    ), "late successful owner could not durably finish")
    _check(state, repository.lease(now=2531.0) is None,
           "late successful event was re-leased")


def _milestones(root: Path, state: list[int]) -> None:
    path = root / "milestones.sqlite"
    _migrate(path)
    repository = StudentNotificationRepository(path, clock=lambda: 3000.0)
    first = repository.record_milestone("secret-sid", "curriculum-key", 25)
    second = repository.record_milestone("secret-sid", "curriculum-key", 25)
    _check(state, first["inserted"] is True and second["inserted"] is False and first["eventId"] == second["eventId"], "milestone was not idempotent")
    _check(state, _count(path, "student_notification_milestones") == 1 and _count(path, "student_notification_events") == 1, "milestone/event transaction duplicated")
    _check(state, repository.milestone_event_current("secret-sid", first["eventId"]) and "secret-sid" not in first["eventId"], "milestone event authority or opacity failed")


def _reminders(state: list[int]) -> None:
    now = dt.datetime(2026, 8, 9, 9, 0, tzinfo=KST)
    iso = lambda seconds: (now + dt.timedelta(seconds=seconds)).isoformat(timespec="seconds")
    schedule = [
        {"kind": "regular", "status": "scheduled", "date": "2026-08-09", "startAt": iso(7200), "slots": [1]},
        {"kind": "extra", "status": "scheduled", "date": "2026-08-09", "startAt": iso(1800), "slots": [2]},
        {"kind": "regular", "status": "scheduled", "date": "2026-08-09", "startAt": iso(7501), "slots": [1]},
        {"kind": "makeup", "status": "cancelled", "date": "2026-08-09", "startAt": iso(3600), "slots": [1]},
        {"kind": "regular", "status": "completed", "date": "2026-08-09", "startAt": iso(3600), "slots": [1]},
    ]
    homework = [
        {"id": "hw-a", "sid": "sid-a", "status": "assigned", "dueAt": iso(86400)},
        {"id": "hw-b", "sid": "sid-a", "status": "assigned", "dueAt": iso(86701)},
        {"id": "hw-c", "sid": "sid-a", "status": "completed", "dueAt": iso(3600)},
        {"id": "hw-d", "sid": "sid-a", "status": "cancelled", "dueAt": iso(3600)},
        {"id": "hw-e", "sid": "sid-a", "status": "assigned", "dueAt": None},
        {"id": "hw-f", "sid": "sid-a", "status": "assigned", "dueAt": iso(0)},
        {"id": "hw-foreign", "sid": "sid-b", "status": "assigned", "dueAt": iso(3600)},
    ]
    rows = build_reminder_candidates(sid="sid-a", schedule=schedule, homework=homework, now=now)
    types = [row["event_type"] for row in rows]
    _check(state, types.count("class_reminder") == 2 and types.count("homework_due") == 1, "reminder boundaries included stale or excluded due rows")
    due_row = next(row for row in rows if row["event_type"] == "homework_due")
    _check(state, due_row["event_id"] == deterministic_event_id("homework_due", "hw-a", iso(86400)),
           "save hook and reminder scanner use different homework event identities")
    _check(state, all(row["sid"] == "sid-a" and "sid-a" not in row["event_id"] for row in rows), "reminder candidate crossed SID or exposed it")
    _check(state, rows == build_reminder_candidates(sid="sid-a", schedule=schedule, homework=homework, now=now), "reminder candidate is not deterministic")
    _check(state, len(build_reminder_candidates(sid="sid-a", schedule=schedule, homework=homework, now=now, max_events=1)) == 1, "reminder cap was ignored")
    try:
        build_reminder_candidates(sid="sid-a", schedule=schedule, homework=homework, now=now, max_events=501)
    except NotificationInputError:
        pass
    else:
        raise AssertionError("reminder cap above 500 was accepted")
    try:
        build_reminder_candidates(sid="sid-a", schedule=schedule, homework=homework, now=now.astimezone(dt.timezone.utc))
    except NotificationInputError:
        pass
    else:
        raise AssertionError("non-KST reminder clock was accepted")


def _schedule_hooks(state: list[int]) -> None:
    rows = [
        {"kind": "regular", "status": "scheduled", "date": "2026-08-10",
         "startAt": "2026-08-10T17:00:00+09:00", "slots": [1]},
        {"kind": "makeup", "status": "scheduled", "date": "2026-08-11",
         "startAt": "2026-08-11T19:00:00+09:00", "slots": [2]},
    ]
    first = schedule_snapshot_event_id("sid-a", rows)
    changed = [dict(rows[0], startAt="2026-08-10T18:00:00+09:00"), rows[1]]
    _check(state, first == schedule_snapshot_event_id("sid-a", reversed(rows))
           and first != schedule_snapshot_event_id("sid-a", changed) and "sid-a" not in first,
           "schedule snapshot identity is not stable, change-sensitive, and opaque")
    before_roster = [{"id": "sid-a", "name": "이름 전", "day1": "월1", "visitTime1": "13:00"}]
    _check(state, student_schedule_changed_sids(
        before_roster, [{**before_roster[0], "name": "이름 후", "school": "학교"}],
    ) == (), "non-schedule roster edit queued a schedule notification")
    _check(state, student_schedule_changed_sids(
        before_roster, [{**before_roster[0], "visitTime1": "14:00"}],
    ) == ("sid-a",), "regular schedule edit did not select the affected SID")

    with patch("core.student_notification_hooks.runtime_repository", return_value=None), patch(
        "core.student_notification_hooks._runtime_json",
        side_effect=AssertionError("rollout-off hook read runtime JSON"),
    ):
        _check(state, enqueue_current_schedule_changes(["sid-a"]) == 0,
               "rollout-off schedule hook did not return before runtime reads")

    students_source = (ROOT / "routes" / "api_students.py").read_text(encoding="utf-8")
    student_routes = {
        node.name: ast.get_source_segment(students_source, node)
        for node in ast.parse(students_source).body
        if isinstance(node, ast.FunctionDef)
    }
    add_route = student_routes["api_add_student"]
    update_route = student_routes["api_update_student_field"]
    progress_route = (ROOT / "routes" / "api_progress.py").read_text(encoding="utf-8")
    attend = (ROOT / "routes" / "api_attend.py").read_text(encoding="utf-8")
    makeup_path = ROOT / "routes" / "api_makeup_carryover.py"
    makeup = makeup_path.read_text(encoding="utf-8")
    _check(state, add_route.index("create_student_with_identity(")
           < add_route.index('enqueue_current_schedule_changes([created["id"]])')
           and add_route.index("save_atomic(STU_PATH, students)")
           < add_route.index('enqueue_current_schedule_changes([data["id"]])')
           and students_source.count("enqueue_current_schedule_changes(") == 3
           and "before_pairs ^ after_pairs" in attend
           and attend.index("save_absent(payload, locked=True)") < attend.index("enqueue_current_schedule_changes("),
           "student/absence schedule hooks are missing or run before persistence")
    notification_position = update_route.index("enqueue_current_schedule_changes([str(sid)])")
    _check(state, update_route.index("mutate_identity_state(") < notification_position
           and update_route.index("save_atomic(STU_PATH, students)") < notification_position
           and 'field = str(field)' in update_route
           and 're.fullmatch(r"(?:day|visitTime)\\d+", field)' in update_route,
           "normal all-students schedule editor route lost its post-commit notification hook")
    _check(state, makeup.count("enqueue_current_schedule_changes(") == 2
           and "_makeup_student_ids(previous) | _makeup_student_ids(normalized)" in makeup
           and 'enqueue_current_schedule_changes(result.get("addedSids") or [])' in makeup,
           "makeup save/sheet-sync hooks lost old/new SID coverage")
    watch = (ROOT / "routes" / "api_watch.py").read_text(encoding="utf-8")
    progress_writer = (ROOT / "core" / "watch_progress_writer.py").read_text(encoding="utf-8")
    progress_notifications = (ROOT / "core" / "progress_notifications.py").read_text(encoding="utf-8")
    _check(state, "progress_notification_snapshot" in progress_route
           and "commit_progress_notifications" in progress_route
           and "save_progress_status" in watch
           and "progress_notification_snapshot" in progress_writer
           and "commit_progress_notifications" in progress_writer
           and "enqueue_progress_milestones" in progress_notifications
           and "from routes.api_basic import" not in watch,
           "progress write seams lost milestone hooks")
    authority = (ROOT / "core" / "student_notification_authority.py").read_text(encoding="utf-8")
    _check(state, "anchor.date() + dt.timedelta(days=45)" in authority,
           "schedule enqueue and delivery authority horizons diverged")
    announcements = (ROOT / "routes" / "api_announcements.py").read_text(encoding="utf-8")
    _check(state, '"notificationEventId": None' in announcements
           and 'deterministic_event_id("announcement_published", announcement_id)' in announcements,
           "student announcement projection lost its opaque notification deep-link alias")

    from core.makeup_payload_rules import makeup_student_ids
    collect = makeup_student_ids
    fixture = {
        "by_absence": {"2026-08-09": {"sid-a|absence": {
            "scheduledMakeup": {"studentId": "sid-a", "makeupDate": "2026-08-10",
                                "makeupTimes": [1], "status": "scheduled"},
        }}},
        "manual": {"2026-08-11": {"row-b": {"sid": "sid-b", "dateOnly": True}}},
    }
    _check(state, collect(fixture) == {"sid-a", "sid-b"},
           "makeup hook did not extract normalized absence/manual student IDs")


def _preference_routes(root: Path, state: list[int]) -> None:
    students, accounts, database = root / "students-fixture.json", root / "accounts-fixture.json", root / "routes.sqlite"
    students.write_text(json.dumps([{"id": "sid-a", "name": "학생"}], ensure_ascii=False), encoding="utf-8")
    accounts.write_text(json.dumps({"aid-a": {
        "sids": ["sid-a"], "pw_hash": generate_password_hash("secret"),
        "must_change_credentials": False, "disabled": False,
    }}, ensure_ascii=False), encoding="utf-8")
    sessions = StudentSessionRepository(database, clock=lambda: 1000.0)
    push = StudentPushRepository(database, clock=lambda: 1000.0)
    _migrate(database)
    notifications = StudentNotificationRepository(database, clock=lambda: 1000.0)
    config = load_student_app_config({
        "STUDENT_APP_PUBLIC_ENABLED": "1", "STUDENT_APP_REMINDERS_ENABLED": "1",
        "STUDENT_APP_SESSION_COOKIE_SECURE": "0", "STUDENT_APP_TEST_INSECURE_COOKIE": "1",
    })
    deps = StudentPushApiDependencies(
        config, StudentAccountRepository(accounts, students), sessions, push,
        type("KeyProvider", (), {"public_key": lambda self: "B" + "A" * 86})(),
        lambda: 1000.0, notifications,
    )
    app = Flask("notification-preferences")
    app.register_blueprint(create_blueprint(deps))
    created = sessions.create_session("aid-a", "sid-a", ["sid-a"], now=1000.0)
    client = app.test_client()
    _check(state, client.get("/api/mobile/push/preferences").status_code == 401,
           "preference GET accepted no session")
    client.set_cookie(config.cookie.name, created["token"])
    first = client.get("/api/mobile/push/preferences")
    _check(state, first.status_code == 200 and first.headers.get("Cache-Control") == "no-store"
           and first.get_json()["revision"] == 0 and all(first.get_json()["preferences"].values()),
           "default preference route response changed")
    _check(state, _count(database, "student_notification_preferences") == 0,
           "preference GET wrote a default row")
    _check(state, client.post("/api/mobile/push/preferences", json={}).status_code == 403,
           "preference POST accepted missing CSRF")
    headers = {"X-CSRF-Token": created["csrf_token"]}
    selected = {"schedule": True, "homework": False, "progress": True, "announcement": False}
    saved = client.post("/api/mobile/push/preferences", json={
        "preferences": selected, "expectedRevision": 0,
    }, headers=headers)
    _check(state, saved.status_code == 200 and saved.get_json() == {
        "ok": True, "preferences": selected, "revision": 1,
    }, "preference POST lost the full snapshot contract")
    stale = client.post("/api/mobile/push/preferences", json={
        "preferences": selected, "expectedRevision": 0,
    }, headers=headers)
    _check(state, stale.status_code == 409 and stale.get_json()["code"] == "preference_revision_conflict",
           "stale preference revision was accepted")
    malformed = client.post("/api/mobile/push/preferences", json={
        "preferences": {"homework": True}, "expectedRevision": 1,
    }, headers=headers)
    _check(state, malformed.status_code == 400, "partial preference snapshot was accepted")

    disabled_config = load_student_app_config({
        "STUDENT_APP_PUBLIC_ENABLED": "1", "STUDENT_APP_REMINDERS_ENABLED": "0",
        "STUDENT_APP_SESSION_COOKIE_SECURE": "0", "STUDENT_APP_TEST_INSECURE_COOKIE": "1",
    })
    disabled_deps = StudentPushApiDependencies(
        disabled_config, deps.accounts, sessions, push, deps.sender, lambda: 1000.0, None,
    )
    disabled_app = Flask("notification-preferences-disabled")
    disabled_app.register_blueprint(create_blueprint(disabled_deps))
    _check(state, disabled_app.test_client().get("/api/mobile/push/preferences").status_code == 404,
           "feature-off preference route did not fail closed")


class _EventAuthority:
    def allowed(self, _lease, _subscription) -> bool:
        return True


class _EventSender:
    def __init__(self) -> None:
        self.transient = True
        self.calls: list[str] = []

    def send_event(self, subscription, _event_type, _event_id):
        endpoint = str(subscription.get("endpoint") or "")
        self.calls.append(endpoint)
        if endpoint.endswith("device-b") and self.transient:
            return PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="timeout")
        return PushSendResult(PushResultStatus.SUCCESS, http_status=201)


class _SlowSuccessSender:
    def __init__(self, clock: list[float]) -> None:
        self.clock, self.calls = clock, 0

    def send_event(self, _subscription, _event_type, _event_id):
        self.calls += 1
        self.clock[0] += 31.0
        return PushSendResult(PushResultStatus.SUCCESS, http_status=201)


class _PermanentSender:
    def __init__(self, status: int) -> None:
        self.status = status

    def send_event(self, _subscription, _event_type, _event_id):
        return PushSendResult(PushResultStatus.PERMANENT_FAILURE, http_status=self.status)


class _AlwaysTransientSender:
    def __init__(self) -> None:
        self.calls = 0

    def send_event(self, _subscription, _event_type, _event_id):
        self.calls += 1
        return PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="timeout")


class _HomeworkRows:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def list_for_sid(self, _sid, *, status="open", cursor=None, page_size=50):
        return (self.rows[:page_size], False)


def _hooks_scanner_delivery(root: Path, state: list[int]) -> None:
    database = root / "integrated.sqlite"
    now = [1000.0]
    push = StudentPushRepository(database, clock=lambda: now[0])
    _migrate(database)
    notifications = StudentNotificationRepository(database, clock=lambda: now[0])
    future = dt.datetime.fromtimestamp(now[0] + 90_000, KST)
    assignments = [{
        "id": "hw_abcdefghijklmnop", "status": "assigned",
        "due_at": future.isoformat(timespec="seconds"),
    }]
    queued = enqueue_homework_events(notifications, "sid-a", assignments, now=dt.datetime.fromtimestamp(now[0], KST))
    repeated = enqueue_homework_events(notifications, "sid-a", assignments, now=dt.datetime.fromtimestamp(now[0], KST))
    _check(state, queued == 2 and repeated == 0, "homework save hook did not dedupe assigned/due events")
    progress = enqueue_progress_milestones(notifications, "sid-a", "course-a", 24, 76, now=now[0])
    _check(state, progress == 3 and enqueue_progress_milestones(
        notifications, "sid-a", "course-a", 24, 76, now=now[0]
    ) == 0, "progress milestone hook repeated thresholds")

    config = load_student_app_config({
        "STUDENT_APP_PUBLIC_ENABLED": "1", "STUDENT_APP_REMINDERS_ENABLED": "1",
        "STUDENT_APP_SESSION_COOKIE_SECURE": "0", "STUDENT_APP_TEST_INSECURE_COOKIE": "1",
    })
    enqueue_announcement("announcement-a", ["sid-a", "sid-b"], config=config,
                         notification_repository=notifications)
    enqueue_announcement("announcement-a", ["sid-a", "sid-b"], config=config,
                         notification_repository=notifications)
    _check(state, _count(database, "student_notification_events",
                         " WHERE event_type='announcement_published'") == 2,
           "generic announcement adapter duplicated or lost target rows")

    scanner_db = root / "scanner.sqlite"
    _migrate(scanner_db)
    scanner_repo = StudentNotificationRepository(scanner_db, clock=lambda: now[0])
    due = dt.datetime.fromtimestamp(now[0] + 86_400, KST).isoformat(timespec="seconds")
    scanner_homework = _HomeworkRows([{
        "id": "hw_scanner_00000001", "sid": "sid-a", "status": "assigned",
        "due_at": due, "assigned_at": dt.datetime.fromtimestamp(now[0], KST).isoformat(timespec="seconds"),
    }])
    inputs = {"students": [{"id": "sid-a"}], "absence": {}, "extra": {}, "weekend": {}, "makeup": {}}
    first = run_scanner(scanner_repo, scanner_homework, now=dt.datetime.fromtimestamp(now[0], KST), **inputs)
    second = run_scanner(scanner_repo, scanner_homework, now=dt.datetime.fromtimestamp(now[0], KST), **inputs)
    _check(state, first == {"candidates": 1, "inserted": 1} and second == {"candidates": 1, "inserted": 0},
           "reminder scanner was not idempotent")

    schedule_db = root / "schedule-recovery.sqlite"
    _migrate(schedule_db)
    schedule_repo = StudentNotificationRepository(schedule_db, clock=lambda: now[0])
    empty_homework = _HomeworkRows([])
    schedule_inputs = {
        "students": [{"id": "sid-a", "day1": "월1", "visitTime1": "13:00"}],
        "absence": {}, "extra": {}, "weekend": {}, "makeup": {},
    }
    event_ids = []
    for visit_time in ("13:00", "14:00", "13:00", "14:00"):
        schedule_inputs["students"][0]["visitTime1"] = visit_time
        revision = schedule_repo.mark_schedule_pending(["sid-a"], now=now[0])["sid-a"]
        recovered = run_scanner(
            schedule_repo, empty_homework, now=dt.datetime.fromtimestamp(now[0], KST),
            **schedule_inputs,
        )
        row = _row(schedule_db, "SELECT event_id FROM student_notification_schedule_state WHERE sid='sid-a'")
        event_ids.append(row[0])
        _check(state, recovered["candidates"] == 1 and recovered["inserted"] == 1
               and schedule_repo.pending_schedule_revisions() == (),
               f"pending schedule revision {revision} was not reconciled")
    _check(state, len(set(event_ids)) == 4
           and _count(schedule_db, "student_notification_events", " WHERE event_type='schedule_changed'") == 4,
           "A-to-B-to-A-to-B schedule mutations were permanently deduplicated")

    worker_db = root / "worker.sqlite"
    worker_push = StudentPushRepository(worker_db, clock=lambda: now[0])
    _migrate(worker_db)
    worker_repo = StudentNotificationRepository(worker_db, clock=lambda: now[0])
    for suffix in ("a", "b"):
        worker_push.upsert_subscription(
            "aid-a", "sid-a", f"device-{suffix}",
            f"https://fcm.googleapis.com/fcm/send/device-{suffix}", "a2V5", "YXV0aA",
            session_id=1, now=now[0],
        )
    event_id = deterministic_event_id("homework_due", "worker-assignment")
    worker_repo.enqueue("homework_due", event_id, "sid-a", now=now[0])
    sender = _EventSender()
    first_delivery = run_delivery(worker_repo, worker_push, sender, _EventAuthority(), limit=1)
    now[0] += 60
    sender.transient = False
    second_delivery = run_delivery(worker_repo, worker_push, sender, _EventAuthority(), limit=1)
    calls_a = sum(endpoint.endswith("device-a") for endpoint in sender.calls)
    calls_b = sum(endpoint.endswith("device-b") for endpoint in sender.calls)
    _check(state, first_delivery["retried"] == 1 and second_delivery["sent"] == 1
           and calls_a == 1 and calls_b == 2,
           "delivery receipts did not suppress a previously successful subscription")

    slow_db = root / "slow-worker.sqlite"
    slow_now = [5000.0]
    slow_push = StudentPushRepository(slow_db, clock=lambda: slow_now[0])
    _migrate(slow_db)
    slow_repo = StudentNotificationRepository(slow_db, clock=lambda: slow_now[0])
    slow_push.upsert_subscription(
        "aid-a", "sid-a", "slow-device",
        "https://fcm.googleapis.com/fcm/send/slow-device", "a2V5", "YXV0aA",
        session_id=1, now=slow_now[0],
    )
    slow_event = deterministic_event_id("homework_due", "slow-assignment")
    slow_repo.enqueue("homework_due", slow_event, "sid-a", now=slow_now[0])
    slow_sender = _SlowSuccessSender(slow_now)
    slow_first = run_delivery(slow_repo, slow_push, slow_sender, _EventAuthority(), limit=1)
    slow_second = run_delivery(slow_repo, slow_push, slow_sender, _EventAuthority(), limit=1)
    _check(state, slow_first["sent"] == 1 and slow_first["deliveries"] == 1
           and slow_second["leased"] == 0 and slow_sender.calls == 1
           and _count(slow_db, "student_notification_deliveries") == 1,
           "provider success beyond the old 30-second lease was delivered twice")

    for status in (404, 410):
        gone_db = root / f"gone-worker-{status}.sqlite"
        gone_push = StudentPushRepository(gone_db, clock=lambda: now[0])
        _migrate(gone_db)
        gone_repo = StudentNotificationRepository(gone_db, clock=lambda: now[0])
        gone_push.upsert_subscription(
            "aid-a", f"sid-gone-{status}", f"gone-{status}",
            f"https://fcm.googleapis.com/fcm/send/gone-{status}", "a2V5", "YXV0aA",
            session_id=1, now=now[0],
        )
        gone_event = deterministic_event_id("homework_due", f"gone-assignment-{status}")
        gone_repo.enqueue("homework_due", gone_event, f"sid-gone-{status}", now=now[0])
        gone_summary = run_delivery(
            gone_repo, gone_push, _PermanentSender(status), _EventAuthority(), limit=1,
        )
        gone_state = _row(
            gone_db,
            "SELECT state,attempts,last_error FROM student_notification_events WHERE event_id=?",
            (gone_event,),
        )
        _check(
            state,
            gone_summary["failed"] == 1 and gone_summary["revoked"] == 1
            and not gone_push.active_subscriptions(f"sid-gone-{status}")
            and gone_state == ("failed", 1, "permanent"),
            f"generic notification {status} did not revoke and terminate the subscription",
        )

    exhausted_db = root / "exhausted-worker.sqlite"
    exhausted_push = StudentPushRepository(exhausted_db, clock=lambda: now[0])
    _migrate(exhausted_db)
    exhausted_repo = StudentNotificationRepository(exhausted_db, clock=lambda: now[0])
    exhausted_push.upsert_subscription(
        "aid-a", "sid-exhausted", "exhausted-device",
        "https://fcm.googleapis.com/fcm/send/exhausted", "a2V5", "YXV0aA",
        session_id=1, now=now[0],
    )
    exhausted_event = deterministic_event_id("homework_due", "exhausted-assignment")
    exhausted_repo.enqueue("homework_due", exhausted_event, "sid-exhausted", now=now[0])
    exhausted_sender = _AlwaysTransientSender()
    summaries = []
    for _ in range(exhausted_repo.MAX_ATTEMPTS):
        summaries.append(run_delivery(
            exhausted_repo, exhausted_push, exhausted_sender, _EventAuthority(), limit=1,
        ))
        row = _row(
            exhausted_db,
            "SELECT state,next_attempt,attempts,last_error FROM student_notification_events WHERE event_id=?",
            (exhausted_event,),
        )
        if row[0] == "pending":
            now[0] = float(row[1])
    exhausted_state = _row(
        exhausted_db,
        "SELECT state,attempts,last_error FROM student_notification_events WHERE event_id=?",
        (exhausted_event,),
    )
    _check(
        state,
        all(item["retried"] == 1 and item["failed"] == 0 for item in summaries[:-1])
        and summaries[-1]["retried"] == 0 and summaries[-1]["failed"] == 1
        and exhausted_state == ("failed", exhausted_repo.MAX_ATTEMPTS, "timeout")
        and exhausted_sender.calls == exhausted_repo.MAX_ATTEMPTS,
        "generic notification retry exhaustion reported retried instead of terminal failure",
    )


def _fresh_file_authority(root: Path, state: list[int]) -> None:
    now_dt = dt.datetime(2026, 8, 10, 10, 0, tzinfo=KST)
    now = now_dt.timestamp()
    database = root / "authority.sqlite"
    students_path = root / "authority-students.json"
    accounts_path = root / "authority-accounts.json"
    announcements_path = root / "authority-announcements.json"
    absent_path, extra_path = root / "authority-absent.json", root / "authority-extra.json"
    weekend_path, makeup_path = root / "authority-weekend.json", root / "authority-makeup.json"
    student = {"id": "sid-a", "name": "학생", "day1": "월1", "visitTime1": "13:25"}
    account = {
        "sids": ["sid-a"], "pw_hash": generate_password_hash("secret"),
        "must_change_credentials": False, "disabled": False,
    }
    students_path.write_text(json.dumps([student], ensure_ascii=False), encoding="utf-8")
    accounts_path.write_text(json.dumps({"aid-a": account}, ensure_ascii=False), encoding="utf-8")
    for path, value in (
        (announcements_path, []), (absent_path, {}), (extra_path, {}),
        (weekend_path, {}), (makeup_path, {}),
    ):
        path.write_text(json.dumps(value), encoding="utf-8")

    sessions = StudentSessionRepository(database, clock=lambda: now)
    push = StudentPushRepository(database, clock=lambda: now)
    homework = StudentHomeworkRepository(database)
    homework.apply_migration(HOMEWORK_MIGRATION.read_text(encoding="utf-8"))
    _migrate(database)
    notifications = StudentNotificationRepository(database, clock=lambda: now)
    accounts = StudentAccountRepository(accounts_path, students_path)
    created = sessions.create_session("aid-a", "sid-a", ["sid-a"], now=now)
    push.upsert_subscription(
        "aid-a", "sid-a", "authority-device",
        "https://fcm.googleapis.com/fcm/send/authority", "a2V5", "YXV0aA",
        session_id=created["session_id"], now=now,
    )
    subscription = push.active_subscriptions("sid-a")[0]
    config = load_student_app_config({
        "STUDENT_APP_PUBLIC_ENABLED": "1", "STUDENT_APP_REMINDERS_ENABLED": "1",
        "STUDENT_APP_SESSION_COOKIE_SECURE": "0", "STUDENT_APP_TEST_INSECURE_COOKIE": "1",
    })
    authority = FileNotificationAuthority(
        notifications, homework, sessions, accounts,
        students_path=students_path, accounts_path=accounts_path,
        announcements_path=announcements_path, absent_path=absent_path,
        extra_path=extra_path, weekend_path=weekend_path, makeup_path=makeup_path,
        config_loader=lambda: config, clock=lambda: now,
    )
    schedule = project_student_schedule(
        student, sid="sid-a", start_date=now_dt.date().isoformat(),
        end_date=(now_dt.date() + dt.timedelta(days=45)).isoformat(),
    )
    snapshot_key = schedule_snapshot_event_id("sid-a", schedule)
    revision = notifications.mark_schedule_pending(["sid-a"], now=now)["sid-a"]
    committed = notifications.commit_schedule_projection(
        "sid-a", revision, snapshot_key, scheduled_at=now, now=now,
    )
    event_id = committed["eventId"]
    lease = notifications.lease(now=now)
    _check(state, lease is not None and authority.allowed(lease, subscription),
           "fresh schedule notification failed current account/session/source authority")
    authority.clock = lambda: now + 20 * 60 * 60
    _check(state, authority.allowed(lease, subscription),
           "midnight changed the schedule snapshot authority window")
    authority.clock = lambda: now
    _check(state, not authority.allowed({**lease, "scheduled_at": now - 86_401}, subscription),
           "stale immediate notification remained deliverable")
    students_path.write_text(json.dumps([{**student, "visitTime1": "14:25"}], ensure_ascii=False), encoding="utf-8")
    _check(state, not authority.allowed(lease, subscription),
           "changed schedule did not invalidate the queued snapshot")
    students_path.write_text(json.dumps([student], ensure_ascii=False), encoding="utf-8")
    selected = {category: category != "schedule" for category in CATEGORIES}
    notifications.update_preferences("aid-a", selected, expected_revision=0, now=now)
    _check(state, not authority.allowed(lease, subscription),
           "disabled notification category remained deliverable")
    notifications.update_preferences(
        "aid-a", {category: True for category in CATEGORIES}, expected_revision=1, now=now,
    )
    narrowed = load_student_app_config({
        "STUDENT_APP_PUBLIC_ENABLED": "1", "STUDENT_APP_REMINDERS_ENABLED": "1",
        "STUDENT_APP_CANARY_SIDS": "sid-b",
        "STUDENT_APP_SESSION_COOKIE_SECURE": "0", "STUDENT_APP_TEST_INSECURE_COOKIE": "1",
    })
    authority.config_loader = lambda: narrowed
    _check(state, not authority.allowed(lease, subscription),
           "canary narrowing did not invalidate a queued notification")
    authority.config_loader = lambda: config
    sessions.revoke(created["token"], now=now)
    _check(state, not authority.allowed(lease, subscription),
           "revoked subscription session remained notification authority")


def run_checks() -> dict[str, object]:
    state = [0]
    production = [
        ROOT / "core" / "student_notification_events.py",
        ROOT / "core" / "student_notification_repository.py",
        ROOT / "core" / "student_notification_outbox.py",
        ROOT / "core" / "student_notification_schedule_state.py",
        ROOT / "core" / "student_reminder_projection.py",
    ]
    _check(state, all(len(path.read_text(encoding="utf-8").splitlines()) <= 250 for path in production), "notification production module exceeds 250 LOC")
    _event_contract(state)
    with tempfile.TemporaryDirectory(prefix="student-notifications-") as raw:
        root = Path(raw)
        _schema_and_preferences(root, state)
        _outbox(root, state)
        _milestones(root, state)
        _preference_routes(root, state)
        _hooks_scanner_delivery(root, state)
        _fresh_file_authority(root, state)
        _check(state, not any(path.name in {"students.json", "progress.json", "app.sqlite"} for path in root.rglob("*")), "checker created runtime-named files")
    _reminders(state)
    _schedule_hooks(state)
    return {"name": "notifications", "assertions": state[0], "passed": True,
            "runtimeIsolation": "temporary SQLite only; no app, core.paths, or runtime JSON imports"}


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False, sort_keys=True))
