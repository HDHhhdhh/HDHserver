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

import core.absent as absent_store
import core.absence_transaction as transaction
import core.makeup_sheet_sync as makeup_rules
import routes.absence_assignment_cleanup as adapter
import routes.api_attend as attend_route
import routes.api_makeup_carryover as makeup_route
import scripts.sync_makeup_sheet_additive as offline_sync
from scripts.verify_absence_transaction import (
    ASSIGNED_LABEL,
    DATE,
    DONE_LABEL,
    KEEP_SID,
    OTHER_DATE,
    SID,
    SyntheticCrash,
    build_fixture,
    read_json,
    run_transaction,
    sqlite_rows,
)


class Matrix:
    def __init__(self) -> None:
        self.passed = 0
        self.known_limitations: list[str] = []
        self.failures: list[str] = []

    def check(self, case_id: str, condition: bool, detail: str) -> None:
        if condition:
            self.passed += 1
            print(f"[PASS] {case_id} - {detail}")
            return
        message = f"{case_id}: {detail}"
        self.failures.append(message)
        print(f"[FAIL] {message}")

    def known(self, case_id: str, condition: bool, detail: str) -> None:
        if not condition:
            self.check(case_id, False, detail)
            return
        message = f"{case_id}: {detail}"
        self.known_limitations.append(message)
        print(f"[KNOWN] {message}")

    def finish(self) -> int:
        total = self.passed + len(self.known_limitations) + len(self.failures)
        print(
            "absence and makeup integration matrix: "
            f"{self.passed} passed, {len(self.known_limitations)} known, "
            f"{len(self.failures)} failed, {total} total"
        )
        if self.failures:
            print("failed cases:")
            for failure in self.failures:
                print(f"- {failure}")
            return 1
        return 0


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def fixture_snapshot(fixture: dict) -> dict:
    paths = fixture["paths"]
    return {
        "updates": read_json(paths["updates"]),
        "progress": read_json(paths["progress"]),
        "logs": read_json(paths["logs"]),
        "sqlite": sqlite_rows(paths["db"]),
        "absent": read_json(paths["absent"]),
        "carryover": read_json(paths["carryover"]),
    }


def sqlite_entry(fixture: dict, date_key: str, sid: str) -> dict:
    for row_date, row_sid, entry_json, _updated_at in sqlite_rows(fixture["paths"]["db"]):
        if row_date == date_key and row_sid == sid:
            return json.loads(entry_json)
    return {}


@contextmanager
def patched_attendance_route(fixture: dict, *, failure_phase: str | None = None, students=None):
    paths = fixture["paths"]
    students_path = paths["absent"].parent / "students.json"
    write_json(students_path, students if students is not None else [
        {"id": SID, "day1": "월1"}, {"id": KEEP_SID, "day1": "월1"},
    ])
    originals = [
        (absent_store, "ABS_PATH", absent_store.ABS_PATH),
        (attend_route, "ABS_PATH", attend_route.ABS_PATH),
        (attend_route, "STU_PATH", attend_route.STU_PATH),
        (attend_route, "UPD_PATH", attend_route.UPD_PATH),
        (attend_route, "PRG_PATH", attend_route.PRG_PATH),
        (attend_route, "MAKEUP_CARRYOVER_PATH", attend_route.MAKEUP_CARRYOVER_PATH),
        (attend_route, "absence_write_scope", attend_route.absence_write_scope),
        (attend_route, "commit_new_absences_locked", attend_route.commit_new_absences_locked),
        (attend_route, "enqueue_current_schedule_changes", attend_route.enqueue_current_schedule_changes),
    ]
    absent_store.ABS_PATH = paths["absent"]
    attend_route.ABS_PATH = paths["absent"]
    attend_route.STU_PATH = students_path
    attend_route.UPD_PATH = paths["updates"]
    attend_route.PRG_PATH = paths["progress"]
    attend_route.MAKEUP_CARRYOVER_PATH = paths["carryover"]
    notifications: list[tuple[str, ...]] = []
    notification_after_commit: list[bool] = []

    @contextmanager
    def real_scope(**kwargs):
        with adapter.absence_write_scope(
            **kwargs,
            log_repository_factory=fixture["repository_factory"],
            journal_dir=paths["journal"],
            lock_timeout_sec=5.0,
        ) as journal_dir:
            yield journal_dir

    def inject(phase: str) -> None:
        if phase == failure_phase:
            raise OSError(f"synthetic attendance failure after {phase}")

    def real_commit(pairs, **kwargs):
        return adapter.commit_new_absences_locked(
            pairs,
            **kwargs,
            log_repository_factory=fixture["repository_factory"],
            failure_injector=inject if failure_phase else None,
        )

    def notify(sids) -> int:
        values = tuple(sorted({str(sid) for sid in sids if str(sid)}))
        notifications.append(values)
        notification_after_commit.append(
            not transaction.journal_path_for(paths["absent"], paths["journal"]).exists()
        )
        return len(values)

    attend_route.absence_write_scope = real_scope
    attend_route.commit_new_absences_locked = real_commit
    attend_route.enqueue_current_schedule_changes = notify

    app = Flask("verify-attendance-route-matrix")
    app.register_blueprint(attend_route.bp_api_attend)
    try:
        yield app.test_client(), notifications, notification_after_commit
    finally:
        for module, name, value in reversed(originals):
            setattr(module, name, value)


