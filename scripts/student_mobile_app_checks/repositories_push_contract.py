"""Adversarial fresh-DB checks for push lease, retry, and payload contracts."""
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
from datetime import datetime
from pathlib import Path
from typing import TypeAlias

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_push_payload import JsonValue, StudentPushRepositoryInputError
from core.student_push_repository import StudentPushRepository

CheckValue: TypeAlias = str | int | float | bool | None | list["CheckValue"] | dict[str, "CheckValue"]
CheckResult: TypeAlias = dict[str, CheckValue]
SqlValue: TypeAlias = str | int | float | None


class CheckFailure(AssertionError):
    """Named contract assertion failure."""


def _check(count: list[int], condition: bool, label: str) -> None:
    count[0] += 1
    if not condition:
        raise CheckFailure(label)


def _row(path: Path, sql: str, params: tuple[SqlValue, ...] = ()) -> tuple[SqlValue, ...] | None:
    db = sqlite3.connect(path)
    try:
        value = db.execute(sql, params).fetchone()
    finally:
        db.close()
    return None if value is None else tuple(value)


def _parallel_enqueue(repo: StudentPushRepository, now: float) -> list[int]:
    barrier, values = threading.Barrier(2), []

    def worker() -> None:
        barrier.wait()
        values.append(repo.enqueue("parallel", "s1", {"type": "announcement"}, now=now))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    return values


def _parallel_lease(repo: StudentPushRepository, now: float) -> list[dict[str, JsonValue] | None]:
    barrier, values = threading.Barrier(2), []

    def worker() -> None:
        barrier.wait()
        values.append(repo.lease(now=now, lease_seconds=30))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    return values


class _ExpiryMutant(StudentPushRepository):
    """Mutation seam that hides the caller's current time from completion."""

    def _now(self, value: float | int | datetime | None = None) -> float:  # noqa: ARG002
        return 1000.0


class _RetryMutant(StudentPushRepository):
    """Mutation seam with an incorrect first retry interval."""

    RETRY_BACKOFF_SECONDS = (1.0, 1.0, 1.0, 1.0, 1.0)


class _PrivacyMutant(StudentPushRepository):
    """Mutation seam that serializes nested values without privacy checks."""

    @staticmethod
    def _payload(value: dict[str, JsonValue], protected_values: tuple[str, ...] = ()) -> str:  # noqa: ARG004
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mutant_detection(count: list[int], label: str, wrong_result: bool) -> None:
    try:
        _check(count, not wrong_result, f"{label} mutant must fail")
    except CheckFailure:
        detected = True
    else:
        detected = False
    _check(count, detected, f"{label} differentiating mutant is caught")


def _run_mutant_probes(count: list[int]) -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="student-app-push-mutants-") as raw:
        root = Path(raw)
        expiry = _ExpiryMutant(root / "expiry.sqlite", clock=lambda: 1000.0)
        expiry_id = expiry.enqueue("expiry", "s1", {"type": "announcement"}, now=1000)
        expiry_lease = expiry.lease(now=1000, lease_seconds=1)
        expiry_wrong = expiry_lease is not None and expiry.complete(expiry_id, expiry_lease["lease_token"], now=1002)

        retry = _RetryMutant(root / "retry.sqlite", clock=lambda: 1000.0)
        retry_id = retry.enqueue("retry", "s1", {"type": "announcement"}, now=1000)
        retry_lease = retry.lease(now=1000, lease_seconds=1)
        retry.complete(retry_id, retry_lease["lease_token"] if retry_lease else "", success=False, error="timeout", now=1000)
        retry_row = _row(root / "retry.sqlite", "SELECT next_attempt FROM student_push_outbox WHERE id=?", (retry_id,))
        retry_wrong = retry_row is not None and float(retry_row[0]) - 1000.0 != 60.0

        privacy = _PrivacyMutant(root / "privacy.sqlite", clock=lambda: 1000.0)
        privacy_secret = secrets.token_urlsafe(32)
        privacy_id = privacy.enqueue("privacy", "s1", {"nested": {"benign": privacy_secret}}, now=1000)
        privacy_count = _row(root / "privacy.sqlite", "SELECT COUNT(*) FROM student_push_outbox WHERE id=?", (privacy_id,))
        privacy_wrong = privacy_count is not None and int(privacy_count[0]) != 0
    _mutant_detection(count, "expiry", expiry_wrong)
    _mutant_detection(count, "retry", retry_wrong)
    _mutant_detection(count, "privacy", privacy_wrong)
    return {"expiry": expiry_wrong, "retry": retry_wrong, "privacy": privacy_wrong}


