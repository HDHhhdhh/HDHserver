from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import closing
from typing import Final, NewType, TypedDict


KST: Final = dt.timezone(dt.timedelta(hours=9))
AdminOperationNoteId = NewType("AdminOperationNoteId", int)


class AdminOperationNote(TypedDict):
    id: AdminOperationNoteId
    content: str
    created_at: str


class AdminOperationNoteRepository:
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
        connection = sqlite3.connect(
            db_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000;")
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=NORMAL;")
        self._ensure_schema(connection)
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS admin_operation_notes ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "content TEXT NOT NULL,"
            "created_at TEXT NOT NULL"
            ");"
        )

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> AdminOperationNote:
        return {
            "id": AdminOperationNoteId(int(row["id"])),
            "content": str(row["content"]),
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _now_iso() -> str:
        return dt.datetime.now(KST).isoformat(timespec="seconds")

    def list_all(self) -> list[AdminOperationNote]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, content, created_at FROM admin_operation_notes "
                "ORDER BY id DESC;"
            ).fetchall()
        return [self._row_to_note(row) for row in rows]

    def create(self, content: str) -> AdminOperationNote:
        created_at = self._now_iso()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE;")
            try:
                cursor = connection.execute(
                    "INSERT INTO admin_operation_notes(content, created_at) VALUES(?, ?);",
                    (content, created_at),
                )
                connection.execute("COMMIT;")
            except sqlite3.Error:
                connection.execute("ROLLBACK;")
                raise
        return {
            "id": AdminOperationNoteId(int(cursor.lastrowid)),
            "content": content,
            "created_at": created_at,
        }

    def delete(self, note_id: AdminOperationNoteId) -> bool:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE;")
            try:
                cursor = connection.execute(
                    "DELETE FROM admin_operation_notes WHERE id=?;",
                    (note_id,),
                )
                connection.execute("COMMIT;")
            except sqlite3.Error:
                connection.execute("ROLLBACK;")
                raise
        return bool(cursor.rowcount)