@contextmanager
def patched_makeup_route(
    fixture: dict,
    candidates: list[dict],
    *,
    failure_phase: str | None = None,
):
    paths = fixture["paths"]
    extra_path = paths["absent"].parent / "extra_attend.json"
    weekend_path = paths["absent"].parent / "weekend_slots.json"
    write_json(extra_path, {})
    write_json(weekend_path, {})
    originals = [
        (absent_store, "ABS_PATH", absent_store.ABS_PATH),
        (makeup_rules, "EXTRA_PATH", makeup_rules.EXTRA_PATH),
        (makeup_rules, "WEEKEND_SLOTS_PATH", makeup_rules.WEEKEND_SLOTS_PATH),
        (makeup_route, "ABS_PATH", makeup_route.ABS_PATH),
        (makeup_route, "UPD_PATH", makeup_route.UPD_PATH),
        (makeup_route, "PRG_PATH", makeup_route.PRG_PATH),
        (makeup_route, "MAKEUP_CARRYOVER_PATH", makeup_route.MAKEUP_CARRYOVER_PATH),
        (makeup_route, "MAKEUP_SHEET_SYNC_CONFIG_PATH", makeup_route.MAKEUP_SHEET_SYNC_CONFIG_PATH),
        (makeup_route, "read_additive_sheet_candidate_window", makeup_route.read_additive_sheet_candidate_window),
        (makeup_route, "absence_write_scope", makeup_route.absence_write_scope),
        (makeup_route, "commit_new_absences_locked", makeup_route.commit_new_absences_locked),
        (makeup_route, "enqueue_current_schedule_changes", makeup_route.enqueue_current_schedule_changes),
    ]
    absent_store.ABS_PATH = paths["absent"]
    makeup_rules.EXTRA_PATH = extra_path
    makeup_rules.WEEKEND_SLOTS_PATH = weekend_path
    makeup_route.ABS_PATH = paths["absent"]
    makeup_route.UPD_PATH = paths["updates"]
    makeup_route.PRG_PATH = paths["progress"]
    makeup_route.MAKEUP_CARRYOVER_PATH = paths["carryover"]
    makeup_route.MAKEUP_SHEET_SYNC_CONFIG_PATH = paths["absent"].parent / "missing_makeup_sheet_sync.json"
    makeup_route.read_additive_sheet_candidate_window = lambda _url, _date, months_back=1: {
        "month": "2026-08",
        "months": [{"month": "2026-07"}, {"month": "2026-08"}],
        "monthErrors": [],
        "matchedRows": 1 if candidates else 0,
        "sheetStudentCount": 1 if candidates else 0,
        "maxSheetRow": 127,
        "unmatchedStarredRows": 0,
        "ambiguousStarredRows": 0,
        "unmatchedStarredDetails": [],
        "candidates": copy.deepcopy(candidates),
    }
    notifications: list[tuple[str, ...]] = []
    notification_after_commit: list[bool] = []

    @contextmanager
    def real_scope(**kwargs):
        with adapter.absence_write_scope(
            **kwargs,
            log_repository_factory=fixture["repository_factory"],
            journal_dir=paths["journal"],
            lock_timeout_sec=5.0,
        ) as journal_dir:
            yield journal_dir

    def inject(phase: str) -> None:
        if phase == failure_phase:
            raise OSError(f"synthetic makeup route failure after {phase}")

    def real_commit(pairs, **kwargs):
        return adapter.commit_new_absences_locked(
            pairs,
            **kwargs,
            log_repository_factory=fixture["repository_factory"],
            failure_injector=inject if failure_phase else None,
        )

    def notify(sids) -> int:
        values = tuple(sorted({str(sid) for sid in sids if str(sid)}))
        notifications.append(values)
        notification_after_commit.append(
            not transaction.journal_path_for(paths["absent"], paths["journal"]).exists()
        )
        return len(values)

    makeup_route.absence_write_scope = real_scope
    makeup_route.commit_new_absences_locked = real_commit
    makeup_route.enqueue_current_schedule_changes = notify

    app = Flask("verify-makeup-route-matrix")
    app.register_blueprint(makeup_route.bp_api_makeup_carryover)
    try:
        yield app.test_client(), notifications, notification_after_commit
    finally:
        for module, name, value in reversed(originals):
            setattr(module, name, value)


