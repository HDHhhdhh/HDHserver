"""Fresh SQLite contract checks for activation-code lifecycle safety.

Run with ``python scripts/student_mobile_app_checks/repositories_activation_contract.py``.
Only temporary databases are opened; receipts contain lengths, booleans, and
counts, never a generated code or identity secret.
"""
# /// script
# requires-python = ">=3.11"
# ///
from __future__ import annotations

import hashlib
import hmac
import json
import os
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

import core.student_activation_codes as activation_module
from core.student_activation_codes import ActivationRedemption, StudentActivationCodeRepository

CheckValue: TypeAlias = str | int | float | bool | None | list["CheckValue"] | dict[str, "CheckValue"]
CheckResult: TypeAlias = dict[str, CheckValue]
OperationResult: TypeAlias = str | ActivationRedemption | None | int


class CheckFailure(AssertionError):
    """Named activation contract assertion failure."""


def _check(count: list[int], condition: bool, label: str) -> None:
    count[0] += 1
    if not condition:
        raise CheckFailure(label)


def _row(path: Path, sql: str, params: tuple[str | int | float | None, ...] = ()) -> tuple[str | int | float | None, ...] | None:
    db = sqlite3.connect(path)
    try:
        value = db.execute(sql, params).fetchone()
    finally:
        db.close()
    return None if value is None else tuple(value)


def _typed_rejected(operation: Callable[[], OperationResult]) -> bool:
    """Recognize only the repository's typed input/state failures."""
    try:
        operation()
    except ValueError as exc:
        return type(exc).__name__ in {"StudentActivationInputError", "StudentActivationStateError"}
    return False


class _RawDigestMutant(StudentActivationCodeRepository):
    """Mutation seam that persists caller values instead of a digest."""

    @staticmethod
    def _digest(value: str) -> str:
        return value


class _ExpiryBypassMutant(StudentActivationCodeRepository):
    """Mutation seam that ignores expiry while resolving a code."""

    @staticmethod
    def _state_usable(expires_at: float, attempts: int, now: float) -> bool:  # noqa: ARG004
        return True


class _AttemptLimitMutant(StudentActivationCodeRepository):
    """Mutation seam that silently raises the mismatch limit to six."""

    @staticmethod
    def _state_usable(expires_at: float, attempts: int, now: float) -> bool:
        return expires_at > now and attempts < 6


def _parallel_issue(repo: StudentActivationCodeRepository) -> tuple[list[str], list[str]]:
    barrier = threading.Barrier(2)
    values: list[str] = []
    failures: list[str] = []

    def worker() -> None:
        barrier.wait()
        try:
            values.append(repo.issue("parallel", ["parallel-sid"], now=2000))
        except (sqlite3.Error, ValueError) as exc:
            failures.append(type(exc).__name__)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    return values, failures


def _mutant_checks(count: list[int]) -> dict[str, bool]:
    """Prove the contract checker catches raw persistence and lifecycle bypasses."""
    with tempfile.TemporaryDirectory(prefix="student-app-activation-mutants-") as raw:
        root = Path(raw)
        raw_repo = _RawDigestMutant(root / "raw.sqlite", clock=lambda: 1000.0)
        raw_code = raw_repo.issue("raw-aid", ["raw-sid"], now=1000)
        raw_row = _row(root / "raw.sqlite", "SELECT code_digest FROM student_activation_codes")
        raw_persisted = raw_row == (raw_code,)
        bypass = _ExpiryBypassMutant(root / "bypass.sqlite", clock=lambda: 1000.0)
        expired_code = bypass.issue("expired", ["s1"], ttl_seconds=1, now=1000)
        expiry_bypassed = bypass.redeem("expired", expired_code, now=1001) is not None
        original_limit = activation_module.MAX_ATTEMPTS
        activation_module.MAX_ATTEMPTS = 6
        attempt_repo = _AttemptLimitMutant(root / "attempt.sqlite", clock=lambda: 1000.0)
        locked_code = attempt_repo.issue("locked", ["s1"], now=1000)
        for _ in range(5):
            attempt_repo.redeem("locked", "000000", now=1000)
        attempt_bypassed = attempt_repo.redeem("locked", locked_code, now=1000) is not None
        activation_module.MAX_ATTEMPTS = original_limit
    for label, wrong in (("raw digest", raw_persisted), ("expired use", expiry_bypassed), ("attempt lock", attempt_bypassed)):
        try:
            _check(count, not wrong, f"{label} mutant must violate the contract")
        except CheckFailure:
            caught = True
        else:
            caught = False
        _check(count, caught, f"{label} differentiating mutant is caught")
    return {"raw_digest_persistence": raw_persisted, "expired_use_bypass": expiry_bypassed, "attempt_lock_bypass": attempt_bypassed}


