"""Fresh temporary-DB lifecycle checks for the student-session repository."""
# /// script
# requires-python = ">=3.11"
# ///
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_session_input import StudentSessionInputError
from core.student_sessions import SessionCreated, SessionView, StudentSessionRepository

CheckValue: TypeAlias = str | int | float | bool | None | list["CheckValue"] | dict[str, "CheckValue"]
CheckResult: TypeAlias = dict[str, CheckValue]
OperationResult: TypeAlias = SessionCreated | SessionView | None | bool | int


class CheckFailure(AssertionError):
    """Named contract assertion failure."""


def _check(count: list[int], condition: bool, label: str) -> None:
    count[0] += 1
    if not condition:
        raise CheckFailure(label)


def _row(path: Path, sql: str, params: tuple[str | int | float | None, ...] = ()) -> tuple[str | int | float | None, ...] | None:
    db = sqlite3.connect(path)
    try:
        found = db.execute(sql, params).fetchone()
    finally:
        db.close()
    return None if found is None else tuple(found)


def _typed_rejected(operation: Callable[[], OperationResult]) -> bool:
    try:
        operation()
    except StudentSessionInputError:
        return True
    return False


class _RawDigestMutant(StudentSessionRepository):
    """Mutation seam that stores caller secrets instead of SHA-256 digests."""

    @staticmethod
    def _digest(value: str) -> str:
        return value


class _ExpiryBypassMutant(StudentSessionRepository):
    """Mutation seam that ignores expiry while resolving a token."""

    def _row_usable(self, row: sqlite3.Row, now: float) -> bool:  # noqa: ARG002
        return row["revoked_at"] is None

    @staticmethod
    def _mark_expired(db: sqlite3.Connection, row: sqlite3.Row, now: float) -> bool:  # noqa: ARG002
        return False


def _mutant_checks(count: list[int]) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="student-app-session-mutants-") as raw:
        root = Path(raw)
        digest_repo = _RawDigestMutant(root / "digest.sqlite", clock=lambda: 1000.0)
        created = digest_repo.create("mutant-aid", "s1", ["s1"], now=1000)
        digest_row = _row(root / "digest.sqlite", "SELECT token_digest,csrf_digest FROM student_app_sessions")
        raw_persisted = digest_row == (created["token"], created["csrf_token"])
        expiry_repo = _ExpiryBypassMutant(root / "expiry.sqlite", clock=lambda: 1000.0)
        expired = expiry_repo.create("expiry-aid", "s1", ["s1"], ttl_seconds=1, now=1000)
        expiry_bypassed = expiry_repo.resolve(expired["token"], now=1002) is not None
    for label, wrong in (("raw digest", raw_persisted), ("expiry", expiry_bypassed)):
        try:
            _check(count, not wrong, f"{label} mutant must violate the contract")
        except CheckFailure:
            caught = True
        else:
            caught = False
        _check(count, caught, f"{label} differentiating mutant is caught")
    return {"raw_digest_persistence": raw_persisted, "expiry_bypass": expiry_bypassed}


