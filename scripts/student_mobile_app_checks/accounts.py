#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
# How to run: C:\\server\\venv\\Scripts\\python.exe scripts\\student_mobile_app_checks\\accounts.py
"""Standalone temporary-fixture checks for Todo 2 account rules/repository."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from typing import Iterator, TypeAlias

from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_account_repository import (  # noqa: E402
    AccountRepositoryError,
    StudentAccountRepository,
)
from core.student_account_rules import (  # noqa: E402
    ActivationDecision,
    AccountInputError,
    account_id_key,
    activation_decision,
    identity_key,
    normalize_account_id,
    validate_password,
)

FixtureValue: TypeAlias = str | int | float | bool | None | list["FixtureValue"] | dict[str, "FixtureValue"]


@contextmanager
def fixture(students: list[dict[str, FixtureValue]], accounts: dict[str, FixtureValue]) -> Iterator[tuple[Path, Path]]:
    """Create and remove an isolated student/account JSON pair."""

    with tempfile.TemporaryDirectory(prefix="student-account-check-") as raw:
        directory = Path(raw)
        students_path = directory / "students.json"
        accounts_path = directory / "auth_accounts.json"
        students_path.write_text(json.dumps(students, ensure_ascii=False, indent=2), encoding="utf-8")
        accounts_path.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
        yield accounts_path, students_path


def _check(state: list[int], condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    state[0] += 1


def _shape(path: Path) -> dict[str, FixtureValue]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError("fixture root is not a map")
    result: dict[str, FixtureValue] = {"top_level_map_entries": 0, "accounts": []}
    entries: list[FixtureValue] = []
    for value in data.values():
        if not isinstance(value, dict):
            continue
        fields = sorted(value)
        sids = value.get("sids")
        entries.append({"field_names": fields, "sids_count": len(sids) if isinstance(sids, list) else 0})
    result["top_level_map_entries"] = len(data)
    result["accounts"] = entries
    return result


def _rules_checks(state: list[int]) -> None:
    """Exercise normalization, identity grouping, decisions, and validators."""

    unique = {"id": "u-1", "name": "Ａlice", "school": "School", "grade": "1"}
    duplicate_a = {"id": "d-1", "name": "Bob", "school": "A", "grade": "1"}
    duplicate_b = {"id": "d-2", "name": "Bob", "school": "B", "grade": "1"}
    _check(state, identity_key(unique).name == "Alice", "NFKC roster name")
    _check(state, identity_key(unique).school == "School", "school grouping")
    _check(state, account_id_key("Ａlice") == "alice", "NFKC/case-fold account key")
    decision = activation_decision("Alice", [unique], {}, "1234")
    _check(state, decision.decision is ActivationDecision.UNIQUE_ACTIVATION, "unique activation")
    duplicate = activation_decision("Bob", [duplicate_a, duplicate_b], {}, "1234")
    _check(state, duplicate.decision is ActivationDecision.ACTIVATION_CODE_REQUIRED, "duplicate code path")
    for value in ("a", "bad/name", "bad name", "\u0000bad", "x" * 33):
        try:
            normalize_account_id(value)
        except AccountInputError:
            state[0] += 1
        else:
            raise AssertionError(f"accepted invalid account id {value!r}")
    for value in ("short", "1234", " Alice123", "Alice123 ", "\u0000password"):
        try:
            validate_password(value, "Alice")
        except AccountInputError as exc:
            _check(state, value != "1234" or exc.reason in {"length", "default_password"}, f"user password rejection {value!r}")
        else:
            raise AssertionError(f"accepted invalid password {value!r}")
    _check(state, validate_password("safe-password", "Alice") == "safe-password", "valid password")


def _repository_checks(state: list[int]) -> dict[str, FixtureValue]:
    """Exercise lifecycle, read purity, refusal, and unknown-field preservation."""

    students = [
        {"id": "u-1", "name": "Alice", "school": "A", "grade": "1"},
        {"id": "c-1", "name": "Cara", "school": "A", "grade": "1"},
        {"id": "r-1", "name": "Dora", "school": "A", "grade": "1"},
        {"id": "d-1", "name": "Bob", "school": "A", "grade": "1"},
        {"id": "d-2", "name": "Bob", "school": "B", "grade": "1"},
    ]
    initial = {"_meta": {"version": 7}, "Alice": {"sids": ["u-1"], "pw_hash": generate_password_hash("1234"), "custom": "keep"}}
    with fixture(students, initial) as (accounts_path, students_path):
        repo = StudentAccountRepository(accounts_path, students_path)
        before = _shape(accounts_path)
        before_read = accounts_path.read_bytes()
        _check(state, repo.get("Alice") is not None, "existing account read")
        _check(state, accounts_path.read_bytes() == before_read, "no write on read")
        public_rejected = accounts_path.read_bytes()
        try:
            repo.public_login("Cara", "custom-pass")
        except AccountRepositoryError as exc:
            _check(state, str(exc).endswith("default_password_required"), "public unique activation requires 1234")
        else:
            raise AssertionError("public unique login accepted a non-default password")
        _check(state, accounts_path.read_bytes() == public_rejected, "public unique rejection byte stable")
        created = repo.public_login("Cara", "1234")
        _check(state, created.created and created.must_change_credentials, "public unique 1234 activation")
        raw = repo.load()
        alice = raw["Cara"]
        _check(state, isinstance(alice, dict) and isinstance(alice.get("pw_hash"), str), "Werkzeug hash")
        _check(state, isinstance(alice, dict) and alice.get("disabled") is False, "disabled false")
        _check(state, isinstance(alice, dict) and alice.get("must_change_credentials") is True, "must change true")
        _check(state, raw.get("_meta") == {"version": 7}, "unknown top-level preserved")
        _check(state, isinstance(raw.get("Alice"), dict) and raw["Alice"].get("custom") == "keep", "unknown account field preserved")
        after_unique = _shape(accounts_path)
        duplicate_before = accounts_path.read_bytes()
        try:
            repo.public_login("Bob", "1234")
        except AccountRepositoryError as exc:
            _check(state, str(exc).endswith("activation_code_required"), "duplicate refused")
        else:
            raise AssertionError("duplicate activation unexpectedly succeeded")
        _check(state, accounts_path.read_bytes() == duplicate_before, "duplicate refusal byte stable")

        legacy_before = accounts_path.read_bytes()
        login = repo.public_login("Alice", "1234")
        _check(state, login.must_change_credentials, "lazy force state")
        _check(state, accounts_path.read_bytes() != legacy_before, "explicit lazy transition writes")
        custom = repo.load()["Alice"]
        _check(state, isinstance(custom, dict) and custom.get("custom") == "keep", "lazy merge preserves field")
        after_lazy = _shape(accounts_path)
        reset = repo.admin_reset("Alice", "1234")
        _check(state, reset.account_id == "Alice" and reset.must_change_credentials and reset.revoke_sessions, "admin reset result")
        reset_accounts = repo.load()
        reset_record = reset_accounts["Alice"]
        _check(state, isinstance(reset_record, dict) and reset_record.get("custom") == "keep", "reset preserves unknown field")
        _check(state, isinstance(reset_record, dict) and reset_record.get("must_change_credentials") is True, "reset must change")
        _check(state, isinstance(reset_record, dict) and isinstance(reset_record.get("pw_hash"), str) and check_password_hash(reset_record["pw_hash"], "1234"), "reset hashes 1234")
        _check(state, reset_accounts.get("_meta") == {"version": 7}, "reset preserves unknown top-level")
        rejected_bytes = accounts_path.read_bytes()
        try:
            repo.activate_unique("Dora", "not-the-default")
        except AccountRepositoryError:
            state[0] += 1
        else:
            raise AssertionError("unique activation accepted a non-default password")
        _check(state, accounts_path.read_bytes() == rejected_bytes, "unique rejection byte stable")
        try:
            repo.activate_unique("bad/name")
        except AccountInputError:
            state[0] += 1
        else:
            raise AssertionError("invalid account ID was accepted")
        _check(state, accounts_path.read_bytes() == rejected_bytes, "ID rejection byte stable")
        try:
            repo.admin_reset("Alice", "short")
        except AccountInputError:
            state[0] += 1
        else:
            raise AssertionError("invalid reset password was accepted")
        _check(state, accounts_path.read_bytes() == rejected_bytes, "password rejection byte stable")
        lifecycle = {"before": before, "after_unique": after_unique, "after_lazy": after_lazy, "after_reset": _shape(accounts_path)}
        return lifecycle


def _legacy_transition_checks(state: list[int]) -> None:
    """Prove custom IDs and custom credentials are not lazily forced."""

    students = [{"id": "s-1", "name": "Alice", "school": "A", "grade": "1"}]
    accounts = {"custom-id": {"sids": ["s-1"], "pw_hash": generate_password_hash("1234"), "disabled": False}}
    with fixture(students, accounts) as (accounts_path, students_path):
        repo = StudentAccountRepository(accounts_path, students_path)
        repo.public_login("custom-id", "1234")
        _check(state, repo.load()["custom-id"].get("must_change_credentials") is None, "custom ID remains legacy false")
    accounts = {"Alice": {"sids": ["s-1"], "pw_hash": generate_password_hash("custom-pass"), "disabled": False}}
    with fixture(students, accounts) as (accounts_path, students_path):
        repo = StudentAccountRepository(accounts_path, students_path)
        before = accounts_path.read_bytes()
        login = repo.public_login("Alice", "custom-pass")
        _check(state, login.decision is ActivationDecision.EXISTING and not login.created, "custom account existing decision")
        _check(state, not login.must_change_credentials, "custom account remains legacy false")
        _check(state, accounts_path.read_bytes() == before, "custom account login byte stable")
        _check(state, repo.load()["Alice"].get("must_change_credentials") is None, "custom password remains legacy false")


def _concurrency_checks(state: list[int]) -> None:
    """Use a deterministic barrier to race two account activations."""

    students = [
        {"id": "a-1", "name": "Alice", "school": "A", "grade": "1"},
        {"id": "b-1", "name": "Bella", "school": "A", "grade": "1"},
    ]
    with fixture(students, {"_unknown": {"keep": True}}) as (accounts_path, students_path):
        barrier = threading.Barrier(3)
        errors: list[BaseException] = []

        def worker(identifier: str) -> None:
            try:
                barrier.wait()
                StudentAccountRepository(accounts_path, students_path).activate_unique(identifier)
            except BaseException as exc:  # noqa: BROAD_EXCEPT_OK
                errors.append(exc)

        first = threading.Thread(target=worker, args=("Alice",))
        second = threading.Thread(target=worker, args=("Bella",))
        first.start()
        second.start()
        barrier.wait()
        first.join()
        second.join()
        _check(state, not errors, "concurrent writes completed")
        result = StudentAccountRepository(accounts_path, students_path).load()
        _check(state, "Alice" in result and "Bella" in result, "concurrent changes preserved")
        _check(state, result.get("_unknown") == {"keep": True}, "concurrent unknown field preserved")


def _atomic_failure_check(state: list[int]) -> None:
    """Prove an exception before replace leaves the original fixture intact."""

    students = [{"id": "s-1", "name": "Alice", "school": "A", "grade": "1"}]
    with fixture(students, {"_meta": {"keep": True}, "Alice": {"sids": ["s-1"], "pw_hash": generate_password_hash("old-pass")}}) as (accounts_path, students_path):
        original = accounts_path.read_bytes()
        original_mtime = accounts_path.stat().st_mtime_ns
        repo = StudentAccountRepository(accounts_path, students_path)
        try:
            original_save = __import__("core.student_account_repository", fromlist=["save_atomic"]).save_atomic
            module = __import__("core.student_account_repository", fromlist=["save_atomic"])
            module.save_atomic = lambda _path, _value: (_ for _ in ()).throw(RuntimeError("injected"))
            try:
                repo.admin_reset("Alice", "1234")
            finally:
                module.save_atomic = original_save
        except RuntimeError:
            state[0] += 1
        else:
            raise AssertionError("save seam did not raise")
        _check(state, accounts_path.read_bytes() == original, "atomic failure preserves bytes")
        _check(state, hashlib.sha256(accounts_path.read_bytes()).digest() == hashlib.sha256(original).digest(), "atomic failure preserves hash")
        _check(state, accounts_path.stat().st_mtime_ns == original_mtime, "atomic failure preserves mtime")


def run_checks() -> dict[str, str | int | bool]:
    """Run all temporary account checks and return redacted lifecycle evidence."""

    state = [0]
    _rules_checks(state)
    _repository_checks(state)
    _legacy_transition_checks(state)
    _concurrency_checks(state)
    _atomic_failure_check(state)
    return {"name": "accounts", "assertions": state[0], "passed": True}


def main() -> int:  # noqa: BROAD_EXCEPT_OK
    """Run checks as a command-line executable."""

    try:
        summary = run_checks()
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK
        print(f"accounts: FAIL: {exc}")
        return 1
    print(f"accounts: PASS ({summary['assertions']} assertions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
