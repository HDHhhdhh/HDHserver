from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Iterable

from core.date_rules import is_iso_date_key


KST = dt.timezone(dt.timedelta(hours=9))
QuickPrinterHistoryKey = tuple[str, str, str, str]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_sid(value: Any) -> str:
    sid = _text(value)
    return str(int(sid)) if sid.isdigit() else sid


def quick_printer_history_key(
    student_id: Any,
    test_id: Any,
    material_id: Any,
    assignment_date: Any,
) -> QuickPrinterHistoryKey:
    return (
        _canonical_sid(student_id),
        _text(test_id),
        _text(material_id),
        _text(assignment_date),
    )


def _normalized_export_item(raw: Any) -> tuple[QuickPrinterHistoryKey, str]:
    if not isinstance(raw, dict):
        raise ValueError("quick-printer export history item must be an object")
    key = quick_printer_history_key(
        raw.get("studentId"),
        raw.get("testId"),
        raw.get("materialId"),
        raw.get("assignmentDate"),
    )
    if not all(key[:3]) or not is_iso_date_key(key[3]):
        raise ValueError("invalid quick-printer export history key")
    export_date = _text(raw.get("exportDate"))
    if not is_iso_date_key(export_date):
        raise ValueError("invalid quick-printer export date")
    return key, export_date


class QuickPrinterExportHistoryRepository:
    """Persistent per-assignment history for successfully generated printer CSV rows."""

    def __init__(
        self,
        *,
        db_path: str | os.PathLike[str] | None = None,
        now_iso: Callable[[], str] | None = None,
    ) -> None:
        self.db_path = str(db_path) if db_path is not None else None
        self.now_iso = now_iso or self._now_kst_iso

    @staticmethod
    def _now_kst_iso() -> str:
        return dt.datetime.now(KST).isoformat(timespec="seconds")

    def _default_db_path(self) -> str:
        if self.db_path:
            return self.db_path
        env_path = _text(os.environ.get("DB_PATH"))
        if env_path:
            return env_path
        return str(Path(__file__).resolve().parents[1] / "app.sqlite")

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
            "CREATE TABLE IF NOT EXISTS quick_printer_export_history ("
            "student_id TEXT NOT NULL,"
            "test_id TEXT NOT NULL,"
            "material_id TEXT NOT NULL,"
            "assignment_date TEXT NOT NULL,"
            "first_export_date TEXT NOT NULL,"
            "last_export_date TEXT NOT NULL,"
            "first_exported_at TEXT NOT NULL,"
            "last_exported_at TEXT NOT NULL,"
            "export_count INTEGER NOT NULL DEFAULT 1,"
            "PRIMARY KEY(student_id, test_id, material_id, assignment_date)"
            ");"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_quick_printer_export_history_student "
            "ON quick_printer_export_history(student_id, assignment_date);"
        )

    def keys_for_students(self, student_ids: Iterable[Any]) -> set[QuickPrinterHistoryKey]:
        students = sorted({_canonical_sid(value) for value in student_ids if _canonical_sid(value)})
        if not students:
            return set()
        placeholders = ",".join("?" for _ in students)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT student_id, test_id, material_id, assignment_date "
                f"FROM quick_printer_export_history WHERE student_id IN ({placeholders});",
                tuple(students),
            ).fetchall()
        return {
            quick_printer_history_key(
                row["student_id"],
                row["test_id"],
                row["material_id"],
                row["assignment_date"],
            )
            for row in rows
        }

    def record_generated(self, items: Iterable[Any]) -> int:
        normalized: dict[QuickPrinterHistoryKey, str] = {}
        for raw in items:
            key, export_date = _normalized_export_item(raw)
            normalized[key] = export_date
        if not normalized:
            raise ValueError("quick-printer generated export history cannot be empty")

        timestamp = _text(self.now_iso())
        if not timestamp:
            raise ValueError("quick-printer export timestamp is empty")

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE;")
            try:
                for key, export_date in sorted(normalized.items()):
                    student_id, test_id, material_id, assignment_date = key
                    connection.execute(
                        "INSERT INTO quick_printer_export_history("
                        "student_id, test_id, material_id, assignment_date, "
                        "first_export_date, last_export_date, first_exported_at, last_exported_at, export_count"
                        ") VALUES(?,?,?,?,?,?,?,?,1) "
                        "ON CONFLICT(student_id, test_id, material_id, assignment_date) DO UPDATE SET "
                        "last_export_date=excluded.last_export_date, "
                        "last_exported_at=excluded.last_exported_at, "
                        "export_count=quick_printer_export_history.export_count + 1;",
                        (
                            student_id,
                            test_id,
                            material_id,
                            assignment_date,
                            export_date,
                            export_date,
                            timestamp,
                            timestamp,
                        ),
                    )
                connection.execute("COMMIT;")
            except Exception:
                connection.execute("ROLLBACK;")
                raise
        return len(normalized)


__all__ = (
    "QuickPrinterExportHistoryRepository",
    "QuickPrinterHistoryKey",
    "quick_printer_history_key",
)