@contextmanager
def patched_offline_sync(
    fixture: dict,
    candidates: list[dict],
    *,
    failure_phase: str | None = None,
):
    paths = fixture["paths"]
    base = paths["absent"].parent
    config_path = base / "makeup_sheet_sync.json"
    status_path = base / "makeup_sheet_sync_status.json"
    backup_dir = base / "backups"
    write_json(
        config_path,
        {
            "enabled": True,
            "sheetUrl": "https://docs.google.com/spreadsheets/d/test/edit",
        },
    )
    originals = [
        (absent_store, "ABS_PATH", absent_store.ABS_PATH),
        (offline_sync, "ABS_PATH", offline_sync.ABS_PATH),
        (offline_sync, "UPD_PATH", offline_sync.UPD_PATH),
        (offline_sync, "PRG_PATH", offline_sync.PRG_PATH),
        (offline_sync, "CARRYOVER_PATH", offline_sync.CARRYOVER_PATH),
        (offline_sync, "CONFIG_PATH", offline_sync.CONFIG_PATH),
        (offline_sync, "STATUS_PATH", offline_sync.STATUS_PATH),
        (offline_sync, "BACKUP_DIR", offline_sync.BACKUP_DIR),
        (offline_sync, "collect_candidates", offline_sync.collect_candidates),
        (offline_sync, "absence_write_scope", offline_sync.absence_write_scope),
        (offline_sync, "commit_new_absences_locked", offline_sync.commit_new_absences_locked),
    ]
    absent_store.ABS_PATH = paths["absent"]
    offline_sync.ABS_PATH = paths["absent"]
    offline_sync.UPD_PATH = paths["updates"]
    offline_sync.PRG_PATH = paths["progress"]
    offline_sync.CARRYOVER_PATH = paths["carryover"]
    offline_sync.CONFIG_PATH = config_path
    offline_sync.STATUS_PATH = status_path
    offline_sync.BACKUP_DIR = backup_dir
    offline_sync.collect_candidates = lambda _url, _today: (
        copy.deepcopy(candidates),
        [{"month": "2026-08", "matchedRows": 1, "candidateCount": len(candidates)}],
    )

    @contextmanager
    def real_scope(**kwargs):
        with adapter.absence_write_scope(
            **kwargs,
            log_repository_factory=fixture["repository_factory"],
            journal_dir=paths["journal"],
        ) as journal_dir:
            yield journal_dir

    def inject(phase: str) -> None:
        if phase == failure_phase:
            raise OSError(f"synthetic offline failure after {phase}")

    def real_commit(pairs, **kwargs):
        return adapter.commit_new_absences_locked(
            pairs,
            **kwargs,
            log_repository_factory=fixture["repository_factory"],
            failure_injector=inject if failure_phase else None,
        )

    offline_sync.absence_write_scope = real_scope
    offline_sync.commit_new_absences_locked = real_commit
    try:
        yield {
            "status": status_path,
            "backups": backup_dir,
            "config": config_path,
        }
    finally:
        for module, name, value in reversed(originals):
            setattr(module, name, value)


def post_current_absence(client, payload: dict):
    current = client.get("/api/absent")
    revision = current.headers.get("X-Absence-Revision")
    return client.post("/api/absent", json=payload, headers={"If-Match": revision or ""})


