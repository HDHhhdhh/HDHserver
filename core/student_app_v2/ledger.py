"""Durable authority for grading and single-use content tickets."""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .contracts import ApiError


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Ledger:
    def __init__(self, path=None):
        if path is None:
            from core.paths import BASE
            path = os.environ.get("STUDENT_APP_V2_DB_PATH", Path(BASE) / "student-app-v2.sqlite")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS submissions(
                    identity TEXT PRIMARY KEY, sid TEXT NOT NULL, client_id TEXT NOT NULL,
                    state TEXT NOT NULL, payload TEXT, response TEXT,
                    UNIQUE(sid,client_id));
                CREATE TABLE IF NOT EXISTS tickets(
                    digest TEXT PRIMARY KEY, sid TEXT NOT NULL, assignment TEXT NOT NULL,
                    target TEXT NOT NULL, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS homework_requests(
                    sid TEXT NOT NULL, client_id TEXT NOT NULL, assignment TEXT NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(sid,client_id));
                CREATE TABLE IF NOT EXISTS submission_epochs(
                    identity TEXT PRIMARY KEY, generation INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS submission_resets(
                    operation_id TEXT PRIMARY KEY, identity TEXT NOT NULL, sid TEXT NOT NULL,
                    client_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    actor TEXT NOT NULL, reason TEXT NOT NULL, request_json TEXT NOT NULL,
                    previous_json TEXT NOT NULL, compatibility_json TEXT NOT NULL,
                    state TEXT NOT NULL, created_at TEXT NOT NULL, response TEXT,
                    UNIQUE(sid,client_id));
                CREATE UNIQUE INDEX IF NOT EXISTS submission_reset_pending
                    ON submission_resets(identity) WHERE state='pending';
                INSERT OR IGNORE INTO submission_epochs
                    SELECT identity,0 FROM submissions;
            """)

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=30, isolation_level=None)) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA busy_timeout=30000")
            con.execute("PRAGMA synchronous=FULL")
            yield con

    @contextmanager
    def lock(self):
        # A separate SQLite lock database lets journal transitions commit while
        # holding a kernel-owned cross-process gate. Process death releases it;
        # no PID-file stealing race or orphan timeout exists at this boundary.
        with closing(sqlite3.connect(str(self.path) + ".gate", timeout=30, isolation_level=None)) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield
            finally:
                con.execute("ROLLBACK")

    def get(self, identity: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT submissions.*,COALESCE(generation,0) AS generation FROM submissions "
                "LEFT JOIN submission_epochs USING(identity) WHERE identity=?", (identity,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for field in ("payload", "response"):
            result[field] = json.loads(result[field]) if result[field] else None
        return result

    def list(self, sid: str) -> list[dict]:
        with self.connect() as con:
            keys = [r[0] for r in con.execute("SELECT identity FROM submissions WHERE sid=?", (sid,))]
        return [row for key in keys if (row := self.get(key)) is not None]

    def generation(self, identity: str) -> int:
        with self.connect() as con:
            row = con.execute("SELECT generation FROM submission_epochs WHERE identity=?", (identity,)).fetchone()
        return row[0] if row else 0

    def was_reset(self, sid: str, client_id: str) -> bool:
        with self.connect() as con:
            return con.execute("SELECT 1 FROM submission_resets WHERE sid=? AND client_id=?",
                               (sid, client_id)).fetchone() is not None

    def assert_current(self, identity: str, client_id: str, generation: int) -> None:
        current = self.get(identity)
        if current is None or current["client_id"] != client_id or current["generation"] != generation:
            raise ApiError("submission_reset", 409)
        if current["state"] == "resetting":
            raise ApiError("submission_reset_pending", 503)

    def reserve(self, identity: str, sid: str, client_id: str, *, generation: int) -> None:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("INSERT OR IGNORE INTO submission_epochs VALUES(?,0)", (identity,))
                if con.execute("SELECT generation FROM submission_epochs WHERE identity=?", (identity,)).fetchone()[0] != generation:
                    raise ApiError("submission_reset", 409)
                if con.execute("SELECT 1 FROM submission_resets WHERE sid=? AND client_id=?", (sid, client_id)).fetchone():
                    raise ApiError("submission_reset", 409)
                con.execute("INSERT INTO submissions VALUES(?,?,?,'grading',NULL,NULL)",
                            (identity, sid, client_id))
                con.execute("COMMIT")
            except sqlite3.IntegrityError:
                con.execute("ROLLBACK")
                raise ApiError("already_submitted", 409) from None

    def graded(self, identity: str, payload: dict, *, client_id: str, generation: int) -> None:
        with self.connect() as con:
            changed = con.execute(
                "UPDATE submissions SET state='reconciling',payload=? WHERE identity=? AND client_id=? "
                "AND state='grading' AND EXISTS(SELECT 1 FROM submission_epochs "
                "WHERE identity=submissions.identity AND generation=?)",
                (canonical(payload), identity, client_id, generation),
            ).rowcount
            if changed != 1:
                raise ApiError("submission_reset", 409)

    def complete(self, identity: str, response: dict, *, client_id: str, generation: int) -> None:
        with self.connect() as con:
            changed = con.execute(
                "UPDATE submissions SET state='complete',response=? WHERE identity=? AND client_id=? "
                "AND state='reconciling' AND EXISTS(SELECT 1 FROM submission_epochs "
                "WHERE identity=submissions.identity AND generation=?)",
                (canonical(response), identity, client_id, generation),
            ).rowcount
            if changed != 1:
                raise ApiError("submission_reset", 409)

    def reset_operation(self, operation_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM submission_resets WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for field in ("request_json", "previous_json", "compatibility_json", "response"):
            result[field] = json.loads(result[field]) if result[field] else None
        return result

    def begin_reset(self, body: dict, saved: dict, compatibility: dict, actor: str, timestamp: str) -> dict:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("INSERT OR IGNORE INTO submission_epochs VALUES(?,0)", (saved["identity"],))
            changed = con.execute(
                "UPDATE submissions SET state='resetting' WHERE identity=? AND client_id=? AND state=?",
                (saved["identity"], saved["client_id"], saved["state"]),
            ).rowcount
            if changed != 1:
                raise ApiError("submission_changed", 409)
            con.execute(
                "INSERT INTO submission_resets VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,NULL)",
                (body["operationId"], saved["identity"], saved["sid"], saved["client_id"],
                 saved["generation"], actor, body["reason"], canonical(body), canonical(saved),
                 canonical(compatibility), timestamp),
            )
            con.execute("UPDATE submission_epochs SET generation=generation+1 WHERE identity=?", (saved["identity"],))
            con.execute("UPDATE tickets SET used=1 WHERE assignment=? AND sid=?", (saved["identity"], saved["sid"]))
            con.execute("COMMIT")
        return self.reset_operation(body["operationId"])

    def finish_reset(self, operation: dict, response: dict) -> None:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            removed = con.execute(
                "DELETE FROM submissions WHERE identity=? AND client_id=? AND state='resetting' "
                "AND EXISTS(SELECT 1 FROM submission_epochs WHERE identity=submissions.identity AND generation=?)",
                (operation["identity"], operation["client_id"], operation["generation"] + 1),
            ).rowcount
            if removed != 1:
                raise ApiError("submission_changed", 409)
            con.execute("UPDATE submission_resets SET state='complete',response=? WHERE operation_id=?",
                        (canonical(response), operation["operation_id"]))
            con.execute("COMMIT")

    def issue_ticket(self, token: str, sid: str, assignment: str, target: str, expires: int):
        with self.connect() as con:
            con.execute("INSERT INTO tickets(digest,sid,assignment,target,expires) VALUES(?,?,?,?,?)",
                        (hashlib.sha256(token.encode()).hexdigest(), sid, assignment, target, expires))

    def consume_ticket(self, token: str, sid: str, assignment: str, timestamp: int) -> str:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT * FROM tickets WHERE digest=? AND sid=? AND assignment=? AND used=0 AND expires>?",
                (hashlib.sha256(token.encode()).hexdigest(), sid, assignment, timestamp),
            ).fetchone()
            if row is None:
                con.execute("ROLLBACK")
                raise ApiError("invalid_solution_ticket", 410)
            con.execute("UPDATE tickets SET used=1 WHERE digest=?", (row["digest"],))
            con.execute("COMMIT")
            return row["target"]
