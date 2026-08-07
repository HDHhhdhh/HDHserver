"""Focused temp-DB contract checks for login-throttle boundaries and lifecycle."""
# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, TypedDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.student_login_throttle import (
    StudentLoginThrottleInputError,
    StudentLoginThrottleRepository,
    ThrottleStatus,
)


class ThrottleCheckFailure(AssertionError):
    """A named throttle contract assertion failed."""


class ThrottleResult(TypedDict):
    """Redacted checker receipt; no caller identifier or IP is included."""

    name: str
    assertions: int
    passed: bool
    digest_only: bool
    temp_db_removed: bool
    mutation_off_by_one: bool
    mutation_raw_persistence: bool
    mutation_success_overclear: bool


T = TypeVar("T")


def _assert(condition: bool, label: str, count: list[int]) -> None:
    count[0] += 1
    if not condition:
        raise ThrottleCheckFailure(label)


def _rejects(action: Callable[[], T], forbidden: tuple[str, ...]) -> bool:
    try:
        action()
    except StudentLoginThrottleInputError as exc:
        return not any(secret in str(exc) for secret in forbidden)
    return False


def _row_count(db_path: Path) -> int:
    db = sqlite3.connect(db_path)
    try:
        row = db.execute("SELECT COUNT(*) FROM student_login_throttle").fetchone()
    finally:
        db.close()
    if row is None:
        raise sqlite3.DatabaseError("throttle row count unavailable")
    return int(row[0])


