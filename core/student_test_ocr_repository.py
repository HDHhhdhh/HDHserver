from __future__ import annotations

import json
import datetime as dt
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Mapping, Sequence

from core.student_test_ocr_rules import (
    ACTION_FULL_SHEET_RETAKE,
    ACTION_NONE,
    ACTION_PENDING_TEACHER,
    ACTION_QUESTION_RECAPTURE,
    ACTION_STUDENT_CHOICE,
    ANSWER_SOURCE_OCR_INITIAL,
    ANSWER_SOURCE_QUESTION_RECAPTURE,
    ANSWER_SOURCE_STUDENT_CHOICE,
    ANSWER_VALUE,
    CHOICE_NUMBER,
    GRADE_CORRECT,
    GRADE_INCORRECT,
    GRADE_PENDING,
    MAX_ANSWER_VALUE_RECAPTURES,
    OCR_ELIGIBLE_MODES,
    PROBLEM_COUNT,
    STATUS_FINALIZED,
    STATUS_PENDING_TEACHER,
    STATUS_READY_TO_GRADE,
    STATUS_RETAKE_REQUIRED,
    STATUS_STUDENT_ACTION_REQUIRED,
    answer_value_recapture_decision,
    normalize_recognized_answer,
    summarize_grades,
)


SUBMISSION_FIELDS = (
    "id",
    "idempotency_key",
    "request_hash",
    "sid",
    "test_id",
    "round_no",
    "assignment_date",
    "status",
    "problem_count",
    "capture_attempts",
    "answer_released",
    "revision",
    "accepted_at",
    "finalized_at",
    "created_at",
    "updated_at",
)
QUESTION_FIELDS = (
    "submission_id",
    "question_no",
    "answer_mode",
    "recognition_state",
    "initial_raw_answer",
    "initial_normalized_answer",
    "current_raw_answer",
    "current_normalized_answer",
    "submitted_answer",
    "answer_source",
    "confidence",
    "student_action",
    "recapture_attempts",
    "initial_grade",
    "effective_grade",
    "crop_relpath",
    "crop_expires_at",
    "updated_at",
)


class StudentTestOcrRepositoryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class StudentTestOcrNotInitializedError(StudentTestOcrRepositoryError):
    def __init__(self):
        super().__init__("ocr_schema_not_initialized", "student test OCR schema is not initialized")


class StudentTestOcrConflictError(StudentTestOcrRepositoryError):
    pass


