from __future__ import annotations

import datetime as dt
import tempfile
from pathlib import Path

from core.student_test_formula_profiles import FORMULA_PROFILE_COMMON
from core.student_test_ocr_job_runner import StudentTestOcrJobRunner
from core.student_test_ocr_repository import StudentTestOcrRepository
from core.student_test_ocr_rules import ANSWER_VALUE, CHOICE_NUMBER, classify_sheet_recognition


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts" / "migrations" / "20260828_create_student_test_ocr.sql"
KST = dt.timezone(dt.timedelta(hours=9))


def _setup(repository: StudentTestOcrRepository, *, suffix: str) -> None:
    modes = [CHOICE_NUMBER, ANSWER_VALUE] * 10
    repository.begin_submission(
        submission_id=f"sub-{suffix}",
        idempotency_key=f"idem-{suffix}",
        request_hash=f"hash-{suffix}",
        sid=f"student-{suffix}",
        test_id="test-1",
        round_no="1",
        assignment_date="2026-08-28",
        answer_modes=modes,
        now="2026-08-28T10:00:00+09:00",
    )
    repository.enqueue_job(
        job_id=f"job-{suffix}",
        submission_id=f"sub-{suffix}",
        payload={
            "schema": "student_test_ocr_job_v1",
            "submissionRevision": 1,
            "catalogRevision": "catalog-revision-1",
            "answerModes": modes,
            "formulaProfile": FORMULA_PROFILE_COMMON,
            "captureRelativePath": f"sub-{suffix}/capture.jpg",
            "cropOutputRelativeDir": f"sub-{suffix}/crops",
            "cropExpiresAt": "2026-09-04T10:00:00+09:00",
        },
        now="2026-08-28T10:00:00+09:00",
    )


def run() -> dict:
    assertions = 0
    with tempfile.TemporaryDirectory(prefix="student-test-ocr-job-runner-") as temp_dir:
        root = Path(temp_dir)
        repository = StudentTestOcrRepository(root / "app.sqlite")
        repository.apply_migration(MIGRATION.read_text(encoding="utf-8"))
        _setup(repository, suffix="ok")
        capture = root / "sub-ok" / "capture.jpg"
        capture.parent.mkdir(parents=True)
        capture.write_bytes(b"capture")

        def cropper(*, asset_root, image_path, output_dir):
            assert asset_root == root.resolve() and image_path == capture.resolve()
            output_dir.mkdir(parents=True)
            items = []
            for number in range(1, 21):
                path = output_dir / f"q{number:03d}.png"
                path.write_bytes(b"crop")
                items.append({"questionNo": number, "imagePath": str(path), "warnings": []})
            return {"quality": {"ok": True, "failures": []}, "items": items}

        def recognizer(*, crops, asset_root, formula_profile):
            assert len(crops) == 20 and asset_root == root.resolve()
            assert formula_profile == FORMULA_PROFILE_COMMON
            candidates = [
                {
                    "questionNo": crop.question_no,
                    "rawAnswer": "3" if crop.answer_mode == CHOICE_NUMBER else "1/2",
                    "confidence": 0.999 if crop.answer_mode == CHOICE_NUMBER else None,
                    "confident": True,
                }
                for crop in crops
            ]
            return classify_sheet_recognition([crop.answer_mode for crop in crops], candidates)

        now = dt.datetime(2026, 8, 28, 10, 0, 1, tzinfo=KST)
        runner = StudentTestOcrJobRunner(
            repository=repository,
            asset_root=root,
            cropper=cropper,
            recognizer=recognizer,
            clock=lambda: now,
        )
        result = runner.run_one()
        assert result is not None and result["state"] == "succeeded"
        saved = repository.get("sub-ok")
        assert saved is not None and saved["status"] == "ready_to_grade" and saved["revision"] == 2
        assert len(repository.list_assets_for_submission("sub-ok")) == 20
        assert repository.get_job_for_submission("sub-ok")["state"] == "succeeded"
        assert runner.run_one() is None
        assertions += 6
        runner.shutdown()

        _setup(repository, suffix="fail")
        failed_capture = root / "sub-fail" / "capture.jpg"
        failed_capture.parent.mkdir(parents=True)
        failed_capture.write_bytes(b"capture")

        def failing_recognizer(**_kwargs):
            raise RuntimeError("engine failed")

        failed_runner = StudentTestOcrJobRunner(
            repository=repository,
            asset_root=root,
            cropper=cropper,
            recognizer=failing_recognizer,
            clock=lambda: now,
        )
        failed = failed_runner.run_one()
        assert failed is not None and failed["state"] == "failed"
        assert repository.get("sub-fail")["status"] == "processing"
        assert repository.get_job_for_submission("sub-fail")["state"] == "failed"
        assert repository.list_assets_for_submission("sub-fail") == []
        assert not any((root / "sub-fail" / "crops").rglob("*.png"))
        assertions += 5
        failed_runner.shutdown()

    return {"name": "student-test-ocr-job-runner", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
