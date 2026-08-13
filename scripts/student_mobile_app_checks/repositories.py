"""Aggregate the five student-mobile-app repository contract checkers.

Run with ``python scripts/student_mobile_app_checks/repositories.py``.  Each
dedicated checker owns a fresh SQLite fixture; this module only dispatches,
validates, and summarizes their redacted receipts.
"""
# /// script
# requires-python = ">=3.11"
# ///
from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.student_mobile_app_checks import repositories_activation_contract as activation_contract
from scripts.student_mobile_app_checks import repositories_audit_contract as audit_contract
from scripts.student_mobile_app_checks import repositories_push_contract as push_contract
from scripts.student_mobile_app_checks import repositories_sessions_contract as sessions_contract
from scripts.student_mobile_app_checks import repositories_throttle_contract as throttle_contract

CheckValue: TypeAlias = str | int | float | bool | None | list["CheckValue"] | dict[str, "CheckValue"]
CheckResult: TypeAlias = dict[str, CheckValue]
ContractRunner: TypeAlias = Callable[[], CheckResult]

EXPECTED_NAMES: Final[tuple[str, ...]] = (
    "repositories_push_contract",
    "repositories_audit_contract",
    "repositories_sessions_contract",
    "repositories_activation_contract",
    "repositories-throttle",
)


class CheckFailure(AssertionError):
    """A dedicated repository checker violated the aggregate result contract."""


@dataclass(frozen=True, slots=True)
class ContractReceipt:
    """The only fields needed to aggregate a dedicated checker receipt."""

    name: str
    assertions: int


def _runners() -> tuple[tuple[str, ContractRunner], ...]:
    """Return explicit runner bindings, resolving module attributes per run."""
    return (
        ("repositories_push_contract", push_contract.run_checks),
        ("repositories_audit_contract", audit_contract.run_checks),
        ("repositories_sessions_contract", sessions_contract.run_checks),
        ("repositories_activation_contract", activation_contract.run_checks),
        ("repositories-throttle", throttle_contract.run_checks),
    )


def _validate_receipt(expected_name: str, result: CheckResult) -> ContractReceipt:
    """Enforce the dispatcher-compatible name, count, and success contract."""
    if type(result) is not dict:
        raise CheckFailure(f"{expected_name} returned a non-dict result")
    name = result.get("name")
    assertions = result.get("assertions")
    passed = result.get("passed")
    if name != expected_name:
        raise CheckFailure(f"{expected_name} returned name {name!r}")
    if type(assertions) is not int or assertions <= 0:
        raise CheckFailure(f"{expected_name} returned a non-positive assertion count")
    if type(passed) is not bool or passed is not True:
        raise CheckFailure(f"{expected_name} reported failure")
    return ContractReceipt(name=expected_name, assertions=assertions)


def _run_contracts() -> tuple[ContractReceipt, ...]:
    """Run every dedicated checker and reject omissions or duplicate names."""
    receipts: list[ContractReceipt] = []
    for expected_name, runner in _runners():
        if not callable(runner):
            raise CheckFailure(f"{expected_name} does not expose callable run_checks")
        receipts.append(_validate_receipt(expected_name, runner()))
    names = tuple(receipt.name for receipt in receipts)
    if names != EXPECTED_NAMES:
        raise CheckFailure(f"dedicated result names mismatch: {names!r}")
    return tuple(receipts)


def _write_receipt(result: CheckResult) -> None:
    """Write a redacted aggregate receipt when the configured path is writable."""
    evidence_root = Path(os.environ.get("STUDENT_APP_EVIDENCE_DIR", ".omo/evidence/student-mobile-app-v2/task-3"))
    try:
        evidence_root.mkdir(parents=True, exist_ok=True)
        (evidence_root / "repositories.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        return


def run_checks() -> CheckResult:
    """Run and aggregate all repository lifecycle, privacy, and boundary checks."""
    receipts = _run_contracts()
    contracts: list[dict[str, CheckValue]] = [
        {"name": receipt.name, "assertions": receipt.assertions} for receipt in receipts
    ]
    result: CheckResult = {
        "name": "repositories",
        "assertions": sum(receipt.assertions for receipt in receipts),
        "passed": True,
        "contracts": contracts,
    }
    _write_receipt(result)
    return result


def main() -> int:
    try:
        result = run_checks()
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK
        print(json.dumps({"name": "repositories", "assertions": 0, "passed": False, "error": type(exc).__name__}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
