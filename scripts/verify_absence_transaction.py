from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.absence_transaction import (
    AbsenceRecoveryRequiredError,
    absence_transaction_scope,
    apply_absence_transaction_locked,
    journal_path_for,
    recover_pending_absence_transaction,
)
from core.log_repository import LogRepository
from core.storage import file_lock


DATE = "2026-08-24"
OTHER_DATE = "2026-08-25"
SID = "sid-a"
KEEP_SID = "sid-keep"
ASSIGNED_LABEL = "단원평가 / 대수 / Lv.3 / 결석 전"
DONE_LABEL = "복습 테스트 / 대수 / 완료"


class SyntheticCrash(BaseException):
    pass


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def read_json(path: Path):
    return json.loads(path.read_text("utf-8"))


def sqlite_rows(path: Path) -> list[tuple]:
    con = sqlite3.connect(path)
    try:
        return con.execute(
            "SELECT date, sid, entry_json, updated_at FROM logs ORDER BY date, sid"
        ).fetchall()
    finally:
        con.close()


def build_fixture(base: Path) -> dict:
    paths = {
        "updates": base / "updates.json",
        "progress": base / "progress.json",
        "logs": base / "logs.json",
        "db": base / "app.sqlite",
        "absent": base / "absent.json",
        "carryover": base / "makeup_carryover.json",
        "journal": base / "journal",
    }
    updates = {
        DATE: {
            SID: {"videos": ["mid-1"], "source": "auto", "unknown": "keep"},
            KEEP_SID: {"videos": ["mid-keep"], "source": "manual"},
        },
        OTHER_DATE: {SID: {"videos": ["mid-other"], "source": "auto"}},
    }
    progress = {
        DATE: {
            SID: {
                "tests": {
                    ASSIGNED_LABEL: "assigned",
                    DONE_LABEL: "done",
                },
                "unknown": {"keep": True},
            },
            KEEP_SID: {"tests": {ASSIGNED_LABEL: "assigned"}},
        },
        OTHER_DATE: {SID: {"tests": {ASSIGNED_LABEL: "assigned"}}},
    }
    logs_json = {
        DATE: {
            SID: {
                "assignedTests": [
                    {"label": ASSIGNED_LABEL, "status": "assigned", "jsonMemo": "keep"},
                    {"label": DONE_LABEL, "status": "done"},
                ],
                "notes": "상담 메모",
                "jsonOnly": "keep",
            },
            KEEP_SID: {"notes": "다른 학생"},
        },
        OTHER_DATE: {SID: {"notes": "다른 날짜"}},
    }
    absent = {
        "by_date": {OTHER_DATE: [KEEP_SID]},
        "by_student": {KEEP_SID: OTHER_DATE},
        "by_slot": {OTHER_DATE: {KEEP_SID: [1]}},
    }
    carryover = {
        "by_absence": {OTHER_DATE: {f"{KEEP_SID}|1": {"state": "carried"}}},
        "manual": {},
    }
    absent_after = copy.deepcopy(absent)
    absent_after["by_date"][DATE] = [SID]
    absent_after["by_student"][SID] = DATE
    absent_after["by_slot"][DATE] = {SID: [1]}
    carryover_after = copy.deepcopy(carryover)
    carryover_after["by_absence"][DATE] = {
        f"{SID}|1": {"state": "carried", "note": ""}
    }

    write_json(paths["updates"], updates)
    write_json(paths["progress"], progress)
    write_json(paths["logs"], logs_json)
    write_json(paths["absent"], absent)
    write_json(paths["carryover"], carryover)

    con = sqlite3.connect(paths["db"])
    try:
        con.execute(
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
        con.execute(
            "INSERT INTO logs(date, sid, entry_json, updated_at) VALUES(?,?,?,?)",
            (
                DATE,
                SID,
                json.dumps(
                    {
                        "assignedTests": [
                            {"label": ASSIGNED_LABEL, "status": "assigned", "sqliteMemo": "keep"},
                            {"label": DONE_LABEL, "status": "done"},
                        ],
                        "notes": "상담 메모",
                        "sqliteOnly": "keep",
                    },
                    ensure_ascii=False,
                ),
                "2026-08-24T00:00:00+09:00",
            ),
        )
        con.execute(
            "INSERT INTO logs(date, sid, entry_json, updated_at) VALUES(?,?,?,?)",
            (
                OTHER_DATE,
                SID,
                json.dumps({"notes": "다른 날짜"}, ensure_ascii=False),
                "2026-08-24T00:00:00+09:00",
            ),
        )
        con.commit()
    finally:
        con.close()

    def repository_factory() -> LogRepository:
        return LogRepository(
            logs_path=paths["logs"],
            db_path=str(paths["db"]),
            lock_factory=lambda: file_lock(paths["logs"], timeout_sec=5.0),
        )

    initial = {
        "updates": copy.deepcopy(updates),
        "progress": copy.deepcopy(progress),
        "logs": copy.deepcopy(logs_json),
        "sqlite": sqlite_rows(paths["db"]),
        "absent": copy.deepcopy(absent),
        "carryover": copy.deepcopy(carryover),
    }
    return {
        "paths": paths,
        "repository_factory": repository_factory,
        "initial": initial,
        "absent_after": absent_after,
        "carryover_after": carryover_after,
    }


def run_transaction(fixture: dict, failure_injector=None) -> str:
    paths = fixture["paths"]
    with absence_transaction_scope(
        absent_path=paths["absent"],
        carryover_path=paths["carryover"],
        updates_path=paths["updates"],
        progress_path=paths["progress"],
        log_repository_factory=fixture["repository_factory"],
        journal_dir=paths["journal"],
        lock_timeout_sec=5.0,
    ) as journal_dir:
        return apply_absence_transaction_locked(
            {(DATE, SID)},
            absent_after=fixture["absent_after"],
            carryover_after=fixture["carryover_after"],
            absent_path=paths["absent"],
            carryover_path=paths["carryover"],
            updates_path=paths["updates"],
            progress_path=paths["progress"],
            log_repository_factory=fixture["repository_factory"],
            journal_dir=journal_dir,
            kind="fixture",
            failure_injector=failure_injector,
        )


def assert_restored(fixture: dict) -> None:
    paths = fixture["paths"]
    initial = fixture["initial"]
    assert read_json(paths["updates"]) == initial["updates"]
    assert read_json(paths["progress"]) == initial["progress"]
    assert read_json(paths["logs"]) == initial["logs"]
    assert sqlite_rows(paths["db"]) == initial["sqlite"]
    assert read_json(paths["absent"]) == initial["absent"]
    assert read_json(paths["carryover"]) == initial["carryover"]
    assert not journal_path_for(paths["absent"], paths["journal"]).exists()
    assert not (paths["journal"] / "_data_mirror").exists()


def test_success_keeps_existing_semantics() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-absence-transaction-success-") as tmpdir:
        fixture = build_fixture(Path(tmpdir))
        transaction_id = run_transaction(fixture)
        paths = fixture["paths"]

        updates = read_json(paths["updates"])
        progress = read_json(paths["progress"])
        logs_json = read_json(paths["logs"])
        assert transaction_id
        assert SID not in updates[DATE]
        assert updates[DATE][KEEP_SID]["source"] == "manual"
        assert updates[OTHER_DATE][SID]["videos"] == ["mid-other"]
        assert progress[DATE][SID]["tests"][ASSIGNED_LABEL] == "interrupted"
        assert progress[DATE][SID]["tests"][DONE_LABEL] == "done"
        assert progress[DATE][SID]["unknown"] == {"keep": True}
        assert progress[OTHER_DATE][SID]["tests"][ASSIGNED_LABEL] == "assigned"
        assert logs_json[DATE][SID]["assignedTests"][0]["status"] == "interrupted"
        assert logs_json[DATE][SID]["jsonOnly"] == "keep"
        assert read_json(paths["absent"]) == fixture["absent_after"]
        assert read_json(paths["carryover"]) == fixture["carryover_after"]
        assert not journal_path_for(paths["absent"], paths["journal"]).exists()
        assert not (paths["journal"] / "_data_mirror").exists()

        sqlite_entry = json.loads(sqlite_rows(paths["db"])[0][2])
        assert sqlite_entry["assignedTests"][0]["status"] == "interrupted"
        assert sqlite_entry["sqliteOnly"] == "keep"
        carryover = sqlite_entry["testAssignmentAbsenceCarryover"]["assignedTests"]
        assert any(item["label"] == ASSIGNED_LABEL for item in carryover)


def test_each_synchronous_failure_rolls_every_store_back() -> None:
    phases = ("updates", "progress", "logs", "absent", "carryover", "before_commit")
    for phase in phases:
        with tempfile.TemporaryDirectory(prefix=f"verify-absence-transaction-{phase}-") as tmpdir:
            fixture = build_fixture(Path(tmpdir))

            def fail(current_phase: str, *, wanted=phase) -> None:
                if current_phase == wanted:
                    raise OSError(f"synthetic failure after {wanted}")

            try:
                run_transaction(fixture, fail)
            except OSError:
                pass
            else:
                raise AssertionError(f"failure injection did not fire: {phase}")
            assert_restored(fixture)


def test_crash_journal_recovers_to_before_state() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-absence-transaction-crash-") as tmpdir:
        fixture = build_fixture(Path(tmpdir))
        paths = fixture["paths"]

        def crash(phase: str) -> None:
            if phase == "logs":
                raise SyntheticCrash("synthetic process termination")

        try:
            run_transaction(fixture, crash)
        except SyntheticCrash:
            pass
        else:
            raise AssertionError("synthetic crash did not fire")

        pending = journal_path_for(paths["absent"], paths["journal"])
        assert pending.exists()
        assert read_json(paths["updates"]) != fixture["initial"]["updates"]

        recovered_id = recover_pending_absence_transaction(
            absent_path=paths["absent"],
            carryover_path=paths["carryover"],
            updates_path=paths["updates"],
            progress_path=paths["progress"],
            log_repository_factory=fixture["repository_factory"],
            journal_dir=paths["journal"],
            lock_timeout_sec=5.0,
        )
        assert recovered_id
        assert_restored(fixture)


def test_failed_rollback_stays_recoverable_and_fails_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-absence-transaction-retry-") as tmpdir:
        fixture = build_fixture(Path(tmpdir))
        paths = fixture["paths"]
        good_factory = fixture["repository_factory"]
        restore_attempts = 0

        class FailOnceRepository:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def restore_entries_raw(self, snapshot, *, json_lock_held=False):
                nonlocal restore_attempts
                restore_attempts += 1
                if restore_attempts == 1:
                    raise OSError("synthetic rollback failure")
                return self.inner.restore_entries_raw(
                    snapshot,
                    json_lock_held=json_lock_held,
                )

        def fail_once_factory():
            return FailOnceRepository(good_factory())

        fixture["repository_factory"] = fail_once_factory

        def fail(phase: str) -> None:
            if phase == "progress":
                raise OSError("synthetic write failure")

        try:
            run_transaction(fixture, fail)
        except AbsenceRecoveryRequiredError:
            pass
        else:
            raise AssertionError("rollback failure must fail closed")

        pending = journal_path_for(paths["absent"], paths["journal"])
        assert pending.exists()
        assert read_json(pending)["state"] == "RECOVERY_REQUIRED"

        recover_pending_absence_transaction(
            absent_path=paths["absent"],
            carryover_path=paths["carryover"],
            updates_path=paths["updates"],
            progress_path=paths["progress"],
            log_repository_factory=good_factory,
            journal_dir=paths["journal"],
            lock_timeout_sec=5.0,
        )
        fixture["repository_factory"] = good_factory
        assert_restored(fixture)


def main() -> int:
    test_success_keeps_existing_semantics()
    test_each_synchronous_failure_rolls_every_store_back()
    test_crash_journal_recovers_to_before_state()
    test_failed_rollback_stays_recoverable_and_fails_closed()
    print("absence transaction rollback and recovery checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
