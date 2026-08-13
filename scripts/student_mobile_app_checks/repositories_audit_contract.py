"""Fresh-DB contract checks for account-audit privacy and typed boundaries."""
# /// script
# requires-python = ">=3.11"
# ///
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeAlias

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_account_audit import (
    JsonValue,
    StudentAccountAuditRepository,
)

CheckValue: TypeAlias = str | int | float | bool | None | list["CheckValue"] | dict[str, "CheckValue"]
SqlValue: TypeAlias = str | int | float | None
CheckResult: TypeAlias = dict[str, CheckValue]


class CheckFailure(AssertionError):
    """A named audit contract assertion failed."""


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


def _rejected(operation: Callable[[], None]) -> bool:
    try:
        operation()
    except ValueError as exc:
        return type(exc).__name__ == "StudentAccountAuditInputError"
    return False


class _ActionMutant(StudentAccountAuditRepository):
    """Mutation seam that accepts an opaque action unchanged."""

    @staticmethod
    def _action(value: str) -> str:
        return value


class _MetadataMutant(StudentAccountAuditRepository):
    """Mutation seam that skips recursive metadata privacy parsing."""

    @staticmethod
    def _metadata(value: Mapping[str, JsonValue] | None) -> str:
        return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _mutant_probe(count: list[int]) -> dict[str, bool]:
    token = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="student-app-audit-mutants-") as raw:
        root = Path(raw)
        action_repo = _ActionMutant(root / "action.sqlite", clock=lambda: 1000.0)
        action_repo.record(token, target_aid="aid", actor_surface="mobile", now=1000)
        action_persisted = _row(root / "action.sqlite", "SELECT COUNT(*) FROM student_account_audit WHERE action=?", (token,)) == (1,)
        metadata_repo = _MetadataMutant(root / "metadata.sqlite", clock=lambda: 1000.0)
        metadata_repo.record("login", target_aid="aid", actor_surface="mobile", metadata={"benign": {"nested": token}}, now=1000)
        metadata_text = _row(root / "metadata.sqlite", "SELECT metadata_json FROM student_account_audit")
        metadata_persisted = metadata_text is not None and token in str(metadata_text[0])
    for label, wrong in (("action", action_persisted), ("nested metadata", metadata_persisted)):
        try:
            _check(count, not wrong, f"{label} mutant must fail")
        except CheckFailure:
            caught = True
        else:
            caught = False
        _check(count, caught, f"{label} differentiating mutant is caught")
    return {"action": action_persisted, "metadata": metadata_persisted}


