BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS student_focus_sessions (
    id TEXT PRIMARY KEY,
    sid TEXT NOT NULL,
    schedule_key TEXT NOT NULL,
    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('regular', 'extra', 'makeup')),
    schedule_date TEXT NOT NULL,
    schedule_start_at REAL NOT NULL CHECK (schedule_start_at >= 0),
    schedule_end_at REAL NOT NULL CHECK (schedule_end_at > schedule_start_at),
    schedule_time_label TEXT NOT NULL,
    schedule_slots_json TEXT NOT NULL,
    started_at REAL NOT NULL CHECK (started_at >= 0),
    ended_at REAL,
    state TEXT NOT NULL CHECK (state IN ('active', 'finished', 'unknown')),
    visibility_state TEXT NOT NULL CHECK (visibility_state IN ('visible', 'hidden', 'unknown')),
    segment_started_at REAL NOT NULL CHECK (segment_started_at >= 0),
    last_event_at REAL NOT NULL CHECK (last_event_at >= 0),
    last_seq INTEGER NOT NULL DEFAULT 0 CHECK (last_seq >= 0),
    event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0),
    visible_ms INTEGER NOT NULL DEFAULT 0 CHECK (visible_ms >= 0),
    hidden_count INTEGER NOT NULL DEFAULT 0 CHECK (hidden_count >= 0),
    hidden_ms INTEGER NOT NULL DEFAULT 0 CHECK (hidden_ms >= 0),
    longest_hidden_ms INTEGER NOT NULL DEFAULT 0 CHECK (longest_hidden_ms >= 0),
    unknown_ms INTEGER NOT NULL DEFAULT 0 CHECK (unknown_ms >= 0),
    created_at REAL NOT NULL CHECK (created_at >= 0),
    updated_at REAL NOT NULL CHECK (updated_at >= 0),
    UNIQUE (sid, schedule_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_student_focus_active_sid
    ON student_focus_sessions(sid) WHERE state = 'active';
CREATE INDEX IF NOT EXISTS idx_student_focus_admin_date
    ON student_focus_sessions(schedule_date, schedule_start_at, sid);

CREATE TABLE IF NOT EXISTS student_focus_events (
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL CHECK (seq >= 1),
    event_type TEXT NOT NULL CHECK (event_type IN ('hidden', 'visible', 'unknown', 'finished')),
    server_at REAL NOT NULL CHECK (server_at >= 0),
    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
    PRIMARY KEY (session_id, seq),
    FOREIGN KEY (session_id) REFERENCES student_focus_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_student_focus_event_retention
    ON student_focus_events(server_at, session_id, seq);

COMMIT;