class StudentTestOcrRepository:
    """Revisioned SQLite persistence for the new OCR submission flow."""

    def __init__(self, db_path: str | os.PathLike[str]):
        self.db_path = os.fspath(db_path)

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        path = Path(self.db_path).absolute()
        if readonly and not path.is_file():
            raise StudentTestOcrNotInitializedError()
        mode = "ro" if readonly else "rw"
        try:
            connection = sqlite3.connect(
                f"{path.as_uri()}?mode={mode}",
                uri=True,
                timeout=30,
                isolation_level=None,
            )
        except sqlite3.OperationalError as error:
            raise StudentTestOcrNotInitializedError() from error
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        if readonly:
            connection.execute("PRAGMA query_only=ON")
        self._require_schema(connection)
        return connection

    @staticmethod
    def _require_schema(connection: sqlite3.Connection) -> None:
        required = {
            "student_test_ocr_assets",
            "student_test_ocr_capture_tokens",
            "student_test_ocr_jobs",
            "student_test_ocr_submissions",
            "student_test_ocr_questions",
            "student_test_ocr_grade_history",
        }
        actual = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?,?,?,?)",
                tuple(sorted(required)),
            )
        }
        if actual != required:
            connection.close()
            raise StudentTestOcrNotInitializedError()

    def apply_migration(self, sql: str) -> None:
        path = Path(self.db_path).absolute()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(sql)

    def schema_ready(self) -> bool:
        try:
            with closing(self._connect(readonly=True)):
                return True
        except StudentTestOcrNotInitializedError:
            return False

    @staticmethod
    def _row_dict(row: sqlite3.Row | None, fields: tuple[str, ...]) -> dict | None:
        if row is None:
            return None
        result = {field: row[field] for field in fields}
        if fields == SUBMISSION_FIELDS:
            result["answer_released"] = bool(result["answer_released"])
        return result

    def _write(self, action: Callable[[sqlite3.Connection], object]):
        with closing(self._connect(readonly=False)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                result = action(connection)
                connection.execute("COMMIT")
                return result
            except Exception:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _validate_text(value: object, label: str, *, maximum: int = 160) -> str:
        text = str(value or "").strip()
        if not text or len(text) > maximum:
            raise StudentTestOcrConflictError("invalid_submission", f"{label} is invalid")
        return text

    @staticmethod
    def _validate_modes(answer_modes: Sequence[object]) -> tuple[str, ...]:
        modes = tuple(str(mode or "").strip() for mode in answer_modes)
        if len(modes) != PROBLEM_COUNT or any(mode not in OCR_ELIGIBLE_MODES for mode in modes):
            raise StudentTestOcrConflictError(
                "invalid_submission",
                "answer modes must contain 20 OCR-eligible questions",
            )
        return modes

    @staticmethod
    def _load_submission_row(connection: sqlite3.Connection, submission_id: str) -> sqlite3.Row | None:
        return connection.execute(
            f"SELECT {','.join(SUBMISSION_FIELDS)} FROM student_test_ocr_submissions WHERE id=?",
            (submission_id,),
        ).fetchone()

    @staticmethod
    def _require_revision(row: sqlite3.Row | None, expected_revision: int) -> sqlite3.Row:
        if row is None:
            raise StudentTestOcrConflictError("submission_not_found", "OCR submission was not found")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise StudentTestOcrConflictError("revision_conflict", "submission revision is invalid")
        if int(row["revision"]) != expected_revision:
            raise StudentTestOcrConflictError("revision_conflict", "OCR submission revision changed")
        return row

    @staticmethod
    def _questions(connection: sqlite3.Connection, submission_id: str) -> list[dict]:
        rows = connection.execute(
            f"SELECT {','.join(QUESTION_FIELDS)} FROM student_test_ocr_questions "
            "WHERE submission_id=? ORDER BY question_no",
            (submission_id,),
        ).fetchall()
        return [StudentTestOcrRepository._row_dict(row, QUESTION_FIELDS) for row in rows]

    @staticmethod
    def _history(connection: sqlite3.Connection, submission_id: str) -> list[dict]:
        rows = connection.execute(
            "SELECT question_no,from_grade,to_grade FROM student_test_ocr_grade_history "
            "WHERE submission_id=? ORDER BY id",
            (submission_id,),
        ).fetchall()
        return [
            {"questionNo": int(row["question_no"]), "from": row["from_grade"], "to": row["to_grade"]}
            for row in rows
        ]

    @staticmethod
    def _hydrate(connection: sqlite3.Connection, row: sqlite3.Row | None) -> dict | None:
        submission = StudentTestOcrRepository._row_dict(row, SUBMISSION_FIELDS)
        if submission is None:
            return None
        questions = StudentTestOcrRepository._questions(connection, submission["id"])
        submission["questions"] = questions
        submission["correctionHistory"] = StudentTestOcrRepository._history(connection, submission["id"])
        grades = [question["effective_grade"] for question in questions]
        submission["result"] = summarize_grades(grades) if grades and all(grades) else None
        return submission

    def get(self, submission_id: str, *, sid: str | None = None) -> dict | None:
        with closing(self._connect(readonly=True)) as connection:
            row = self._load_submission_row(connection, submission_id)
            if row is None or (sid is not None and str(row["sid"]) != sid):
                return None
            return self._hydrate(connection, row)

    def get_by_idempotency_key(self, idempotency_key: str) -> dict | None:
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                f"SELECT {','.join(SUBMISSION_FIELDS)} FROM student_test_ocr_submissions WHERE idempotency_key=?",
                (str(idempotency_key or "").strip(),),
            ).fetchone()
            return self._hydrate(connection, row)

    def _insert_submission(
        self,
        connection: sqlite3.Connection,
        *,
        values: Mapping[str, str],
        modes: Sequence[str],
    ) -> dict:
        existing = connection.execute(
            f"SELECT {','.join(SUBMISSION_FIELDS)} FROM student_test_ocr_submissions WHERE idempotency_key=?",
            (values["idempotency_key"],),
        ).fetchone()
        if existing is not None:
            identity = ("request_hash", "sid", "test_id", "round_no", "assignment_date")
            if all(str(existing[field]) == values[field] for field in identity):
                return self._hydrate(connection, existing)
            raise StudentTestOcrConflictError(
                "idempotency_conflict",
                "idempotency key was reused for another OCR submission",
            )
        active = connection.execute(
            "SELECT id FROM student_test_ocr_submissions "
            "WHERE sid=? AND test_id=? AND round_no=? AND assignment_date=?",
            (values["sid"], values["test_id"], values["round_no"], values["assignment_date"]),
        ).fetchone()
        if active is not None:
            raise StudentTestOcrConflictError(
                "submission_already_exists",
                "this assigned test already has an OCR submission",
            )
        connection.execute(
            "INSERT INTO student_test_ocr_submissions("
            "id,idempotency_key,request_hash,sid,test_id,round_no,assignment_date,status,problem_count,"
            "capture_attempts,answer_released,revision,accepted_at,finalized_at,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,'processing',20,0,0,1,NULL,NULL,?,?)",
            (
                values["id"],
                values["idempotency_key"],
                values["request_hash"],
                values["sid"],
                values["test_id"],
                values["round_no"],
                values["assignment_date"],
                values["now"],
                values["now"],
            ),
        )
        connection.executemany(
            "INSERT INTO student_test_ocr_questions("
            "submission_id,question_no,answer_mode,recognition_state,updated_at"
            ") VALUES(?,?,?,'awaiting',?)",
            [(values["id"], number, mode, values["now"]) for number, mode in enumerate(modes, start=1)],
        )
        return self._hydrate(connection, self._load_submission_row(connection, values["id"]))

    def begin_submission(
        self,
        *,
        submission_id: str,
        idempotency_key: str,
        request_hash: str,
        sid: str,
        test_id: str,
        round_no: str,
        assignment_date: str,
        answer_modes: Sequence[object],
        now: str,
    ) -> dict:
        modes = self._validate_modes(answer_modes)
        values = {
            "id": self._validate_text(submission_id, "submission id"),
            "idempotency_key": self._validate_text(idempotency_key, "idempotency key"),
            "request_hash": self._validate_text(request_hash, "request hash"),
            "sid": self._validate_text(sid, "sid"),
            "test_id": self._validate_text(test_id, "test id"),
            "round_no": self._validate_text(round_no, "round"),
            "assignment_date": self._validate_text(assignment_date, "assignment date"),
            "now": self._validate_text(now, "timestamp"),
        }

        def action(connection: sqlite3.Connection):
            return self._insert_submission(connection, values=values, modes=modes)

        return self._write(action)

    def issue_capture_token(
        self,
        *,
        token_id: str,
        token_digest: str,
        sid: str,
        test_id: str,
        round_no: str,
        assignment_date: str,
        assignment_label: str,
        expires_at: str,
        created_at: str,
    ) -> dict:
        digest = str(token_digest or "").strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise StudentTestOcrConflictError("invalid_token", "capture token digest is invalid")
        values = {
            "id": self._validate_text(token_id, "token id"),
            "digest": digest,
            "sid": self._validate_text(sid, "sid"),
            "test_id": self._validate_text(test_id, "test id"),
            "round_no": self._validate_text(round_no, "round"),
            "assignment_date": self._validate_text(assignment_date, "assignment date"),
            "assignment_label": self._validate_text(assignment_label, "assignment label", maximum=500),
            "expires_at": self._validate_text(expires_at, "token expiry"),
            "created_at": self._validate_text(created_at, "token creation time"),
        }

        def action(connection: sqlite3.Connection):
            existing_submission = connection.execute(
                "SELECT id FROM student_test_ocr_submissions "
                "WHERE sid=? AND test_id=? AND round_no=? AND assignment_date=?",
                (values["sid"], values["test_id"], values["round_no"], values["assignment_date"]),
            ).fetchone()
            if existing_submission is not None:
                raise StudentTestOcrConflictError(
                    "submission_already_exists",
                    "this assigned test already has an OCR submission",
                )
            connection.execute(
                "INSERT INTO student_test_ocr_capture_tokens("
                "id,token_digest,sid,test_id,round_no,assignment_date,assignment_label,expires_at,used_at,created_at"
                ") VALUES(?,?,?,?,?,?,?,?,NULL,?)",
                (
                    values["id"],
                    values["digest"],
                    values["sid"],
                    values["test_id"],
                    values["round_no"],
                    values["assignment_date"],
                    values["assignment_label"],
                    values["expires_at"],
                    values["created_at"],
                ),
            )
            row = connection.execute(
                "SELECT id,sid,test_id,round_no,assignment_date,assignment_label,expires_at,used_at,created_at "
                "FROM student_test_ocr_capture_tokens WHERE id=?",
                (values["id"],),
            ).fetchone()
            return dict(row)

        return self._write(action)

    def get_capture_token(self, token_digest: str, *, now: str, include_used: bool = False) -> dict | None:
        digest = str(token_digest or "").strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            return None
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT id,sid,test_id,round_no,assignment_date,assignment_label,expires_at,used_at,created_at "
                "FROM student_test_ocr_capture_tokens WHERE token_digest=?",
                (digest,),
            ).fetchone()
            if row is None or (row["used_at"] is not None and not include_used) or str(row["expires_at"]) <= str(now):
                return None
            return dict(row)

    def create_capture_submission(
        self,
        *,
        token_digest: str,
        submission_id: str,
        idempotency_key: str,
        request_hash: str,
        sid: str,
        test_id: str,
        round_no: str,
        assignment_date: str,
        assignment_label: str,
        answer_modes: Sequence[object],
        full_sheet_asset: Mapping[str, object],
        job_id: str,
        job_payload: Mapping[str, object],
        now: str,
    ) -> dict:
        modes = self._validate_modes(answer_modes)
        values = {
            "id": self._validate_text(submission_id, "submission id"),
            "idempotency_key": self._validate_text(idempotency_key, "idempotency key"),
            "request_hash": self._validate_text(request_hash, "request hash"),
            "sid": self._validate_text(sid, "sid"),
            "test_id": self._validate_text(test_id, "test id"),
            "round_no": self._validate_text(round_no, "round"),
            "assignment_date": self._validate_text(assignment_date, "assignment date"),
            "assignment_label": self._validate_text(assignment_label, "assignment label", maximum=500),
            "now": self._validate_text(now, "timestamp"),
        }
        digest = str(token_digest or "").strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise StudentTestOcrConflictError("invalid_token", "capture token digest is invalid")
        self._reject_answer_key_fields(job_payload)
        payload_json = json.dumps(job_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        asset_id = self._validate_text(full_sheet_asset.get("id"), "asset id")
        relative = str(full_sheet_asset.get("relativePath") or "").replace("\\", "/").strip("/")
        expires_at = self._validate_text(full_sheet_asset.get("expiresAt"), "asset expiry")
        created_at = self._validate_text(full_sheet_asset.get("createdAt") or now, "asset creation time")
        if not relative or ".." in relative.split("/"):
            raise StudentTestOcrConflictError("invalid_asset", "full-sheet asset path is invalid")
        job_id_text = self._validate_text(job_id, "job id")

        def action(connection: sqlite3.Connection):
            existing = connection.execute(
                f"SELECT {','.join(SUBMISSION_FIELDS)} FROM student_test_ocr_submissions WHERE idempotency_key=?",
                (values["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                identity = ("request_hash", "sid", "test_id", "round_no", "assignment_date")
                if all(str(existing[field]) == values[field] for field in identity):
                    saved_job = connection.execute(
                        "SELECT id,state FROM student_test_ocr_jobs WHERE submission_id=?",
                        (existing["id"],),
                    ).fetchone()
                    return {"submission": self._hydrate(connection, existing), "job": dict(saved_job) if saved_job else None}
                raise StudentTestOcrConflictError("idempotency_conflict", "capture request id was reused")
            token = connection.execute(
                "SELECT id,sid,test_id,round_no,assignment_date,assignment_label,expires_at,used_at "
                "FROM student_test_ocr_capture_tokens WHERE token_digest=?",
                (digest,),
            ).fetchone()
            if token is None:
                raise StudentTestOcrConflictError("invalid_token", "capture token was not found")
            identity = {
                "sid": values["sid"],
                "test_id": values["test_id"],
                "round_no": values["round_no"],
                "assignment_date": values["assignment_date"],
                "assignment_label": values["assignment_label"],
            }
            if any(str(token[field]) != expected for field, expected in identity.items()):
                raise StudentTestOcrConflictError("invalid_token", "capture token identity does not match")
            if token["used_at"] is not None:
                raise StudentTestOcrConflictError("token_used", "capture token was already used")
            if str(token["expires_at"]) <= values["now"]:
                raise StudentTestOcrConflictError("token_expired", "capture token expired")
            submission = self._insert_submission(connection, values=values, modes=modes)
            cursor = connection.execute(
                "UPDATE student_test_ocr_capture_tokens SET used_at=? WHERE id=? AND used_at IS NULL",
                (values["now"], token["id"]),
            )
            if not cursor.rowcount:
                raise StudentTestOcrConflictError("token_used", "capture token was already used")
            connection.execute(
                "INSERT INTO student_test_ocr_assets("
                "id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at"
                ") VALUES(?,?,NULL,'full_sheet',?,?,NULL,?)",
                (asset_id, values["id"], relative, expires_at, created_at),
            )
            connection.execute(
                "INSERT INTO student_test_ocr_jobs("
                "id,submission_id,state,payload_json,result_json,attempts,lease_token,lease_expires_at,error_code,created_at,updated_at"
                ") VALUES(?,?,'queued',?,'',0,'','','',?,?)",
                (job_id_text, values["id"], payload_json, values["now"], values["now"]),
            )
            return {"submission": submission, "job": {"id": job_id_text, "state": "queued"}}

        return self._write(action)

    @staticmethod
    def _validated_recognition_decision(decision: Mapping[str, object]) -> tuple[str, dict[int, Mapping[str, object]]]:
        status = str(decision.get("status") or "")
        if status not in {STATUS_READY_TO_GRADE, STATUS_STUDENT_ACTION_REQUIRED, STATUS_RETAKE_REQUIRED}:
            raise StudentTestOcrConflictError("invalid_recognition", "recognition status is invalid")
        items = decision.get("items")
        if not isinstance(items, list) or len(items) != PROBLEM_COUNT:
            raise StudentTestOcrConflictError("invalid_recognition", "recognition must contain 20 questions")
        indexed: dict[int, Mapping[str, object]] = {}
        for item in items:
            if not isinstance(item, Mapping):
                raise StudentTestOcrConflictError("invalid_recognition", "recognition item is invalid")
            number = item.get("questionNo")
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= PROBLEM_COUNT or number in indexed:
                raise StudentTestOcrConflictError("invalid_recognition", "recognition question coverage is invalid")
            indexed[number] = item
        return status, indexed

    def _apply_sheet_recognition(
        self,
        connection: sqlite3.Connection,
        submission_id: str,
        *,
        status: str,
        indexed: Mapping[int, Mapping[str, object]],
        expected_revision: int,
        now: str,
    ) -> dict:
        row = self._require_revision(self._load_submission_row(connection, submission_id), expected_revision)
        if row["status"] not in {"processing", STATUS_RETAKE_REQUIRED}:
            raise StudentTestOcrConflictError("state_conflict", "submission is not accepting a full-sheet result")
        questions = self._questions(connection, submission_id)
        if len(questions) != PROBLEM_COUNT:
            raise StudentTestOcrConflictError("state_conflict", "submission question set is incomplete")
        for question in questions:
            number = int(question["question_no"])
            item = indexed[number]
            mode = str(item.get("answerMode") or "")
            if mode != question["answer_mode"]:
                raise StudentTestOcrConflictError("invalid_recognition", "recognition answer mode changed")
            raw = str(item.get("rawAnswer") or "").strip()
            normalized = normalize_recognized_answer(mode, item.get("normalizedAnswer") or raw)
            recognition_state = str(item.get("recognitionState") or "")
            if recognition_state not in {"confident", "uncertain"}:
                raise StudentTestOcrConflictError("invalid_recognition", "recognition state is invalid")
            student_action = str(item.get("studentAction") or ACTION_NONE)
            allowed_actions = {
                ACTION_NONE,
                ACTION_STUDENT_CHOICE,
                ACTION_QUESTION_RECAPTURE,
                ACTION_FULL_SHEET_RETAKE,
            }
            if student_action not in allowed_actions:
                raise StudentTestOcrConflictError("invalid_recognition", "student action is invalid")
            if recognition_state == "confident" and not normalized:
                raise StudentTestOcrConflictError("invalid_recognition", "confident recognition must contain an answer")
            confidence = item.get("confidence")
            if confidence is not None:
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                    raise StudentTestOcrConflictError("invalid_recognition", "recognition confidence is invalid")
            initial_raw = question["initial_raw_answer"] or raw
            initial_normalized = question["initial_normalized_answer"] or normalized
            source = ANSWER_SOURCE_OCR_INITIAL if recognition_state == "confident" else ""
            submitted = normalized if recognition_state == "confident" else ""
            crop_relative = str(item.get("cropRelativePath") or question["crop_relpath"] or "").replace("\\", "/").strip("/")
            crop_expires_at = str(item.get("cropExpiresAt") or question["crop_expires_at"] or "").strip()
            if crop_relative and ".." in crop_relative.split("/"):
                raise StudentTestOcrConflictError("invalid_recognition", "recognition crop path is invalid")
            connection.execute(
                "UPDATE student_test_ocr_questions SET recognition_state=?,initial_raw_answer=?,"
                "initial_normalized_answer=?,current_raw_answer=?,current_normalized_answer=?,submitted_answer=?,"
                "answer_source=?,confidence=?,student_action=?,recapture_attempts=0,initial_grade='',effective_grade='',"
                "crop_relpath=?,crop_expires_at=?,updated_at=? "
                "WHERE submission_id=? AND question_no=?",
                (
                    recognition_state,
                    initial_raw,
                    initial_normalized,
                    raw,
                    normalized,
                    submitted,
                    source,
                    None if confidence is None else float(confidence),
                    student_action,
                    crop_relative,
                    crop_expires_at,
                    now,
                    submission_id,
                    number,
                ),
            )
        connection.execute(
            "UPDATE student_test_ocr_submissions SET status=?,capture_attempts=capture_attempts+1,"
            "revision=revision+1,updated_at=? WHERE id=?",
            (status, now, submission_id),
        )
        return self._hydrate(connection, self._load_submission_row(connection, submission_id))

    def record_sheet_recognition(
        self,
        submission_id: str,
        decision: Mapping[str, object],
        *,
        expected_revision: int,
        now: str,
    ) -> dict:
        status, indexed = self._validated_recognition_decision(decision)

        def action(connection: sqlite3.Connection):
            return self._apply_sheet_recognition(
                connection,
                submission_id,
                status=status,
                indexed=indexed,
                expected_revision=expected_revision,
                now=now,
            )

        return self._write(action)

    @staticmethod
    def _recognition_completion_status(connection: sqlite3.Connection, submission_id: str) -> str:
        row = connection.execute(
            "SELECT COUNT(*) FROM student_test_ocr_questions WHERE submission_id=? "
            "AND student_action IN ('student_choice','question_recapture')",
            (submission_id,),
        ).fetchone()
        return STATUS_STUDENT_ACTION_REQUIRED if int(row[0]) else STATUS_READY_TO_GRADE

    def record_student_choice(
        self,
        submission_id: str,
        *,
        question_no: int,
        choice: object,
        expected_revision: int,
        now: str,
    ) -> dict:
        normalized = normalize_recognized_answer(CHOICE_NUMBER, choice)
        if not normalized:
            raise StudentTestOcrConflictError("invalid_choice", "student choice must be 1 through 5")

        def action(connection: sqlite3.Connection):
            row = self._require_revision(self._load_submission_row(connection, submission_id), expected_revision)
            if row["status"] != STATUS_STUDENT_ACTION_REQUIRED:
                raise StudentTestOcrConflictError("state_conflict", "submission is not waiting for student input")
            question = connection.execute(
                f"SELECT {','.join(QUESTION_FIELDS)} FROM student_test_ocr_questions "
                "WHERE submission_id=? AND question_no=?",
                (submission_id, question_no),
            ).fetchone()
            if question is None or question["answer_mode"] != CHOICE_NUMBER or question["student_action"] != ACTION_STUDENT_CHOICE:
                raise StudentTestOcrConflictError("state_conflict", "question is not waiting for a student choice")
            connection.execute(
                "UPDATE student_test_ocr_questions SET recognition_state='confident',current_raw_answer=?,"
                "current_normalized_answer=?,submitted_answer=?,answer_source=?,confidence=NULL,student_action='none',updated_at=? "
                "WHERE submission_id=? AND question_no=?",
                (str(choice).strip(), normalized, normalized, ANSWER_SOURCE_STUDENT_CHOICE, now, submission_id, question_no),
            )
            status = self._recognition_completion_status(connection, submission_id)
            connection.execute(
                "UPDATE student_test_ocr_submissions SET status=?,revision=revision+1,updated_at=? WHERE id=?",
                (status, now, submission_id),
            )
            return self._hydrate(connection, self._load_submission_row(connection, submission_id))

        return self._write(action)

    def record_answer_value_recapture(
        self,
        submission_id: str,
        *,
        question_no: int,
        raw_answer: object,
        confident: bool,
        confidence: float | None,
        asset_id: str,
        crop_relpath: str,
        crop_expires_at: str,
        asset_created_at: str,
        expected_revision: int,
        now: str,
        job_id: str | None = None,
        lease_token: str = "",
    ) -> dict:
        raw = str(raw_answer or "").strip()
        normalized = normalize_recognized_answer(ANSWER_VALUE, raw)
        if confident and not normalized:
            raise StudentTestOcrConflictError("invalid_recognition", "confident recapture must contain an answer")
        if confidence is not None and (
            isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1
        ):
            raise StudentTestOcrConflictError("invalid_recognition", "recapture confidence is invalid")
        asset_id_text = self._validate_text(asset_id, "asset id")
        crop_relative = str(crop_relpath or "").replace("\\", "/").strip("/")
        crop_expiry = self._validate_text(crop_expires_at, "asset expiry")
        asset_created = self._validate_text(asset_created_at, "asset creation time")
        if not crop_relative or ".." in crop_relative.split("/"):
            raise StudentTestOcrConflictError("invalid_asset", "recapture asset path is invalid")

        def action(connection: sqlite3.Connection):
            row = self._require_revision(self._load_submission_row(connection, submission_id), expected_revision)
            if job_id is not None:
                job = connection.execute(
                    "SELECT state,lease_token,lease_expires_at,payload_json FROM student_test_ocr_jobs "
                    "WHERE id=? AND submission_id=?", (job_id, submission_id),
                ).fetchone()
                if (job is None or job["state"] != "running" or job["lease_token"] != lease_token
                        or job["lease_expires_at"] <= now):
                    raise StudentTestOcrConflictError("lease_conflict", "OCR job lease changed")
                payload = json.loads(job["payload_json"])
                if payload.get("schema") != "student_test_ocr_question_job_v1" or payload.get("questionNo") != question_no:
                    raise StudentTestOcrConflictError("invalid_job", "question job context is invalid")
            expected_status = "processing" if job_id is not None else STATUS_STUDENT_ACTION_REQUIRED
            if row["status"] != expected_status:
                raise StudentTestOcrConflictError("state_conflict", "submission is not waiting for a question recapture")
            question = connection.execute(
                f"SELECT {','.join(QUESTION_FIELDS)} FROM student_test_ocr_questions "
                "WHERE submission_id=? AND question_no=?",
                (submission_id, question_no),
            ).fetchone()
            if question is None or question["answer_mode"] != ANSWER_VALUE or question["student_action"] != ACTION_QUESTION_RECAPTURE:
                raise StudentTestOcrConflictError("state_conflict", "question is not waiting for an answer-value recapture")
            attempts = int(question["recapture_attempts"]) + 1
            if attempts > MAX_ANSWER_VALUE_RECAPTURES:
                raise StudentTestOcrConflictError("recapture_limit", "question recapture limit was reached")
            next_action = answer_value_recapture_decision(attempts_used=attempts, confident=confident)
            recognition_state = "confident" if confident else ("pending_teacher" if next_action == ACTION_PENDING_TEACHER else "uncertain")
            if job_id is None:
                connection.execute(
                    "INSERT INTO student_test_ocr_assets("
                    "id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at"
                    ") VALUES(?,?,?,'student_crop',?,?,NULL,?)",
                    (asset_id_text, submission_id, question_no, crop_relative, crop_expiry, asset_created),
                )
            else:
                asset = connection.execute(
                    "SELECT id FROM student_test_ocr_assets WHERE id=? AND submission_id=? AND question_no=? "
                    "AND relative_path=? AND expires_at=? AND deleted_at IS NULL",
                    (asset_id_text, submission_id, question_no, crop_relative, crop_expiry),
                ).fetchone()
                if asset is None:
                    raise StudentTestOcrConflictError("invalid_asset", "queued question asset changed")
            connection.execute(
                "UPDATE student_test_ocr_questions SET recognition_state=?,current_raw_answer=?,"
                "current_normalized_answer=?,submitted_answer=?,answer_source=?,confidence=?,student_action=?,"
                "recapture_attempts=?,crop_relpath=?,crop_expires_at=?,updated_at=? "
                "WHERE submission_id=? AND question_no=?",
                (
                    recognition_state,
                    raw,
                    normalized,
                    normalized if confident else "",
                    ANSWER_SOURCE_QUESTION_RECAPTURE if confident else "",
                    None if confidence is None else float(confidence),
                    next_action,
                    attempts,
                    crop_relative,
                    crop_expiry,
                    now,
                    submission_id,
                    question_no,
                ),
            )
            status = self._recognition_completion_status(connection, submission_id)
            connection.execute(
                "UPDATE student_test_ocr_submissions SET status=?,revision=revision+1,updated_at=? WHERE id=?",
                (status, now, submission_id),
            )
            if job_id is not None:
                connection.execute(
                    "UPDATE student_test_ocr_jobs SET state='succeeded',result_json=?,lease_token='',"
                    "lease_expires_at='',error_code='',updated_at=? WHERE id=?",
                    (json.dumps({"questionNo": question_no, "confident": bool(confident)}, separators=(",", ":")), now, job_id),
                )
            return self._hydrate(connection, self._load_submission_row(connection, submission_id))

        return self._write(action)

    def register_full_sheet_retake(
        self,
        submission_id: str,
        *,
        full_sheet_asset: Mapping[str, object],
        job_payload: Mapping[str, object],
        expected_revision: int,
        now: str,
    ) -> dict:
        self._reject_answer_key_fields(job_payload)
        payload_json = json.dumps(job_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(payload_json) > 100_000:
            raise StudentTestOcrConflictError("invalid_job", "OCR job payload is too large")
        asset_id = self._validate_text(full_sheet_asset.get("id"), "asset id")
        relative = str(full_sheet_asset.get("relativePath") or "").replace("\\", "/").strip("/")
        expires_at = self._validate_text(full_sheet_asset.get("expiresAt"), "asset expiry")
        created_at = self._validate_text(full_sheet_asset.get("createdAt") or now, "asset creation time")
        if not relative or ".." in relative.split("/"):
            raise StudentTestOcrConflictError("invalid_asset", "full-sheet asset path is invalid")
        payload_revision = job_payload.get("submissionRevision")
        if (
            isinstance(payload_revision, bool)
            or not isinstance(payload_revision, int)
            or payload_revision != expected_revision + 1
        ):
            raise StudentTestOcrConflictError("invalid_job", "retake job revision is invalid")

        def action(connection: sqlite3.Connection):
            row = self._require_revision(self._load_submission_row(connection, submission_id), expected_revision)
            if row["status"] != STATUS_RETAKE_REQUIRED:
                raise StudentTestOcrConflictError("state_conflict", "submission is not waiting for a full-sheet retake")
            job = connection.execute(
                "SELECT id,state FROM student_test_ocr_jobs WHERE submission_id=?",
                (submission_id,),
            ).fetchone()
            if job is None or job["state"] not in {"succeeded", "failed"}:
                raise StudentTestOcrConflictError("state_conflict", "OCR job is not ready for a full-sheet retake")
            connection.execute(
                "INSERT INTO student_test_ocr_assets("
                "id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at"
                ") VALUES(?,?,NULL,'full_sheet',?,?,NULL,?)",
                (asset_id, submission_id, relative, expires_at, created_at),
            )
            connection.execute(
                "UPDATE student_test_ocr_submissions SET status='processing',revision=revision+1,updated_at=? WHERE id=?",
                (now, submission_id),
            )
            connection.execute(
                "UPDATE student_test_ocr_jobs SET state='queued',payload_json=?,result_json='',lease_token='',"
                "lease_expires_at='',error_code='',updated_at=? WHERE id=?",
                (payload_json, now, job["id"]),
            )
            return {
                "submission": self._hydrate(connection, self._load_submission_row(connection, submission_id)),
                "job": {"id": job["id"], "state": "queued"},
            }

        return self._write(action)

    def register_question_recapture(
        self, submission_id: str, *, question_no: int, student_crop: Mapping[str, object],
        job_payload: Mapping[str, object], expected_revision: int, now: str,
    ) -> dict:
        self._reject_answer_key_fields(job_payload)
        if (type(question_no) is not int or not 1 <= question_no <= PROBLEM_COUNT
                or job_payload.get("schema") != "student_test_ocr_question_job_v1"
                or job_payload.get("questionNo") != question_no
                or type(job_payload.get("submissionRevision")) is not int
                or job_payload["submissionRevision"] != expected_revision + 1):
            raise StudentTestOcrConflictError("invalid_job", "question recapture job is invalid")
        asset_id = self._validate_text(student_crop.get("id"), "asset id")
        relative = self._validate_text(student_crop.get("relativePath"), "crop path", maximum=1000)
        expiry = self._validate_text(student_crop.get("expiresAt"), "crop expiry")
        created = self._validate_text(student_crop.get("createdAt"), "crop creation")
        if (".." in relative.replace("\\", "/").split("/") or relative != job_payload.get("captureRelativePath")
                or asset_id != job_payload.get("captureAssetId") or expiry != job_payload.get("cropExpiresAt")
                or created != job_payload.get("cropCreatedAt")):
            raise StudentTestOcrConflictError("invalid_asset", "question crop context is invalid")
        encoded = json.dumps(job_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(encoded) > 100_000:
            raise StudentTestOcrConflictError("invalid_job", "question job is too large")

        def action(connection: sqlite3.Connection):
            row = self._require_revision(self._load_submission_row(connection, submission_id), expected_revision)
            question = connection.execute(
                "SELECT answer_mode,student_action,recapture_attempts FROM student_test_ocr_questions "
                "WHERE submission_id=? AND question_no=?", (submission_id, question_no),
            ).fetchone()
            job = connection.execute(
                "SELECT id,state FROM student_test_ocr_jobs WHERE submission_id=?", (submission_id,),
            ).fetchone()
            if (row["status"] != STATUS_STUDENT_ACTION_REQUIRED or question is None
                    or question["answer_mode"] != ANSWER_VALUE or question["student_action"] != ACTION_QUESTION_RECAPTURE
                    or question["recapture_attempts"] >= MAX_ANSWER_VALUE_RECAPTURES
                    or job is None or job["state"] != "succeeded"):
                raise StudentTestOcrConflictError("state_conflict", "question is not ready for recapture")
            connection.execute(
                "INSERT INTO student_test_ocr_assets(id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at) "
                "VALUES(?,?,?,'student_crop',?,?,NULL,?)", (asset_id, submission_id, question_no, relative, expiry, created),
            )
            connection.execute(
                "UPDATE student_test_ocr_submissions SET status='processing',revision=revision+1,updated_at=? WHERE id=?",
                (now, submission_id),
            )
            connection.execute(
                "UPDATE student_test_ocr_jobs SET state='queued',payload_json=?,result_json='',lease_token='',"
                "lease_expires_at='',error_code='',updated_at=? WHERE id=?", (encoded, now, job["id"]),
            )
            return self._hydrate(connection, self._load_submission_row(connection, submission_id))
        return self._write(action)

    def record_grading(
        self,
        submission_id: str,
        grade_states: Sequence[object],
        *,
        expected_revision: int,
        now: str,
    ) -> dict:
        summary = summarize_grades(grade_states)
        grades = tuple(str(grade) for grade in grade_states)

        def action(connection: sqlite3.Connection):
            row = self._require_revision(self._load_submission_row(connection, submission_id), expected_revision)
            if row["status"] != STATUS_READY_TO_GRADE:
                raise StudentTestOcrConflictError("state_conflict", "submission is not ready to grade")
            questions = self._questions(connection, submission_id)
            if len(questions) != PROBLEM_COUNT:
                raise StudentTestOcrConflictError("state_conflict", "submission question set is incomplete")
            for question, grade in zip(questions, grades):
                if grade == GRADE_PENDING:
                    if question["recognition_state"] != "pending_teacher":
                        raise StudentTestOcrConflictError("invalid_grading", "only teacher-pending recognition can be pending")
                elif not question["submitted_answer"]:
                    raise StudentTestOcrConflictError("invalid_grading", "graded question is missing its submitted answer")
                connection.execute(
                    "UPDATE student_test_ocr_questions SET initial_grade=?,effective_grade=?,updated_at=? "
                    "WHERE submission_id=? AND question_no=?",
                    (grade, grade, now, submission_id, question["question_no"]),
                )
            finalized_at = now if summary["status"] == STATUS_FINALIZED else None
            connection.execute(
                "UPDATE student_test_ocr_submissions SET status=?,answer_released=1,accepted_at=?,finalized_at=?,"
                "revision=revision+1,updated_at=? WHERE id=?",
                (summary["status"], now, finalized_at, now, submission_id),
            )
            return self._hydrate(connection, self._load_submission_row(connection, submission_id))

        return self._write(action)

    def resolve_pending(
        self,
        submission_id: str,
        *,
        question_no: int,
        correct: bool,
        expected_revision: int,
        now: str,
    ) -> dict:
        def action(connection: sqlite3.Connection):
            row = self._require_revision(self._load_submission_row(connection, submission_id), expected_revision)
            if row["status"] != STATUS_PENDING_TEACHER:
                raise StudentTestOcrConflictError("state_conflict", "submission has no teacher-pending questions")
            question = connection.execute(
                "SELECT effective_grade FROM student_test_ocr_questions WHERE submission_id=? AND question_no=?",
                (submission_id, question_no),
            ).fetchone()
            if question is None or question["effective_grade"] != GRADE_PENDING:
                raise StudentTestOcrConflictError("grade_transition_rejected", "only a pending question can be resolved")
            grade = GRADE_CORRECT if correct else GRADE_INCORRECT
            connection.execute(
                "UPDATE student_test_ocr_questions SET effective_grade=?,student_action='none',updated_at=? "
                "WHERE submission_id=? AND question_no=?",
                (grade, now, submission_id, question_no),
            )
            pending = connection.execute(
                "SELECT COUNT(*) FROM student_test_ocr_questions WHERE submission_id=? AND effective_grade='pending'",
                (submission_id,),
            ).fetchone()[0]
            status = STATUS_PENDING_TEACHER if int(pending) else STATUS_FINALIZED
            finalized_at = row["finalized_at"] if int(pending) else now
            connection.execute(
                "UPDATE student_test_ocr_submissions SET status=?,finalized_at=?,revision=revision+1,updated_at=? WHERE id=?",
                (status, finalized_at, now, submission_id),
            )
            return self._hydrate(connection, self._load_submission_row(connection, submission_id))

        return self._write(action)

    def correct_wrong_to_correct(
        self,
        submission_id: str,
        *,
        question_no: int,
        expected_revision: int,
        now: str,
    ) -> dict:
        def action(connection: sqlite3.Connection):
            row = self._require_revision(self._load_submission_row(connection, submission_id), expected_revision)
            if row["status"] not in {STATUS_PENDING_TEACHER, STATUS_FINALIZED}:
                raise StudentTestOcrConflictError("state_conflict", "submission is not an accepted result")
            question = connection.execute(
                "SELECT effective_grade FROM student_test_ocr_questions WHERE submission_id=? AND question_no=?",
                (submission_id, question_no),
            ).fetchone()
            if question is None or question["effective_grade"] != GRADE_INCORRECT:
                raise StudentTestOcrConflictError(
                    "grade_transition_rejected",
                    "only an incorrect question can be changed to correct",
                )
            try:
                connection.execute(
                    "INSERT INTO student_test_ocr_grade_history(submission_id,question_no,from_grade,to_grade) "
                    "VALUES(?,?,'incorrect','correct')",
                    (submission_id, question_no),
                )
            except sqlite3.IntegrityError as error:
                raise StudentTestOcrConflictError(
                    "grade_transition_rejected",
                    "this question was already corrected",
                ) from error
            connection.execute(
                "UPDATE student_test_ocr_questions SET effective_grade='correct',updated_at=? "
                "WHERE submission_id=? AND question_no=?",
                (now, submission_id, question_no),
            )
            connection.execute(
                "UPDATE student_test_ocr_submissions SET revision=revision+1,updated_at=? WHERE id=?",
                (now, submission_id),
            )
            return self._hydrate(connection, self._load_submission_row(connection, submission_id))

        return self._write(action)

    def list_pending_for_date(self, assignment_date: str) -> list[dict]:
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                f"SELECT {','.join(SUBMISSION_FIELDS)} FROM student_test_ocr_submissions "
                "WHERE assignment_date=? AND status='pending_teacher' ORDER BY updated_at,id",
                (assignment_date,),
            ).fetchall()
            return [self._hydrate(connection, row) for row in rows]

    def list_overdue_pending(
        self, *, before_date: str, now: str, limit: int = 100, after_id: str = "",
    ) -> list[dict]:
        day = dt.date.fromisoformat(before_date)
        if day.isoformat() != before_date:
            raise ValueError("invalid overdue date")
        instant = self._retention_instant(now)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("invalid overdue limit")
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT s.id,s.sid,s.test_id,s.round_no,s.assignment_date "
                "FROM student_test_ocr_submissions s WHERE s.assignment_date<? AND s.id>? "
                "AND s.assignment_date>='0001-01-01' AND date(s.assignment_date)=s.assignment_date "
                "AND s.status='pending_teacher' AND EXISTS("
                "SELECT 1 FROM student_test_ocr_questions q WHERE q.submission_id=s.id "
                "AND q.effective_grade='pending') ORDER BY s.id LIMIT ?",
                (before_date, after_id, limit),
            ).fetchall()
            summaries = []
            for row in rows:
                try:
                    if dt.date.fromisoformat(row["assignment_date"]).isoformat() != row["assignment_date"]:
                        continue
                except (TypeError, ValueError):
                    continue
                questions = connection.execute(
                    "SELECT question_no,crop_expires_at FROM student_test_ocr_questions "
                    "WHERE submission_id=? AND effective_grade='pending' ORDER BY question_no",
                    (row["id"],),
                ).fetchall()
                expired = 0
                for question in questions:
                    try:
                        expired += self._retention_instant(question["crop_expires_at"]) <= instant
                    except StudentTestOcrConflictError:
                        # Missing/invalid expiry is not proof that a file can be deleted.
                        pass
                summaries.append({**dict(row), "pendingQuestionNos": [q["question_no"] for q in questions],
                                  "expiredCropCount": expired})
            return summaries

    @staticmethod
    def _reject_answer_key_fields(value: object) -> None:
        forbidden = {
            "answer",
            "answers",
            "answerkey",
            "answerkeys",
            "correctanswer",
            "correctanswers",
            "expected",
            "canonical",
            "grading",
        }

        def visit(node: object) -> None:
            if isinstance(node, Mapping):
                for key, nested in node.items():
                    compact = "".join(character for character in str(key).lower() if character.isalnum())
                    if compact in forbidden:
                        raise StudentTestOcrConflictError(
                            "answer_key_leak",
                            "OCR job payload must not contain answer-key or grading fields",
                        )
                    visit(nested)
            elif isinstance(node, list):
                for nested in node:
                    visit(nested)

        visit(value)

    def enqueue_job(
        self,
        *,
        job_id: str,
        submission_id: str,
        payload: Mapping[str, object],
        now: str,
    ) -> dict:
        self._reject_answer_key_fields(payload)
        payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(payload_json) > 100_000:
            raise StudentTestOcrConflictError("invalid_job", "OCR job payload is too large")

        def action(connection: sqlite3.Connection):
            if self._load_submission_row(connection, submission_id) is None:
                raise StudentTestOcrConflictError("submission_not_found", "OCR submission was not found")
            existing = connection.execute(
                "SELECT id,submission_id,state,payload_json,result_json,attempts,lease_token,lease_expires_at,"
                "error_code,created_at,updated_at FROM student_test_ocr_jobs WHERE submission_id=?",
                (submission_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] == payload_json:
                    return dict(existing)
                raise StudentTestOcrConflictError("idempotency_conflict", "submission already has another OCR job")
            connection.execute(
                "INSERT INTO student_test_ocr_jobs("
                "id,submission_id,state,payload_json,result_json,attempts,lease_token,lease_expires_at,error_code,created_at,updated_at"
                ") VALUES(?,?,'queued',?,'',0,'','','',?,?)",
                (job_id, submission_id, payload_json, now, now),
            )
            row = connection.execute(
                "SELECT id,submission_id,state,payload_json,result_json,attempts,lease_token,lease_expires_at,"
                "error_code,created_at,updated_at FROM student_test_ocr_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            return dict(row)

        return self._write(action)

    def list_ready_to_grade(self, *, limit: int = 100, after_id: str = "") -> list[dict]:
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                f"SELECT {','.join(SUBMISSION_FIELDS)} FROM student_test_ocr_submissions "
                "WHERE status='ready_to_grade' AND id>? ORDER BY id LIMIT ?", (after_id, limit),
            ).fetchall()
            return [self._hydrate(connection, row) for row in rows]

    def has_recovery_work(self, *, now: str) -> bool:
        with closing(self._connect(readonly=True)) as connection:
            return connection.execute(
                "SELECT 1 FROM student_test_ocr_jobs WHERE state='queued' "
                "OR (state='running' AND lease_expires_at<>'' AND lease_expires_at<=?) LIMIT 1", (now,),
            ).fetchone() is not None or connection.execute(
                "SELECT 1 FROM student_test_ocr_submissions WHERE status='ready_to_grade' LIMIT 1",
            ).fetchone() is not None

    def renew_job_lease(self, job_id: str, *, lease_token: str, now: str, lease_expires_at: str) -> bool:
        def action(connection: sqlite3.Connection):
            changed = connection.execute(
                "UPDATE student_test_ocr_jobs SET lease_expires_at=?,updated_at=? WHERE id=? AND state='running' "
                "AND lease_token=? AND lease_expires_at>?", (lease_expires_at, now, job_id, lease_token, now),
            )
            return changed.rowcount == 1
        return bool(self._write(action))

    def lease_next_job(self, *, lease_token: str, now: str, lease_expires_at: str) -> dict | None:
        def action(connection: sqlite3.Connection):
            row = connection.execute(
                "SELECT id FROM student_test_ocr_jobs WHERE state='queued' "
                "OR (state='running' AND lease_expires_at<>'' AND lease_expires_at<=?) "
                "ORDER BY created_at,id LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE student_test_ocr_jobs SET state='running',attempts=attempts+1,lease_token=?,"
                "lease_expires_at=?,error_code='',updated_at=? WHERE id=?",
                (lease_token, lease_expires_at, now, row["id"]),
            )
            leased = connection.execute(
                "SELECT id,submission_id,state,payload_json,result_json,attempts,lease_token,lease_expires_at,"
                "error_code,created_at,updated_at FROM student_test_ocr_jobs WHERE id=?",
                (row["id"],),
            ).fetchone()
            result = dict(leased)
            result["payload"] = json.loads(result["payload_json"])
            return result

        return self._write(action)

    def finish_job(
        self,
        job_id: str,
        *,
        lease_token: str,
        succeeded: bool,
        result: Mapping[str, object] | None,
        error_code: str,
        now: str,
    ) -> dict:
        result_json = (
            json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            if isinstance(result, Mapping)
            else ""
        )
        if len(result_json) > 500_000 or len(str(error_code or "")) > 80:
            raise StudentTestOcrConflictError("invalid_job", "OCR job outcome is too large")

        def action(connection: sqlite3.Connection):
            row = connection.execute(
                "SELECT state,lease_token,lease_expires_at,submission_id FROM student_test_ocr_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if row is None or row["state"] != "running" or row["lease_token"] != lease_token or row["lease_expires_at"] <= now:
                raise StudentTestOcrConflictError("lease_conflict", "OCR job lease changed")
            state = "succeeded" if succeeded else "failed"
            connection.execute(
                "UPDATE student_test_ocr_jobs SET state=?,result_json=?,lease_token='',lease_expires_at='',"
                "error_code=?,updated_at=? WHERE id=?",
                (state, result_json, "" if succeeded else str(error_code or "ocr_failed"), now, job_id),
            )
            if not succeeded:
                connection.execute(
                    "UPDATE student_test_ocr_submissions SET status='failed',revision=revision+1,updated_at=? "
                    "WHERE id=? AND status='processing'",
                    (now, row["submission_id"]),
                )
            saved = connection.execute(
                "SELECT id,submission_id,state,payload_json,result_json,attempts,lease_token,lease_expires_at,"
                "error_code,created_at,updated_at FROM student_test_ocr_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            return dict(saved)

        return self._write(action)

    def finish_job_with_recognition(
        self,
        job_id: str,
        *,
        lease_token: str,
        submission_id: str,
        decision: Mapping[str, object],
        assets: Sequence[Mapping[str, object]] = (),
        expected_revision: int,
        now: str,
    ) -> dict:
        status, indexed = self._validated_recognition_decision(decision)
        result_json = json.dumps(decision, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        if len(result_json) > 500_000:
            raise StudentTestOcrConflictError("invalid_job", "OCR recognition result is too large")
        prepared_assets: list[tuple[str, int, str, str, str, str]] = []
        asset_ids: set[str] = set()
        for raw_asset in assets:
            asset_id = str(raw_asset.get("id") or "").strip()
            question_no = raw_asset.get("questionNo")
            kind = str(raw_asset.get("kind") or "")
            relative = str(raw_asset.get("relativePath") or "").replace("\\", "/").strip("/")
            expires_at = str(raw_asset.get("expiresAt") or "").strip()
            created_at = str(raw_asset.get("createdAt") or now).strip()
            if (
                not asset_id
                or asset_id in asset_ids
                or isinstance(question_no, bool)
                or not isinstance(question_no, int)
                or not 1 <= question_no <= PROBLEM_COUNT
                or kind != "student_crop"
                or not relative
                or ".." in relative.split("/")
                or not expires_at
            ):
                raise StudentTestOcrConflictError("invalid_asset", "OCR crop asset contract is invalid")
            asset_ids.add(asset_id)
            prepared_assets.append((asset_id, question_no, kind, relative, expires_at, created_at))
        if prepared_assets and len(prepared_assets) != PROBLEM_COUNT:
            raise StudentTestOcrConflictError("invalid_asset", "OCR recognition must register all 20 crop assets")

        def action(connection: sqlite3.Connection):
            job = connection.execute(
                "SELECT state,lease_token,lease_expires_at,submission_id FROM student_test_ocr_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if (
                job is None
                or job["state"] != "running"
                or job["lease_token"] != lease_token
                or job["lease_expires_at"] <= now
                or job["submission_id"] != submission_id
            ):
                raise StudentTestOcrConflictError("lease_conflict", "OCR job lease changed")
            submission = self._apply_sheet_recognition(
                connection,
                submission_id,
                status=status,
                indexed=indexed,
                expected_revision=expected_revision,
                now=now,
            )
            if prepared_assets:
                connection.executemany(
                    "INSERT INTO student_test_ocr_assets("
                    "id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at"
                    ") VALUES(?,?,?,?,?,?,NULL,?)",
                    [
                        (asset_id, submission_id, question_no, kind, relative, expires_at, created_at)
                        for asset_id, question_no, kind, relative, expires_at, created_at in prepared_assets
                    ],
                )
            connection.execute(
                "UPDATE student_test_ocr_jobs SET state='succeeded',result_json=?,lease_token='',lease_expires_at='',"
                "error_code='',updated_at=? WHERE id=?",
                (result_json, now, job_id),
            )
            saved_job = connection.execute(
                "SELECT id,submission_id,state,payload_json,result_json,attempts,lease_token,lease_expires_at,"
                "error_code,created_at,updated_at FROM student_test_ocr_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            return {"job": dict(saved_job), "submission": submission}

        return self._write(action)

    def get_job_for_submission(self, submission_id: str) -> dict | None:
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT id,submission_id,state,payload_json,result_json,attempts,lease_token,lease_expires_at,"
                "error_code,created_at,updated_at FROM student_test_ocr_jobs WHERE submission_id=?",
                (submission_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["payload"] = json.loads(result["payload_json"])
            result["result"] = json.loads(result["result_json"]) if result["result_json"] else None
            return result

    def register_asset(
        self,
        *,
        asset_id: str,
        submission_id: str,
        question_no: int | None,
        kind: str,
        relative_path: str,
        expires_at: str,
        created_at: str,
    ) -> dict:
        if kind not in {"full_sheet", "student_crop", "solution_crop"}:
            raise StudentTestOcrConflictError("invalid_asset", "OCR asset kind is invalid")
        if question_no is not None and (
            isinstance(question_no, bool) or not isinstance(question_no, int) or not 1 <= question_no <= PROBLEM_COUNT
        ):
            raise StudentTestOcrConflictError("invalid_asset", "OCR asset question number is invalid")
        relative = str(relative_path or "").replace("\\", "/").strip("/")
        if not relative or ".." in relative.split("/"):
            raise StudentTestOcrConflictError("invalid_asset", "OCR asset path is invalid")

        def action(connection: sqlite3.Connection):
            if self._load_submission_row(connection, submission_id) is None:
                raise StudentTestOcrConflictError("submission_not_found", "OCR submission was not found")
            connection.execute(
                "INSERT INTO student_test_ocr_assets("
                "id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at"
                ") VALUES(?,?,?,?,?,?,NULL,?)",
                (asset_id, submission_id, question_no, kind, relative, expires_at, created_at),
            )
            row = connection.execute(
                "SELECT id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at "
                "FROM student_test_ocr_assets WHERE id=?",
                (asset_id,),
            ).fetchone()
            return dict(row)

        return self._write(action)

    @staticmethod
    def _retention_instant(value: str) -> dt.datetime:
        try:
            result = dt.datetime.fromisoformat(value)
            if result.tzinfo is None or result.utcoffset() is None:
                raise ValueError()
            return result.astimezone(dt.timezone.utc)
        except (TypeError, ValueError):
            raise StudentTestOcrConflictError("invalid_asset_timestamp", "OCR retention timestamp is invalid")

    def expired_assets(self, *, now: str, limit: int = 100, after_id: str = "") -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("invalid asset retention limit")
        self._retention_instant(now)
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at "
                "FROM student_test_ocr_assets WHERE deleted_at IS NULL AND id>? "
                "AND (julianday(expires_at)<=julianday(?) OR julianday(expires_at) IS NULL) ORDER BY id LIMIT ?",
                (after_id, now, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def purge_expired_asset(self, asset_id: str, *, now: str, unlink: Callable[[dict], None]) -> str:
        instant = self._retention_instant(now)

        def action(connection: sqlite3.Connection):
            row = connection.execute(
                "SELECT id,submission_id,relative_path,expires_at,deleted_at "
                "FROM student_test_ocr_assets WHERE id=?", (asset_id,),
            ).fetchone()
            if row is None or row["deleted_at"] is not None:
                return "not_due"
            if self._retention_instant(row["expires_at"]) > instant:
                return "not_due"
            job = connection.execute(
                "SELECT state,lease_expires_at FROM student_test_ocr_jobs WHERE submission_id=?",
                (row["submission_id"],),
            ).fetchone()
            if job is not None and job["state"] == "running":
                try:
                    if self._retention_instant(job["lease_expires_at"]) > instant:
                        return "busy"
                except StudentTestOcrConflictError:
                    return "busy"
            # BEGIN IMMEDIATE excludes lease acquisition/renewal until this single-file deletion commits.
            unlink(dict(row))
            connection.execute(
                "UPDATE student_test_ocr_assets SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (now, asset_id),
            )
            return "deleted"

        return self._write(action)

    def list_assets_for_submission(self, submission_id: str, *, include_deleted: bool = False) -> list[dict]:
        where = "submission_id=?" if include_deleted else "submission_id=? AND deleted_at IS NULL"
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at "
                f"FROM student_test_ocr_assets WHERE {where} ORDER BY kind,question_no,id",
                (submission_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_asset(self, asset_id: str) -> dict | None:
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT id,submission_id,question_no,kind,relative_path,expires_at,deleted_at,created_at "
                "FROM student_test_ocr_assets WHERE id=?",
                (str(asset_id or "").strip(),),
            ).fetchone()
            return dict(row) if row is not None else None

    def mark_asset_deleted(self, asset_id: str, *, deleted_at: str) -> bool:
        def action(connection: sqlite3.Connection):
            cursor = connection.execute(
                "UPDATE student_test_ocr_assets SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (deleted_at, asset_id),
            )
            return bool(cursor.rowcount)

        return self._write(action)