def run_checks() -> CheckResult:
    """Exercise safe labels, recursive privacy, malformed boundaries, and integrity."""
    count, secret_lengths = [0], {}
    with tempfile.TemporaryDirectory(prefix="student-app-audit-contract-") as raw:
        root, path = Path(raw), Path(raw) / "app.sqlite"
        db = sqlite3.connect(path)
        try:
            db.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
            db.execute("INSERT INTO sentinel(value) VALUES ('keep')")
            db.commit()
        finally:
            db.close()
        audit = StudentAccountAuditRepository(path, clock=lambda: 1000.0)
        normal_metadata = {
            "result": "ok",
            "outcomeCode": "idempotency_conflict",
            "nested": {"statusCode": 200, "values": [True, None, "/app?announcement=1", ("safe", "value")]},
        }
        event_id = audit.record("login", target_aid="aid-1", actor_surface="mobile", metadata=normal_metadata, now=1000)
        _check(count, event_id == 1 and audit.count() == 1, "normal audit record persists")
        event = audit.list_events(target_aid="aid-1")[0]
        _check(count, event["action"] == "login" and event["actor_surface"] == "mobile", "normal labels roundtrip")
        _check(count, event["target_aid_digest"] == audit._digest("aid-1"), "target aid is digest-only")
        expected_metadata = {**normal_metadata, "nested": {"statusCode": 200, "values": [True, None, "/app?announcement=1", ["safe", "value"]]}}
        _check(count, event["metadata"] == expected_metadata, "unknown safe metadata roundtrips")
        for label in ("reset", "disable", "enable", "revoke", "code", "push", "account.reset", "activation_code_issue", "push.subscribe"):
            audit.record(label, target_aid="aid-1", actor_surface="admin", now=1000)
        _check(count, audit.count() == 10, "future account and push labels remain allowed")
        baseline = _row(path, "SELECT COUNT(*), MAX(id) FROM student_account_audit")
        token = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(1_000_000):06d}"
        endpoint = "https://push.example/raw-endpoint"
        auth_key = secrets.token_urlsafe(16)
        secret_lengths.update({"session_token": len(token), "activation_code": len(code), "endpoint": len(endpoint), "auth_key": len(auth_key)})
        operations: list[Callable[[], None]] = []
        for secret in (token, code, endpoint, auth_key):
            operations.extend((
                lambda secret=secret: audit.record(secret, target_aid="aid-1", actor_surface="mobile", now=1000),
                lambda secret=secret: audit.record("login", target_aid="aid-1", actor_surface=secret, now=1000),
                lambda secret=secret: audit.record("login", target_aid="aid-1", actor_surface="mobile", metadata={"benign": [({"nested": (secret,)},)]}, now=1000),
            ))
        operations.append(lambda: audit.record("login", target_aid="aid-1", actor_surface="mobile", metadata={"benign": 123456}, now=1000))
        for key in ("token", "activation_code", "endpoint", "auth", "private_key"):
            operations.append(lambda key=key: audit.record("login", target_aid="aid-1", actor_surface="mobile", metadata={"nested": {key: "safe"}}, now=1000))
        for operation in operations:
            _check(count, _rejected(operation), "secret-like audit input is typed-rejected")
        _check(count, _row(path, "SELECT COUNT(*), MAX(id) FROM student_account_audit") == baseline, "rejected input leaves audit rows unchanged")
        malformed: list[Callable[[], None]] = [
            lambda: getattr(audit, "record")(17, target_aid="aid-1", actor_surface="mobile", now=1000),
            lambda: audit.record("unknown", target_aid="aid-1", actor_surface="mobile", now=1000),
            lambda: audit.record("login", target_aid="aid-1", actor_surface="opaque-surface", now=1000),
            lambda: audit.record("login", target_aid="aid-1", target_ref="other", actor_surface="mobile", now=1000),
            lambda: audit.record("login", target_aid="aid-1", actor_surface="mobile", now=float("nan")),
            lambda: getattr(audit, "record")("login", target_aid="aid-1", actor_surface="mobile", metadata=["not-an-object"], now=1000),
            lambda: getattr(audit, "record")("login", target_aid="aid-1", actor_surface="mobile", metadata={1: "bad"}, now=1000),
            lambda: audit.record("login", target_aid="aid-1", actor_surface="mobile", metadata={"deep": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": "too-deep"}}}}}}}}}, now=1000),
            lambda: audit.record("login", target_aid="aid-1", actor_surface="mobile", metadata={"large": "x" * 1025}, now=1000),
            lambda: audit.record("login", target_aid="aid-1", actor_surface="mobile", metadata={"many": list(range(65))}, now=1000),
        ]
        for operation in malformed:
            _check(count, _rejected(operation), "malformed audit input has typed failure")
        _check(count, _row(path, "SELECT COUNT(*), MAX(id) FROM student_account_audit") == baseline, "malformed input leaves rows unchanged")
        integrity = str(_row(path, "PRAGMA integrity_check")[0])
        sentinel = str(_row(path, "SELECT value FROM sentinel")[0])
        _check(count, integrity == "ok" and sentinel == "keep", "integrity and unrelated sentinel preserved")
        mutants = _mutant_probe(count)
    result: CheckResult = {"name": "repositories_audit_contract", "assertions": count[0], "passed": True, "mutants": mutants, "secret_lengths": secret_lengths, "integrity": integrity, "sentinel": sentinel, "temporary_db_removed": not root.exists()}
    evidence_root = Path(os.environ.get("STUDENT_APP_EVIDENCE_DIR", ".omo/evidence/student-mobile-app-v2/task-3"))
    try:
        evidence_root.mkdir(parents=True, exist_ok=True)
        (evidence_root / "audit-remediation-l1-green.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except PermissionError:
        fallback = ROOT / ".codex-temp" / "student-mobile-app-v2" / "task-3"
        fallback.mkdir(parents=True, exist_ok=True)
        (fallback / "audit-remediation-l1-green.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False, sort_keys=True))
