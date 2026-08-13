BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS student_homework_assignments (
    id TEXT PRIMARY KEY,
    sid TEXT NOT NULL,
    curriculum_sid TEXT,
    title TEXT NOT NULL,
    book TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    assigned_at TEXT NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('assigned', 'completed', 'cancelled')),
    completed_at TEXT,
    source_log_date TEXT NOT NULL,
    source_row_id TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (status = 'completed' AND completed_at IS NOT NULL)
        OR (status <> 'completed' AND completed_at IS NULL)
    ),
    UNIQUE (source_log_date, source_row_id)
);

CREATE INDEX IF NOT EXISTS idx_student_homework_sid_status_due_assigned_id
    ON student_homework_assignments(sid, status, due_at, assigned_at, id);
CREATE INDEX IF NOT EXISTS idx_student_homework_sid_source
    ON student_homework_assignments(sid, source_log_date, source_row_id);

CREATE TABLE IF NOT EXISTS student_homework_reconciliations (
    id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE,
    sid TEXT NOT NULL,
    source_log_date TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    desired_log_json TEXT NOT NULL,
    desired_assignments_json TEXT NOT NULL,
    log_state TEXT NOT NULL CHECK (log_state IN ('pending', 'succeeded', 'failed', 'conflict')),
    homework_state TEXT NOT NULL CHECK (homework_state IN ('pending', 'succeeded', 'failed', 'conflict')),
    state TEXT NOT NULL CHECK (state IN ('prepared', 'partial_failure', 'completed', 'blocked')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error_code TEXT NOT NULL DEFAULT '' CHECK (last_error_code IN (
        '', 'log_write_failed', 'homework_write_failed', 'revision_conflict',
        'idempotency_conflict', 'homework_not_initialized', 'invalid_payload',
        'unexpected_failure'
    )),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_student_homework_reconciliation_active_source
    ON student_homework_reconciliations(sid, source_log_date)
    WHERE state IN ('prepared', 'partial_failure');
CREATE INDEX IF NOT EXISTS idx_student_homework_reconciliation_state
    ON student_homework_reconciliations(state, updated_at, id);

COMMIT;
