from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import uuid
from contextlib import ExitStack, contextmanager
from typing import Any, Callable, Iterator

from core.absence_assignment_cleanup import (
    clear_absence_update_assignments_map,
    cleared_assignment_log_entry,
    collect_absence_test_carryovers_from_state,
    transition_absence_progress_tests_map,
)
from core.progress_store import load_progress_strict, save_progress_strict
from core.storage import file_lock, save_atomic


JOURNAL_VERSION = 1
PENDING_JOURNAL_NAME = "pending.json"


class AbsenceTransactionError(RuntimeError):
    pass


class AbsenceRecoveryRequiredError(AbsenceTransactionError):
    pass


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def journal_directory_for(absent_path: Any) -> pathlib.Path:
    return pathlib.Path(absent_path).resolve().parent / "instance" / "absence_transactions"


def journal_path_for(absent_path: Any, journal_dir: Any | None = None) -> pathlib.Path:
    directory = pathlib.Path(journal_dir) if journal_dir is not None else journal_directory_for(absent_path)
    return directory / PENDING_JOURNAL_NAME


def _coordinator_target(journal_dir: pathlib.Path) -> pathlib.Path:
    return journal_dir / "coordinator"


def _load_json_strict(path: Any) -> Any:
    target = pathlib.Path(path)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text("utf-8-sig"))
    except Exception as exc:
        raise AbsenceTransactionError(f"failed to read transaction store {target.name}: {exc}") from exc


def _load_object_strict(path: Any) -> dict:
    value = _load_json_strict(path)
    if not isinstance(value, dict):
        raise AbsenceTransactionError(f"transaction store must be an object: {pathlib.Path(path).name}")
    return value


def _snapshot_document(path: Any) -> dict:
    target = pathlib.Path(path)
    return {
        "exists": target.exists(),
        "value": copy.deepcopy(_load_json_strict(target)) if target.exists() else None,
    }


def _restore_document(path: Any, snapshot: dict) -> None:
    target = pathlib.Path(path)
    if not isinstance(snapshot, dict):
        raise AbsenceRecoveryRequiredError(f"invalid document snapshot: {target.name}")
    if snapshot.get("exists") is True:
        before_value = copy.deepcopy(snapshot.get("value"))
        if target.exists() and _load_json_strict(target) == before_value:
            return
        save_atomic(target, before_value)
        return
    if target.exists():
        target.unlink()


def _snapshot_dates(data: dict, pairs: set[tuple[str, str]]) -> list[dict]:
    return [
        {
            "date": date,
            "exists": date in data,
            "value": copy.deepcopy(data.get(date)),
        }
        for date in sorted({date for date, _sid in pairs})
    ]


def _restore_dates(data: dict, snapshots: list[dict]) -> dict:
    restored = dict(data)
    for item in snapshots:
        if not isinstance(item, dict):
            raise AbsenceRecoveryRequiredError("invalid date snapshot row")
        date = str(item.get("date") or "")
        if not date:
            raise AbsenceRecoveryRequiredError("invalid date snapshot key")
        if item.get("exists") is True:
            restored[date] = copy.deepcopy(item.get("value"))
        else:
            restored.pop(date, None)
    return restored


def _restore_updates_dates(path: Any, snapshots: list[dict]) -> None:
    current = _load_object_strict(path)
    restored = _restore_dates(current, snapshots)
    if restored != current:
        save_atomic(path, restored)


def _restore_progress_dates(path: Any, snapshots: list[dict]) -> None:
    current = load_progress_strict(path)
    restored = _restore_dates(current, snapshots)
    if restored != current:
        save_progress_strict(path, restored)


def _write_journal(path: pathlib.Path, journal: dict) -> None:
    journal["updatedAt"] = _utc_now()
    save_atomic(path, journal, mirror=False)


def _read_journal(path: pathlib.Path) -> dict:
    try:
        journal = json.loads(path.read_text("utf-8-sig"))
    except Exception as exc:
        raise AbsenceRecoveryRequiredError(f"absence transaction journal is unreadable: {exc}") from exc
    if not isinstance(journal, dict) or journal.get("version") != JOURNAL_VERSION:
        raise AbsenceRecoveryRequiredError("absence transaction journal version is invalid")
    return journal