def run_checks() -> CheckResult:
    """Exercise activation lifecycle, exact boundaries, malformed inputs, and concurrency."""
    count = [0]
    secret_lengths: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="student-app-activation-contract-") as raw:
        root, path = Path(raw), Path(raw) / "app.sqlite"
        db = sqlite3.connect(path)
        try:
            db.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
            db.execute("INSERT INTO sentinel(value) VALUES ('keep')")
            db.commit()
        finally:
            db.close()
        codes = StudentActivationCodeRepository(path, timeout=2.0, clock=lambda: 1000.0)
        with codes._connect() as checked:
            _check(count, checked.row_factory is sqlite3.Row, "row factory is sqlite3.Row")
            _check(count, int(checked.execute("PRAGMA foreign_keys").fetchone()[0]) == 1, "foreign keys enabled")
            _check(count, checked.isolation_level is None, "short autocommit connection")
        code = codes.issue("aid-1", ["s1", "s2"], now=1000)
        secret_lengths["activation_code"] = len(code)
        _check(count, len(code) == 6 and code.isascii() and code.isdigit(), "issued code is six ASCII digits")
        digest = _row(path, "SELECT code_digest FROM student_activation_codes WHERE identity_key=?", (codes._digest("aid-1"),))
        expected_digest = hmac.new(b"student-app-activation-code-v1", code.encode(), hashlib.sha256).hexdigest()
        _check(count, digest == (expected_digest,), "stored code is keyed SHA-256 digest-only")
        _check(count, code not in repr(digest), "raw issued code is absent from protected row")
        redeemed = codes.redeem("aid-1", code, now=1001)
        _check(count, redeemed is not None and redeemed["sids"] == ["s1", "s2"], "identity-bound SID set roundtrips exactly")
        _check(count, codes.redeem("aid-1", code, now=1001) is None, "one-use redemption rejects reuse")
        replacement_old = codes.issue("replace", ["old-sid"], now=1000)
        replacement_new = codes.issue("replace", ["new-sid"], now=1001)
        _check(count, codes.redeem("replace", replacement_old, now=1001) is None, "second issue invalidates previous code")
        replacement_result = codes.redeem("replace", replacement_new, now=1001)
        _check(count, replacement_result is not None and replacement_result["sids"] == ["new-sid"], "replacement code binds replacement SID set")
        exact_boundary = codes.issue("boundary", ["s1"], now=1000)
        _check(count, codes.redeem("boundary", exact_boundary, now=1000 + 86400) is None, "default 24-hour boundary is expired")
        _check(count, _row(path, "SELECT used FROM student_activation_codes WHERE identity_key=?", (codes._digest("boundary"),)) == (1,), "expired redemption marks code spent")
        lock_code = codes.issue("lock", ["s1"], now=1000)
        for _ in range(4):
            _check(count, codes.redeem("lock", "000000", now=1000) is None, "first four mismatches reject")
        _check(count, _row(path, "SELECT attempts,used FROM student_activation_codes WHERE identity_key=?", (codes._digest("lock"),)) == (4, 0), "four mismatches remain active")
        _check(count, codes.redeem("lock", "000000", now=1000) is None, "fifth mismatch rejects")
        _check(count, _row(path, "SELECT attempts,used FROM student_activation_codes WHERE identity_key=?", (codes._digest("lock"),)) == (5, 1), "fifth mismatch disposes code")
        _check(count, codes.redeem("lock", lock_code, now=1000) is None, "correct code cannot bypass attempt lock")
        mismatch = codes.issue("mismatch", ["s1"], now=1000)
        rows_before = _row(path, "SELECT COUNT(*),MAX(id) FROM student_activation_codes")
        _check(count, codes.redeem("other", mismatch, now=1000) is None, "wrong identity is rejected")
        _check(count, _row(path, "SELECT COUNT(*),MAX(id) FROM student_activation_codes") == rows_before, "wrong identity does not write")
        group_a = codes.issue("same||A||1", ["group-a"], now=1000)
        group_b = codes.issue("same||B||2", ["group-b"], now=1000)
        selected = codes.redeem_candidates(("same||A||1", "same||B||2"), group_b, now=1000)
        _check(count, selected is not None and selected["identity_key"] == "same||B||2" and selected["sids"] == ["group-b"], "candidate redemption selects the code-bound canonical group atomically")
        _check(count, _row(path, "SELECT attempts,used FROM student_activation_codes WHERE identity_key=?", (codes._digest("same||A||1"),)) == (0, 0), "selecting group B does not mutate group A attempts")
        _check(count, codes.redeem("same||A||1", group_a, now=1000) is not None, "unselected group A code remains redeemable")
        outside = codes.issue("other||C||3", ["group-c"], now=1000)
        _check(count, codes.redeem_candidates(("same||A||1", "same||B||2"), outside, now=1000) is None, "a code outside the allowed candidate set is rejected")
        _check(count, codes.redeem("other||C||3", outside, now=1000) is not None, "rejected outside code remains redeemable")
        malformed: list[Callable[[], OperationResult]] = [
            lambda: codes.issue(17, ["s1"], now=1000),
            lambda: codes.issue("aid", "s1", now=1000),
            lambda: codes.issue("aid", ["s1", 1], now=1000),
            lambda: codes.issue("aid", ["s1"], ttl_seconds="bad", now=1000),
            lambda: codes.issue("aid", ["s1"], ttl_seconds=True, now=1000),
            lambda: codes.issue("aid", ["s1"], ttl_seconds=0, now=1000),
            lambda: codes.issue("aid", ["s1"], now="bad"),
            lambda: codes.issue("aid", ["s1"], now=float("nan")),
        ]
        malformed_rows = _row(path, "SELECT COUNT(*),MAX(id) FROM student_activation_codes")
        for operation in malformed:
            _check(count, _typed_rejected(operation), "malformed issue input is typed-rejected")
        _check(count, _row(path, "SELECT COUNT(*),MAX(id) FROM student_activation_codes") == malformed_rows, "malformed issue input leaves no rows")
        _check(count, codes.redeem(17, mismatch, now=1000) is None and codes.redeem("aid", "123", now=1000) is None, "malformed lookup values fail closed")
        lookup_rows = _row(path, "SELECT COUNT(*),MAX(id) FROM student_activation_codes")
        _check(count, _typed_rejected(lambda: codes.redeem("mismatch", mismatch, now="bad")), "malformed redeem clock is typed-rejected")
        _check(count, _typed_rejected(lambda: codes.expire(now="bad")), "malformed expire clock is typed-rejected")
        _check(count, _row(path, "SELECT COUNT(*),MAX(id) FROM student_activation_codes") == lookup_rows, "malformed lookup input leaves rows unchanged")
        corrupt = codes.issue("corrupt", ["s1"], now=1000)
        db = sqlite3.connect(path)
        try:
            db.execute("UPDATE student_activation_codes SET attempts='bad' WHERE identity_key=?", (codes._digest("corrupt"),))
            db.commit()
        finally:
            db.close()
        _check(count, codes.redeem("corrupt", corrupt, now=1000) is None, "malformed stored attempts fail closed")
        _check(count, _row(path, "SELECT attempts FROM student_activation_codes WHERE identity_key=?", (codes._digest("corrupt"),)) == ("bad",), "malformed stored attempts do not write")
        parallel, failures = _parallel_issue(codes)
        _check(count, len(parallel) == 2 and not failures, "two concurrent issuers complete")
        active = int(_row(path, "SELECT COUNT(*) FROM student_activation_codes WHERE identity_key=? AND used=0", (codes._digest("parallel"),))[0])
        _check(count, active == 1, "identity has exactly one active code after concurrent issue")
        outcomes = [codes.redeem("parallel", candidate, now=2000) is not None for candidate in parallel]
        _check(count, sum(outcomes) == 1, "exactly one concurrent result remains redeemable")
        integrity = str(_row(path, "PRAGMA integrity_check")[0])
        sentinel = str(_row(path, "SELECT value FROM sentinel")[0])
        _check(count, integrity == "ok" and sentinel == "keep", "integrity and unrelated sentinel are preserved")
        protected = repr(_row(path, "SELECT identity_key,sids_json,code_digest,used,attempts FROM student_activation_codes"))
        _check(count, code not in protected and replacement_new not in protected and lock_code not in protected, "raw codes absent from all protected rows")
        mutants = _mutant_checks(count)
    result: CheckResult = {
        "name": "repositories_activation_contract",
        "assertions": count[0],
        "passed": True,
        "mutants": mutants,
        "secret_lengths": secret_lengths,
        "integrity": integrity,
        "sentinel": sentinel,
        "raw_secret_absent": True,
        "temporary_db_removed": not root.exists(),
    }
    evidence_root = Path(os.environ.get("STUDENT_APP_EVIDENCE_DIR", ".omo/evidence/student-mobile-app-v2/task-3"))
    try:
        evidence_root.mkdir(parents=True, exist_ok=True)
        (evidence_root / "activation-remediation-l1-green.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except PermissionError:
        fallback = ROOT / ".codex-temp" / "student-mobile-app-v2" / "task-3"
        fallback.mkdir(parents=True, exist_ok=True)
        (fallback / "activation-remediation-l1-green.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    result = run_checks()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