def run_attendance_cases(matrix: Matrix) -> None:
    pairs = attend_route._absence_pairs(
        {
            "by_date": {DATE: ["sid-date"]},
            "by_student": {"sid-student": DATE},
            "by_slot": {DATE: {"sid-slot": [2], "sid-invalid-slot": [3]}},
        }
    )
    matrix.check(
        "A01",
        pairs == {(DATE, "sid-date"), (DATE, "sid-student"), (DATE, "sid-slot")},
        "new absence detection accepts each canonical index and ignores invalid slots",
    )

    with tempfile.TemporaryDirectory(prefix="verify-attendance-preconditions-") as raw:
        fixture = build_fixture(Path(raw))
        before = fixture_snapshot(fixture)
        with patched_attendance_route(fixture) as (client, notifications, _postcommit):
            invalid_json = client.post("/api/absent", data="[]", content_type="application/json")
            missing_revision = client.post("/api/absent", json=fixture["absent_after"])
            stale_revision = client.post(
                "/api/absent",
                json=fixture["absent_after"],
                headers={"If-Match": "stale"},
            )
        matrix.check(
            "A02",
            (invalid_json.status_code, missing_revision.status_code, stale_revision.status_code)
            == (400, 428, 409)
            and fixture_snapshot(fixture) == before
            and notifications == [],
            "invalid JSON missing revision and stale revision make no writes",
        )

    with tempfile.TemporaryDirectory(prefix="verify-attendance-success-") as raw:
        fixture = build_fixture(Path(raw))
        with patched_attendance_route(fixture) as (client, notifications, postcommit):
            created = post_current_absence(client, fixture["absent_after"])
            created_revision = created.headers.get("X-Absence-Revision")
            after_create = fixture_snapshot(fixture)

            repeated = client.post(
                "/api/absent",
                json=fixture["absent_after"],
                headers={"If-Match": created_revision or ""},
            )
            repeated_revision = repeated.headers.get("X-Absence-Revision")
            after_repeat = fixture_snapshot(fixture)

            cancelled = client.post(
                "/api/absent",
                json=fixture["initial"]["absent"],
                headers={"If-Match": repeated_revision or ""},
            )
            after_cancel = fixture_snapshot(fixture)

        progress_entry = after_create["progress"][DATE][SID]
        log_entry = after_create["logs"][DATE][SID]
        sql_entry = sqlite_entry(fixture, DATE, SID)
        matrix.check(
            "A03",
            created.status_code == 200
            and after_create["absent"] == fixture["absent_after"]
            and SID not in after_create["updates"][DATE],
            "new absence route atomically saves absence and removes only its date/SID video assignment",
        )
        matrix.check(
            "A04",
            progress_entry["tests"][ASSIGNED_LABEL] == "interrupted"
            and progress_entry["tests"][DONE_LABEL] == "done"
            and progress_entry["unknown"] == {"keep": True},
            "new absence changes assigned tests to interrupted and preserves done plus unknown fields",
        )
        matrix.check(
            "A05",
            log_entry["assignedTests"][0]["status"] == "interrupted"
            and sql_entry["assignedTests"][0]["status"] == "interrupted"
            and "testAssignmentAbsenceCarryover" in sql_entry,
            "new absence updates both JSON and SQLite logs after collecting test carryover",
        )
        matrix.check(
            "A06",
            after_create["updates"][OTHER_DATE][SID]["videos"] == ["mid-other"]
            and after_create["updates"][DATE][KEEP_SID]["videos"] == ["mid-keep"]
            and after_create["carryover"] == fixture["initial"]["carryover"],
            "attendance cleanup preserves unrelated dates students and makeup carryover store",
        )
        matrix.check(
            "A07",
            repeated.status_code == 200 and after_repeat == after_create and notifications[1] == (),
            "repeating the same absence payload is idempotent",
        )
        matrix.check(
            "A08",
            cancelled.status_code == 200
            and after_cancel["absent"] == fixture["initial"]["absent"]
            and SID not in after_cancel["updates"][DATE]
            and after_cancel["progress"][DATE][SID]["tests"][ASSIGNED_LABEL] == "interrupted",
            "absence cancellation removes absence only and does not silently recreate assignments",
        )
        matrix.check(
            "A09",
            notifications[0] == (SID,)
            and notifications[2] == (SID,)
            and all(postcommit),
            "schedule notifications identify changed SIDs only after commit",
        )

    with tempfile.TemporaryDirectory(prefix="verify-attendance-combined-") as raw:
        fixture = build_fixture(Path(raw))
        combined = copy.deepcopy(fixture["absent_after"])
        combined["by_date"].pop(OTHER_DATE, None)
        combined["by_student"].pop(KEEP_SID, None)
        combined["by_slot"].pop(OTHER_DATE, None)
        with patched_attendance_route(fixture) as (client, notifications, postcommit):
            response = post_current_absence(client, combined)
        stored = fixture_snapshot(fixture)
        matrix.check(
            "A10",
            response.status_code == 200
            and stored["absent"] == combined
            and notifications == [tuple(sorted((KEEP_SID, SID)))]
            and postcommit == [True],
            "one revision can atomically add a new absence and cancel an old one",
        )

    with tempfile.TemporaryDirectory(prefix="verify-attendance-failure-") as raw:
        fixture = build_fixture(Path(raw))
        before = fixture_snapshot(fixture)
        with patched_attendance_route(fixture, failure_phase="progress") as (client, notifications, _postcommit):
            response = post_current_absence(client, fixture["absent_after"])
        matrix.check(
            "A11",
            response.status_code == 500
            and fixture_snapshot(fixture) == before
            and notifications == []
            and not transaction.journal_path_for(fixture["paths"]["absent"], fixture["paths"]["journal"]).exists(),
            "actual attendance HTTP failure rolls JSON SQLite and journal fully back",
        )

    with tempfile.TemporaryDirectory(prefix="verify-attendance-invalid-date-") as raw:
        fixture = build_fixture(Path(raw))
        before = fixture_snapshot(fixture)
        invalid = copy.deepcopy(fixture["initial"]["absent"])
        invalid.setdefault("by_date", {})["2026-99-99"] = ["sid-invalid-date"]
        with patched_attendance_route(fixture) as (client, notifications, _postcommit):
            response = post_current_absence(client, invalid)
        stores_unchanged = fixture_snapshot(fixture) == before and notifications == []
        if response.status_code == 400:
            matrix.check(
                "A12",
                stores_unchanged,
                "invalid calendar dates return a client error without persistence",
            )
        else:
            matrix.known(
                "A12",
                response.status_code == 500 and stores_unchanged,
                "semantic-invalid date currently returns 500 but writes nothing and sends no notification",
            )


