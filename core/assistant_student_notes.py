from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import closing


KST = dt.timezone(dt.timedelta(hours=9))


class AssistantStudentNoteRepository:
    def __init__(self, *, db_path: str | None = None):
        self.db_path = db_path

    def _default_db_path(self) -> str:
        if self.db_path:
            return self.db_path
        env_path = (os.environ.get("DB_PATH") or "").strip()
        if env_path:
            return env_path
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.sqlite")

    def _connect(self) -> sqlite3.Connection:
        db_path = self._default_db_path()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        con = sqlite3.connect(
            db_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=30000;")
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        self._ensure_schema(con)
        return con

    @staticmethod
    def _ensure_schema(con: sqlite3.Connection) -> None:
        con.execute(
            "CREATE TABLE IF NOT EXISTS assistant_student_notes ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "student_id TEXT NOT NULL,"
            "content TEXT NOT NULL,"
            "created_by TEXT NOT NULL,"
            "updated_by TEXT NOT NULL DEFAULT '',"
            "created_at TEXT NOT NULL,"
            "updated_at TEXT NOT NULL"
            ");"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_assistant_student_notes_student_created "
            "ON assistant_student_notes(student_id, created_at DESC, id DESC);"
        )
        columns = {str(row["name"]) for row in con.execute("PRAGMA table_info(assistant_student_notes);")}
        if "updated_by" not in columns:
            con.execute("ALTER TABLE assistant_student_notes ADD COLUMN updated_by TEXT NOT NULL DEFAULT ''; ")
        con.execute("UPDATE assistant_student_notes SET updated_by=created_by WHERE updated_by='';")

    @staticmethod
    def _row_to_note(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "student_id": str(row["student_id"]),
            "content": str(row["content"]),
            "created_by": str(row["created_by"]),
            "updated_by": str(row["updated_by"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _now_iso() -> str:
        return dt.datetime.now(KST).isoformat(timespec="seconds")

    def list_for_student(self, student_id: str) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute(
                "SELECT id, student_id, content, created_by, updated_by, created_at, updated_at "
                "FROM assistant_student_notes WHERE student_id=? "
                "ORDER BY created_at DESC, id DESC;",
                (student_id,),
            ).fetchall()
        return [self._row_to_note(row) for row in rows if row is not None]

    def create(self, student_id: str, content: str, created_by: str) -> dict:
        now = self._now_iso()
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE;")
            try:
                cur = con.execute(
                    "INSERT INTO assistant_student_notes("
                    "student_id, content, created_by, updated_by, created_at, updated_at"
                    ") VALUES(?,?,?,?,?,?);",
                    (student_id, content, created_by, created_by, now, now),
                )
                row = con.execute(
                    "SELECT id, student_id, content, created_by, updated_by, created_at, updated_at "
                    "FROM assistant_student_notes WHERE id=? AND student_id=?;",
                    (cur.lastrowid, student_id),
                ).fetchone()
                con.execute("COMMIT;")
            except Exception:
                con.execute("ROLLBACK;")
                raise
        note = self._row_to_note(row)
        if note is None:
            raise RuntimeError("created note was not found")
        return note

    def update(self, student_id: str, note_id: int, content: str, updated_by: str) -> dict | None:
        now = self._now_iso()
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE;")
            try:
                cur = con.execute(
                    "UPDATE assistant_student_notes SET content=?, updated_by=?, updated_at=? "
                    "WHERE id=? AND student_id=?;",
                    (content, updated_by, now, note_id, student_id),
                )
                row = None
                if cur.rowcount:
                    row = con.execute(
                        "SELECT id, student_id, content, created_by, updated_by, created_at, updated_at "
                        "FROM assistant_student_notes WHERE id=? AND student_id=?;",
                        (note_id, student_id),
                    ).fetchone()
                con.execute("COMMIT;")
            except Exception:
                con.execute("ROLLBACK;")
                raise
        return self._row_to_note(row)

    def delete(self, student_id: str, note_id: int) -> bool:
        with closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE;")
            try:
                cur = con.execute(
                    "DELETE FROM assistant_student_notes WHERE id=? AND student_id=?;",
                    (note_id, student_id),
                )
                con.execute("COMMIT;")
            except Exception:
                con.execute("ROLLBACK;")
                raise
        return bool(cur.rowcount)