def _parallel_create(repo: StudentSessionRepository) -> tuple[list[SessionCreated], list[str]]:
    barrier = threading.Barrier(2)
    values: list[SessionCreated] = []
    failures: list[str] = []

    def worker(index: int) -> None:
        barrier.wait()
        try:
            values.append(repo.create(f"parallel-aid-{index}", f"parallel-sid-{index}", [f"parallel-sid-{index}"], now=3000))
        except sqlite3.Error as exc:
            failures.append(type(exc).__name__)

    threads = [threading.Thread(target=worker, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    return values, failures


def _parallel_expiry(repo: StudentSessionRepository, token: str) -> tuple[list[SessionView | None], list[str]]:
    barrier = threading.Barrier(3)
    values: list[SessionView | None] = []
    failures: list[str] = []

    def worker() -> None:
        barrier.wait()
        try:
            values.append(repo.resolve(token, now=3002))
        except sqlite3.Error as exc:
            failures.append(type(exc).__name__)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
    return values, failures


def run_checks() -> CheckResult:
    """Exercise lifecycle, malformed boundaries, privacy, and concurrency."""
    count, secret_lengths = [0], {}
    with tempfile.TemporaryDirectory(prefix="student-app-session-contract-") as raw:
        root, path = Path(raw), Path(raw) / "app.sqlite"
        db = sqlite3.connect(path)
        try:
            db.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
            db.execute("INSERT INTO sentinel(value) VALUES ('keep')")
            db.commit()
        finally:
            db.close()
        sessions = StudentSessionRepository(path, timeout=2.0, clock=lambda: 1000.0)
        with sessions._connect() as checked:
            _check(count, checked.row_factory is sqlite3.Row, "row factory is sqlite3.Row")
            _check(count, int(checked.execute("PRAGMA foreign_keys").fetchone()[0]) == 1, "foreign keys enabled")
            _check(count, checked.isolation_level is None, "short autocommit connection")
        session = sessions.create("aid-1", "s1", ["s1", "s2"], ttl_seconds=60, now=1000)
        secret_lengths.update({"token": len(session["token"]), "csrf": len(session["csrf_token"])})
        _check(count, sessions.resolve(session["token"], csrf_token=session["csrf_token"], now=1001) == {"session_id": session["session_id"], "aid": "aid-1", "active_sid": "s1", "allowed_sids": ["s1", "s2"], "created_at": 1000.0, "expires_at": 1060.0, "last_seen": 1001.0}, "session resolves with exact allowlist")
        _check(count, sessions.resolve(session["token"], csrf_token="wrong", now=1002) is None, "CSRF mismatch rejects")
        _check(count, _row(path, "SELECT last_seen FROM student_app_sessions WHERE id=?", (session["session_id"],)) == (1001.0,), "CSRF rejection does not move last_seen")
        rotated = sessions.rotate(session["token"], active_sid="s2", now=1003)
        _check(count, rotated is not None, "rotation creates successor")
        if rotated is None:
            raise CheckFailure("rotation result unavailable")
        _check(count, sessions.resolve(session["token"], now=1003) is None and sessions.resolve(rotated["token"], now=1003)["active_sid"] == "s2", "rotation revokes old token and accepts new token")
        before_invalid_rotate = _row(path, "SELECT COUNT(*),MAX(id) FROM student_app_sessions")
        _check(count, sessions.rotate(rotated["token"], active_sid="not-allowed", now=1004) is None, "rotation enforces allowed SID")
        _check(count, _row(path, "SELECT COUNT(*),MAX(id) FROM student_app_sessions") == before_invalid_rotate, "invalid rotation does not write")
        revoked = sessions.create("revoke-aid", "s1", ["s1"], now=1000)
        _check(count, sessions.revoke(revoked["token"], now=1005) and not sessions.revoke(revoked["token"], now=1006) and sessions.resolve(revoked["token"], now=1006) is None, "revoke is idempotent and fail-closed")
        boundary = sessions.create("expiry-aid", "s1", ["s1"], ttl_seconds=10, now=2000)
        _check(count, sessions.resolve(boundary["token"], now=2010) is None, "exact expiry boundary rejects")
        _check(count, sessions.expire(now=2010) >= 1, "expire marks boundary rows")
        observed = sessions.create("observed-expiry-aid", "s1", ["s1"], ttl_seconds=1, now=3000)
        _check(count, sessions.resolve(observed["token"], now=3002) is None, "observed expiry rejects")
        marker = _row(path, "SELECT revoked_at FROM student_app_sessions WHERE id=?", (observed["session_id"],))
        _check(count, marker == (3002.0,), "observed expiry writes terminal revoke marker")
        _check(count, sessions.resolve(observed["token"], now=2999) is None, "terminal expiry blocks clock rollback")
        concurrent_expired, concurrent_failures = _parallel_expiry(sessions, observed["token"])
        _check(count, concurrent_expired == [None, None] and not concurrent_failures, "concurrent expired resolves are idempotent")
        _check(count, _row(path, "SELECT revoked_at FROM student_app_sessions WHERE id=?", (observed["session_id"],)) == marker, "repeated expiry preserves terminal marker")
        unobserved = sessions.create("unobserved-rollback-aid", "s1", ["s1"], ttl_seconds=60, now=4000)
        _check(count, sessions.resolve(unobserved["token"], now=3999) is not None, "unobserved valid session survives clock rollback")
        disabled_a = sessions.create("disabled-aid", "s1", ["s1"], now=1000)
        disabled_b = sessions.create("disabled-aid", "s2", ["s1", "s2"], now=1000)
        _check(count, sessions.revoke_account("disabled-aid", now=1001) == 2 and sessions.resolve(disabled_a["token"], now=1001) is None and sessions.resolve(disabled_b["token"], now=1001) is None, "account revoke disables every session")
        baseline = _row(path, "SELECT COUNT(*),MAX(id) FROM student_app_sessions")
        malformed: list[Callable[[], OperationResult]] = [
            lambda: sessions.create(123, "s1", ["s1"], now=1000),
            lambda: sessions.create("aid", 1, ["s1"], now=1000),
            lambda: sessions.create("aid", "s1", ["s1", 1], now=1000),
            lambda: sessions.create("aid", "s1", ["s1"], ttl_seconds="bad", now=1000),
            lambda: sessions.create("aid", "s1", ["s1"], now="bad"),
            lambda: sessions.create("aid", "s2", ["s1"], now=1000),
            lambda: sessions.resolve(rotated["token"], now="bad"),
            lambda: sessions.rotate(rotated["token"], now="bad"),
            lambda: sessions.revoke(rotated["token"], now="bad"),
            lambda: sessions.expire(now="bad"),
        ]
        for operation in malformed:
            _check(count, _typed_rejected(operation), "malformed creation is typed-rejected")
        _check(count, _row(path, "SELECT COUNT(*),MAX(id) FROM student_app_sessions") == baseline, "typed malformed creation leaves no rows")
        lookup_baseline = baseline
        _check(count, sessions.resolve(b"bad") is None and sessions.resolve("short", csrf_token=b"bad") is None and sessions.rotate("short", active_sid=1) is None and not sessions.revoke("", now="bad") and sessions.revoke_account(123) == 0, "malformed lookup inputs fail closed")
        _check(count, _row(path, "SELECT COUNT(*),MAX(id) FROM student_app_sessions") == lookup_baseline, "malformed lookup inputs do not write")
        unknown = secrets.token_urlsafe(32)
        _check(count, sessions.resolve(unknown, now=1000) is None and not sessions.revoke(unknown, now=1000), "unknown token is a safe miss")
        rows = _row(path, "SELECT token_digest,csrf_digest FROM student_app_sessions WHERE id=?", (session["session_id"],))
        protected = repr(rows)
        _check(count, rows == (hashlib.sha256(session["token"].encode()).hexdigest(), hashlib.sha256(session["csrf_token"].encode()).hexdigest()), "SHA-256 token and CSRF digests persist")
        _check(count, session["token"] not in protected and session["csrf_token"] not in protected and unknown not in protected, "raw token material is absent")
        parallel, failures = _parallel_create(sessions)
        _check(count, len(parallel) == 2 and not failures and len({item["session_id"] for item in parallel}) == 2, "concurrent independent session writes succeed")
        integrity = str(_row(path, "PRAGMA integrity_check")[0])
        sentinel = str(_row(path, "SELECT value FROM sentinel")[0])
        _check(count, integrity == "ok" and sentinel == "keep", "integrity and sentinel are preserved")
        mutants = _mutant_checks(count)
        result: CheckResult = {"name": "repositories_sessions_contract", "assertions": count[0], "passed": True, "mutants": mutants, "secret_lengths": secret_lengths, "integrity": integrity, "sentinel": sentinel, "raw_secret_absent": True, "temporary_db_removed": False}
    result["temporary_db_removed"] = not root.exists()
    evidence_root = Path(os.environ.get("STUDENT_APP_EVIDENCE_DIR", ".omo/evidence/student-mobile-app-v2/task-3"))
    try:
        evidence_root.mkdir(parents=True, exist_ok=True)
        (evidence_root / "sessions-remediation-l1-green.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except PermissionError:
        fallback = ROOT / ".codex-temp" / "student-mobile-app-v2" / "task-3"
        fallback.mkdir(parents=True, exist_ok=True)
        (fallback / "sessions-remediation-l1-green.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    result = run_checks()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