def _write_receipts(root: Path, result: ThrottleResult) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "throttle-contract.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (root / "throttle-cleanup-receipt.json").write_text(
            json.dumps({"temporary_db_removed": result["temp_db_removed"], "live_runtime_touched": False}, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        fallback = ROOT / ".codex-temp" / "student-mobile-app-v2" / "task-3"
        fallback.mkdir(parents=True, exist_ok=True)
        (fallback / "throttle-contract.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (fallback / "throttle-cleanup-receipt.json").write_text(
            json.dumps({"temporary_db_removed": result["temp_db_removed"], "live_runtime_touched": False}, sort_keys=True),
            encoding="utf-8",
        )


def _parallel_failures(repo: StudentLoginThrottleRepository, count: int) -> tuple[list[ThrottleStatus], list[str]]:
    barrier = threading.Barrier(count)
    values: list[ThrottleStatus] = []
    errors: list[str] = []

    def worker() -> None:
        try:
            barrier.wait()
            values.append(repo.record_failure("parallel-user", "198.51.100.88", now=3000))
        except (sqlite3.Error, StudentLoginThrottleInputError, threading.BrokenBarrierError) as exc:
            errors.append(type(exc).__name__)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return values, errors


def run_checks() -> ThrottleResult:
    """Exercise throttle lifecycle, malformed boundaries, privacy, and mutants."""
    count = [0]
    evidence_root = Path(os.environ.get("STUDENT_APP_THROTTLE_EVIDENCE_DIR", ".omo/evidence/student-mobile-app-v2/task-3"))
    raw_identifier, raw_ip = "Alpha Student", "203.0.113.10"
    with tempfile.TemporaryDirectory(prefix="todo3-throttle-") as temporary:
        root, db_path = Path(temporary), Path(temporary) / "throttle.sqlite"
        db = sqlite3.connect(db_path)
        try:
            db.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
            db.execute("INSERT INTO sentinel(value) VALUES ('keep')")
            db.commit()
        finally:
            db.close()
        repo = StudentLoginThrottleRepository(db_path, clock=lambda: 1000.0)
        with repo._connect() as checked:
            _assert(checked.row_factory is sqlite3.Row, "row_factory is sqlite3.Row", count)
            _assert(int(checked.execute("PRAGMA foreign_keys").fetchone()[0]) == 1, "foreign_keys is enabled", count)
        for index in range(1, 7):
            state = repo.record_failure(raw_identifier, raw_ip, now=1000 + index)
            _assert(state["blocked"] is (index >= 5), "five-failure threshold is exact", count)
            if index < 5:
                _assert(state["identifier_failures"] == index, "first four failures remain allowed", count)
        boundary = 1001 + repo.window_seconds
        reset = repo.status(raw_identifier, raw_ip, now=boundary)
        _assert(not reset["blocked"] and reset["identifier_failures"] == 0 and reset["ip_failures"] == 0, "exact window boundary resets", count)
        repo.record_failure(raw_identifier, raw_ip, now=2000)
        repo.record_failure(raw_identifier, raw_ip, now=2001)
        repo.record_failure(raw_identifier, raw_ip, now=2002)
        repo.record_failure("Other Student", "198.51.100.20", now=2000)
        repo.record_failure("Other Student", "198.51.100.20", now=2001)
        repo.record_success(" alpha student ", now=2003)
        cleared = repo.status(raw_identifier, raw_ip, now=2003)
        other = repo.status("Other Student", "198.51.100.20", now=2003)
        aggregate = repo.status("Other Student", raw_ip, now=2003)
        independent = repo.status("Third Student", "192.0.2.44", now=2003)
        _assert(cleared["identifier_failures"] == 0 and cleared["ip_failures"] == 3, "success clears only identifier bucket", count)
        _assert(other["identifier_failures"] == 2 and other["ip_failures"] == 2, "other identifier remains independent", count)
        _assert(aggregate["identifier_failures"] == 2 and aggregate["ip_failures"] == 3, "IP aggregate bucket remains", count)
        _assert(independent["identifier_failures"] == 0 and independent["ip_failures"] == 0, "independent identifier and IP remain clear", count)
        with repo._connect() as checked:
            rows = checked.execute("SELECT bucket_type,key_digest FROM student_login_throttle").fetchall()
            protected = "|".join(f"{row[0]}|{row[1]}" for row in rows).encode("utf-8")
            digest_only = all(len(str(row[1])) == 64 for row in rows)
            _assert(digest_only and raw_identifier.encode() not in protected and raw_ip.encode() not in protected, "rows contain digest-only keys", count)
            _assert(checked.execute("SELECT value FROM sentinel").fetchone()[0] == "keep", "sentinel row survives", count)
            _assert(str(checked.execute("PRAGMA integrity_check").fetchone()[0]) == "ok", "integrity_check is ok", count)
        before_malformed = _row_count(db_path)
        malformed = (
            (lambda: repo.record_failure(42, raw_ip, now=2004)),
            (lambda: repo.record_failure(raw_identifier, "not-an-ip", now=2004)),
            (lambda: repo.status(raw_identifier, raw_ip, now="bad")),
            (lambda: repo.record_failure(raw_identifier, raw_ip, now=float("nan"))),
            (lambda: repo.record_success(raw_identifier, now=True)),
            (lambda: StudentLoginThrottleRepository(db_path, window_seconds="600")),
            (lambda: StudentLoginThrottleRepository(db_path, max_failures=0)),
        )
        for action in malformed:
            _assert(_rejects(action, (raw_identifier, raw_ip)), "malformed input has typed safe rejection", count)
            _assert(_row_count(db_path) == before_malformed, "malformed input performs no write", count)
        bad_clock = StudentLoginThrottleRepository(db_path, clock=lambda: "bad")
        _assert(_rejects(lambda: bad_clock.status(raw_identifier, raw_ip), (raw_identifier, raw_ip)), "injected clock is parsed", count)
        _assert(_row_count(db_path) == before_malformed, "bad injected clock performs no write", count)
        values, errors = _parallel_failures(repo, 8)
        final_parallel = repo.status("parallel-user", "198.51.100.88", now=3000)
        _assert(len(values) == 8 and not errors, "concurrent failures all complete", count)
        _assert(final_parallel["blocked"] and final_parallel["identifier_failures"] == 5 and final_parallel["ip_failures"] == 5, "concurrent failures lose no count", count)
        mutant_path = root / "mutant.sqlite"
        mutant = StudentLoginThrottleRepository(mutant_path, max_failures=6)
        for index in range(5):
            mutant.record_failure("mutant-user", "192.0.2.55", now=4000 + index)
        mutation_off_by_one = not mutant.status("mutant-user", "192.0.2.55", now=4004)["blocked"]
        _assert(mutation_off_by_one, "off-by-one limit mutant is detected", count)
        raw_mutant_path = root / "raw-mutant.sqlite"
        raw_mutant = StudentLoginThrottleRepository(raw_mutant_path)
        with raw_mutant._connect() as changed:
            changed.execute("INSERT INTO student_login_throttle(bucket_type,key_digest,window_started,failures,updated_at) VALUES('identifier',?,?,?,?)", (raw_identifier, 1, 1, 1))
            raw_rows = "|".join(str(row[0]) for row in changed.execute("SELECT key_digest FROM student_login_throttle").fetchall()).encode("utf-8")
        mutation_raw_persistence = raw_identifier.encode() in raw_rows
        _assert(mutation_raw_persistence, "raw persistence mutant is detected", count)
        overclear_path = root / "overclear-mutant.sqlite"
        overclear = StudentLoginThrottleRepository(overclear_path)
        overclear.record_failure("overclear-user", "192.0.2.66", now=5000)
        with overclear._connect() as changed:
            changed.execute("DELETE FROM student_login_throttle")
        mutation_success_overclear = overclear.status("overclear-user", "192.0.2.66", now=5000)["ip_failures"] == 0
        _assert(mutation_success_overclear, "success-overclear mutant is detected", count)
        result: ThrottleResult = {
            "name": "repositories-throttle",
            "assertions": count[0],
            "passed": True,
            "digest_only": digest_only,
            "temp_db_removed": False,
            "mutation_off_by_one": mutation_off_by_one,
            "mutation_raw_persistence": mutation_raw_persistence,
            "mutation_success_overclear": mutation_success_overclear,
        }
    result["temp_db_removed"] = not root.exists()
    _write_receipts(evidence_root, result)
    return result


def main() -> int:
    try:
        result = run_checks()
    except (ThrottleCheckFailure, StudentLoginThrottleInputError, sqlite3.Error) as exc:
        print(json.dumps({"name": "repositories-throttle", "assertions": 0, "passed": False, "error": type(exc).__name__}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
