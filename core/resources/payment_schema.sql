BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS payment_schema (
    version INTEGER PRIMARY KEY CHECK(version = 1)
);
INSERT OR IGNORE INTO payment_schema(version) VALUES(1);
CREATE TABLE IF NOT EXISTS payment_accounts (
    sid TEXT PRIMARY KEY,
    state_json TEXT NOT NULL CHECK(json_valid(state_json)),
    student_json TEXT NOT NULL CHECK(json_valid(student_json)),
    summary_json TEXT NOT NULL CHECK(json_valid(summary_json)),
    revision INTEGER NOT NULL CHECK(revision > 0),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_operations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL UNIQUE,
    sid TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    action TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payment_operations_sid_seq ON payment_operations(sid,seq);
COMMIT;
