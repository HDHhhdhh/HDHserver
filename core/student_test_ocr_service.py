from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from core.student_test_ocr_assets import store_capture_file
from core.student_test_formula_profiles import FormulaProfileError, formula_profile_for_test
from core.student_test_ocr_eligibility import (
    OcrEligibilityError,
    find_test_definition,
    resolve_ocr_eligible_assignment,
)
from core.student_test_ocr_job_runner import StudentTestOcrJobRunner
from core.student_test_ocr_repository import (
    StudentTestOcrConflictError,
    StudentTestOcrRepository,
)
from core.student_test_ocr_rules import (
    ACTION_QUESTION_RECAPTURE,
    ACTION_STUDENT_CHOICE,
    ANSWER_VALUE,
    GRADE_INCORRECT,
    GRADE_PENDING,
    STATUS_PENDING_TEACHER,
    STATUS_READY_TO_GRADE,
    STATUS_RETAKE_REQUIRED,
    STATUS_STUDENT_ACTION_REQUIRED,
    grade_submission,
    validate_test_answer_contract,
)


KST = dt.timezone(dt.timedelta(hours=9))


@dataclass(frozen=True, slots=True)
class StudentTestOcrServiceError(RuntimeError):
    code: str
    message: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


def _fail(code: str, message: str, status_code: int = 400) -> None:
    raise StudentTestOcrServiceError(code, message, status_code)


