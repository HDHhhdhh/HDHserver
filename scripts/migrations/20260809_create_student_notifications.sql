BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS student_notification_preferences (
    aid TEXT PRIMARY KEY,
    schedule_enabled INTEGER NOT NULL CHECK (schedule_enabled IN (0, 1)),
    homework_enabled INTEGER NOT NULL CHECK (homework_enabled IN (0, 1)),
    progress_enabled INTEGER NOT NULL CHECK (progress_enabled IN (0, 1)),
    announcement_enabled INTEGER NOT NULL CHECK (announcement_enabled IN (0, 1)),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at REAL NOT NULL CHECK (updated_at >= 0)
);

CREATE TABLE IF NOT EXISTS student_notification_events (
    id INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'class_reminder', 'schedule_changed', 'homework_assigned',
        'homework_due', 'progress_milestone', 'announcement_published'
    )),
    event_id TEXT NOT NULL,
    sid TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    scheduled_at REAL NOT NULL CHECK (scheduled_at >= 0),
    state TEXT NOT NULL CHECK (state IN ('pending', 'leased', 'sent', 'failed', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt REAL NOT NULL CHECK (next_attempt >= 0),
    lease_until REAL,
    lease_digest TEXT,
    last_error TEXT,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    updated_at REAL NOT NULL CHECK (updated_at >= 0),
    UNIQUE (event_type, event_id, sid)
);

CREATE INDEX IF NOT EXISTS idx_student_notification_events_ready
    ON student_notification_events(state, next_attempt, lease_until, id);
CREATE INDEX IF NOT EXISTS idx_student_notification_events_sid
    ON student_notification_events(sid, state, scheduled_at, id);

CREATE TABLE IF NOT EXISTS student_notification_schedule_state (
    sid TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    snapshot_key TEXT,
    event_id TEXT,
    pending INTEGER NOT NULL CHECK (pending IN (0, 1)),
    updated_at REAL NOT NULL CHECK (updated_at >= 0)
);

CREATE INDEX IF NOT EXISTS idx_student_notification_schedule_pending
    ON student_notification_schedule_state(pending, updated_at, sid);

CREATE TABLE IF NOT EXISTS student_notification_milestones (
    sid TEXT NOT NULL,
    curriculum_key TEXT NOT NULL,
    milestone INTEGER NOT NULL CHECK (milestone IN (25, 50, 75, 100)),
    reached_at REAL NOT NULL CHECK (reached_at >= 0),
    PRIMARY KEY (sid, curriculum_key, milestone)
);

CREATE TABLE IF NOT EXISTS student_notification_deliveries (
    event_row_id INTEGER NOT NULL,
    subscription_id INTEGER NOT NULL CHECK (subscription_id >= 1),
    state TEXT NOT NULL CHECK (state IN ('sent', 'permanent_failure')),
    created_at REAL NOT NULL CHECK (created_at >= 0),
    updated_at REAL NOT NULL CHECK (updated_at >= 0),
    PRIMARY KEY (event_row_id, subscription_id),
    FOREIGN KEY (event_row_id) REFERENCES student_notification_events(id)
);

CREATE INDEX IF NOT EXISTS idx_student_notification_deliveries_subscription
    ON student_notification_deliveries(subscription_id, state, event_row_id);

COMMIT;