def run_self_study_absence_cases(matrix: Matrix) -> None:
    cases = [
        ("manual-on", {"id": SID, "day1": "월1"}, True, True),
        ("scheduled", {"id": SID, "day1": "월1", "selfStudyDays": ["day1"]}, None, True),
        ("manual-off", {"id": SID, "day1": "월1", "selfStudyDays": ["day1"]}, False, False),
        ("other-weekday", {"id": SID, "day1": "월1", "day2": "화1", "selfStudyDays": ["day2"]}, None, False),
        ("regular", {"id": SID, "day1": "월1"}, None, False),
    ]
    for name, student, self_study, exempt in cases:
        with tempfile.TemporaryDirectory(prefix=f"verify-self-study-{name}-") as raw:
            fixture = build_fixture(Path(raw))
            if self_study is not None:
                fixture["repository_factory"]().transform_entries(
                    {(DATE, SID)},
                    lambda entry, _sid: ({**entry, "selfStudy": self_study}, True),
                )
            with patched_attendance_route(fixture, students=[student]) as (client, _notifications, _postcommit):
                response = post_current_absence(client, fixture["absent_after"])
                saved = fixture_snapshot(fixture)
                marker = saved["carryover"]["by_absence"].get(DATE, {}).get(SID, {})
                repeated = post_current_absence(client, fixture["absent_after"])
            matrix.check(
                f"S-{name}",
                response.status_code == 200 and repeated.status_code == 200
                and (marker.get("state") == "self-study") == exempt
                and fixture_snapshot(fixture) == saved
                and SID not in saved["updates"][DATE]
                and saved["progress"][DATE][SID]["tests"][ASSIGNED_LABEL] == "interrupted"
                and saved["carryover"]["by_absence"][OTHER_DATE] == fixture["initial"]["carryover"]["by_absence"][OTHER_DATE],
                "self-study exemption uses the absence date, explicit log override, and unchanged assignment cleanup",
            )
            if exempt:
                with patched_makeup_route(fixture, []) as (client, _notifications, _postcommit):
                    snapshot = client.get("/api/makeup-carryover")
                    payload = snapshot.get_json()
                    payload["by_absence"][DATE][SID]["state"] = "open"
                    saved_response = client.post(
                        "/api/makeup-carryover", json=payload,
                        headers={"If-Match": snapshot.headers["X-Makeup-Carryover-Revision"]},
                    )
                matrix.check(
                    f"S-{name}-reload",
                    saved_response.status_code == 200
                    and saved_response.get_json()["by_absence"][DATE][SID]["state"] == "self-study",
                    "cold route GET and older-client open write preserve the persisted self-study exemption",
                )

    for makeup_slot, exempt in ((1, False), (2, True)):
        with tempfile.TemporaryDirectory(prefix="verify-self-study-makeup-") as raw:
            fixture = build_fixture(Path(raw))
            carryover = read_json(fixture["paths"]["carryover"])
            carryover["by_absence"].setdefault(OTHER_DATE, {})[SID] = {"scheduledMakeup": {
                "studentId": SID, "makeupDate": DATE, "makeupTimes": [makeup_slot], "status": "scheduled",
            }}
            write_json(fixture["paths"]["carryover"], carryover)
            student = {"id": SID, "day1": "월1", "selfStudyDays": ["day1"]}
            with patched_attendance_route(fixture, students=[student]) as (client, _notifications, _postcommit):
                response = post_current_absence(client, fixture["absent_after"])
            saved = fixture_snapshot(fixture)
            marker = saved["carryover"]["by_absence"].get(DATE, {}).get(SID, {})
            matrix.check(
                f"S-makeup-slot-{makeup_slot}",
                response.status_code == 200 and (marker.get("state") == "self-study") == exempt,
                "an overlapping makeup is a class absence; another slot keeps the self-study exemption",
            )

    for phase in ("updates", "progress", "logs", "absent", "carryover", "before_commit"):
        with tempfile.TemporaryDirectory(prefix=f"verify-self-study-rollback-{phase}-") as raw:
            fixture = build_fixture(Path(raw))
            # Production progress uses compact JSON; don't mistake fixture indentation
            # normalization for loss of a rollback before-image.
            progress_path = fixture["paths"]["progress"]
            progress_path.write_text(json.dumps(
                read_json(progress_path), ensure_ascii=False, separators=(",", ":"),
            ), "utf-8")
            before = fixture_snapshot(fixture)
            before_bytes = {key: fixture["paths"][key].read_bytes() for key in ("updates", "progress", "logs", "absent", "carryover")}
            with patched_attendance_route(
                fixture, failure_phase=phase,
                students=[{"id": SID, "day1": "월1", "selfStudyDays": ["day1"]}],
            ) as (client, notifications, _postcommit):
                response = post_current_absence(client, fixture["absent_after"])
            matrix.check(
                f"S-rollback-{phase}",
                response.status_code == 500 and fixture_snapshot(fixture) == before
                and all(fixture["paths"][key].read_bytes() == content for key, content in before_bytes.items())
                and notifications == [],
                "failed self-study absence rolls back all five JSON stores and SQLite without notifications",
            )

    with tempfile.TemporaryDirectory(prefix="verify-self-study-recovery-") as raw:
        fixture = build_fixture(Path(raw))
        students = [{"id": SID, "day1": "월1", "selfStudyDays": ["day1"]}]
        with patched_attendance_route(fixture, students=students) as (client, _notifications, _postcommit):
            assert post_current_absence(client, fixture["absent_after"]).status_code == 200
            fixture["repository_factory"]().transform_entries(
                {(DATE, SID)}, lambda entry, _sid: ({**entry, "selfStudy": False}, True),
            )
            assert read_json(fixture["paths"]["carryover"])["by_absence"][DATE][SID]["state"] == "self-study"
            recovered = client.post("/api/absent/recover", json={"date": DATE, "sids": [SID]})
            reabsent = post_current_absence(client, fixture["absent_after"])
        matrix.check(
            "S-recover-regular",
            recovered.status_code == 200 and reabsent.status_code == 200
            and read_json(fixture["paths"]["carryover"])["by_absence"][DATE][SID]["state"] == "open",
            "later setting changes alone do not rewrite history; recovery plus a new regular absence can reopen its demand",
        )


