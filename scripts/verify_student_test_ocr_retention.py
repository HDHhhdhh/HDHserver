"""OS-temp retention, lease exclusion, safe-path and read-only overdue oracles."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from core.student_test_ocr_assets import _unlink_registered_asset, purge_expired_asset_page, OcrAssetError
from core.student_test_ocr_repository import StudentTestOcrRepository
from core.student_test_ocr_maintenance import StudentTestOcrMaintenance
from core.student_test_ocr_service import StudentTestOcrService, StudentTestOcrServiceError

KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime(2026, 10, 4, 0, 0, tzinfo=KST)
CREATED = "2026-09-27T00:00:00+09:00"
MIGRATION = Path(__file__).resolve().parent / "migrations/20260828_create_student_test_ocr.sql"


class RetentionChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-retention-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / "images"
        self.assets.mkdir()
        self.db = self.root / "test.sqlite"
        self.repo = StudentTestOcrRepository(self.db)
        self.repo.apply_migration(MIGRATION.read_text(encoding="utf-8"))
        self.submission("s")

    def sql(self, query, values=()):
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute(query, values)
            connection.commit()

    def submission(self, identifier, date="2026-10-03"):
        self.repo.begin_submission(
            submission_id=identifier, idempotency_key=identifier, request_hash=identifier,
            sid=identifier, test_id="unit", round_no="1", assignment_date=date,
            answer_modes=["answer_value"] * 20, now=CREATED,
        )

    def asset(self, identifier="a", path="s/a.jpg", expiry=None, submission="s"):
        expiry = expiry or NOW.isoformat(timespec="seconds")
        self.repo.register_asset(
            asset_id=identifier, submission_id=submission, question_no=1, kind="student_crop",
            relative_path=path, expires_at=expiry, created_at=CREATED,
        )
        target = self.assets / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic registered image")
        return target

    def job(self, now=CREATED):
        return self.repo.enqueue_job(job_id="job", submission_id="s", payload={}, now=now)

    def purge(self, now=NOW, **kwargs):
        return purge_expired_asset_page(self.repo, root=self.assets, now=now, **kwargs)

    def test_exact_seven_days_and_utc_instant(self):
        target = self.asset(expiry="2026-10-03T15:00:00+00:00")
        self.assertEqual(self.purge(NOW-dt.timedelta(seconds=1))["examined"], 0)
        result = self.purge(NOW.astimezone(dt.timezone.utc))
        self.assertEqual(result["deleted"], ("a",))
        self.assertFalse(target.exists())
        self.assertEqual(self.repo.get_asset("a")["deleted_at"], "2026-10-04T00:00:00+09:00")
        self.assertEqual(self.purge()["examined"], 0)

    def test_current_row_expiry_rechecked(self):
        self.asset()
        rows = self.repo.expired_assets(now=NOW.isoformat())
        self.assertEqual(len(rows), 1)
        self.sql("UPDATE student_test_ocr_assets SET expires_at=? WHERE id='a'",
                 ((NOW+dt.timedelta(days=1)).isoformat(),))
        called = []
        state = self.repo.purge_expired_asset("a", now=NOW.isoformat(), unlink=lambda row: called.append(row))
        self.assertEqual((state, called), ("not_due", []))
        self.assertIsNone(self.repo.get_asset("a")["deleted_at"])

    def test_running_lease_is_skipped_then_expiry_is_retryable(self):
        target = self.asset()
        self.job()
        self.repo.lease_next_job(lease_token="owner", now=NOW.isoformat(),
                                lease_expires_at=(NOW+dt.timedelta(seconds=1)).isoformat())
        self.assertEqual(self.purge()["busy"], ("a",))
        self.assertTrue(target.exists())
        self.assertEqual(self.purge(NOW+dt.timedelta(seconds=1))["deleted"], ("a",))

    def test_delete_transaction_excludes_new_lease(self):
        target = self.asset()
        self.job()
        entered, release, acquired = threading.Event(), threading.Event(), threading.Event()
        results, errors = [], []

        def unlink(row):
            entered.set()
            if not release.wait(5):
                raise AssertionError("release timed out")
            _unlink_registered_asset(self.assets, row["relative_path"])

        def deletion():
            try:
                results.append(self.repo.purge_expired_asset("a", now=NOW.isoformat(), unlink=unlink))
            except Exception as error:
                errors.append(error)

        def leasing():
            try:
                results.append(self.repo.lease_next_job(
                    lease_token="new-owner", now=NOW.isoformat(),
                    lease_expires_at=(NOW+dt.timedelta(seconds=10)).isoformat(),
                ))
                acquired.set()
            except Exception as error:
                errors.append(error)

        deleter = threading.Thread(target=deletion)
        leaser = threading.Thread(target=leasing)
        deleter.start()
        self.assertTrue(entered.wait(5))
        leaser.start()
        try:
            self.assertFalse(acquired.wait(0.15))
        finally:
            release.set()
            deleter.join(5)
            leaser.join(5)
        self.assertFalse(deleter.is_alive() or leaser.is_alive())
        self.assertEqual(errors, [])
        self.assertFalse(target.exists())
        self.assertTrue(acquired.is_set())
        self.assertIsNotNone(self.repo.get_asset("a")["deleted_at"])

    def test_unlink_failure_retries_without_tombstone(self):
        target = self.asset()
        with patch("core.student_test_ocr_assets._unlink_registered_asset", side_effect=PermissionError()):
            self.assertEqual(self.purge()["failed"], ("a",))
        self.assertTrue(target.exists())
        self.assertIsNone(self.repo.get_asset("a")["deleted_at"])
        self.assertEqual(self.purge()["deleted"], ("a",))

    def test_deleted_file_failed_db_update_then_missing_retry(self):
        target = self.asset()
        self.sql("CREATE TRIGGER fail_tombstone BEFORE UPDATE OF deleted_at "
                 "ON student_test_ocr_assets BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        self.assertEqual(self.purge()["failed"], ("a",))
        self.assertFalse(target.exists())
        self.assertIsNone(self.repo.get_asset("a")["deleted_at"])
        self.sql("DROP TRIGGER fail_tombstone")
        self.assertEqual(self.purge()["deleted"], ("a",))

    def test_failed_first_page_does_not_hide_tail(self):
        for index in range(101):
            self.asset(f"a{index:03}", f"s/a{index:03}.jpg")
        original = _unlink_registered_asset
        def unlink(root, relative):
            if relative != "s/a100.jpg":
                raise PermissionError("injected")
            original(root, relative)
        with patch("core.student_test_ocr_assets._unlink_registered_asset", side_effect=unlink):
            first = self.purge(limit=100)
            second = self.purge(limit=100, after_id=first["lastId"])
        self.assertEqual(len(first["failed"]), 100)
        self.assertEqual(second["deleted"], ("a100",))

    def test_absolute_ads_traversal_and_directory_are_rejected(self):
        outside = self.root / "outside.jpg"
        outside.write_bytes(b"preserve")
        for relative in ("", "../outside.jpg", "/outside.jpg", "C:/outside.jpg",
                         "s/a.jpg:stream", r"\\host\share\file", "s//a.jpg", "s/./a.jpg"):
            with self.subTest(relative=relative), self.assertRaises(OcrAssetError):
                _unlink_registered_asset(self.assets, relative)
        directory = self.assets / "s"
        directory.mkdir(exist_ok=True)
        with self.assertRaises(OcrAssetError):
            _unlink_registered_asset(self.assets, "s")
        self.assertEqual(outside.read_bytes(), b"preserve")

    def test_internal_and_external_symlinks_are_rejected(self):
        protected = self.assets / "protected.jpg"
        protected.write_bytes(b"preserve internal")
        external = self.root / "external.jpg"
        external.write_bytes(b"preserve external")
        for index, target in enumerate((protected, external)):
            link = self.assets / f"link{index}.jpg"
            try:
                link.symlink_to(target)
            except OSError as error:
                self.skipTest(f"OS does not permit symlink creation: {type(error).__name__}")
            with self.assertRaises(OcrAssetError):
                _unlink_registered_asset(self.assets, link.name)
            self.assertTrue(link.is_symlink() and target.exists())

    def test_reparse_attribute_is_rejected(self):
        target = self.asset()
        native_lstat = Path.lstat
        class ReparseStat:
            st_mode = 0o100644
            st_file_attributes = 1024
        def lstat(path, *args, **kwargs):
            return ReparseStat() if path == target else native_lstat(path, *args, **kwargs)
        with patch.object(Path, "lstat", lstat), self.assertRaises(OcrAssetError):
            _unlink_registered_asset(self.assets, "s/a.jpg")
        self.assertTrue(target.exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction oracle")
    def test_native_junction_parent_and_root_are_rejected(self):
        protected_dir = self.root / "protected"
        protected_dir.mkdir()
        protected = protected_dir / "keep.jpg"
        protected.write_bytes(b"preserve junction target")
        link = self.assets / "junction"
        command = "New-Item -ItemType Junction -Path '{}' -Target '{}' -ErrorAction Stop | Out-Null".format(
            str(link).replace("'", "''"), str(protected_dir).replace("'", "''"),
        )
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, "temporary junction creation failed")
        with self.assertRaises(OcrAssetError):
            _unlink_registered_asset(self.assets, "junction/keep.jpg")
        with self.assertRaises(OcrAssetError):
            _unlink_registered_asset(link, "keep.jpg")
        self.assertEqual(protected.read_bytes(), b"preserve junction target")

    def test_admin_crop_access_uses_same_instant_and_rejects_invalid_expiry(self):
        target = self.asset(expiry=(NOW+dt.timedelta(seconds=1)).astimezone(dt.timezone.utc).isoformat())
        service = StudentTestOcrService(
            repository=self.repo, job_runner=SimpleNamespace(), asset_root=self.assets,
            tests_config_loader=lambda: {}, progress_loader=lambda: {},
            log_entry_loader=lambda *_: {}, catalog_revision=lambda _: "",
            answer_url_resolver=lambda _: "", clock=lambda: NOW,
        )
        self.assertEqual(service.admin_asset_path(asset_id="a"), target.resolve())
        self.sql("UPDATE student_test_ocr_assets SET expires_at=? WHERE id='a'",
                 (NOW.astimezone(dt.timezone.utc).isoformat(),))
        with self.assertRaises(StudentTestOcrServiceError) as expired:
            service.admin_asset_path(asset_id="a")
        self.assertEqual((expired.exception.code, expired.exception.status_code), ("asset_not_found", 404))
        self.sql("UPDATE student_test_ocr_assets SET expires_at='not-a-time' WHERE id='a'")
        with self.assertRaises(StudentTestOcrServiceError):
            service.admin_asset_path(asset_id="a")

    def test_results_questions_and_history_survive_deletion(self):
        self.asset()
        self.sql("UPDATE student_test_ocr_submissions SET status='finalized' WHERE id='s'")
        self.sql("UPDATE student_test_ocr_questions SET initial_raw_answer='1/2',"
                 "initial_grade='incorrect',effective_grade='correct' WHERE submission_id='s' AND question_no=1")
        self.sql("INSERT INTO student_test_ocr_grade_history(submission_id,question_no,from_grade,to_grade) "
                 "VALUES('s',1,'incorrect','correct')")
        before = self.repo.get("s")
        self.assertEqual(self.purge()["deleted"], ("a",))
        self.assertEqual(self.repo.get("s"), before)

    def test_overdue_is_kst_read_only_and_excludes_today_future_finalized(self):
        for identifier, date, status in (("y", "2026-10-03", "pending_teacher"),
                                        ("t", "2026-10-04", "pending_teacher"),
                                        ("f", "2026-10-05", "pending_teacher"),
                                        ("z", "2026-10-02", "finalized")):
            self.submission(identifier, date)
            self.sql("UPDATE student_test_ocr_submissions SET status=? WHERE id=?", (status, identifier))
            self.sql("UPDATE student_test_ocr_questions SET effective_grade='pending',"
                     "crop_expires_at=? WHERE submission_id=? AND question_no=2", (NOW.isoformat(), identifier))
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        rows = self.repo.list_overdue_pending(before_date="2026-10-04", now=NOW.isoformat())
        self.assertEqual([(r["id"], r["pendingQuestionNos"], r["expiredCropCount"]) for r in rows],
                         [("y", [2], 1)])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)
        self.assertNotIn("answer", str(rows).lower())

    def test_naive_timestamps_fail_closed(self):
        self.asset(expiry="2026-10-03T00:00:00")
        self.assertEqual(self.purge()["failed"], ("a",))
        with self.assertRaises(OcrAssetError):
            self.purge(NOW.replace(tzinfo=None))
        self.assertTrue((self.assets / "s/a.jpg").exists())

    def test_corrupted_expiry_is_reported_but_not_deleted(self):
        target = self.asset(expiry="not-a-time")
        self.assertEqual(self.purge()["failed"], ("a",))
        self.assertTrue(target.exists())
        self.assertIsNone(self.repo.get_asset("a")["deleted_at"])
        report = StudentTestOcrMaintenance(self.repo, self.assets, lambda: NOW).run_once()
        self.assertEqual((report["status"], report["retention"]["failedCount"]), ("error", 1))
        self.assertIn("asset_delete_failed", report["errorCodes"])


if __name__ == "__main__":
    unittest.main()
