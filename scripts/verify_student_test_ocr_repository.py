from __future__ import annotations

import tempfile
from pathlib import Path

from core.student_test_ocr_repository import (
    StudentTestOcrConflictError,
    StudentTestOcrRepository,
)
from core.student_test_ocr_rules import (
    ANSWER_VALUE,
    CHOICE_NUMBER,
    GRADE_CORRECT,
    GRADE_INCORRECT,
    GRADE_PENDING,
    STATUS_FINALIZED,
    STATUS_PENDING_TEACHER,
    STATUS_READY_TO_GRADE,
    classify_sheet_recognition,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts" / "migrations" / "20260828_create_student_test_ocr.sql"


def _raises(code: str, callback) -> None:
    try:
        callback()
    except StudentTestOcrConflictError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError(f"expected {code}")


def _candidates(*, uncertain=()) -> list[dict]:
    uncertain_set = set(uncertain)
    return [
        {
            "questionNo": question_no,
            "rawAnswer": "3" if question_no % 2 else "1/2",
            "confidence": 0.99 if question_no not in uncertain_set else 0.2,
            "confident": question_no not in uncertain_set,
        }
        for question_no in range(1, 21)
    ]


def run() -> dict:
    assertions = 0
    modes = [CHOICE_NUMBER, ANSWER_VALUE] * 10
    with tempfile.TemporaryDirectory(prefix="student-test-ocr-repository-") as temp_dir:
        db_path = Path(temp_dir) / "app.sqlite"
        repository = StudentTestOcrRepository(db_path)
        assert repository.schema_ready() is False
        repository.apply_migration(MIGRATION.read_text(encoding="utf-8"))
        assert repository.schema_ready() is True
        assertions += 2

        submission = repository.begin_submission(
            submission_id="sub-1",
            idempotency_key="idem-1",
            request_hash="hash-1",
            sid="student-1",
            test_id="test-1",
            round_no="1",
            assignment_date="2026-08-28",
            answer_modes=modes,
            now="2026-08-28T10:00:00+09:00",
        )
        assert submission["status"] == "processing" and len(submission["questions"]) == 20
        assert submission["revision"] == 1 and submission["answer_released"] is False
        assertions += 2

        duplicate = repository.begin_submission(
            submission_id="ignored-duplicate-id",
            idempotency_key="idem-1",
            request_hash="hash-1",
            sid="student-1",
            test_id="test-1",
            round_no="1",
            assignment_date="2026-08-28",
            answer_modes=modes,
            now="2026-08-28T10:00:01+09:00",
        )
        assert duplicate["id"] == "sub-1" and duplicate["revision"] == 1
        _raises(
            "idempotency_conflict",
            lambda: repository.begin_submission(
                submission_id="sub-2",
                idempotency_key="idem-1",
                request_hash="other-hash",
                sid="student-1",
                test_id="test-1",
                round_no="1",
                assignment_date="2026-08-28",
                answer_modes=modes,
                now="2026-08-28T10:00:01+09:00",
            ),
        )
        assertions += 2

        job = repository.enqueue_job(
            job_id="job-1",
            submission_id="sub-1",
            payload={
                "schema": "student_test_ocr_job_v1",
                "submissionRevision": 1,
                "catalogRevision": "catalog-revision-1",
                "answerModes": modes,
                "crops": [{"questionNo": number, "relativePath": f"sub-1/q{number:03d}.jpg"} for number in range(1, 21)],
            },
            now="2026-08-28T10:00:01+09:00",
        )
        assert job["state"] == "queued" and job["attempts"] == 0
        _raises(
            "answer_key_leak",
            lambda: repository.enqueue_job(
                job_id="job-leak",
                submission_id="sub-1",
                payload={"answerKeys": ["3"] * 20},
                now="2026-08-28T10:00:01+09:00",
            ),
        )
        leased = repository.lease_next_job(
            lease_token="lease-1",
            now="2026-08-28T10:00:01+09:00",
            lease_expires_at="2026-08-28T10:02:01+09:00",
        )
        assert leased is not None and leased["id"] == "job-1" and leased["attempts"] == 1
        assert "answerKeys" not in leased["payload"]
        finished_job = repository.finish_job(
            "job-1",
            lease_token="lease-1",
            succeeded=True,
            result={"status": "student_action_required", "uncertainCount": 2},
            error_code="",
            now="2026-08-28T10:00:02+09:00",
        )
        assert finished_job["state"] == "succeeded" and finished_job["lease_token"] == ""
        saved_job = repository.get_job_for_submission("sub-1")
        assert saved_job is not None and saved_job["result"]["uncertainCount"] == 2
        assertions += 6

        asset = repository.register_asset(
            asset_id="asset-1",
            submission_id="sub-1",
            question_no=None,
            kind="full_sheet",
            relative_path="sub-1/full-sheet.jpg",
            expires_at="2026-09-04T10:00:00+09:00",
            created_at="2026-08-28T10:00:00+09:00",
        )
        assert asset["relative_path"] == "sub-1/full-sheet.jpg"
        assert repository.expired_assets(now="2026-09-04T09:59:59+09:00") == []
        expired = repository.expired_assets(now="2026-09-04T10:00:00+09:00")
        assert [item["id"] for item in expired] == ["asset-1"]
        assert repository.mark_asset_deleted("asset-1", deleted_at="2026-09-04T10:00:01+09:00") is True
        assert repository.expired_assets(now="2026-09-05T10:00:00+09:00") == []
        assertions += 5

        decision = classify_sheet_recognition(modes, _candidates(uncertain=(1, 2)))
        submission = repository.record_sheet_recognition(
            "sub-1",
            decision,
            expected_revision=1,
            now="2026-08-28T10:00:02+09:00",
        )
        assert submission["status"] == "student_action_required" and submission["revision"] == 2
        assert submission["questions"][0]["student_action"] == "student_choice"
        assert submission["questions"][1]["student_action"] == "question_recapture"
        assertions += 3

        submission = repository.record_student_choice(
            "sub-1",
            question_no=1,
            choice="③",
            expected_revision=2,
            now="2026-08-28T10:00:03+09:00",
        )
        assert submission["questions"][0]["submitted_answer"] == "3"
        assert submission["questions"][0]["answer_source"] == "student_choice_correction"
        assertions += 2

        submission = repository.record_answer_value_recapture(
            "sub-1",
            question_no=2,
            raw_answer="?",
            confident=False,
            confidence=0.1,
            asset_id="asset-q2-attempt-1",
            crop_relpath="sub-1/q002-attempt-1.jpg",
            crop_expires_at="2026-09-04T10:00:04+09:00",
            asset_created_at="2026-08-28T10:00:04+09:00",
            expected_revision=3,
            now="2026-08-28T10:00:04+09:00",
        )
        assert submission["status"] == "student_action_required"
        assert submission["questions"][1]["recapture_attempts"] == 1
        assertions += 2

        submission = repository.record_answer_value_recapture(
            "sub-1",
            question_no=2,
            raw_answer="?",
            confident=False,
            confidence=0.1,
            asset_id="asset-q2-attempt-2",
            crop_relpath="sub-1/q002-attempt-2.jpg",
            crop_expires_at="2026-09-04T10:00:05+09:00",
            asset_created_at="2026-08-28T10:00:05+09:00",
            expected_revision=4,
            now="2026-08-28T10:00:05+09:00",
        )
        assert submission["status"] == STATUS_READY_TO_GRADE
        assert submission["questions"][1]["recognition_state"] == "pending_teacher"
        assert submission["questions"][1]["recapture_attempts"] == 2
        assertions += 3

        grades = [GRADE_CORRECT] * 20
        grades[1] = GRADE_PENDING
        grades[2] = GRADE_INCORRECT
        submission = repository.record_grading(
            "sub-1",
            grades,
            expected_revision=5,
            now="2026-08-28T10:00:06+09:00",
        )
        assert submission["status"] == STATUS_PENDING_TEACHER
        assert submission["answer_released"] is True and submission["result"]["score"] is None
        assert submission["result"]["correctCount"] == 18
        assertions += 3

        pending = repository.list_pending_for_date("2026-08-28")
        assert [item["id"] for item in pending] == ["sub-1"]
        assertions += 1

        submission = repository.resolve_pending(
            "sub-1",
            question_no=2,
            correct=False,
            expected_revision=6,
            now="2026-08-28T10:00:07+09:00",
        )
        assert submission["status"] == STATUS_FINALIZED and submission["result"]["score"] == 18
        assert submission["questions"][1]["initial_grade"] == GRADE_PENDING
        assert submission["questions"][1]["effective_grade"] == GRADE_INCORRECT
        assertions += 3

        submission = repository.correct_wrong_to_correct(
            "sub-1",
            question_no=3,
            expected_revision=7,
            now="2026-08-28T10:00:08+09:00",
        )
        assert submission["result"]["score"] == 19
        assert submission["questions"][2]["initial_grade"] == GRADE_INCORRECT
        assert submission["questions"][2]["effective_grade"] == GRADE_CORRECT
        assert submission["correctionHistory"] == [
            {"questionNo": 3, "from": GRADE_INCORRECT, "to": GRADE_CORRECT}
        ]
        assert set(submission["correctionHistory"][0]) == {"questionNo", "from", "to"}
        assertions += 5

        _raises(
            "grade_transition_rejected",
            lambda: repository.correct_wrong_to_correct(
                "sub-1",
                question_no=3,
                expected_revision=8,
                now="2026-08-28T10:00:09+09:00",
            ),
        )
        _raises(
            "revision_conflict",
            lambda: repository.correct_wrong_to_correct(
                "sub-1",
                question_no=2,
                expected_revision=7,
                now="2026-08-28T10:00:09+09:00",
            ),
        )
        assertions += 2

        final = repository.get("sub-1", sid="student-1")
        assert final is not None and final["revision"] == 8
        assert repository.get("sub-1", sid="other-student") is None
        assert repository.list_pending_for_date("2026-08-28") == []
        assertions += 3

        digest = "a" * 64
        issued = repository.issue_capture_token(
            token_id="token-1",
            token_digest=digest,
            sid="student-capture",
            test_id="test-capture",
            round_no="1",
            assignment_date="2026-08-29",
            assignment_label="단원평가 / 공수1 / Lv.3 / 1회차 / 지수",
            expires_at="2026-08-29T10:10:00+09:00",
            created_at="2026-08-29T10:00:00+09:00",
        )
        assert issued["used_at"] is None
        assertions += 1
        capture_payload = {
            "schema": "student_test_ocr_job_v1",
            "submissionRevision": 1,
            "catalogRevision": "catalog-revision-1",
            "answerModes": modes,
            "captureRelativePath": "sub-capture/full-sheet.jpg",
            "cropOutputRelativeDir": "sub-capture/crops",
            "cropExpiresAt": "2026-09-05T10:01:00+09:00",
        }
        created = repository.create_capture_submission(
            token_digest=digest,
            submission_id="sub-capture",
            idempotency_key="capture-request-1",
            request_hash="capture-hash-1",
            sid="student-capture",
            test_id="test-capture",
            round_no="1",
            assignment_date="2026-08-29",
            assignment_label="단원평가 / 공수1 / Lv.3 / 1회차 / 지수",
            answer_modes=modes,
            full_sheet_asset={
                "id": "asset-capture",
                "relativePath": "sub-capture/full-sheet.jpg",
                "expiresAt": "2026-09-05T10:01:00+09:00",
                "createdAt": "2026-08-29T10:01:00+09:00",
            },
            job_id="job-capture",
            job_payload=capture_payload,
            now="2026-08-29T10:01:00+09:00",
        )
        assert created["submission"]["status"] == "processing" and created["job"]["state"] == "queued"
        assert len(repository.list_assets_for_submission("sub-capture")) == 1
        assertions += 2
        repeated = repository.create_capture_submission(
            token_digest=digest,
            submission_id="ignored-id",
            idempotency_key="capture-request-1",
            request_hash="capture-hash-1",
            sid="student-capture",
            test_id="test-capture",
            round_no="1",
            assignment_date="2026-08-29",
            assignment_label="단원평가 / 공수1 / Lv.3 / 1회차 / 지수",
            answer_modes=modes,
            full_sheet_asset={
                "id": "ignored-asset",
                "relativePath": "ignored/full-sheet.jpg",
                "expiresAt": "2026-09-05T10:01:00+09:00",
            },
            job_id="ignored-job",
            job_payload=capture_payload,
            now="2026-08-29T10:01:01+09:00",
        )
        assert repeated["submission"]["id"] == "sub-capture" and repeated["job"]["id"] == "job-capture"
        assertions += 1

    assert not db_path.exists()
    assertions += 1
    return {"name": "student-test-ocr-repository", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