def run_makeup_rule_cases(matrix: Matrix) -> None:
    carryover = {"by_absence": {}, "manual": {}}
    absent = {"by_date": {}, "by_student": {}, "by_slot": {}}
    candidates = [
        {"date": DATE, "sid": SID, "slot": 2, "cell": "*"},
        {"date": DATE, "sid": SID, "slot": 1, "cell": "*"},
        {"date": DATE, "sid": SID, "slot": 1, "cell": "duplicate"},
        {"date": DATE, "sid": SID, "slot": 3, "cell": "invalid"},
        {"date": "", "sid": SID, "slot": 1, "cell": "invalid"},
    ]
    carryover_before = copy.deepcopy(carryover)
    absent_before = copy.deepcopy(absent)
    merged = makeup_rules.merge_additive_sheet_absences(
        carryover,
        absent,
        candidates,
        now="2026-08-24T00:00:00.000Z",
    )
    matrix.check(
        "M01",
        merged["added"] == 2
        and merged["addedPairs"] == [{"date": DATE, "sid": SID}]
        and merged["absent"]["by_slot"][DATE][SID] == [1, 2]
        and carryover == carryover_before
        and absent == absent_before,
        "additive merge deduplicates invalid input groups both slots by pair and leaves inputs immutable",
    )

    repeated = makeup_rules.merge_additive_sheet_absences(
        merged["carryover"],
        merged["absent"],
        candidates,
        now="2026-08-24T01:00:00.000Z",
    )
    empty = makeup_rules.merge_additive_sheet_absences(
        merged["carryover"],
        merged["absent"],
        [],
        now="2026-08-24T02:00:00.000Z",
    )
    matrix.check(
        "M02",
        repeated["added"] == 0
        and repeated["carryover"] == merged["carryover"]
        and repeated["absent"] == merged["absent"]
        and empty["carryover"] == merged["carryover"]
        and empty["absent"] == merged["absent"],
        "repeated or empty sheet sync is idempotent and never deletes state",
    )

    protected_carryover = {
        "by_absence": {
            "2026-08-10": {
                "scheduled|1": {
                    "state": "carried",
                    "scheduledMakeup": {
                        "originalAbsenceId": "absence|2026-08-10|scheduled|1",
                        "studentId": "scheduled",
                        "makeupDate": "2026-08-30",
                        "makeupTimes": [1],
                        "status": "scheduled",
                    },
                }
            },
            "2026-08-11": {"carry|1": {"state": "open"}},
        },
        "manual": {
            "2026-08-12": {"manual-date": {"sid": "manual-date", "dateOnly": True}},
            "2026-08-13": {"manual-slot": {"sid": "manual-slot", "slots": [2]}},
        },
    }
    protected_absent = {
        "by_date": {"2026-08-14": ["absent"]},
        "by_student": {"absent": "2026-08-14"},
        "by_slot": {"2026-08-14": {"absent": [1]}},
    }
    protected_candidates = [
        {"date": "2026-08-10", "sid": "scheduled", "slot": 1},
        {"date": "2026-08-11", "sid": "carry", "slot": 1},
        {"date": "2026-08-12", "sid": "manual-date", "slot": 2},
        {"date": "2026-08-13", "sid": "manual-slot", "slot": 2},
        {"date": "2026-08-14", "sid": "absent", "slot": 1},
    ]
    protected = makeup_rules.merge_additive_sheet_absences(
        protected_carryover,
        protected_absent,
        protected_candidates,
        now="2026-08-24T00:00:00.000Z",
    )
    matrix.check(
        "M03",
        protected["added"] == 4
        and protected["skippedExisting"] == 1
        and protected["protectedScheduled"] == 1
        and protected["carryover"] == protected_carryover
        and protected["absent"]["by_date"]["2026-08-10"] == ["scheduled"]
        and protected["absent"]["by_date"]["2026-08-11"] == ["carry"]
        and protected["absent"]["by_date"]["2026-08-12"] == ["manual-date"]
        and protected["absent"]["by_date"]["2026-08-13"] == ["manual-slot"]
        and protected["absent"]["by_date"]["2026-08-14"] == ["absent"],
        "scheduled carryover and manual rows stay intact while missing source absences are restored",
    )

    latest_absent = {
        "by_date": {},
        "by_student": {SID: "2026-08-20"},
        "by_slot": {},
    }
    earlier = makeup_rules.merge_additive_sheet_absences(
        {"by_absence": {}, "manual": {}},
        latest_absent,
        [{"date": "2026-08-10", "sid": SID, "slot": 1}],
        now="2026-08-24T00:00:00.000Z",
    )
    matrix.check(
        "M04",
        earlier["absent"]["by_student"][SID] == "2026-08-20",
        "adding an older absence never regresses the student's latest absence index",
    )

    regular = {"day1": "월12"}
    self_study = {"day1": "월자습"}
    matrix.check(
        "M05",
        makeup_rules._slots_for_absence(regular, DATE, "*") == [1, 2]
        and makeup_rules._slots_for_absence(self_study, DATE, "6시 *") == [2]
        and makeup_rules._slots_for_absence({}, DATE, "*") == [1],
        "sheet slot inference prefers regular slots then 6pm fallback then slot one",
    )


