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
            row = con.execute("SELECT * FROM submissions WHERE identity=?", (identity,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for field in ("payload", "response"):
            result[field] = json.loads(result[field]) if result[field] else None
        return result

    def list(self, sid: str) -> list[dict]:
        with self.connect() as con:
            keys = [r[0] for r in con.execute("SELECT identity FROM submissions WHERE sid=?", (sid,))]
        return [self.get(key) for key in keys]

    def reserve(self, identity: str, sid: str, client_id: str) -> None:
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute("INSERT INTO submissions VALUES(?,?,?,'grading',NULL,NULL)",
                            (identity, sid, client_id))
                con.execute("COMMIT")
            except sqlite3.IntegrityError:
                con.execute("ROLLBACK")
                raise ApiError("already_submitted", 409) from None

    def graded(self, identity: str, payload: dict) -> None:
        with self.connect() as con:
            con.execute("UPDATE submissions SET state='reconciling',payload=? WHERE identity=? AND state='grading'",
                        (canonical(payload), identity))

    def complete(self, identity: str, response: dict) -> None:
        with self.connect() as con:
            con.execute("UPDATE submissions SET state='complete',response=? WHERE identity=?",
                        (canonical(response), identity))

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
