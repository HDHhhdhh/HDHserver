"""Temp-only queue/recovery/HTTP oracles. No model, production store or network."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from pathlib import Path
from unittest.mock import patch

from core.student_test_ocr_context import test_context
from core.student_test_ocr_job_runner import StudentTestOcrJobRunner
from core.student_test_ocr_repository import StudentTestOcrConflictError, StudentTestOcrRepository
from core.student_test_ocr_rules import ANSWER_VALUE, CHOICE_NUMBER, classify_sheet_recognition
from core.student_test_ocr_service import StudentTestOcrService, StudentTestOcrServiceError
from core.test_config_safety import tests_config_revision

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts/migrations/20260828_create_student_test_ocr.sql"
KST = dt.timezone(dt.timedelta(hours=9))
LABEL = "단원평가 / 공수1 / Lv.3 / 1회차 / fixture"
HTTP_FIXTURE_SECONDS: list[float] = []


class PassiveRunner:
    def wake(self):
        return None


def wait_for(check, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("observable state did not arrive")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-lifecycle-")
        self.root = Path(self.temp.name)
        self.repository = StudentTestOcrRepository(self.root / "app.sqlite")
        self.repository.apply_migration(MIGRATION.read_text(encoding="utf-8"))
        self.now = dt.datetime(2026, 10, 4, 10, 0, tzinfo=KST)
        self.test = {
            "id": "test-1", "name": "fixture", "curriculum": "공수1", "difficulty": "Lv.3",
            "round": "1", "problems": 20,
            "answerModes": {"1": [CHOICE_NUMBER, ANSWER_VALUE] + [CHOICE_NUMBER] * 18},
            "answerKeys": {"1": ["3", "1/2"] + ["3"] * 18},
        }
        self.config = {"categories": {"UNIT": {"label": "단원평가", "tests": [self.test]}}}
        self.progress = {"2026-10-04": {f"sid-{i}": {"tests": {LABEL: "assigned"}} for i in range(6)}}
        self.runners = []
        self.sheet_calls = 0
        self.question_calls = 0
        self.uncertain = {2}
        self.question_confident = True
        self.release = threading.Event()
        self.started = threading.Event()
        self.block_question = False
        self.service = StudentTestOcrService(
            repository=self.repository, job_runner=PassiveRunner(), asset_root=self.root / "assets",
            tests_config_loader=lambda: self.config, progress_loader=lambda: self.progress,
            log_entry_loader=lambda *_: {"assignedTests": [{"id": "test-1", "label": LABEL}]},
            catalog_revision=tests_config_revision, answer_url_resolver=lambda _: "https://drive.google.com/fixture",
            clock=lambda: self.now, answer_value_recognizer=self.question_recognizer,
        )

    def tearDown(self):
        self.release.set()
        for runner in self.runners:
            runner.shutdown()
        self.temp.cleanup()

    def cropper(self, *, output_dir, **_):
        output_dir.mkdir(parents=True, exist_ok=False)
        items = []
        for number in range(1, 21):
            image = output_dir / f"q{number:02d}.png"
            image.write_bytes(b"literal crop")
            items.append({"questionNo": number, "imagePath": str(image),
                          "recognitionImagePath": str(image), "warnings": []})
        return {"quality": {"ok": True}, "items": items}

    def recognizer(self, *, crops, **_):
        self.sheet_calls += 1
        return classify_sheet_recognition([crop.answer_mode for crop in crops], [
            {"questionNo": crop.question_no, "rawAnswer": "1/2" if crop.question_no == 2 else "3",
             "confidence": 0.9999, "confident": crop.question_no not in self.uncertain} for crop in crops
        ])

    def question_recognizer(self, *, question_no, **_):
        self.question_calls += 1
        self.started.set()
        if self.block_question:
            if not self.release.wait(5):
                raise RuntimeError("fixture release timed out")
        return {"questionNo": question_no, "rawAnswer": "1/2" if self.question_confident else "?",
                "confidence": 0.9999 if self.question_confident else 0.1, "confident": self.question_confident}

    def runner(self, **kwargs):
        runner = StudentTestOcrJobRunner(
            repository=self.repository, asset_root=self.root / "assets", cropper=self.cropper,
            recognizer=self.recognizer, recapture_recognizer=self.question_recognizer,
            before_recognition=self.service.require_job_context, clock=lambda: self.now,
            on_recognition_committed=self.service.complete_recognition, **kwargs,
        )
        self.runners.append(runner)
        return runner

    def capture(self, index=0):
        session = self.service.start_capture_session(sid=f"sid-{index}", assignment_date="2026-10-04",
            test_id="test-1", assignment_label=LABEL)
        return self.service.submit_full_capture(token=session["token"], request_id=f"request-000{index}",
            content=b"\xff\xd8\xff\xe0" + b"fixture" * 20)["submissionId"]

    def recapture(self, submission_id, index=0):
        return self.service.submit_answer_value_recapture(
            submission_id=submission_id, sid=f"sid-{index}", question_no=2,
            revision=self.repository.get(submission_id)["revision"], content=b"\xff\xd8\xff\xe0" + b"recapture" * 20)

    def test_round_scoped_context_and_conflict(self):
        baseline = test_context(self.config, "test-1", "1")["revision"]
        self.assertTrue(baseline.startswith("test-v1:"))
        other = copy.deepcopy(self.test)
        other.update(id="test-2", name="another test")
        self.config["categories"]["UNIT"]["tests"].append(other)
        self.test["name"] = "renamed"
        self.test["sourceFiles"] = {"solutionFileId": "changed-link"}
        self.test["answerKeys"]["2"] = ["5"] * 20
        self.test["answerModes"]["2"] = [CHOICE_NUMBER] * 20
        self.assertEqual(test_context(self.config, "test-1", "1")["revision"], baseline)
        for field, value in (("answerKeys", "4"), ("answerModes", ANSWER_VALUE)):
            original = self.test[field]["1"][0]
            self.test[field]["1"][0] = value
            self.assertNotEqual(test_context(self.config, "test-1", "1")["revision"], baseline)
            self.test[field]["1"][0] = original
        self.test["curriculum"] = "대수"
        self.assertNotEqual(test_context(self.config, "test-1", "1")["revision"], baseline)

    def test_unrelated_edit_does_not_block_recapture_or_grading(self):
        submission = self.capture()
        self.runner().run_one()
        self.config["policy"] = {"newUnrelatedRule": True}
        self.test["answerKeys"]["2"] = ["4"] * 20
        accepted = self.recapture(submission)
        self.assertEqual(accepted["status"], "processing")
        self.assertEqual(self.question_calls, 0)
        self.runner().run_one()
        saved = self.service.status(submission_id=submission, sid="sid-0")
        self.assertEqual(saved["status"], "finalized")
        self.assertEqual(saved["result"]["score"], 20)
        self.assertNotIn("answerKeys", json.dumps(saved))

    def test_current_key_change_blocks_before_model_and_preserves_capture(self):
        submission = self.capture()
        self.test["answerKeys"]["1"][0] = "4"
        outcome = self.runner().run_one()
        self.assertEqual(outcome["errorCode"], "test_catalog_changed")
        self.assertEqual(self.sheet_calls, 0)
        saved = self.repository.get(submission)
        self.assertEqual(saved["status"], "failed")
        self.assertIsNone(saved["result"])
        assets = self.repository.list_assets_for_submission(submission)
        self.assertEqual(len(assets), 1)
        self.assertTrue((self.root / "assets" / assets[0]["relative_path"]).is_file())

    def test_recapture_changed_contract_is_no_write(self):
        submission = self.capture()
        self.runner().run_one()
        saved = self.repository.get(submission)
        before = sorted(path.relative_to(self.root / "assets").as_posix()
                        for path in (self.root / "assets").rglob("*") if path.is_file())
        self.test["answerKeys"]["1"][1] = "2/3"
        with self.assertRaises(StudentTestOcrServiceError) as denied:
            self.recapture(submission)
        self.assertEqual(denied.exception.code, "test_catalog_changed")
        self.assertEqual(self.repository.get(submission), saved)
        self.assertEqual(sorted(path.relative_to(self.root / "assets").as_posix()
                         for path in (self.root / "assets").rglob("*") if path.is_file()), before)

    def test_http_returns_while_question_worker_is_blocked(self):
        from flask import Flask
        import routes.api_student_test_ocr as routes
        submission = self.capture()
        self.runner().run_one()
        self.block_question = True
        self.service.job_runner = self.runner()
        app = Flask("ocr-lifecycle-fixture")
        app.config["STUDENT_TEST_OCR_SERVICE"] = self.service
        app.register_blueprint(routes.bp_api_student_test_ocr)
        with ExitStack() as stack:
            for name, value in (("BASE", self.root), ("TESTS_CFG_PATH", self.root / "tests.json"),
                                ("PRG_PATH", self.root / "progress.json"),
                                ("ANSWER_LINK_MAP_PATH", self.root / "answer-map.json")):
                stack.enter_context(patch.object(routes, name, value))
            stack.enter_context(patch.object(routes, "_academy_allowed", return_value=True))
            client = app.test_client()
            revision = self.repository.get(submission)["revision"]
            def post():
                return client.post(f"/api/student-test-ocr/submissions/{submission}/recapture", data={
                    "sid": "sid-0", "questionNo": "2", "revision": str(revision),
                    "capture": (io.BytesIO(b"\xff\xd8\xff\xe0" + b"http-fixture" * 20), "capture.jpg")})
            started = time.perf_counter()
            response = post()
            HTTP_FIXTURE_SECONDS.append(time.perf_counter() - started)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["status"], "processing")
            self.assertTrue(self.started.wait(2))
            self.assertFalse(self.release.is_set())
            self.assertEqual(post().status_code, 409)
            self.assertEqual(len(self.repository.list_assets_for_submission(submission)), 22)
            self.release.set()
            wait_for(lambda: self.repository.get(submission)["status"] == "finalized")
            status = client.get(f"/api/student-test-ocr/submissions/{submission}?sid=sid-0")
            self.assertEqual(status.json["result"]["score"], 20)
            self.assertNotIn("answerKeys", json.dumps(status.json))

    def test_two_uncertain_recaptures_still_become_pending(self):
        submission = self.capture()
        self.runner().run_one()
        self.question_confident = False
        for attempt in (1, 2):
            self.recapture(submission)
            self.runner().run_one()
            self.assertEqual(self.repository.get(submission)["questions"][1]["recapture_attempts"], attempt)
        result = self.service.status(submission_id=submission, sid="sid-0")
        self.assertEqual(result["status"], "pending_teacher")
        self.assertIsNone(result["result"]["score"])
        self.assertEqual(result["result"]["pendingCount"], 1)
        self.assertTrue(result["answerUrl"])
        self.assertTrue(result["pendingMessage"])

    def test_question_failure_keeps_registered_crop(self):
        submission = self.capture()
        self.runner().run_one()
        self.recapture(submission)
        runner = self.runner()
        runner.recapture_recognizer = lambda **_: (_ for _ in ()).throw(RuntimeError("injected worker failure"))
        outcome = runner.run_one()
        self.assertEqual(outcome["state"], "failed")
        self.assertEqual(self.repository.get(submission)["status"], "failed")
        assets = self.repository.list_assets_for_submission(submission)
        self.assertEqual(len(assets), 22)
        for asset in assets:
            self.assertTrue((self.root / "assets" / asset["relative_path"]).is_file())
            self.assertEqual(dt.datetime.fromisoformat(asset["expires_at"]) - dt.datetime.fromisoformat(asset["created_at"]),
                             dt.timedelta(days=7))

    def test_grading_recovers_without_poll_or_new_inference(self):
        self.uncertain = set()
        submission = self.capture()
        with patch.object(self.repository, "record_grading", side_effect=RuntimeError("injected grade write failure")):
            outcome = self.runner().run_one()
        self.assertEqual(outcome["state"], "succeeded")
        self.assertIn("gradingErrorCode", outcome)
        self.assertEqual(self.repository.get(submission)["status"], "ready_to_grade")
        before_calls = self.sheet_calls
        restored = self.runner()
        restored.start_recovery(interval_seconds=0.1)
        wait_for(lambda: self.repository.get(submission)["status"] == "finalized")
        self.assertEqual(self.sheet_calls, before_calls)
        self.assertEqual(len(self.repository.list_assets_for_submission(submission)), 21)

    def test_crash_lease_and_stale_finish(self):
        submission = self.capture()
        job = self.repository.lease_next_job(lease_token="dead-process", now=self.now.isoformat(timespec="seconds"),
            lease_expires_at=(self.now + dt.timedelta(seconds=3)).isoformat(timespec="seconds"))
        self.now += dt.timedelta(seconds=4)
        with self.assertRaises(StudentTestOcrConflictError):
            self.repository.finish_job(job["id"], lease_token="dead-process", succeeded=False,
                result=None, error_code="stale", now=self.now.isoformat(timespec="seconds"))
        restored = self.runner()
        restored.start_recovery(interval_seconds=0.1)
        wait_for(lambda: self.repository.get_job_for_submission(submission)["state"] == "succeeded")
        self.assertEqual(self.repository.get_job_for_submission(submission)["attempts"], 2)

    def test_heartbeat_prevents_reclaim_during_work(self):
        submission = self.capture()
        self.runner().run_one()
        self.recapture(submission)
        self.block_question = True
        runner = self.runner(lease_seconds=3)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(runner.run_one)
            self.assertTrue(self.started.wait(2))
            self.now += dt.timedelta(seconds=2)
            wait_for(lambda: self.repository.get_job_for_submission(submission)["lease_expires_at"].endswith("05+09:00"))
            other = self.repository.lease_next_job(lease_token="other-process",
                now=(self.now + dt.timedelta(seconds=2)).isoformat(timespec="seconds"),
                lease_expires_at=(self.now + dt.timedelta(seconds=5)).isoformat(timespec="seconds"))
            self.assertIsNone(other)
            self.release.set()
            self.assertEqual(future.result(timeout=3)["state"], "succeeded")

    def test_wake_at_last_empty_query_is_not_lost(self):
        first = self.capture()
        empty_seen = threading.Event()
        release_empty = threading.Event()
        runner = self.runner()
        original = runner.run_one
        observed = [False]
        def boundary():
            result = original()
            if result is None and not observed[0]:
                observed[0] = True
                empty_seen.set()
                if not release_empty.wait(4):
                    raise RuntimeError("fixture boundary timed out")
            return result
        with patch.object(runner, "run_one", side_effect=boundary):
            future = runner.wake()
            self.assertTrue(empty_seen.wait(3))
            second = self.capture(1)
            runner.wake()
            release_empty.set()
            future.result(timeout=4)
        self.assertEqual(self.repository.get_job_for_submission(first)["state"], "succeeded")
        self.assertEqual(self.repository.get_job_for_submission(second)["state"], "succeeded")

    def test_drain_database_failure_can_be_woken_again(self):
        submission = self.capture()
        runner = self.runner()
        with patch.object(self.repository, "lease_next_job", side_effect=RuntimeError("injected DB failure")):
            with self.assertRaises(RuntimeError):
                runner.wake().result(timeout=2)
        runner.wake().result(timeout=3)
        self.assertEqual(self.repository.get_job_for_submission(submission)["state"], "succeeded")

    def test_drain_over_one_hundred_jobs_continues(self):
        runner = self.runner()
        remaining = iter([{"state": "succeeded"} for _ in range(103)] + [None])
        with patch.object(runner, "run_one", side_effect=lambda: next(remaining)):
            self.assertEqual(len(runner.wake().result(timeout=2)), 103)

    def test_grading_failure_page_cannot_starve_later_submission(self):
        modes = self.test["answerModes"]["1"]
        decision = classify_sheet_recognition(modes, [
            {"questionNo": n, "rawAnswer": "1/2" if n == 2 else "3", "confident": True, "confidence": 0.9999}
            for n in range(1, 21)])
        for index in range(101):
            identifier = f"blocked-{index:03d}" if index < 100 else "zz-good"
            self.repository.begin_submission(submission_id=identifier, idempotency_key=f"idem-{index}",
                request_hash=f"hash-{index}", sid=f"writer-{index}", test_id="test-1", round_no="1",
                assignment_date="2026-10-04", answer_modes=modes, now=self.now.isoformat(timespec="seconds"))
            self.repository.record_sheet_recognition(identifier, decision, expected_revision=1,
                now=self.now.isoformat(timespec="seconds"))
        seen = []
        def grade(submission):
            seen.append(submission["id"])
            if submission["id"] != "zz-good":
                raise RuntimeError("permanent conflict fixture")
            return self.repository.record_grading(submission["id"], ["correct"] * 20,
                expected_revision=submission["revision"], now=self.now.isoformat(timespec="seconds"))
        runner = self.runner()
        runner.on_recognition_committed = grade
        runner.recover_grading()
        self.assertEqual(len(set(seen)), 101)
        self.assertEqual(self.repository.get("zz-good")["status"], "finalized")
        self.assertEqual(self.repository.get("blocked-000")["status"], "ready_to_grade")

    def test_shutdown_finishes_only_inflight_and_keeps_next_queued(self):
        first = self.capture()
        self.now += dt.timedelta(seconds=1)
        second = self.capture(1)
        started, released = threading.Event(), threading.Event()
        calls = []
        original = self.recognizer
        def blocked(**kwargs):
            calls.append("started")
            started.set()
            if not released.wait(4):
                raise RuntimeError("shutdown fixture timed out")
            return original(**kwargs)
        runner = self.runner()
        runner.recognizer = blocked
        future = runner.wake()
        self.assertTrue(started.wait(2))
        closer = threading.Thread(target=runner.shutdown)
        closer.start()
        def closed():
            try:
                runner.wake()
                return False
            except RuntimeError:
                return True
        wait_for(closed)
        released.set()
        closer.join(timeout=4)
        self.assertFalse(closer.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.repository.get_job_for_submission(first)["state"], "succeeded")
        self.assertEqual(self.repository.get_job_for_submission(second)["state"], "queued")
        self.assertEqual(len(future.result()), 1)

    def test_concurrent_grading_returns_committed_status_without_duplicate_write(self):
        self.uncertain = set()
        submission = self.capture()
        runner = self.runner()
        runner.on_recognition_committed = None
        runner.run_one()
        barrier = threading.Barrier(2)
        original = self.repository.record_grading
        def racing(*args, **kwargs):
            barrier.wait(timeout=3)
            return original(*args, **kwargs)
        with patch.object(self.repository, "record_grading", side_effect=racing):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(self.service.status, submission_id=submission, sid="sid-0") for _ in range(2)]
                results = [future.result(timeout=4) for future in futures]
        self.assertTrue(all(result["status"] == "finalized" for result in results))
        self.assertEqual(self.repository.get(submission)["revision"], 3)

    def test_catalog_writer_waits_until_grade_commit(self):
        self.uncertain = set()
        submission = self.capture()
        runner = self.runner()
        runner.on_recognition_committed = None
        runner.run_one()
        catalog_lock = threading.Lock()
        self.service.catalog_guard = lambda: catalog_lock
        grading, released = threading.Event(), threading.Event()
        writer_attempted, writer_entered = threading.Event(), threading.Event()
        original = self.repository.record_grading
        def paused(*args, **kwargs):
            grading.set()
            if not released.wait(4):
                raise RuntimeError("catalog fixture timed out")
            return original(*args, **kwargs)
        def writer():
            writer_attempted.set()
            with catalog_lock:
                writer_entered.set()
                self.test["answerKeys"]["1"][0] = "4"
        with patch.object(self.repository, "record_grading", side_effect=paused):
            with ThreadPoolExecutor(max_workers=2) as executor:
                grade_future = executor.submit(self.service.status, submission_id=submission, sid="sid-0")
                self.assertTrue(grading.wait(2))
                writer_future = executor.submit(writer)
                self.assertTrue(writer_attempted.wait(2))
                self.assertFalse(writer_entered.wait(0.05))
                released.set()
                self.assertEqual(grade_future.result(timeout=3)["result"]["score"], 20)
                writer_future.result(timeout=3)
        self.assertEqual(self.service.status(submission_id=submission, sid="sid-0")["result"]["score"], 20)

    def test_legacy_job_is_not_rebound_to_current_context(self):
        submission = self.capture()
        job = self.repository.get_job_for_submission(submission)
        payload = job["payload"]
        payload["catalogRevision"] = hashlib.sha256(json.dumps(self.config, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        with closing(sqlite3.connect(self.repository.db_path)) as connection:
            connection.execute("UPDATE student_test_ocr_jobs SET payload_json=? WHERE id=?",
                (json.dumps(payload), job["id"]))
            connection.commit()
        self.config["unrelatedLegacyChange"] = True
        result = self.runner().run_one()
        self.assertEqual(result["errorCode"], "test_catalog_changed")
        self.assertEqual(self.sheet_calls, 0)
        self.assertEqual(self.repository.get_job_for_submission(submission)["payload"]["catalogRevision"],
                         payload["catalogRevision"])

    def test_expired_capture_is_not_reprocessed(self):
        submission = self.capture()
        self.now += dt.timedelta(days=7)
        result = self.runner().run_one()
        self.assertEqual(result["errorCode"], "capture_expired")
        self.assertEqual(self.sheet_calls, 0)
        self.assertEqual(self.repository.get(submission)["status"], "failed")


def run() -> dict:
    HTTP_FIXTURE_SECONDS.clear()
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(LifecycleTests))
    if not result.wasSuccessful():
        raise AssertionError("OCR lifecycle regression failed")
    return {"passed": True, "tests": result.testsRun, "providerCallCount": 0,
            "httpFixtureSubmitSeconds": HTTP_FIXTURE_SECONDS,
            "latencyScope": "OS-temp Flask test_client + blocked fake recognizer, not model/camera/network latency"}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