def run_makeup_route_cases(matrix: Matrix) -> None:
    with tempfile.TemporaryDirectory(prefix="verify-makeup-route-noop-") as raw:
        fixture = build_fixture(Path(raw))
        before = fixture_snapshot(fixture)
        with patched_makeup_route(fixture, []) as (client, notifications, _postcommit):
            response = client.post(
                "/api/makeup-sheet-sync",
                json={"sheetUrl": "https://docs.google.com/spreadsheets/d/test/edit", "date": DATE},
            )
        matrix.check(
            "M06",
            response.status_code == 200
            and response.get_json()["added"] == 0
            and fixture_snapshot(fixture) == before
            and notifications == [],
            "no-op makeup HTTP sync performs no transaction or notification",
        )

    route_candidates = [
        {"date": DATE, "sid": SID, "slot": 1, "cell": "*"},
        {"date": DATE, "sid": SID, "slot": 2, "cell": "*"},
    ]
    with tempfile.TemporaryDirectory(prefix="verify-makeup-route-success-") as raw:
        fixture = build_fixture(Path(raw))
        with patched_makeup_route(fixture, route_candidates) as (client, notifications, postcommit):
            response = client.post(
                "/api/makeup-sheet-sync",
                json={"sheetUrl": "https://docs.google.com/spreadsheets/d/test/edit", "date": DATE},
            )
        stored = fixture_snapshot(fixture)
        matrix.check(
            "M07",
            response.status_code == 200
            and response.get_json()["added"] == 2
            and response.get_json()["addedPairs"] == [{"date": DATE, "sid": SID}]
            and stored["absent"]["by_slot"][DATE][SID] == [1, 2]
            and set(stored["carryover"]["by_absence"][DATE]) == {f"{SID}|1", f"{SID}|2"},
            "actual makeup HTTP sync commits both slots as one new absence pair",
        )
        matrix.check(
            "M08",
            SID not in stored["updates"][DATE]
            and stored["progress"][DATE][SID]["tests"][ASSIGNED_LABEL] == "interrupted"
            and stored["logs"][DATE][SID]["assignedTests"][0]["status"] == "interrupted"
            and sqlite_entry(fixture, DATE, SID)["assignedTests"][0]["status"] == "interrupted",
            "makeup HTTP sync applies the same updates progress and dual-log cleanup",
        )
        matrix.check(
            "M09",
            notifications == [(SID,)] and postcommit == [True],
            "makeup HTTP notification occurs only after atomic commit",
        )

    with tempfile.TemporaryDirectory(prefix="verify-makeup-route-failure-") as raw:
        fixture = build_fixture(Path(raw))
        before = fixture_snapshot(fixture)
        with patched_makeup_route(fixture, route_candidates, failure_phase="logs") as (client, notifications, _postcommit):
            response = client.post(
                "/api/makeup-sheet-sync",
                json={"sheetUrl": "https://docs.google.com/spreadsheets/d/test/edit", "date": DATE},
            )
        matrix.check(
            "M10",
            response.status_code == 500
            and fixture_snapshot(fixture) == before
            and notifications == []
            and not transaction.journal_path_for(fixture["paths"]["absent"], fixture["paths"]["journal"]).exists(),
            "actual makeup HTTP failure restores every store and suppresses notification",
        )


def run_offline_cases(matrix: Matrix) -> None:
    candidates = [{"date": DATE, "sid": SID, "slot": 1, "cell": "*"}]

    with tempfile.TemporaryDirectory(prefix=".verify-offline-dry-run-", dir=ROOT) as raw:
        fixture = build_fixture(Path(raw))
        before = fixture_snapshot(fixture)
        with patched_offline_sync(fixture, candidates) as files:
            result = offline_sync.run(dry_run=True, today=dt.date.fromisoformat(DATE))
            status_exists = files["status"].exists()
            backups_exist = files["backups"].exists() and any(files["backups"].iterdir())
        matrix.check(
            "O01",
            result["dryRun"] is True
            and result["added"] == 1
            and fixture_snapshot(fixture) == before
            and not status_exists
            and not backups_exist,
            "offline dry-run reads and plans without data status or backup writes",
        )

    with tempfile.TemporaryDirectory(prefix=".verify-offline-live-", dir=ROOT) as raw:
        fixture = build_fixture(Path(raw))
        with patched_offline_sync(fixture, candidates) as files:
            result = offline_sync.run(dry_run=False, today=dt.date.fromisoformat(DATE))
            status = read_json(files["status"])
            backup_exists = bool(result["backup"]) and Path(result["backup"]).is_file()
        stored = fixture_snapshot(fixture)
        matrix.check(
            "O02",
            result["added"] == 1
            and backup_exists
            and status["ok"] is True
            and stored["absent"]["by_slot"][DATE][SID] == [1]
            and SID not in stored["updates"][DATE],
            "offline live sync backs up then commits through the real transaction and records status",
        )

    with tempfile.TemporaryDirectory(prefix=".verify-offline-failure-", dir=ROOT) as raw:
        fixture = build_fixture(Path(raw))
        before = fixture_snapshot(fixture)
        with patched_offline_sync(fixture, candidates, failure_phase="progress") as files:
            try:
                offline_sync.run(dry_run=False, today=dt.date.fromisoformat(DATE))
            except OSError:
                failed = True
            else:
                failed = False
            status_exists = files["status"].exists()
        matrix.check(
            "O03",
            failed
            and fixture_snapshot(fixture) == before
            and not status_exists
            and not transaction.journal_path_for(fixture["paths"]["absent"], fixture["paths"]["journal"]).exists(),
            "offline transaction failure restores operational stores and leaves no success status",
        )


