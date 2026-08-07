ALTER TABLE assistant_student_notes ADD COLUMN updated_by TEXT NOT NULL DEFAULT '';
UPDATE assistant_student_notes SET updated_by=created_by WHERE updated_by='';
