from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import student_test_ocr_assets as assets
from core.student_test_ocr_maintenance import StudentTestOcrMaintenance
from core.student_test_ocr_repository import StudentTestOcrRepository


KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime(2026, 10, 4, 0, 0, tzinfo=KST)
MIGRATION = ROOT / "scripts/migrations/20260828_create_student_test_ocr.sql"
JPEG = b"\xff\xd8\xff\xe0" + b"temporary-capture" * 4


def empty_page(*args, **kwargs) -> dict:
    return {"examined": 0, "deleted": (), "failed": (), "busy": (), "lastId": None}


def overdue_row(identity: str = "pending-1") -> dict:
    return {"id": identity, "sid": "student-1", "test_id": "test-1", "round_no": "1",
            "assignment_date": "2026-10-03", "pendingQuestionNos": [1, 2], "expiredCropCount": 1}


class FakeRepository:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = []
        self.fail = False

    def list_overdue_pending(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("private answer and C:/private/student.png")
        return [row for row in self.rows if row["id"] > kwargs["after_id"]][:kwargs["limit"]]


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(prefix="ocr-maintenance-") as directory:
        root = Path(directory)
        repository = StudentTestOcrRepository(root / "app.sqlite")
        repository.apply_migration(MIGRATION.read_text(encoding="utf-8"))
        yield repository, root / "assets"


def submission(repository, identity="sub-1", date="2026-10-03"):
    repository.begin_submission(
        submission_id=identity, idempotency_key="idem-" + identity, request_hash="hash-" + identity,
        sid="student-1", test_id="test-" + identity, round_no="1", assignment_date=date,
        answer_modes=["answer_value"] * 20, now=(NOW - dt.timedelta(days=7)).isoformat(timespec="seconds"),
    )


def capture(repository, root, identity="asset-1", owner="sub-1"):
    return assets.store_and_register_capture(
        repository, root=root, asset_id=identity, submission_id=owner, question_no=1,
        kind="student_crop", content=JPEG, created_at=NOW - dt.timedelta(days=7),
    )


def pending(repository, identity, date, *, status="pending_teacher"):
    submission(repository, identity, date)
    with closing(sqlite3.connect(repository.db_path)) as connection:
        with connection:
            connection.execute("UPDATE student_test_ocr_submissions SET status=? WHERE id=?", (status, identity))
            connection.execute(
                "UPDATE student_test_ocr_questions SET effective_grade='pending',initial_grade='pending',"
                "initial_raw_answer='private handwritten value',current_raw_answer='private current value',"
                "crop_relpath='private/current.jpg',crop_expires_at=? "
                "WHERE submission_id=? AND question_no=1",
                (NOW.isoformat(timespec="seconds"), identity),
            )


def digest_files(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


class MaintenanceChecks(unittest.TestCase):
    def make_runner(self, repository=None, **kwargs):
        runner = StudentTestOcrMaintenance(
            repository or FakeRepository(), Path(tempfile.gettempdir()) / "unused-ocr-maintenance",
            kwargs.pop("clock", lambda: NOW), **kwargs,
        )
        self.addCleanup(runner.shutdown)
        return runner

    def test_constructor_is_inert_and_options_are_strict(self):
        repository = FakeRepository()
        with patch.object(assets, "purge_expired_asset_page") as purge:
            runner = self.make_runner(repository)
            self.assertEqual(runner.snapshot()["status"], "not_started")
            self.assertFalse(runner.snapshot()["executionEnabled"])
            purge.assert_not_called()
            self.assertEqual(repository.calls, [])
        for name, value in (("interval_seconds", 0), ("interval_seconds", True),
                            ("interval_seconds", float("nan")), ("page_size", True),
                            ("page_size", 501), ("maximum_pages", 0)):
            with self.assertRaises(ValueError):
                self.make_runner(**{name: value})

    def test_inspect_has_no_file_or_database_mutation(self):
        with fixture() as (repository, root):
            pending(repository, "old-pending", "2026-10-03")
            pending(repository, "today-pending", "2026-10-04")
            capture(repository, root, owner="old-pending")
            before = digest_files(root.parent)
            runner = StudentTestOcrMaintenance(repository, root, lambda: NOW)
            try:
                report = runner.inspect()
                self.assertEqual(report["overdue"]["returnedSubmissionCount"], 1)
                self.assertEqual(report["overdue"]["submissions"][0]["submissionId"], "old-pending")
                self.assertEqual(report["overdue"]["returnedExpiredCropCount"], 1)
                self.assertFalse(report["executionEnabled"])
                self.assertEqual(report["retention"],
                                 {"examined": 0, "deletedCount": 0, "failedCount": 0,
                                  "busyCount": 0, "pages": 0, "partial": False})
                self.assertEqual(before, digest_files(root.parent))
                self.assertEqual(runner.snapshot()["status"], "not_started")
                self.assertNotIn("private", json.dumps(report))
            finally:
                runner.shutdown()

    def test_exact_seven_day_boundary_and_history_preservation(self):
        with fixture() as (repository, root):
            pending(repository, "sub-1", "2026-10-03")
            stored = capture(repository, root)
            previous = repository.get("sub-1")
            clock = [NOW - dt.timedelta(seconds=1)]
            runner = StudentTestOcrMaintenance(repository, root, lambda: clock[0])
            try:
                self.assertEqual(runner.run_once()["retention"]["deletedCount"], 0)
                self.assertTrue(Path(stored["absolute_path"]).is_file())
                clock[0] = NOW
                report = runner.run_once()
                self.assertEqual(report["retention"]["deletedCount"], 1)
                self.assertFalse(Path(stored["absolute_path"]).exists())
                self.assertEqual(repository.get_asset("asset-1")["deleted_at"], "2026-10-04T00:00:00+09:00")
                self.assertEqual(repository.get("sub-1"), previous)
                self.assertEqual(runner.run_once()["retention"]["deletedCount"], 0)
            finally:
                runner.shutdown()

    def test_active_lease_is_busy_then_retryable(self):
        with fixture() as (repository, root):
            submission(repository)
            stored = capture(repository, root)
            repository.enqueue_job(job_id="job-1", submission_id="sub-1", payload={"schema": "verifier"},
                                   now=NOW.isoformat(timespec="seconds"))
            repository.lease_next_job(lease_token="lease-1", now=NOW.isoformat(timespec="seconds"),
                                      lease_expires_at=(NOW + dt.timedelta(minutes=1)).isoformat(timespec="seconds"))
            runner = StudentTestOcrMaintenance(repository, root, lambda: NOW)
            try:
                report = runner.run_once()
                self.assertEqual(report["retention"]["busyCount"], 1)
                self.assertTrue(report["retention"]["partial"])
                self.assertTrue(Path(stored["absolute_path"]).is_file())
                self.assertIsNone(repository.get_asset("asset-1")["deleted_at"])
                repository.finish_job("job-1", lease_token="lease-1", succeeded=False, result=None,
                                      error_code="verifier", now=NOW.isoformat(timespec="seconds"))
                self.assertEqual(runner.run_once()["retention"]["deletedCount"], 1)
            finally:
                runner.shutdown()

    def test_first_hundred_bad_rows_do_not_starve_tail(self):
        with fixture() as (repository, root):
            submission(repository)
            for index in range(1, 101):
                repository.register_asset(
                    asset_id=f"a{index:03d}", submission_id="sub-1", question_no=1, kind="student_crop",
                    relative_path=f"bad:ads-{index}", expires_at=NOW.isoformat(timespec="seconds"),
                    created_at=(NOW - dt.timedelta(days=7)).isoformat(timespec="seconds"),
                )
            stored = capture(repository, root, identity="a101")
            runner = StudentTestOcrMaintenance(repository, root, lambda: NOW, maximum_pages=1)
            try:
                first = runner.run_once()
                self.assertEqual(first["retention"]["failedCount"], 100)
                self.assertTrue(first["retention"]["partial"])
                second = runner.run_once()
                self.assertEqual(second["retention"]["deletedCount"], 1)
                self.assertFalse(Path(stored["absolute_path"]).exists())
                self.assertEqual(runner.run_once()["retention"]["failedCount"], 100)
                self.assertIsNone(repository.get_asset("a001")["deleted_at"])
            finally:
                runner.shutdown()

    def test_file_deleted_commit_failure_retries_missing_file(self):
        with fixture() as (repository, root):
            submission(repository)
            stored = capture(repository, root)
            runner = StudentTestOcrMaintenance(repository, root, lambda: NOW)
            original_write = repository._write

            def fail_after_action(action):
                def fail(connection):
                    action(connection)
                    raise RuntimeError("private C:/student/crop.jpg")
                return original_write(fail)

            try:
                with patch.object(repository, "_write", fail_after_action):
                    report = runner.run_once()
                self.assertEqual(report["retention"]["failedCount"], 1)
                self.assertFalse(Path(stored["absolute_path"]).exists())
                self.assertIsNone(repository.get_asset("asset-1")["deleted_at"])
                self.assertNotIn("private", json.dumps(report))
                self.assertEqual(runner.run_once()["retention"]["deletedCount"], 1)
                self.assertIsNotNone(repository.get_asset("asset-1")["deleted_at"])
            finally:
                runner.shutdown()

    def test_overdue_is_read_only_and_excludes_today_future_finalized(self):
        with fixture() as (repository, root):
            pending(repository, "old", "2026-10-03")
            pending(repository, "today", "2026-10-04")
            pending(repository, "future", "2026-10-05")
            pending(repository, "final", "2026-10-02", status="finalized")
            before = [repository.get(identity) for identity in ("old", "today", "future", "final")]
            runner = StudentTestOcrMaintenance(repository, root, lambda: NOW)
            try:
                report = runner.inspect()
                self.assertEqual([row["submissionId"] for row in report["overdue"]["submissions"]], ["old"])
                self.assertEqual([repository.get(identity) for identity in ("old", "today", "future", "final")], before)
            finally:
                runner.shutdown()

    def test_utc_clock_normalizes_kst_midnight(self):
        repository = FakeRepository([overdue_row()])
        runner = self.make_runner(repository, clock=lambda: dt.datetime(2026, 10, 3, 15, tzinfo=dt.timezone.utc))
        report = runner.inspect()
        self.assertEqual(report["checkedAt"], "2026-10-04T00:00:00+09:00")
        self.assertEqual(repository.calls[0]["before_date"], "2026-10-04")
        self.assertEqual(repository.calls[0]["now"], "2026-10-04T00:00:00+09:00")

    def test_errors_are_redacted_and_independent_checks_continue(self):
        repository = FakeRepository([overdue_row()])
        runner = self.make_runner(repository)
        with patch.object(assets, "purge_expired_asset_page", side_effect=RuntimeError("private /students/photo.jpg")):
            report = runner.run_once()
        self.assertEqual(report["errorCodes"], ["asset_retention_failed"])
        self.assertEqual(report["overdue"]["returnedSubmissionCount"], 1)
        self.assertNotIn("private", json.dumps(report))
        repository.fail = True
        with patch.object(assets, "purge_expired_asset_page", empty_page):
            report = runner.run_once()
        self.assertEqual(report["errorCodes"], ["overdue_review_failed"])
        self.assertNotIn("private", json.dumps(report))

    def test_transient_tick_error_retries_next_time(self):
        runner = self.make_runner()
        with patch.object(assets, "purge_expired_asset_page",
                          side_effect=[RuntimeError("private"), empty_page()]):
            self.assertEqual(runner.run_once()["status"], "error")
            self.assertEqual(runner.run_once()["status"], "ok")

    def test_simultaneous_tick_is_busy_without_overlap(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def blocked(*args, **kwargs):
            calls.append(kwargs["after_id"])
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test release timeout")
            return empty_page()

        runner = self.make_runner()
        with patch.object(assets, "purge_expired_asset_page", blocked):
            worker = threading.Thread(target=runner.run_once)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(runner.run_once()["status"], "busy")
                self.assertEqual(calls, [""])
            finally:
                release.set()
                worker.join(2)
            self.assertFalse(worker.is_alive())

    def test_start_is_concurrently_idempotent_and_shutdown_waits(self):
        entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
        starts = threading.Barrier(3)
        calls = []
        repository = FakeRepository()

        def blocked(*args, **kwargs):
            calls.append(1)
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test release timeout")
            return empty_page()

        runner = self.make_runner(repository, interval_seconds=60)

        def start():
            starts.wait()
            runner.start()

        with patch.object(assets, "purge_expired_asset_page", blocked):
            callers = [threading.Thread(target=start) for _ in range(2)]
            for caller in callers:
                caller.start()
            starts.wait()
            for caller in callers:
                caller.join(2)
            closer = threading.Thread(target=lambda: (runner.shutdown(), stopped.set()))
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(calls, [1])
                closer.start()
                self.assertFalse(stopped.wait(0.03))
            finally:
                release.set()
                closer.join(2)
            self.assertTrue(stopped.is_set())
            self.assertEqual(repository.calls, [])
            self.assertEqual(runner.run_once()["status"], "closed")
            runner.start()
            self.assertEqual(calls, [1])

    def test_shutdown_waits_for_manually_started_tick(self):
        entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
        runner = self.make_runner()

        def blocked(*args, **kwargs):
            entered.set()
            release.wait(2)
            return empty_page()

        with patch.object(assets, "purge_expired_asset_page", blocked):
            tick = threading.Thread(target=runner.run_once)
            closer = threading.Thread(target=lambda: (runner.shutdown(), stopped.set()))
            tick.start()
            try:
                self.assertTrue(entered.wait(2))
                closer.start()
                self.assertFalse(stopped.wait(0.03))
            finally:
                release.set()
                tick.join(2)
                closer.join(2)
            self.assertTrue(stopped.is_set())
            self.assertEqual(runner.run_once()["status"], "closed")

    def test_scheduler_retries_and_new_lifetime_catches_up_immediately(self):
        failed, recovered = threading.Event(), threading.Event()
        calls = []

        def retry(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                failed.set()
                raise RuntimeError("private")
            recovered.set()
            return empty_page()

        runner = self.make_runner(interval_seconds=0.02)
        with patch.object(assets, "purge_expired_asset_page", retry):
            runner.start()
            self.assertTrue(failed.wait(2))
            self.assertTrue(recovered.wait(2))
            runner.shutdown()
            count = len(calls)
            next_runner = self.make_runner(interval_seconds=60)
            recovered.clear()
            next_runner.start()
            self.assertTrue(recovered.wait(2))
            next_runner.shutdown()
            self.assertEqual(len(calls), count + 1)

    def test_bounded_overdue_counts_are_explicitly_partial(self):
        rows = [overdue_row(f"pending-{number}") for number in range(1, 6)]
        rows[0]["initial_raw_answer"] = "private answer"
        runner = self.make_runner(FakeRepository(rows), page_size=2, maximum_pages=1)
        report = runner.inspect()
        self.assertTrue(report["overdue"]["partial"])
        self.assertEqual(report["overdue"]["returnedSubmissionCount"], 2)
        self.assertEqual(report["overdue"]["returnedQuestionCount"], 4)
        self.assertNotIn("private answer", json.dumps(report))
        self.assertNotIn("totalCount", report["overdue"])

    def test_inspect_does_not_change_cursor_latest_or_scheduler(self):
        repository = FakeRepository([overdue_row()])
        runner = self.make_runner(repository, page_size=1, maximum_pages=1)
        received = []

        def pages(*args, **kwargs):
            received.append(kwargs["after_id"])
            return {"examined": 1, "deleted": (), "failed": ("asset-a",), "busy": (), "lastId": "asset-a"} \
                if kwargs["after_id"] == "" else empty_page()

        with patch.object(assets, "purge_expired_asset_page", pages):
            first = runner.run_once()
            before = runner.snapshot()
            inspected = runner.inspect()
            self.assertFalse(inspected["executionEnabled"])
            self.assertEqual(runner.snapshot(), before)
            runner.run_once()
        self.assertEqual(received, ["", "asset-a"])
        first["errorCodes"].append("caller mutation")
        self.assertNotIn("caller mutation", runner.snapshot()["errorCodes"])
        snapshot = runner.snapshot()
        snapshot["overdue"]["submissions"].clear()
        self.assertEqual(runner.snapshot()["overdue"]["returnedSubmissionCount"], 1)

    def test_invalid_clock_is_redacted_and_never_checks_storage(self):
        repository = FakeRepository()
        runner = self.make_runner(repository, clock=lambda: dt.datetime(2026, 10, 4))
        with patch.object(assets, "purge_expired_asset_page") as purge:
            report = runner.run_once()
            self.assertEqual(report["errorCodes"], ["invalid_clock"])
            self.assertTrue(report["retention"]["partial"])
            self.assertTrue(report["overdue"]["partial"])
            inspection = runner.inspect()
            self.assertFalse(inspection["executionEnabled"])
            purge.assert_not_called()
            self.assertEqual(repository.calls, [])

    def test_bad_projection_is_a_redacted_error(self):
        row = overdue_row()
        row["pendingQuestionNos"] = [True]
        runner = self.make_runner(FakeRepository([row]))
        report = runner.inspect()
        self.assertEqual(report["errorCodes"], ["overdue_review_failed"])
        self.assertTrue(report["overdue"]["partial"])


def run() -> dict:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MaintenanceChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    return {"name": "student-test-ocr-maintenance", "tests": result.testsRun, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['tests']} tests")