def run_journal_cases(matrix: Matrix) -> None:
    with tempfile.TemporaryDirectory(prefix="verify-committed-journal-") as raw:
        fixture = build_fixture(Path(raw))
        original_remove = transaction._remove_journal
        transaction._remove_journal = lambda _path: None
        try:
            run_transaction(fixture)
        finally:
            transaction._remove_journal = original_remove
        pending = transaction.journal_path_for(fixture["paths"]["absent"], fixture["paths"]["journal"])
        committed_before_recovery = fixture_snapshot(fixture)
        state = read_json(pending).get("state") if pending.exists() else ""
        recovered = transaction.recover_pending_absence_transaction(
            absent_path=fixture["paths"]["absent"],
            carryover_path=fixture["paths"]["carryover"],
            updates_path=fixture["paths"]["updates"],
            progress_path=fixture["paths"]["progress"],
            log_repository_factory=fixture["repository_factory"],
            journal_dir=fixture["paths"]["journal"],
            lock_timeout_sec=5.0,
        )
        matrix.check(
            "T01",
            state == "COMMITTED"
            and bool(recovered)
            and fixture_snapshot(fixture) == committed_before_recovery
            and not pending.exists(),
            "restart cleanup removes a committed journal without rolling committed data back",
        )

    with tempfile.TemporaryDirectory(prefix="verify-journal-barrier-") as raw:
        fixture = build_fixture(Path(raw))

        def crash(phase: str) -> None:
            if phase == "logs":
                raise SyntheticCrash("synthetic process termination")

        try:
            run_transaction(fixture, crash)
        except SyntheticCrash:
            pass
        else:
            raise AssertionError("synthetic crash did not fire")
        try:
            with transaction.absence_consistency_barrier(
                absent_path=fixture["paths"]["absent"],
                journal_dir=fixture["paths"]["journal"],
                lock_timeout_sec=5.0,
            ):
                pass
        except transaction.AbsenceRecoveryRequiredError:
            blocked = True
        else:
            blocked = False
        transaction.recover_pending_absence_transaction(
            absent_path=fixture["paths"]["absent"],
            carryover_path=fixture["paths"]["carryover"],
            updates_path=fixture["paths"]["updates"],
            progress_path=fixture["paths"]["progress"],
            log_repository_factory=fixture["repository_factory"],
            journal_dir=fixture["paths"]["journal"],
            lock_timeout_sec=5.0,
        )
        matrix.check(
            "T02",
            blocked and fixture_snapshot(fixture) == fixture["initial"],
            "read barrier fails closed on unfinished journal and recovery restores before-images",
        )

    with tempfile.TemporaryDirectory(prefix="verify-invalid-transaction-") as raw:
        fixture = build_fixture(Path(raw))
        before = fixture_snapshot(fixture)
        try:
            transaction.apply_absence_transaction_locked(
                set(),
                absent_after=fixture["absent_after"],
                absent_path=fixture["paths"]["absent"],
                carryover_path=fixture["paths"]["carryover"],
                updates_path=fixture["paths"]["updates"],
                progress_path=fixture["paths"]["progress"],
                log_repository_factory=fixture["repository_factory"],
                journal_dir=fixture["paths"]["journal"],
            )
        except ValueError:
            rejected = True
        else:
            rejected = False
        noop = transaction.recover_pending_absence_transaction(
            absent_path=fixture["paths"]["absent"],
            carryover_path=fixture["paths"]["carryover"],
            updates_path=fixture["paths"]["updates"],
            progress_path=fixture["paths"]["progress"],
            log_repository_factory=fixture["repository_factory"],
            journal_dir=fixture["paths"]["journal"],
            lock_timeout_sec=5.0,
        )
        matrix.check(
            "T03",
            rejected and noop is None and fixture_snapshot(fixture) == before,
            "empty transaction and no-pending recovery are mutation-free",
        )

    from scripts.verify_absence_transaction import main as verify_transaction

    matrix.check(
        "T04",
        verify_transaction() == 0,
        "success six synchronous failures crash recovery and rollback-retry matrix passes",
    )


def main() -> int:
    matrix = Matrix()
    run_attendance_cases(matrix)
    run_self_study_absence_cases(matrix)
    run_makeup_rule_cases(matrix)
    run_makeup_route_cases(matrix)
    run_offline_cases(matrix)
    run_journal_cases(matrix)

    from scripts.verify_makeup_schedule_links import (
        test_makeup_revision_guard,
        test_scheduled_makeup_normalization,
    )
    from scripts.verify_makeup_sheet_additive_sync import (
        test_reader_hard_caps_at_row_127_and_rejects_ambiguous_matches,
    )

    try:
        test_scheduled_makeup_normalization()
        test_makeup_revision_guard()
        matrix.check("M11", True, "makeup normalization and optimistic revision guard pass")
    except Exception:
        matrix.check("M11", False, "makeup normalization and optimistic revision guard pass")

    try:
        test_reader_hard_caps_at_row_127_and_rejects_ambiguous_matches()
        matrix.check("M12", True, "sheet reader caps row 127 and rejects ambiguous student matches")
    except Exception:
        matrix.check("M12", False, "sheet reader caps row 127 and rejects ambiguous student matches")

    return matrix.finish()


if __name__ == "__main__":
    raise SystemExit(main())