def run_checks() -> CheckResult:
    """Run all push contract scenarios against a disposable SQLite database."""

    count, secret_lengths = [0], {}
    with tempfile.TemporaryDirectory(prefix="student-app-push-contract-") as raw:
        root, path = Path(raw), Path(raw) / "app.sqlite"
        db = sqlite3.connect(path)
        try:
            db.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
            db.execute("INSERT INTO sentinel(value) VALUES ('keep')")
            db.commit()
        finally:
            db.close()
        push = StudentPushRepository(path, clock=lambda: 1000.0)
        active_id = push.enqueue("active", "s1", {"type": "announcement", "url": "/app?announcement=active"}, now=1000)
        active = push.lease(now=1000, lease_seconds=10)
        _check(count, active is not None and push.complete(active_id, active["lease_token"], now=1001), "active lease completes")
        expired_id = push.enqueue("expired", "s1", {"type": "announcement"}, now=1000)
        expired = push.lease(now=1000, lease_seconds=1)
        expired_result = expired is not None and push.complete(expired_id, expired["lease_token"], now=1002)
        _check(count, not expired_result, "expired lease completion is rejected before reclaim")
        reclaimed = push.lease(now=1002, lease_seconds=1)
        _check(count, reclaimed is not None and reclaimed["outbox_id"] == expired_id, "expired lease is reclaimable")
        _check(count, expired is not None and not push.complete(expired_id, expired["lease_token"], now=1002), "reclaimed row rejects old token")
        _check(count, reclaimed is not None and push.complete(expired_id, reclaimed["lease_token"], now=1002), "reclaimed token completes")

        retry_id = push.enqueue("schedule", "s1", {"type": "announcement"}, now=1000)
        expected, deltas = (60, 300, 1800, 7200, 21600), []
        current = 2000.0
        for expected_delta in expected:
            lease = push.lease(now=current, lease_seconds=1)
            _check(count, lease is not None and lease["outbox_id"] == retry_id, "retry lease is acquired")
            _check(count, lease is not None and push.complete(retry_id, lease["lease_token"], success=False, error="timeout", now=current), "retry completion is recorded")
            row = _row(path, "SELECT state,attempts,next_attempt FROM student_push_outbox WHERE id=?", (retry_id,))
            _check(count, row is not None and row[0] == "pending" and int(row[1]) == len(deltas) + 1, "retry remains pending through schedule")
            delta = float(row[2]) - current if row is not None else -1.0
            deltas.append(int(delta))
            _check(count, delta == expected_delta, "retry delta matches contract")
            current += expected_delta
        final_lease = push.lease(now=current, lease_seconds=1)
        _check(count, final_lease is not None and push.complete(retry_id, final_lease["lease_token"], success=False, error="timeout", now=current), "sixth retry completion is recorded")
        final_row = _row(path, "SELECT state,attempts FROM student_push_outbox WHERE id=?", (retry_id,))
        _check(count, final_row == ("failed", 6), "terminal failure follows all five backoffs")

        parallel_ids = _parallel_enqueue(push, 3000)
        parallel_count = _row(path, "SELECT COUNT(*) FROM student_push_outbox WHERE announcement_id='parallel' AND sid='s1'")
        _check(count, len(parallel_ids) == 2 and parallel_count == (1,), "concurrent enqueue deduplicates")
        owners = [item for item in _parallel_lease(push, 3000) if item is not None]
        _check(count, len(owners) == 1, "concurrent lease has one owner")
        if owners:
            push.complete(owners[0]["outbox_id"], owners[0]["lease_token"], now=3001)

        subscription_id = push.upsert_subscription("aid-1", "s1", "device", "https://push.example/endpoint", "a2V5", "YXV0aA", now=1000)
        revoke_id = push.enqueue("gone", "s1", {"type": "announcement"}, subscription_id=subscription_id, now=1000)
        revoke_lease = push.lease(now=1000, lease_seconds=10)
        _check(count, revoke_lease is not None and revoke_lease["outbox_id"] == revoke_id, "410 row is leased")
        _check(count, revoke_lease is not None and push.complete(revoke_id, revoke_lease["lease_token"], status_code=410, now=1001), "410 completion is recorded")
        revoked = _row(path, "SELECT revoked_at IS NOT NULL FROM student_push_subscriptions WHERE id=?", (subscription_id,))
        _check(count, revoked == (1,), "410 revokes subscription")

        normal_payload = {"type": "announcement", "announcementId": "normal", "url": "/app?announcement=normal", "nested": {"title": "notice"}}
        normal_id = push.enqueue("normal", "s1", normal_payload, now=1000)
        normal_lease = push.lease(now=1000, lease_seconds=10)
        _check(count, normal_lease is not None and normal_lease["outbox_id"] == normal_id and normal_lease["payload"] == normal_payload, "normal payload roundtrips")
        raw_values = {"session_token": secrets.token_urlsafe(32), "activation_code": "246810", "endpoint": "https://push.example/raw", "auth": "YXV0aA"}
        for label, value in raw_values.items():
            secret_lengths[label] = len(value)
            before = _row(path, "SELECT COUNT(*) FROM student_push_outbox")[0]
            try:
                push.enqueue(f"raw-{label}", "s1", {"nested": {"benign": value}}, now=1000)
            except StudentPushRepositoryInputError:
                rejected = True
            else:
                rejected = False
            after = _row(path, "SELECT COUNT(*) FROM student_push_outbox")[0]
            _check(count, rejected and before == after, f"nested raw {label} rejected without persistence")

        integrity = _row(path, "PRAGMA integrity_check")[0]
        sentinel = _row(path, "SELECT value FROM sentinel")[0]
        _check(count, integrity == "ok" and sentinel == "keep", "integrity and unrelated sentinel preserved")
        mutants = _run_mutant_probes(count)
    temporary_removed = not root.exists()
    result: CheckResult = {"name": "repositories_push_contract", "assertions": count[0], "passed": True, "retry_deltas": list(expected), "mutants": mutants, "secret_lengths": secret_lengths, "integrity": str(integrity), "sentinel": str(sentinel), "temporary_db_removed": temporary_removed}
    evidence_root = Path(os.environ.get("STUDENT_APP_EVIDENCE_DIR", ".omo/evidence/student-mobile-app-v2/task-3"))
    try:
        evidence_root.mkdir(parents=True, exist_ok=True)
        (evidence_root / "push-remediation-l1-green.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except PermissionError:
        fallback = ROOT / ".codex-temp" / "student-mobile-app-v2" / "task-3"
        fallback.mkdir(parents=True, exist_ok=True)
        (fallback / "push-remediation-l1-green.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False, sort_keys=True))