class StudentTestOcrService:
    def __init__(
        self,
        *,
        repository: StudentTestOcrRepository,
        job_runner: StudentTestOcrJobRunner,
        asset_root: Path,
        tests_config_loader: Callable[[], Mapping[str, object]],
        progress_loader: Callable[[], Mapping[str, object]],
        log_entry_loader: Callable[[str, str], Mapping[str, object]],
        catalog_revision: Callable[[Mapping[str, object]], str],
        answer_url_resolver: Callable[[Mapping[str, object]], str],
        clock: Callable[[], dt.datetime],
        answer_value_recognizer: Callable[..., Mapping[str, object]] | None = None,
        solution_crop_provider: object | None = None,
        token_ttl_seconds: int = 600,
    ):
        self.repository = repository
        self.job_runner = job_runner
        self.asset_root = asset_root.resolve()
        self.tests_config_loader = tests_config_loader
        self.progress_loader = progress_loader
        self.log_entry_loader = log_entry_loader
        self.catalog_revision = catalog_revision
        self.answer_url_resolver = answer_url_resolver
        self.clock = clock
        self.answer_value_recognizer = answer_value_recognizer
        self.solution_crop_provider = solution_crop_provider
        self.token_ttl_seconds = token_ttl_seconds

    def _now(self) -> dt.datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            _fail("invalid_clock", "OCR service clock must include a timezone", 500)
        return value.astimezone(KST)

    def _eligibility(
        self,
        *,
        sid: str,
        assignment_date: str,
        test_id: str,
        assignment_label: str,
    ) -> tuple[dict, Mapping[str, object], str]:
        tests_config = self.tests_config_loader()
        progress = self.progress_loader()
        log_entry = self.log_entry_loader(assignment_date, sid)
        try:
            eligibility = resolve_ocr_eligible_assignment(
                tests_config=tests_config,
                progress=progress,
                log_entry=log_entry,
                sid=sid,
                assignment_date=assignment_date,
                test_id=test_id,
                assignment_label=assignment_label,
            )
        except OcrEligibilityError as error:
            raise StudentTestOcrServiceError(error.code, error.message, 409) from error
        return eligibility, tests_config, self.catalog_revision(tests_config)

    def start_capture_session(
        self,
        *,
        sid: str,
        assignment_date: str,
        test_id: str,
        assignment_label: str,
    ) -> dict:
        now = self._now()
        if assignment_date != now.date().isoformat():
            _fail("capture_date_not_today", "OCR capture is available only for today's assigned test", 409)
        eligibility, _config, _revision = self._eligibility(
            sid=sid,
            assignment_date=assignment_date,
            test_id=test_id,
            assignment_label=assignment_label,
        )
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        token_id = uuid.uuid4().hex
        expires_at = now + dt.timedelta(seconds=self.token_ttl_seconds)
        try:
            self.repository.issue_capture_token(
                token_id=token_id,
                token_digest=digest,
                sid=sid,
                test_id=test_id,
                round_no=eligibility["round"],
                assignment_date=assignment_date,
                assignment_label=assignment_label,
                expires_at=expires_at.isoformat(timespec="seconds"),
                created_at=now.isoformat(timespec="seconds"),
            )
        except StudentTestOcrConflictError as error:
            raise StudentTestOcrServiceError(error.code, str(error), 409) from error
        return {
            "token": token,
            "expiresAt": expires_at.isoformat(timespec="seconds"),
            "testId": test_id,
            "testName": eligibility["testName"],
            "round": eligibility["round"],
            "problemCount": 20,
        }

    def submit_full_capture(self, *, token: str, request_id: str, content: bytes) -> dict:
        now = self._now()
        now_text = now.isoformat(timespec="seconds")
        token_text = str(token or "").strip()
        request_id_text = str(request_id or "").strip()
        if len(token_text) < 32 or not 8 <= len(request_id_text) <= 160:
            _fail("invalid_capture_request", "capture token or request id is invalid")
        token_digest = hashlib.sha256(token_text.encode("utf-8")).hexdigest()
        token_row = self.repository.get_capture_token(token_digest, now=now_text, include_used=True)
        if token_row is None:
            _fail("invalid_or_expired_token", "capture token is invalid or expired", 409)
        idempotency_key = hashlib.sha256(f"{token_digest}:{request_id_text}".encode("utf-8")).hexdigest()
        if token_row.get("used_at") is not None:
            existing = self.repository.get_by_idempotency_key(idempotency_key)
            if existing is None:
                _fail("token_used", "capture token was already used", 409)
            self.job_runner.wake()
            return {"submissionId": existing["id"], "status": existing["status"]}
        eligibility, tests_config, catalog_revision = self._eligibility(
            sid=str(token_row["sid"]),
            assignment_date=str(token_row["assignment_date"]),
            test_id=str(token_row["test_id"]),
            assignment_label=str(token_row["assignment_label"]),
        )
        if str(token_row["round_no"]) != eligibility["round"]:
            _fail("assignment_identity_mismatch", "capture token round no longer matches", 409)

        submission_id = f"ocr_{uuid.uuid4().hex}"
        asset_id = uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        stored = store_capture_file(
            root=self.asset_root,
            asset_id=asset_id,
            submission_id=submission_id,
            question_no=None,
            kind="full_sheet",
            content=content,
            created_at=now,
        )
        image_hash = hashlib.sha256(content).hexdigest()
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "sid": token_row["sid"],
                    "testId": token_row["test_id"],
                    "round": token_row["round_no"],
                    "date": token_row["assignment_date"],
                    "catalogRevision": catalog_revision,
                    "formulaProfile": eligibility["formulaProfile"],
                    "imageSha256": image_hash,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        job_payload = {
            "schema": "student_test_ocr_job_v1",
            "submissionRevision": 1,
            "catalogRevision": catalog_revision,
            "answerModes": list(eligibility["answerModes"]),
            "formulaProfile": eligibility["formulaProfile"],
            "captureRelativePath": stored["relative_path"],
            "cropOutputRelativeDir": f"{submission_id}/crops",
            "cropExpiresAt": stored["expires_at"],
        }
        try:
            created = self.repository.create_capture_submission(
                token_digest=token_digest,
                submission_id=submission_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                sid=str(token_row["sid"]),
                test_id=str(token_row["test_id"]),
                round_no=str(token_row["round_no"]),
                assignment_date=str(token_row["assignment_date"]),
                assignment_label=str(token_row["assignment_label"]),
                answer_modes=eligibility["answerModes"],
                full_sheet_asset={
                    "id": asset_id,
                    "relativePath": stored["relative_path"],
                    "expiresAt": stored["expires_at"],
                    "createdAt": stored["created_at"],
                },
                job_id=job_id,
                job_payload=job_payload,
                now=now_text,
            )
        except Exception:
            Path(stored["absolute_path"]).unlink(missing_ok=True)
            raise
        actual_id = created["submission"]["id"]
        if actual_id != submission_id:
            Path(stored["absolute_path"]).unlink(missing_ok=True)
        self.job_runner.wake()
        return {"submissionId": actual_id, "status": created["submission"]["status"]}

    def _grade_if_ready(self, submission: dict) -> dict:
        if submission.get("status") != STATUS_READY_TO_GRADE:
            return submission
        job = self.repository.get_job_for_submission(submission["id"])
        if not isinstance(job, dict) or not isinstance(job.get("payload"), dict):
            _fail("grading_context_unavailable", "OCR grading context is unavailable", 503)
        tests_config = self.tests_config_loader()
        if str(job["payload"].get("catalogRevision") or "") != self.catalog_revision(tests_config):
            _fail("test_catalog_changed", "test catalog changed during OCR processing", 409)
        try:
            definition = find_test_definition(tests_config, submission["test_id"])
            contract = validate_test_answer_contract(
                category=definition["categoryKey"],
                test=definition["test"],
                round_no=submission["round_no"],
            )
        except (OcrEligibilityError, ValueError) as error:
            _fail("grading_context_unavailable", str(error), 409)
        questions = submission["questions"]
        modes = tuple(question["answer_mode"] for question in questions)
        if modes != tuple(contract["answerModes"]):
            _fail("test_catalog_changed", "answer modes changed during OCR processing", 409)
        pending = [
            int(question["question_no"])
            for question in questions
            if question["recognition_state"] == "pending_teacher"
        ]
        answers = [question["submitted_answer"] or None for question in questions]
        graded = grade_submission(
            answer_modes=modes,
            submitted_answers=answers,
            answer_keys=contract["answerKeys"],
            pending_question_nos=pending,
        )
        try:
            return self.repository.record_grading(
                submission["id"],
                graded["gradeStates"],
                expected_revision=int(submission["revision"]),
                now=self._now().isoformat(timespec="seconds"),
            )
        except StudentTestOcrConflictError as error:
            raise StudentTestOcrServiceError(error.code, str(error), 409) from error

    def complete_recognition(self, submission: dict) -> dict:
        """Finish server-side grading even if the camera page stops polling."""
        fresh = self.repository.get(submission["id"])
        if fresh is None:
            _fail("submission_not_found", "OCR submission was not found", 404)
        return self._grade_if_ready(fresh)

    def status(self, *, submission_id: str, sid: str) -> dict:
        submission = self.repository.get(submission_id, sid=sid)
        if submission is None:
            _fail("submission_not_found", "OCR submission was not found", 404)
        if submission["status"] == "processing":
            self.job_runner.wake()
        submission = self._grade_if_ready(submission)
        questions = submission["questions"]
        result = submission.get("result")
        response = {
            "submissionId": submission["id"],
            "status": submission["status"],
            "revision": submission["revision"],
            "problemCount": submission["problem_count"],
            "answerReleased": submission["answer_released"],
            "studentActions": [
                {
                    "questionNo": int(question["question_no"]),
                    "answerMode": question["answer_mode"],
                    "action": question["student_action"],
                    "recaptureAttempts": int(question["recapture_attempts"]),
                }
                for question in questions
                if question["student_action"] in {ACTION_STUDENT_CHOICE, ACTION_QUESTION_RECAPTURE}
            ],
            "retakeRequired": submission["status"] == STATUS_RETAKE_REQUIRED,
        }
        if isinstance(result, dict):
            response["result"] = {
                "correctCount": result["correctCount"],
                "incorrectCount": result["incorrectCount"],
                "pendingCount": result["pendingCount"],
                "problemCount": result["problemCount"],
                "score": result["score"],
                "wrongQuestionNos": [
                    int(question["question_no"])
                    for question in questions
                    if question["effective_grade"] == GRADE_INCORRECT
                ],
                "pendingQuestionNos": [
                    int(question["question_no"])
                    for question in questions
                    if question["effective_grade"] == "pending"
                ],
            }
        if submission["answer_released"]:
            response["answerUrl"] = self.answer_url_resolver(submission)
        if submission["status"] == STATUS_PENDING_TEACHER:
            response["pendingMessage"] = "정답 여부는 선생님이 판별합니다."
        return response

    def submit_choice(
        self,
        *,
        submission_id: str,
        sid: str,
        question_no: int,
        choice: object,
        revision: int,
    ) -> dict:
        if self.repository.get(submission_id, sid=sid) is None:
            _fail("submission_not_found", "OCR submission was not found", 404)
        try:
            submission = self.repository.record_student_choice(
                submission_id,
                question_no=question_no,
                choice=choice,
                expected_revision=revision,
                now=self._now().isoformat(timespec="seconds"),
            )
        except StudentTestOcrConflictError as error:
            raise StudentTestOcrServiceError(error.code, str(error), 409) from error
        submission = self._grade_if_ready(submission)
        return self.status(submission_id=submission_id, sid=sid)

    def submit_answer_value_recapture(
        self,
        *,
        submission_id: str,
        sid: str,
        question_no: int,
        revision: int,
        content: bytes,
    ) -> dict:
        submission = self.repository.get(submission_id, sid=sid)
        if submission is None:
            _fail("submission_not_found", "OCR submission was not found", 404)
        if submission["assignment_date"] != self._now().date().isoformat():
            _fail("capture_date_not_today", "question recapture is available only on the assignment date", 409)
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or int(submission["revision"]) != revision
        ):
            _fail("revision_conflict", "OCR submission revision changed", 409)
        if submission["status"] != STATUS_STUDENT_ACTION_REQUIRED:
            _fail("state_conflict", "submission is not waiting for a question recapture", 409)
        question = next(
            (item for item in submission["questions"] if int(item["question_no"]) == question_no),
            None,
        )
        if (
            not isinstance(question, dict)
            or question.get("answer_mode") != ANSWER_VALUE
            or question.get("student_action") != ACTION_QUESTION_RECAPTURE
        ):
            _fail("state_conflict", "question is not waiting for an answer-value recapture", 409)
        if not callable(self.answer_value_recognizer):
            _fail("ocr_runtime_unavailable", "answer-value OCR runtime is unavailable", 503)

        now = self._now()
        now_text = now.isoformat(timespec="seconds")
        asset_id = uuid.uuid4().hex
        stored = store_capture_file(
            root=self.asset_root,
            asset_id=asset_id,
            submission_id=submission_id,
            question_no=question_no,
            kind="student_crop",
            content=content,
            created_at=now,
        )
        target = Path(stored["absolute_path"])
        try:
            tests_config = self.tests_config_loader()
            job = self.repository.get_job_for_submission(submission_id)
            if not isinstance(job, dict) or not isinstance(job.get("payload"), dict):
                _fail("grading_context_unavailable", "OCR grading context is unavailable", 503)
            if str(job["payload"].get("catalogRevision") or "") != self.catalog_revision(tests_config):
                _fail("test_catalog_changed", "test catalog changed during OCR processing", 409)
            try:
                definition = find_test_definition(tests_config, submission["test_id"])
                formula_profile = formula_profile_for_test(definition["test"], (ANSWER_VALUE,))
            except (OcrEligibilityError, FormulaProfileError) as error:
                _fail("grading_context_unavailable", str(error), 409)
            if formula_profile != job["payload"].get("formulaProfile"):
                _fail("test_catalog_changed", "subjective OCR profile changed during processing", 409)
            recognized = self.answer_value_recognizer(
                question_no=question_no,
                image_path=target,
                asset_root=self.asset_root,
                formula_profile=formula_profile,
            )
            if not isinstance(recognized, Mapping) or recognized.get("questionNo") != question_no:
                _fail("invalid_worker_response", "question recapture OCR response is invalid", 503)
            confidence = recognized.get("confidence")
            try:
                updated = self.repository.record_answer_value_recapture(
                    submission_id,
                    question_no=question_no,
                    raw_answer=recognized.get("rawAnswer"),
                    confident=recognized.get("confident") is True,
                    confidence=confidence,
                    asset_id=asset_id,
                    crop_relpath=stored["relative_path"],
                    crop_expires_at=stored["expires_at"],
                    asset_created_at=stored["created_at"],
                    expected_revision=revision,
                    now=now_text,
                )
            except StudentTestOcrConflictError as error:
                raise StudentTestOcrServiceError(error.code, str(error), 409) from error
        except Exception:
            target.unlink(missing_ok=True)
            raise
        self._grade_if_ready(updated)
        return self.status(submission_id=submission_id, sid=sid)

    def submit_full_retake(
        self,
        *,
        submission_id: str,
        sid: str,
        revision: int,
        content: bytes,
    ) -> dict:
        submission = self.repository.get(submission_id, sid=sid)
        if submission is None:
            _fail("submission_not_found", "OCR submission was not found", 404)
        now = self._now()
        if submission["assignment_date"] != now.date().isoformat():
            _fail("capture_date_not_today", "full-sheet retake is available only on the assignment date", 409)
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or int(submission["revision"]) != revision
        ):
            _fail("revision_conflict", "OCR submission revision changed", 409)
        if submission["status"] != STATUS_RETAKE_REQUIRED:
            _fail("state_conflict", "submission is not waiting for a full-sheet retake", 409)
        job = self.repository.get_job_for_submission(submission_id)
        tests_config = self.tests_config_loader()
        catalog_revision = self.catalog_revision(tests_config)
        if (
            not isinstance(job, dict)
            or not isinstance(job.get("payload"), dict)
            or str(job["payload"].get("catalogRevision") or "") != catalog_revision
        ):
            _fail("test_catalog_changed", "test catalog changed before the full-sheet retake", 409)
        try:
            definition = find_test_definition(tests_config, submission["test_id"])
            formula_profile = formula_profile_for_test(
                definition["test"],
                tuple(question["answer_mode"] for question in submission["questions"]),
            )
        except (OcrEligibilityError, FormulaProfileError) as error:
            _fail("grading_context_unavailable", str(error), 409)
        if formula_profile != job["payload"].get("formulaProfile"):
            _fail("test_catalog_changed", "subjective OCR profile changed before the full-sheet retake", 409)

        asset_id = uuid.uuid4().hex
        stored = store_capture_file(
            root=self.asset_root,
            asset_id=asset_id,
            submission_id=submission_id,
            question_no=None,
            kind="full_sheet",
            content=content,
            created_at=now,
        )
        target = Path(stored["absolute_path"])
        modes = [str(question["answer_mode"]) for question in submission["questions"]]
        payload = {
            "schema": "student_test_ocr_job_v1",
            "submissionRevision": revision + 1,
            "catalogRevision": catalog_revision,
            "answerModes": modes,
            "formulaProfile": formula_profile,
            "captureRelativePath": stored["relative_path"],
            "cropOutputRelativeDir": f"{submission_id}/crops",
            "cropExpiresAt": stored["expires_at"],
        }
        try:
            try:
                self.repository.register_full_sheet_retake(
                    submission_id,
                    full_sheet_asset={
                        "id": asset_id,
                        "relativePath": stored["relative_path"],
                        "expiresAt": stored["expires_at"],
                        "createdAt": stored["created_at"],
                    },
                    job_payload=payload,
                    expected_revision=revision,
                    now=now.isoformat(timespec="seconds"),
                )
            except StudentTestOcrConflictError as error:
                raise StudentTestOcrServiceError(error.code, str(error), 409) from error
        except Exception:
            target.unlink(missing_ok=True)
            raise
        self.job_runner.wake()
        return self.status(submission_id=submission_id, sid=sid)

    def admin_pending(self, *, assignment_date: str) -> dict:
        try:
            parsed_date = dt.date.fromisoformat(str(assignment_date or "").strip())
        except ValueError as error:
            raise StudentTestOcrServiceError("invalid_date", "pending review date is invalid") from error
        date_key = parsed_date.isoformat()
        submissions = self.repository.list_pending_for_date(date_key)
        return {
            "date": date_key,
            "submissions": [
                {
                    "submissionId": submission["id"],
                    "sid": submission["sid"],
                    "testId": submission["test_id"],
                    "round": submission["round_no"],
                    "revision": int(submission["revision"]),
                    "pendingQuestionNos": [
                        int(question["question_no"])
                        for question in submission["questions"]
                        if question["effective_grade"] == GRADE_PENDING
                    ],
                    "updatedAt": submission["updated_at"],
                }
                for submission in submissions
            ],
        }

    def _admin_detail_projection(self, submission: dict) -> dict:
        tests_config = self.tests_config_loader()
        try:
            definition = find_test_definition(tests_config, submission["test_id"])
            contract = validate_test_answer_contract(
                category=definition["categoryKey"],
                test=definition["test"],
                round_no=submission["round_no"],
            )
        except (OcrEligibilityError, ValueError) as error:
            _fail("grading_context_unavailable", str(error), 409)
        now_text = self._now().isoformat(timespec="seconds")
        assets = [
            asset
            for asset in self.repository.list_assets_for_submission(submission["id"])
            if str(asset.get("expires_at") or "") > now_text
        ]
        latest_assets: dict[tuple[int, str], dict] = {}
        for asset in assets:
            question_no = asset.get("question_no")
            if isinstance(question_no, bool) or not isinstance(question_no, int):
                continue
            key = (question_no, str(asset.get("kind") or ""))
            previous = latest_assets.get(key)
            if previous is None or str(asset.get("created_at") or "") >= str(previous.get("created_at") or ""):
                latest_assets[key] = asset

        questions = []
        for question, expected in zip(submission["questions"], contract["answerKeys"]):
            number = int(question["question_no"])
            student_asset = latest_assets.get((number, "student_crop"))
            solution_asset = latest_assets.get((number, "solution_crop"))
            dynamic_solution_crop = bool(
                solution_asset is None
                and self.solution_crop_provider is not None
                and callable(getattr(self.solution_crop_provider, "available", None))
                and self.solution_crop_provider.available(definition["test"], submission["round_no"])
            )
            questions.append(
                {
                    "questionNo": number,
                    "answerMode": question["answer_mode"],
                    "recognitionState": question["recognition_state"],
                    "currentAnswer": question["current_normalized_answer"],
                    "submittedAnswer": question["submitted_answer"],
                    "expectedAnswer": expected,
                    "initialGrade": question["initial_grade"],
                    "effectiveGrade": question["effective_grade"],
                    "studentCropUrl": (
                        f"/api/student-test-ocr/admin/assets/{student_asset['id']}" if student_asset else ""
                    ),
                    "solutionCropUrl": (
                        f"/api/student-test-ocr/admin/assets/{solution_asset['id']}"
                        if solution_asset
                        else (
                            f"/api/student-test-ocr/admin/submissions/{submission['id']}/solution-crop/{number}"
                            if dynamic_solution_crop
                            else ""
                        )
                    ),
                }
            )
        result = submission.get("result") or {}
        return {
            "submissionId": submission["id"],
            "sid": submission["sid"],
            "testId": submission["test_id"],
            "testName": str(definition["test"].get("name") or submission["test_id"]),
            "round": submission["round_no"],
            "assignmentDate": submission["assignment_date"],
            "status": submission["status"],
            "revision": int(submission["revision"]),
            "result": {
                "correctCount": int(result.get("correctCount") or 0),
                "incorrectCount": int(result.get("incorrectCount") or 0),
                "pendingCount": int(result.get("pendingCount") or 0),
                "problemCount": int(result.get("problemCount") or 20),
                "score": result.get("score"),
            },
            "questions": questions,
            "answerUrl": self.answer_url_resolver(submission),
            "correctionHistory": list(submission.get("correctionHistory") or []),
        }

    def admin_detail(self, *, submission_id: str) -> dict:
        submission = self.repository.get(submission_id)
        if submission is None:
            _fail("submission_not_found", "OCR submission was not found", 404)
        return self._admin_detail_projection(submission)

    def admin_solution_crop(self, *, submission_id: str, question_no: int) -> bytes:
        if isinstance(question_no, bool) or not isinstance(question_no, int) or not 1 <= question_no <= 20:
            _fail("invalid_question", "solution crop question number is invalid")
        submission = self.repository.get(submission_id)
        if submission is None:
            _fail("submission_not_found", "OCR submission was not found", 404)
        tests_config = self.tests_config_loader()
        try:
            definition = find_test_definition(tests_config, submission["test_id"])
            validate_test_answer_contract(
                category=definition["categoryKey"],
                test=definition["test"],
                round_no=submission["round_no"],
            )
        except (OcrEligibilityError, ValueError) as error:
            _fail("grading_context_unavailable", str(error), 409)
        provider = self.solution_crop_provider
        renderer = getattr(provider, "render", None) if provider is not None else None
        content = renderer(definition["test"], submission["round_no"], question_no) if callable(renderer) else None
        if not isinstance(content, bytes) or not content.startswith(b"\x89PNG\r\n\x1a\n"):
            _fail("solution_crop_unavailable", "official solution crop is unavailable", 404)
        return content

    def admin_resolve_pending(
        self,
        *,
        submission_id: str,
        question_no: int,
        correct: bool,
        revision: int,
    ) -> dict:
        if not isinstance(correct, bool):
            _fail("invalid_request", "pending decision must be a boolean")
        try:
            submission = self.repository.resolve_pending(
                submission_id,
                question_no=question_no,
                correct=correct,
                expected_revision=revision,
                now=self._now().isoformat(timespec="seconds"),
            )
        except StudentTestOcrConflictError as error:
            raise StudentTestOcrServiceError(error.code, str(error), 409) from error
        return self._admin_detail_projection(submission)

    def admin_correct_wrong(
        self,
        *,
        submission_id: str,
        question_no: int,
        revision: int,
    ) -> dict:
        try:
            submission = self.repository.correct_wrong_to_correct(
                submission_id,
                question_no=question_no,
                expected_revision=revision,
                now=self._now().isoformat(timespec="seconds"),
            )
        except StudentTestOcrConflictError as error:
            raise StudentTestOcrServiceError(error.code, str(error), 409) from error
        return self._admin_detail_projection(submission)

    def admin_asset_path(self, *, asset_id: str) -> Path:
        asset = self.repository.get_asset(asset_id)
        if (
            asset is None
            or asset.get("deleted_at") is not None
            or str(asset.get("expires_at") or "") <= self._now().isoformat(timespec="seconds")
        ):
            _fail("asset_not_found", "OCR review asset was not found", 404)
        path = (self.asset_root / str(asset["relative_path"])).resolve()
        try:
            path.relative_to(self.asset_root)
        except ValueError as error:
            raise StudentTestOcrServiceError("invalid_asset_path", "OCR review asset path is invalid", 500) from error
        if not path.is_file():
            _fail("asset_not_found", "OCR review asset was not found", 404)
        return path
