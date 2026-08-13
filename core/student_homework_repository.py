from __future__ import annotations
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, Iterable

ASSIGNMENT_FIELDS = (
    "id", "sid", "curriculum_sid", "title", "book", "scope", "assigned_at",
    "due_at", "status", "completed_at", "source_log_date", "source_row_id",
    "revision", "created_at", "updated_at",
)
RECONCILIATION_FIELDS = (
    "id", "operation_id", "sid", "source_log_date", "request_hash",
    "desired_log_json", "desired_assignments_json", "log_state", "homework_state",
    "state", "attempts", "last_error_code", "created_at", "updated_at",
)
ERROR_CODES = {
    "", "log_write_failed", "homework_write_failed", "revision_conflict",
    "idempotency_conflict", "homework_not_initialized", "invalid_payload",
    "unexpected_failure",
}

class HomeworkRepositoryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
class HomeworkNotInitializedError(HomeworkRepositoryError):
    def __init__(self):
        super().__init__("homework_not_initialized", "student homework schema is not initialized")
class HomeworkConflictError(HomeworkRepositoryError):
    pass
class StudentHomeworkRepository:
    """Explicitly migrated, SID-scoped homework persistence."""
    def __init__(self, db_path: str):
        self.db_path = os.fspath(db_path)
    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        path = Path(self.db_path).absolute()
        if readonly and not path.is_file():
            raise HomeworkNotInitializedError()
        mode = "ro" if readonly else "rw"
        try:
            con = sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True, timeout=30, isolation_level=None)
        except sqlite3.OperationalError as exc:
            raise HomeworkNotInitializedError() from exc
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=30000")
        if readonly:
            con.execute("PRAGMA query_only=ON")
        self._require_schema(con)
        return con
    @staticmethod
    def _require_schema(con: sqlite3.Connection) -> None:
        names = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)",
            ("student_homework_assignments", "student_homework_reconciliations"),
        )}
        if len(names) != 2:
            con.close()
            raise HomeworkNotInitializedError()
    def apply_migration(self, sql: str) -> None:
        path = Path(self.db_path).absolute()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as con:
            con.executescript(sql)
    def schema_ready(self) -> bool:
        try:
            with closing(self._connect(readonly=True)):
                return True
        except HomeworkNotInitializedError:
            return False
    @staticmethod
    def _dict(row: sqlite3.Row | None, fields: tuple[str, ...]) -> dict | None:
        return None if row is None else {field: row[field] for field in fields}
    def _write(self, action: Callable[[sqlite3.Connection], object]):
        with closing(self._connect(readonly=False)) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                result = action(con)
                con.execute("COMMIT")
                return result
            except Exception:
                con.execute("ROLLBACK")
                raise
    def get(self, sid: str, assignment_id: str) -> dict | None:
        with closing(self._connect(readonly=True)) as con:
            row = con.execute(
                f"SELECT {','.join(ASSIGNMENT_FIELDS)} FROM student_homework_assignments WHERE sid=? AND id=?",
                (sid, assignment_id),
            ).fetchone()
        return self._dict(row, ASSIGNMENT_FIELDS)
    def count_open(self, sid: str) -> int:
        with closing(self._connect(readonly=True)) as con:
            row = con.execute(
                "SELECT COUNT(*) FROM student_homework_assignments WHERE sid=? AND status='assigned'", (sid,)
            ).fetchone()
        return int(row[0])
    def list_for_log_date(self, sid: str, source_log_date: str) -> list[dict]:
        with closing(self._connect(readonly=True)) as con:
            rows = con.execute(
                f"SELECT {','.join(ASSIGNMENT_FIELDS)} FROM student_homework_assignments "
                "WHERE sid=? AND source_log_date=? ORDER BY source_row_id,id",
                (sid, source_log_date),
            ).fetchall()
        return [self._dict(row, ASSIGNMENT_FIELDS) for row in rows]
    def list_for_sid(self, sid: str, *, status: str = "open", cursor=None, page_size: int = 50):
        if status not in {"open", "all"} or not isinstance(page_size, int) or not 1 <= page_size <= 50:
            raise ValueError("invalid homework list options")
        where, params = ["sid=?"], [sid]
        if status == "open":
            where.append("status='assigned'")
        if cursor is not None:
            missing, due, assigned, item_id = cursor
            key = "CASE WHEN due_at IS NULL THEN 1 ELSE 0 END"
            where.append(
                f"({key}>? OR ({key}=? AND COALESCE(due_at,'')>?) OR "
                f"({key}=? AND COALESCE(due_at,'')=? AND assigned_at<?) OR "
                f"({key}=? AND COALESCE(due_at,'')=? AND assigned_at=? AND id>?))"
            )
            params += [missing, missing, due, missing, due, assigned, missing, due, assigned, item_id]
        sql = (
            f"SELECT {','.join(ASSIGNMENT_FIELDS)} FROM student_homework_assignments "
            f"WHERE {' AND '.join(where)} ORDER BY due_at IS NULL, due_at, assigned_at DESC, id LIMIT ?"
        )
        with closing(self._connect(readonly=True)) as con:
            rows = con.execute(sql, (*params, page_size + 1)).fetchall()
        return ([self._dict(row, ASSIGNMENT_FIELDS) for row in rows[:page_size]], len(rows) > page_size)
    @staticmethod
    def _same(existing: dict, item: dict) -> bool:
        fields = ("curriculum_sid", "title", "book", "scope", "assigned_at", "due_at", "status", "completed_at")
        return all(existing[field] == item[field] for field in fields)
    def apply_batch(self, sid: str, source_log_date: str, assignments: Iterable[dict], *, now: str) -> list[dict]:
        items = list(assignments)
        if len({item["source_row_id"] for item in items}) != len(items):
            raise HomeworkConflictError("idempotency_conflict", "duplicate source row in batch")
        def action(con: sqlite3.Connection):
            result = []
            for item in items:
                row = con.execute(
                    f"SELECT {','.join(ASSIGNMENT_FIELDS)} FROM student_homework_assignments "
                    "WHERE source_log_date=? AND source_row_id=?",
                    (source_log_date, item["source_row_id"]),
                ).fetchone()
                existing = self._dict(row, ASSIGNMENT_FIELDS)
                if existing and existing["sid"] != sid:
                    raise HomeworkConflictError("idempotency_conflict", "source row belongs to another student")
                if existing and self._same(existing, item):
                    result.append(existing)
                    continue
                if existing:
                    expected = item.get("expected_revision")
                    if expected != existing["revision"]:
                        raise HomeworkConflictError("revision_conflict", "homework revision changed")
                    revision = existing["revision"] + 1
                    con.execute(
                        "UPDATE student_homework_assignments SET curriculum_sid=?,title=?,book=?,scope=?,"
                        "assigned_at=?,due_at=?,status=?,completed_at=?,revision=?,updated_at=? "
                        "WHERE id=? AND sid=? AND revision=?",
                        (*(item[key] for key in ASSIGNMENT_FIELDS[2:10]), revision, now, existing["id"], sid, expected),
                    )
                    item_id = existing["id"]
                else:
                    item_id, revision = item["id"], 1
                    con.execute(
                        "INSERT INTO student_homework_assignments(id,sid,curriculum_sid,title,book,scope,assigned_at,"
                        "due_at,status,completed_at,source_log_date,source_row_id,revision,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (item_id, sid, *(item[key] for key in ASSIGNMENT_FIELDS[2:10]), source_log_date,
                         item["source_row_id"], revision, now, now),
                    )
                saved = con.execute(
                    f"SELECT {','.join(ASSIGNMENT_FIELDS)} FROM student_homework_assignments WHERE id=? AND sid=?",
                    (item_id, sid),
                ).fetchone()
                result.append(self._dict(saved, ASSIGNMENT_FIELDS))
            return result
        return self._write(action)
    def patch(self, sid: str, assignment_id: str, changes: dict, *, expected_revision: int, now: str) -> dict:
        current = self.get(sid, assignment_id)
        if current is None:
            raise HomeworkConflictError("revision_conflict", "homework assignment was not found")
        item = {**current, **changes, "expected_revision": expected_revision}
        return self.apply_batch(sid, current["source_log_date"], [item], now=now)[0]
    def begin_operation(self, operation: dict) -> dict:
        def action(con: sqlite3.Connection):
            existing = con.execute(
                f"SELECT {','.join(RECONCILIATION_FIELDS)} FROM student_homework_reconciliations WHERE operation_id=?",
                (operation["operation_id"],),
            ).fetchone()
            if existing:
                row = self._dict(existing, RECONCILIATION_FIELDS)
                if row["request_hash"] == operation["request_hash"] and row["sid"] == operation["sid"]:
                    return row
                raise HomeworkConflictError("idempotency_conflict", "operation id was reused")
            active = con.execute(
                "SELECT id FROM student_homework_reconciliations WHERE sid=? AND source_log_date=? "
                "AND state IN ('prepared','partial_failure')",
                (operation["sid"], operation["source_log_date"]),
            ).fetchone()
            if active:
                raise HomeworkConflictError("revision_conflict", "homework reconciliation is already active")
            con.execute(
                f"INSERT INTO student_homework_reconciliations({','.join(RECONCILIATION_FIELDS)}) "
                f"VALUES({','.join('?' for _ in RECONCILIATION_FIELDS)})",
                tuple(operation[field] for field in RECONCILIATION_FIELDS),
            )
            return operation.copy()
        return self._write(action)
    def _record_outcome(self, operation_id: str, column: str, outcome: str, error_code: str, now: str) -> dict:
        if column not in {"log_state", "homework_state"} or outcome not in {"succeeded", "failed", "conflict"}:
            raise ValueError("invalid reconciliation outcome")
        if error_code not in ERROR_CODES or (outcome != "succeeded" and not error_code):
            raise ValueError("invalid reconciliation error code")
        def action(con: sqlite3.Connection):
            row = con.execute(
                f"SELECT {','.join(RECONCILIATION_FIELDS)} FROM student_homework_reconciliations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise HomeworkConflictError("revision_conflict", "reconciliation was not found")
            data = self._dict(row, RECONCILIATION_FIELDS)
            data[column] = outcome
            states = {data["log_state"], data["homework_state"]}
            state = "blocked" if "conflict" in states else "completed" if states == {"succeeded"} else (
                "partial_failure" if "failed" in states else "prepared"
            )
            last_error = "" if state == "completed" else (error_code or data["last_error_code"])
            con.execute(
                f"UPDATE student_homework_reconciliations SET {column}=?,state=?,attempts=attempts+1,"
                "last_error_code=?,updated_at=? WHERE operation_id=?",
                (outcome, state, last_error, now, operation_id),
            )
            saved = con.execute(
                f"SELECT {','.join(RECONCILIATION_FIELDS)} FROM student_homework_reconciliations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            return self._dict(saved, RECONCILIATION_FIELDS)
        return self._write(action)
    def record_log_outcome(self, operation_id: str, outcome: str, *, error_code: str = "", now: str) -> dict:
        return self._record_outcome(operation_id, "log_state", outcome, error_code, now)
    def record_homework_outcome(self, operation_id: str, outcome: str, *, error_code: str = "", now: str) -> dict:
        return self._record_outcome(operation_id, "homework_state", outcome, error_code, now)
    def pending_for_source(self, sid: str, source_log_date: str) -> dict | None:
        with closing(self._connect(readonly=True)) as con:
            row = con.execute(
                f"SELECT {','.join(RECONCILIATION_FIELDS)} FROM student_homework_reconciliations "
                "WHERE sid=? AND source_log_date=? AND state IN ('prepared','partial_failure')",
                (sid, source_log_date),
            ).fetchone()
        return self._dict(row, RECONCILIATION_FIELDS)
