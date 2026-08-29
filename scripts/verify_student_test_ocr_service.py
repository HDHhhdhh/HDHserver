from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

from core.student_test_formula_profiles import FORMULA_PROFILE_COMMON
from core.student_test_ocr_job_runner import StudentTestOcrJobRunner
from core.student_test_ocr_repository import StudentTestOcrRepository
from core.student_test_ocr_rules import ANSWER_VALUE, CHOICE_NUMBER, classify_sheet_recognition
from core.student_test_ocr_service import StudentTestOcrService
from core.test_config_safety import tests_config_revision


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts" / "migrations" / "20260828_create_student_test_ocr.sql"
KST = dt.timezone(dt.timedelta(hours=9))
LABEL = "단원평가 / 공수1 / Lv.3 / 1회차 / 지수 Lv.3"


class PassiveRunner:
    def __init__(self):
        self.wake_count = 0

    def wake(self):
        self.wake_count += 1
        return None


class FakeSolutionCropProvider:
    def available(self, test, round_no):
        return test.get("sourceId") == "unit-source-1" and str(round_no) == "1"

    def render(self, test, round_no, question_no):
        if not self.available(test, round_no):
            return None
        return b"\x89PNG\r\n\x1a\n" + f"question-{question_no}".encode("ascii")


def _config() -> dict:
    return {
        "categories": {
            "UNIT": {
                "label": "단원평가",
                "tests": [
                    {
                        "id": "test-1",
                        "sourceId": "unit-source-1",
                        "name": "지수 Lv.3",
                        "curriculum": "공수1",
                        "difficulty": "Lv.3",
                        "round": "1",
                        "problems": 20,
                        "answerModes": {"1": [CHOICE_NUMBER, ANSWER_VALUE] * 10},
                        "answerKeys": {"1": ["3", "1/2"] * 10},
                    }
                ],
            }
        }
    }


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="student-test-ocr-service-") as temp_dir:
        root = Path(temp_dir)
        repository = StudentTestOcrRepository(root / "app.sqlite")
        repository.apply_migration(MIGRATION.read_text(encoding="utf-8"))
        config = _config()
        progress = {
            "2026-08-28": {
                sid: {"tests": {LABEL: "assigned"}}
                for sid in ("student-1", "student-2", "student-3", "student-4")
            }
        }
        log_entry = {"testAssignmentDailyTests": [{"id": "test-1", "label": LABEL}]}
        now = dt.datetime(2026, 8, 28, 10, 0, 0, tzinfo=KST)
        passive = PassiveRunner()
        recapture_results = []

        def answer_value_recognizer(**kwargs):
            assert kwargs["formula_profile"] == FORMULA_PROFILE_COMMON
            if recapture_results:
                return {"questionNo": kwargs["question_no"], **recapture_results.pop(0)}
            return {
                "questionNo": kwargs["question_no"],
                "rawAnswer": "1/2",
                "confidence": 0.9999,
                "confident": True,
            }

        service = StudentTestOcrService(
            repository=repository,
            job_runner=passive,
            asset_root=root / "assets",
            tests_config_loader=lambda: config,
            progress_loader=lambda: progress,
            log_entry_loader=lambda _date, _sid: log_entry,
            catalog_revision=tests_config_revision,
            answer_url_resolver=lambda _submission: "https://drive.google.com/answer",
            clock=lambda: now,
            answer_value_recognizer=answer_value_recognizer,
            solution_crop_provider=FakeSolutionCropProvider(),
        )
        session = service.start_capture_session(
            sid="student-1",
            assignment_date="2026-08-28",
            test_id="test-1",
            assignment_label=LABEL,
        )
        assert len(session["token"]) >= 32 and session["problemCount"] == 20
        assert session["round"] == "1"
        assertions += 2

        jpeg = b"\xff\xd8\xff\xe0" + b"camera-frame" * 20
        accepted = service.submit_full_capture(
            token=session["token"],
            request_id="capture-request-0001",
            content=jpeg,
        )
        assert accepted["status"] == "processing" and passive.wake_count == 1
        submission_id = accepted["submissionId"]
        assets = repository.list_assets_for_submission(submission_id)
        assert len(assets) == 1 and assets[0]["kind"] == "full_sheet"
        job = repository.get_job_for_submission(submission_id)
        assert job["state"] == "queued" and "answerKeys" not in job["payload"]
        assert job["payload"]["formulaProfile"] == FORMULA_PROFILE_COMMON
        assertions += 4

        duplicate = service.submit_full_capture(
            token=session["token"],
            request_id="capture-request-0001",
            content=jpeg,
        )
        assert duplicate["submissionId"] == submission_id and len(repository.list_assets_for_submission(submission_id)) == 1
        assertions += 1

        def cropper(*, asset_root, image_path, output_dir):
            assert image_path.is_file() and image_path.is_relative_to(asset_root)
            output_dir.mkdir(parents=True)
            items = []
            for number in range(1, 21):
                path = output_dir / f"q{number:03d}.png"
                path.write_bytes(b"crop")
                items.append({"questionNo": number, "imagePath": str(path), "warnings": []})
            return {"quality": {"ok": True, "failures": []}, "items": items}

        def recognizer(*, crops, asset_root, formula_profile):
            del asset_root
            assert formula_profile == FORMULA_PROFILE_COMMON
            return classify_sheet_recognition(
                [crop.answer_mode for crop in crops],
                [
                    {
                        "questionNo": crop.question_no,
                        "rawAnswer": "3" if crop.answer_mode == CHOICE_NUMBER else "0.5",
                        "confidence": 0.999 if crop.answer_mode == CHOICE_NUMBER else None,
                        "confident": True,
                    }
                    for crop in crops
                ],
            )

        processing_runner = StudentTestOcrJobRunner(
            repository=repository,
            asset_root=root / "assets",
            cropper=cropper,
            recognizer=recognizer,
            clock=lambda: now + dt.timedelta(seconds=1),
        )
        processed = processing_runner.run_one()
        assert processed is not None and processed["state"] == "succeeded"
        processing_runner.shutdown()
        assertions += 1

        status = service.status(submission_id=submission_id, sid="student-1")
        assert status["status"] == "finalized" and status["result"]["score"] == 20
        assert status["result"]["wrongQuestionNos"] == [] and status["result"]["pendingQuestionNos"] == []
        assert status["answerReleased"] is True and status["answerUrl"] == "https://drive.google.com/answer"
        assert "answerKeys" not in str(status) and "correctAnswer" not in str(status)
        assertions += 4

        assert service.repository.get(submission_id)["questions"][1]["submitted_answer"] == "0.5"
        assert len(repository.list_assets_for_submission(submission_id)) == 21
        assertions += 2

        action_session = service.start_capture_session(
            sid="student-2",
            assignment_date="2026-08-28",
            test_id="test-1",
            assignment_label=LABEL,
        )
        action_capture = service.submit_full_capture(
            token=action_session["token"],
            request_id="capture-request-0002",
            content=jpeg,
        )
        action_submission_id = action_capture["submissionId"]

        def action_recognizer(*, crops, asset_root, formula_profile):
            del asset_root
            assert formula_profile == FORMULA_PROFILE_COMMON
            return classify_sheet_recognition(
                [crop.answer_mode for crop in crops],
                [
                    {
                        "questionNo": crop.question_no,
                        "rawAnswer": "3" if crop.answer_mode == CHOICE_NUMBER else "0.5",
                        "confidence": 0.999,
                        "confident": crop.question_no not in {1, 2},
                    }
                    for crop in crops
                ],
            )

        action_runner = StudentTestOcrJobRunner(
            repository=repository,
            asset_root=root / "assets",
            cropper=cropper,
            recognizer=action_recognizer,
            clock=lambda: now + dt.timedelta(seconds=2),
        )
        assert action_runner.run_one()["state"] == "succeeded"
        action_runner.shutdown()
        action_status = service.status(submission_id=action_submission_id, sid="student-2")
        assert [item["action"] for item in action_status["studentActions"]] == [
            "student_choice",
            "question_recapture",
        ]
        action_status = service.submit_choice(
            submission_id=action_submission_id,
            sid="student-2",
            question_no=1,
            choice=3,
            revision=action_status["revision"],
        )
        action_status = service.submit_answer_value_recapture(
            submission_id=action_submission_id,
            sid="student-2",
            question_no=2,
            revision=action_status["revision"],
            content=jpeg,
        )
        assert action_status["status"] == "finalized" and action_status["result"]["score"] == 20
        assert len(repository.list_assets_for_submission(action_submission_id)) == 22
        assertions += 4

        retake_session = service.start_capture_session(
            sid="student-3",
            assignment_date="2026-08-28",
            test_id="test-1",
            assignment_label=LABEL,
        )
        retake_capture = service.submit_full_capture(
            token=retake_session["token"],
            request_id="capture-request-0003",
            content=jpeg,
        )
        retake_submission_id = retake_capture["submissionId"]

        def retake_recognizer(*, crops, asset_root, formula_profile):
            del asset_root
            assert formula_profile == FORMULA_PROFILE_COMMON
            return classify_sheet_recognition(
                [crop.answer_mode for crop in crops],
                [
                    {
                        "questionNo": crop.question_no,
                        "rawAnswer": "3" if crop.answer_mode == CHOICE_NUMBER else "0.5",
                        "confidence": 0.999,
                        "confident": crop.question_no > 4,
                    }
                    for crop in crops
                ],
            )

        retake_runner = StudentTestOcrJobRunner(
            repository=repository,
            asset_root=root / "assets",
            cropper=cropper,
            recognizer=retake_recognizer,
            clock=lambda: now + dt.timedelta(seconds=3),
        )
        assert retake_runner.run_one()["state"] == "succeeded"
        retake_runner.shutdown()
        retake_status = service.status(submission_id=retake_submission_id, sid="student-3")
        assert retake_status["retakeRequired"] is True and retake_status["studentActions"] == []
        retake_status = service.submit_full_retake(
            submission_id=retake_submission_id,
            sid="student-3",
            revision=retake_status["revision"],
            content=jpeg,
        )
        retake_job = repository.get_job_for_submission(retake_submission_id)
        assert retake_status["status"] == "processing" and retake_job["state"] == "queued"
        assert retake_job["payload"]["submissionRevision"] == retake_status["revision"]
        assert len([asset for asset in repository.list_assets_for_submission(retake_submission_id) if asset["kind"] == "full_sheet"]) == 2
        assertions += 4

        pending_session = service.start_capture_session(
            sid="student-4",
            assignment_date="2026-08-28",
            test_id="test-1",
            assignment_label=LABEL,
        )
        pending_capture = service.submit_full_capture(
            token=pending_session["token"],
            request_id="capture-request-0004",
            content=jpeg,
        )
        pending_submission_id = pending_capture["submissionId"]

        def pending_recognizer(*, crops, asset_root, formula_profile):
            del asset_root
            assert formula_profile == FORMULA_PROFILE_COMMON
            return classify_sheet_recognition(
                [crop.answer_mode for crop in crops],
                [
                    {
                        "questionNo": crop.question_no,
                        "rawAnswer": "3" if crop.answer_mode == CHOICE_NUMBER else "0.5",
                        "confidence": 0.999,
                        "confident": crop.question_no != 2,
                    }
                    for crop in crops
                ],
            )

        pending_runner = StudentTestOcrJobRunner(
            repository=repository,
            asset_root=root / "assets",
            cropper=cropper,
            recognizer=pending_recognizer,
            clock=lambda: now + dt.timedelta(seconds=4),
        )
        pending_results = pending_runner.run_until_empty(maximum_jobs=3)
        assert pending_results and all(result["state"] == "succeeded" for result in pending_results)
        assert pending_submission_id in {result["submission"]["id"] for result in pending_results}
        pending_runner.shutdown()
        pending_status = service.status(submission_id=pending_submission_id, sid="student-4")
        recapture_results.extend(
            [
                {"rawAnswer": "?", "confidence": 0.1, "confident": False},
                {"rawAnswer": "?", "confidence": 0.1, "confident": False},
            ]
        )
        for _attempt in range(2):
            pending_status = service.submit_answer_value_recapture(
                submission_id=pending_submission_id,
                sid="student-4",
                question_no=2,
                revision=pending_status["revision"],
                content=jpeg,
            )
        assert pending_status["status"] == "pending_teacher" and pending_status["result"]["score"] is None
        assert pending_status["studentActions"] == [] and pending_status["pendingMessage"]
        assertions += 3

        admin_pending = service.admin_pending(assignment_date="2026-08-28")
        assert [item["submissionId"] for item in admin_pending["submissions"]] == [pending_submission_id]
        admin_detail = service.admin_detail(submission_id=pending_submission_id)
        pending_question = admin_detail["questions"][1]
        assert pending_question["expectedAnswer"] == "1/2" and pending_question["effectiveGrade"] == "pending"
        assert pending_question["studentCropUrl"].startswith("/api/student-test-ocr/admin/assets/")
        assert pending_question["solutionCropUrl"].endswith("/solution-crop/2")
        assert admin_detail["answerUrl"].startswith("https://drive.google.com/")
        assert service.admin_solution_crop(submission_id=pending_submission_id, question_no=2).startswith(b"\x89PNG")
        assertions += 5

        latest_q2_asset = [
            asset
            for asset in repository.list_assets_for_submission(pending_submission_id)
            if asset["question_no"] == 2 and asset["kind"] == "student_crop"
        ][-1]
        assert service.admin_asset_path(asset_id=latest_q2_asset["id"]).is_file()
        admin_detail = service.admin_resolve_pending(
            submission_id=pending_submission_id,
            question_no=2,
            correct=False,
            revision=admin_detail["revision"],
        )
        assert admin_detail["status"] == "finalized" and admin_detail["result"]["score"] == 19
        admin_detail = service.admin_correct_wrong(
            submission_id=pending_submission_id,
            question_no=2,
            revision=admin_detail["revision"],
        )
        assert admin_detail["result"]["score"] == 20
        assert admin_detail["correctionHistory"] == [
            {"questionNo": 2, "from": "incorrect", "to": "correct"}
        ]
        assertions += 4

    return {"name": "student-test-ocr-service", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
