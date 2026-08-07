CREATE TABLE IF NOT EXISTS assistant_student_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id TEXT NOT NULL,
  content TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assistant_student_notes_student_created
ON assistant_student_notes(student_id, created_at DESC, id DESC);
