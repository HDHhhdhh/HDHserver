BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS student_test_ocr_submissions (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    sid TEXT NOT NULL,
    test_id TEXT NOT NULL,
    round_no TEXT NOT NULL,
    assignment_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'processing', 'student_action_required', 'retake_required',
        'ready_to_grade', 'pending_teacher', 'finalized', 'failed'
    )),
    problem_count INTEGER NOT NULL DEFAULT 20 CHECK (problem_count = 20),
    capture_attempts INTEGER NOT NULL DEFAULT 0 CHECK (capture_attempts >= 0),
    answer_released INTEGER NOT NULL DEFAULT 0 CHECK (answer_released IN (0, 1)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    accepted_at TEXT,
    finalized_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (sid, test_id, round_no, assignment_date)
);

CREATE INDEX IF NOT EXISTS idx_student_test_ocr_submission_sid_date
    ON student_test_ocr_submissions(sid, assignment_date DESC, created_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_student_test_ocr_submission_pending
    ON student_test_ocr_submissions(assignment_date, status, updated_at, id)
    WHERE status = 'pending_teacher';

CREATE TABLE IF NOT EXISTS student_test_ocr_capture_tokens (
    id TEXT PRIMARY KEY,
    token_digest TEXT NOT NULL UNIQUE,
    sid TEXT NOT NULL,
    test_id TEXT NOT NULL,
    round_no TEXT NOT NULL,
    assignment_date TEXT NOT NULL,
    assignment_label TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_student_test_ocr_token_lookup
    ON student_test_ocr_capture_tokens(token_digest, expires_at, used_at);

CREATE TABLE IF NOT EXISTS student_test_ocr_questions (
    submission_id TEXT NOT NULL,
    question_no INTEGER NOT NULL CHECK (question_no BETWEEN 1 AND 20),
    answer_mode TEXT NOT NULL CHECK (answer_mode IN ('choice_number', 'answer_value')),
    recognition_state TEXT NOT NULL DEFAULT 'awaiting' CHECK (recognition_state IN (
        'awaiting', 'confident', 'uncertain', 'pending_teacher'
    )),
    initial_raw_answer TEXT NOT NULL DEFAULT '',
    initial_normalized_answer TEXT NOT NULL DEFAULT '',
    current_raw_answer TEXT NOT NULL DEFAULT '',
    current_normalized_answer TEXT NOT NULL DEFAULT '',
    submitted_answer TEXT NOT NULL DEFAULT '',
    answer_source TEXT NOT NULL DEFAULT '' CHECK (answer_source IN (
        '', 'ocr_initial', 'student_choice_correction', 'ocr_question_recapture'
    )),
    confidence REAL,
    student_action TEXT NOT NULL DEFAULT 'none' CHECK (student_action IN (
        'none', 'student_choice', 'question_recapture', 'full_sheet_retake', 'pending_teacher'
    )),
    recapture_attempts INTEGER NOT NULL DEFAULT 0 CHECK (recapture_attempts BETWEEN 0 AND 2),
    initial_grade TEXT NOT NULL DEFAULT '' CHECK (initial_grade IN ('', 'correct', 'incorrect', 'pending')),
    effective_grade TEXT NOT NULL DEFAULT '' CHECK (effective_grade IN ('', 'correct', 'incorrect', 'pending')),
    crop_relpath TEXT NOT NULL DEFAULT '',
    crop_expires_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (submission_id, question_no),
    FOREIGN KEY (submission_id) REFERENCES student_test_ocr_submissions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_student_test_ocr_question_pending
    ON student_test_ocr_questions(effective_grade, submission_id, question_no)
    WHERE effective_grade = 'pending';

CREATE TABLE IF NOT EXISTS student_test_ocr_assets (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    question_no INTEGER CHECK (question_no BETWEEN 1 AND 20),
    kind TEXT NOT NULL CHECK (kind IN ('full_sheet', 'student_crop', 'solution_crop')),
    relative_path TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES student_test_ocr_submissions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_student_test_ocr_asset_retention
    ON student_test_ocr_assets(expires_at, id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS student_test_ocr_jobs (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'succeeded', 'failed')),
    payload_json TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_token TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES student_test_ocr_submissions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_student_test_ocr_job_queue
    ON student_test_ocr_jobs(state, lease_expires_at, created_at, id);

CREATE TABLE IF NOT EXISTS student_test_ocr_grade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL,
    question_no INTEGER NOT NULL CHECK (question_no BETWEEN 1 AND 20),
    from_grade TEXT NOT NULL CHECK (from_grade = 'incorrect'),
    to_grade TEXT NOT NULL CHECK (to_grade = 'correct'),
    FOREIGN KEY (submission_id, question_no)
        REFERENCES student_test_ocr_questions(submission_id, question_no) ON DELETE CASCADE,
    UNIQUE (submission_id, question_no)
);

COMMIT;
