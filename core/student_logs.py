from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import closing
from typing import Final, NewType, TypedDict


KST: Final = dt.timezone(dt.timedelta(hours=9))
StudentOperationLogId = NewType("StudentOperationLogId", int)


class StudentOperationLog(TypedDict):
    id: StudentOperationLogId
    sid: str
    student_name: str
    kind: str
    comment: str
    date: str
    created_at: str


class StudentOperationLogRepository:
    """SQLite-backed student operation logs kept separate from class logs/notes."""

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
            "CREATE TABLE IF NOT EXISTS student_operation_logs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "sid TEXT NOT NULL,"
            "student_name TEXT NOT NULL,"
            "kind TEXT NOT NULL,"
            "comment TEXT NOT NULL,"
            "date TEXT NOT NULL,"
            "created_at TEXT NOT NULL"
            ");"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_student_operation_logs_created "
            "ON student_operation_logs(created_at DESC, id DESC);"
        )

    @staticmethod
    def _row_to_log(row: sqlite3.Row) -> StudentOperationLog:
        return {
            "id": StudentOperationLogId(int(row["id"])),
            "sid": str(row["sid"]),
            "student_name": str(row["student_name"]),
            "kind": str(row["kind"]),
            "comment": str(row["comment"]),
            "date": str(row["date"]),
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _now_iso() -> str:
        return dt.datetime.now(KST).isoformat(timespec="seconds")

    def list_all(self) -> list[StudentOperationLog]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, sid, student_name, kind, comment, date, created_at "
                "FROM student_operation_logs ORDER BY id DESC;"
            ).fetchall()
        return [self._row_to_log(row) for row in rows]

    def create(
        self,
        *,
        sid: str,
        student_name: str,
        kind: str,
        comment: str,
        date: str,
    ) -> StudentOperationLog:
        created_at = self._now_iso()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE;")
            try:
                cursor = connection.execute(
                    "INSERT INTO student_operation_logs("
                    "sid, student_name, kind, comment, date, created_at) "
                    "VALUES(?, ?, ?, ?, ?, ?);",
                    (sid, student_name, kind, comment, date, created_at),
                )
                connection.execute("COMMIT;")
            except sqlite3.Error:
                connection.execute("ROLLBACK;")
                raise
        return {
            "id": StudentOperationLogId(int(cursor.lastrowid)),
            "sid": sid,
            "student_name": student_name,
            "kind": kind,
            "comment": comment,
            "date": date,
            "created_at": created_at,
        }

    def clear_all(self) -> int:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE;")
            try:
                cursor = connection.execute("DELETE FROM student_operation_logs;")
                connection.execute("COMMIT;")
            except sqlite3.Error:
                connection.execute("ROLLBACK;")
                raise
        return int(cursor.rowcount or 0)


__all__ = ["StudentOperationLog", "StudentOperationLogId", "StudentOperationLogRepository"]