def _remove_journal(path: pathlib.Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _normalize_pairs(pairs: set[tuple[str, str]]) -> set[tuple[str, str]]:
    normalized: set[tuple[str, str]] = set()
    for date_raw, sid_raw in pairs:
        date = str(date_raw or "").strip()
        sid = str(sid_raw or "").strip()
        if not date or not sid:
            raise ValueError("absence transaction pairs require date and sid")
        try:
            dt.date.fromisoformat(date)
        except ValueError as exc:
            raise ValueError(f"invalid absence transaction date: {date}") from exc
        normalized.add((date, sid))
    return normalized


def _record_phase(
    journal_path: pathlib.Path,
    journal: dict,
    phase: str,
    failure_injector: Callable[[str], None] | None,
) -> None:
    phases = journal.setdefault("appliedPhases", [])
    if phase not in phases:
        phases.append(phase)
    journal["state"] = "APPLYING"
    _write_journal(journal_path, journal)
    if failure_injector is not None:
        failure_injector(phase)


def _restore_transaction_snapshot_locked(
    *,
    snapshot: dict,
    updates_path: Any,
    progress_path: Any,
    absent_path: Any,
    carryover_path: Any,
    log_repository: Any,
    log_json_lock_held: bool,
) -> None:
    errors: list[str] = []

    def attempt(label: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")

    carryover_snapshot = snapshot.get("carryover")
    if isinstance(carryover_snapshot, dict):
        attempt("carryover", lambda: _restore_document(carryover_path, carryover_snapshot))

    absent_snapshot = snapshot.get("absent")
    attempt("absent", lambda: _restore_document(absent_path, absent_snapshot))

    log_snapshot = snapshot.get("logs")
    attempt(
        "logs",
        lambda: log_repository.restore_entries_raw(
            log_snapshot,
            json_lock_held=log_json_lock_held,
        ),
    )

    progress_dates = snapshot.get("progressDates")
    attempt(
        "progress",
        lambda: _restore_progress_dates(progress_path, progress_dates),
    )

    updates_dates = snapshot.get("updatesDates")
    attempt(
        "updates",
        lambda: _restore_updates_dates(updates_path, updates_dates),
    )

    if errors:
        raise AbsenceRecoveryRequiredError("; ".join(errors))


def apply_absence_transaction_locked(
    pairs: set[tuple[str, str]],
    *,
    absent_after: dict,
    absent_path: Any,
    carryover_path: Any,
    updates_path: Any,
    progress_path: Any,
    log_repository_factory: Callable[[], Any],
    journal_dir: Any,
    carryover_after: dict | None = None,
    kind: str = "absence",
    failure_injector: Callable[[str], None] | None = None,
) -> str:
    """Apply a new-absence cleanup while caller holds carryover and absence locks."""
    normalized_pairs = _normalize_pairs(pairs)
    if not normalized_pairs:
        raise ValueError("absence transaction requires at least one new pair")
    if not isinstance(absent_after, dict):
        raise ValueError("absence transaction requires object-shaped absent state")
    if carryover_after is not None and not isinstance(carryover_after, dict):
        raise ValueError("absence transaction carryover must be an object")

    journal_dir_path = pathlib.Path(journal_dir)
    journal_dir_path.mkdir(parents=True, exist_ok=True)
    pending_path = journal_dir_path / PENDING_JOURNAL_NAME
    if pending_path.exists():
        raise AbsenceRecoveryRequiredError("an unfinished absence transaction must be recovered first")

    repository = log_repository_factory()
    transaction_id = uuid.uuid4().hex
    journal: dict = {}
    snapshot: dict = {}

    with ExitStack() as stack:
        stack.enter_context(file_lock(updates_path, timeout_sec=8.0))
        stack.enter_context(file_lock(progress_path, timeout_sec=8.0))
        stack.enter_context(repository.mutation_lock())

        updates_before = _load_object_strict(updates_path)
        progress_before = load_progress_strict(progress_path)
        log_snapshot, effective_log_entries = repository.snapshot_entries_raw(
            normalized_pairs,
            json_lock_held=True,
        )
        test_carryovers = collect_absence_test_carryovers_from_state(
            normalized_pairs,
            progress=progress_before,
            log_entries=effective_log_entries,
        )
        updates_after, updates_changed = clear_absence_update_assignments_map(
            updates_before,
            normalized_pairs,
        )
        progress_after, progress_changed = transition_absence_progress_tests_map(
            progress_before,
            normalized_pairs,
        )

        snapshot = {
            "updatesDates": _snapshot_dates(updates_before, normalized_pairs),
            "progressDates": _snapshot_dates(progress_before, normalized_pairs),
            "logs": log_snapshot,
            "absent": _snapshot_document(absent_path),
            "carryover": _snapshot_document(carryover_path) if carryover_after is not None else None,
        }
        journal = {
            "version": JOURNAL_VERSION,
            "transactionId": transaction_id,
            "kind": str(kind or "absence"),
            "state": "PREPARED",
            "createdAt": _utc_now(),
            "updatedAt": _utc_now(),
            "pairs": [
                {"date": date, "sid": sid}
                for date, sid in sorted(normalized_pairs)
            ],
            "appliedPhases": [],
            "snapshot": snapshot,
        }
        _write_journal(pending_path, journal)

        try:
            if updates_changed:
                save_atomic(updates_path, updates_after)
            _record_phase(pending_path, journal, "updates", failure_injector)

            if progress_changed:
                save_progress_strict(progress_path, progress_after)
            _record_phase(pending_path, journal, "progress", failure_injector)

            for pair in sorted(normalized_pairs):
                carryover = test_carryovers.get(pair)
                repository.transform_entries(
                    {pair},
                    lambda entry, sid, carryover=carryover: cleared_assignment_log_entry(
                        entry,
                        sid,
                        carryover,
                    ),
                    json_lock_held=True,
                )
            _record_phase(pending_path, journal, "logs", failure_injector)

            save_atomic(absent_path, absent_after)
            _record_phase(pending_path, journal, "absent", failure_injector)

            if carryover_after is not None:
                save_atomic(carryover_path, carryover_after)
                _record_phase(pending_path, journal, "carryover", failure_injector)

            if failure_injector is not None:
                failure_injector("before_commit")
            journal["state"] = "COMMITTED"
            _write_journal(pending_path, journal)
        except Exception as original_error:
            try:
                journal["state"] = "ROLLING_BACK"
                _write_journal(pending_path, journal)
            except Exception:
                pass

            try:
                _restore_transaction_snapshot_locked(
                    snapshot=snapshot,
                    updates_path=updates_path,
                    progress_path=progress_path,
                    absent_path=absent_path,
                    carryover_path=carryover_path,
                    log_repository=repository,
                    log_json_lock_held=True,
                )
            except Exception as rollback_error:
                try:
                    journal["state"] = "RECOVERY_REQUIRED"
                    journal["recoveryError"] = f"{type(rollback_error).__name__}: {rollback_error}"
                    _write_journal(pending_path, journal)
                except Exception:
                    pass
                raise AbsenceRecoveryRequiredError(
                    f"absence transaction {transaction_id} requires recovery: {rollback_error}"
                ) from original_error

            try:
                journal["state"] = "ROLLED_BACK"
                _write_journal(pending_path, journal)
                _remove_journal(pending_path)
            except Exception:
                pass
            raise

    _remove_journal(pending_path)
    return transaction_id


def _recover_pending_under_coordinator(
    *,
    absent_path: Any,
    carryover_path: Any,
    updates_path: Any,
    progress_path: Any,
    log_repository_factory: Callable[[], Any],
    journal_dir: pathlib.Path,
    lock_timeout_sec: float,
) -> str | None:
    pending_path = journal_dir / PENDING_JOURNAL_NAME
    if not pending_path.exists():
        return None

    journal = _read_journal(pending_path)
    transaction_id = str(journal.get("transactionId") or "unknown")
    state = str(journal.get("state") or "")
    if state in {"COMMITTED", "ROLLED_BACK"}:
        _remove_journal(pending_path)
        return transaction_id

    snapshot = journal.get("snapshot")
    if not isinstance(snapshot, dict):
        raise AbsenceRecoveryRequiredError(
            f"absence transaction {transaction_id} has no valid rollback snapshot"
        )

    repository = log_repository_factory()
    with ExitStack() as stack:
        stack.enter_context(file_lock(carryover_path, timeout_sec=lock_timeout_sec))
        stack.enter_context(file_lock(absent_path, timeout_sec=lock_timeout_sec))
        stack.enter_context(file_lock(updates_path, timeout_sec=8.0))
        stack.enter_context(file_lock(progress_path, timeout_sec=8.0))
        stack.enter_context(repository.mutation_lock())

        try:
            journal["state"] = "ROLLING_BACK"
            _write_journal(pending_path, journal)
            _restore_transaction_snapshot_locked(
                snapshot=snapshot,
                updates_path=updates_path,
                progress_path=progress_path,
                absent_path=absent_path,
                carryover_path=carryover_path,
                log_repository=repository,
                log_json_lock_held=True,
            )
            journal["state"] = "ROLLED_BACK"
            journal.pop("recoveryError", None)
            _write_journal(pending_path, journal)
        except Exception as exc:
            try:
                journal["state"] = "RECOVERY_REQUIRED"
                journal["recoveryError"] = f"{type(exc).__name__}: {exc}"
                _write_journal(pending_path, journal)
            except Exception:
                pass
            raise AbsenceRecoveryRequiredError(
                f"absence transaction {transaction_id} recovery failed: {exc}"
            ) from exc

    _remove_journal(pending_path)
    return transaction_id


@contextmanager
def absence_transaction_scope(
    *,
    absent_path: Any,
    carryover_path: Any,
    updates_path: Any,
    progress_path: Any,
    log_repository_factory: Callable[[], Any],
    journal_dir: Any | None = None,
    lock_timeout_sec: float = 15.0,
) -> Iterator[pathlib.Path]:
    directory = pathlib.Path(journal_dir) if journal_dir is not None else journal_directory_for(absent_path)
    directory.mkdir(parents=True, exist_ok=True)

    with file_lock(_coordinator_target(directory), timeout_sec=lock_timeout_sec):
        _recover_pending_under_coordinator(
            absent_path=absent_path,
            carryover_path=carryover_path,
            updates_path=updates_path,
            progress_path=progress_path,
            log_repository_factory=log_repository_factory,
            journal_dir=directory,
            lock_timeout_sec=lock_timeout_sec,
        )
        with file_lock(carryover_path, timeout_sec=lock_timeout_sec):
            with file_lock(absent_path, timeout_sec=lock_timeout_sec):
                yield directory


def recover_pending_absence_transaction(
    *,
    absent_path: Any,
    carryover_path: Any,
    updates_path: Any,
    progress_path: Any,
    log_repository_factory: Callable[[], Any],
    journal_dir: Any | None = None,
    lock_timeout_sec: float = 15.0,
) -> str | None:
    directory = pathlib.Path(journal_dir) if journal_dir is not None else journal_directory_for(absent_path)
    pending_path = directory / PENDING_JOURNAL_NAME
    if not pending_path.exists():
        return None

    with file_lock(_coordinator_target(directory), timeout_sec=lock_timeout_sec):
        return _recover_pending_under_coordinator(
            absent_path=absent_path,
            carryover_path=carryover_path,
            updates_path=updates_path,
            progress_path=progress_path,
            log_repository_factory=log_repository_factory,
            journal_dir=directory,
            lock_timeout_sec=lock_timeout_sec,
        )


@contextmanager
def absence_consistency_barrier(
    *,
    absent_path: Any,
    journal_dir: Any | None = None,
    lock_timeout_sec: float = 30.0,
) -> Iterator[None]:
    directory = pathlib.Path(journal_dir) if journal_dir is not None else journal_directory_for(absent_path)
    directory.mkdir(parents=True, exist_ok=True)
    with file_lock(_coordinator_target(directory), timeout_sec=lock_timeout_sec):
        pending_path = directory / PENDING_JOURNAL_NAME
        if pending_path.exists():
            journal = _read_journal(pending_path)
            if str(journal.get("state") or "") not in {"COMMITTED", "ROLLED_BACK"}:
                raise AbsenceRecoveryRequiredError("absence transaction recovery is required")
            _remove_journal(pending_path)
        yield


__all__ = (
    "AbsenceRecoveryRequiredError",
    "AbsenceTransactionError",
    "absence_consistency_barrier",
    "absence_transaction_scope",
    "apply_absence_transaction_locked",
    "journal_directory_for",
    "journal_path_for",
    "recover_pending_absence_transaction",
)
