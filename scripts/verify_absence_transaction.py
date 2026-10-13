from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.absence_transaction import (
    AbsenceRecoveryRequiredError,
    absence_consistency_barrier,
    absence_transaction_scope,
    apply_absence_transaction_locked,
    journal_path_for,
    recover_pending_absence_transaction,
)
from core.log_repository import LogRepository
from core.request_consistency import absence_barrier_mode
import core.absence_transaction as transaction_module
from core.storage import InterProcessFileLock, file_lock


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


def test_crash_journal_recovers_to_before_state(*, legacy_pretty=False) -> None:
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
        if legacy_pretty:
            write_json(pending, read_json(pending))
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


def test_lock_release_retries_a_transient_windows_remove_failure() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-lock-release-retry-") as tmpdir:
        lock_path = Path(tmpdir) / "coordinator.lock"
        lock = InterProcessFileLock(str(lock_path), poll_sec=0.001)
        lock.acquire()
        original_remove = os.remove
        remove_attempts = 0

        def flaky_remove(path) -> None:
            nonlocal remove_attempts
            remove_attempts += 1
            if remove_attempts == 1:
                raise PermissionError("synthetic transient sharing violation")
            original_remove(path)

        with mock.patch("core.storage.os.remove", side_effect=flaky_remove):
            lock.release()

        assert remove_attempts == 2
        assert not lock_path.exists()


def test_active_same_process_lock_is_never_broken_as_stale() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-active-local-lock-") as tmpdir:
        lock_path = Path(tmpdir) / "coordinator.lock"
        owner = InterProcessFileLock(
            str(lock_path),
            timeout_sec=0.2,
            poll_sec=0.005,
            stale_sec=0.01,
        )
        owner.acquire()
        old = time.time() - 60
        os.utime(lock_path, (old, old))
        contender = InterProcessFileLock(
            str(lock_path),
            timeout_sec=0.05,
            poll_sec=0.005,
            stale_sec=0.01,
        )
        try:
            try:
                contender.acquire()
            except TimeoutError:
                pass
            else:
                contender.release()
                raise AssertionError("an active same-process lock must not be broken")
        finally:
            owner.release()
        assert not lock_path.exists()


def test_failed_release_same_process_orphan_is_recovered() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-local-lock-orphan-") as tmpdir:
        lock_path = Path(tmpdir) / "coordinator.lock"
        owner = InterProcessFileLock(str(lock_path), poll_sec=0.001)
        owner.acquire()

        with mock.patch(
            "core.storage.os.remove",
            side_effect=PermissionError("synthetic persistent sharing violation"),
        ):
            owner.release()

        assert lock_path.exists()
        old = time.time() - 5
        os.utime(lock_path, (old, old))

        contender = InterProcessFileLock(
            str(lock_path),
            timeout_sec=0.2,
            poll_sec=0.005,
            stale_sec=30.0,
        )
        contender.acquire()
        contender.release()
        assert not lock_path.exists()


def test_consistency_barrier_is_reentrant_in_one_context() -> None:
    with tempfile.TemporaryDirectory(
        prefix="verify-absence-barrier-reentrant-"
    ) as tmpdir:
        root = Path(tmpdir)
        absent_path = root / "absent.json"
        journal_dir = root / "journal"
        write_json(absent_path, {})

        with absence_consistency_barrier(
            absent_path=absent_path,
            journal_dir=journal_dir,
            lock_timeout_sec=0.2,
        ):
            with absence_consistency_barrier(
                absent_path=absent_path,
                journal_dir=journal_dir,
                lock_timeout_sec=0.2,
            ):
                assert not journal_path_for(
                    absent_path,
                    journal_dir,
                ).exists()


def test_compact_journal_preserves_payload() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-compact-absence-journal-") as tmp:
        path = Path(tmp) / "pending.json"
        journal = {"version": 1, "state": "PREPARED", "unknown": {"한글": ["보존"] * 40}}
        with mock.patch.object(transaction_module, "_utc_now", return_value="2026-10-03T00:00:00Z"):
            transaction_module._write_journal(path, journal)
        assert transaction_module._read_journal(path) == {
            "version": 1, "state": "PREPARED", "unknown": {"한글": ["보존"] * 40},
            "updatedAt": "2026-10-03T00:00:00Z",
        }
        assert len(path.read_bytes()) < len(json.dumps(journal, ensure_ascii=False, indent=2).encode("utf-8"))
        assert not (path.parent / "_data_mirror").exists()


def test_storage_only_readers_preserve_writer_exclusion() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-absence-read-cohort-") as tmp:
        root = Path(tmp)
        absent = root / "absent.json"
        journal = root / "journal"
        write_json(absent, {})
        entered = [threading.Event(), threading.Event()]
        released = [threading.Event(), threading.Event()]
        start = threading.Barrier(3)
        writer_entered = threading.Event()

        def reader(index, path, query):
            mode = absence_barrier_mode(path, "GET", query)
            assert mode == "shared"
            start.wait(timeout=2)
            with absence_consistency_barrier(absent_path=absent, journal_dir=journal,
                                             lock_timeout_sec=2, shared=mode == "shared"):
                entered[index].set()
                assert released[index].wait(timeout=3)

        def writer():
            assert absence_barrier_mode("/api/progress/patch", "POST", {}) == "exclusive"
            with absence_consistency_barrier(absent_path=absent, journal_dir=journal, lock_timeout_sec=2):
                writer_entered.set()

        with ThreadPoolExecutor(max_workers=3) as pool:
            readers = [pool.submit(reader, 0, "/api/makeup-carryover", {}),
                       pool.submit(reader, 1, "/api/updates", {"readOnly": "true"})]
            try:
                start.wait(timeout=2)
                assert all(event.wait(timeout=2) for event in entered), "both storage-only readers join"
                writing = pool.submit(writer)
                assert not writer_entered.wait(timeout=0.05), "writer cannot bypass active readers"
                released[0].set()
                readers[0].result(timeout=1)
                assert not writer_entered.wait(timeout=0.05), "last reader still owns the lease"
                released[1].set()
                readers[1].result(timeout=1)
                writing.result(timeout=2)
                assert writer_entered.is_set()
            finally:
                released[0].set()
                released[1].set()
        assert read_json(absent) == {}
        write_json(journal_path_for(absent, journal), {"version": 1, "state": "PREPARED"})
        try:
            with absence_consistency_barrier(absent_path=absent, journal_dir=journal, shared=True):
                raise AssertionError("shared reads must reject a pending journal")
        except AbsenceRecoveryRequiredError:
            pass


def main() -> int:
    test_success_keeps_existing_semantics()
    test_each_synchronous_failure_rolls_every_store_back()
    test_crash_journal_recovers_to_before_state()
    test_crash_journal_recovers_to_before_state(legacy_pretty=True)
    test_compact_journal_preserves_payload()
    test_storage_only_readers_preserve_writer_exclusion()
    test_failed_rollback_stays_recoverable_and_fails_closed()
    test_lock_release_retries_a_transient_windows_remove_failure()
    test_active_same_process_lock_is_never_broken_as_stale()
    test_failed_release_same_process_orphan_is_recovered()
    test_consistency_barrier_is_reentrant_in_one_context()
    print("absence transaction rollback and recovery checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
