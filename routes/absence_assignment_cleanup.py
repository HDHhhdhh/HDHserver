from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator

from core.absence_assignment_cleanup import (
    clear_assignments_for_new_absences as _clear_assignments_for_new_absences,
)
from core.absence_transaction import (
    AbsenceRecoveryRequiredError,
    absence_consistency_barrier,
    absence_transaction_scope,
    apply_absence_transaction_locked,
    recover_pending_absence_transaction,
)
from core.paths import ABS_PATH, BASE, PRG_PATH, UPD_PATH


MAKEUP_CARRYOVER_PATH = BASE / "makeup_carryover.json"


def _repository_factory(factory: Callable[[], Any] | None) -> Callable[[], Any]:
    if factory is not None:
        return factory
    from routes.api_basic import get_log_repository

    return get_log_repository


def clear_assignments_for_new_absences(
    pairs: set[tuple[str, str]],
    *,
    updates_path: Any = UPD_PATH,
    progress_path: Any = PRG_PATH,
    log_repository_factory: Callable[[], Any] | None = None,
) -> None:
    """Compatibility entry point for callers that do not own absence state."""
    _clear_assignments_for_new_absences(
        pairs,
        updates_path=updates_path,
        progress_path=progress_path,
        log_repository_factory=_repository_factory(log_repository_factory),
    )


@contextmanager
def absence_write_scope(
    *,
    absent_path: Any = ABS_PATH,
    carryover_path: Any = MAKEUP_CARRYOVER_PATH,
    updates_path: Any = UPD_PATH,
    progress_path: Any = PRG_PATH,
    log_repository_factory: Callable[[], Any] | None = None,
    journal_dir: Any | None = None,
    lock_timeout_sec: float = 15.0,
) -> Iterator[Any]:
    with absence_transaction_scope(
        absent_path=absent_path,
        carryover_path=carryover_path,
        updates_path=updates_path,
        progress_path=progress_path,
        log_repository_factory=_repository_factory(log_repository_factory),
        journal_dir=journal_dir,
        lock_timeout_sec=lock_timeout_sec,
    ) as active_journal_dir:
        yield active_journal_dir


def commit_new_absences_locked(
    pairs: set[tuple[str, str]],
    *,
    absent_after: dict,
    absent_path: Any = ABS_PATH,
    carryover_path: Any = MAKEUP_CARRYOVER_PATH,
    updates_path: Any = UPD_PATH,
    progress_path: Any = PRG_PATH,
    log_repository_factory: Callable[[], Any] | None = None,
    journal_dir: Any,
    carryover_after: dict | None = None,
    kind: str = "absence",
    failure_injector: Callable[[str], None] | None = None,
) -> str:
    return apply_absence_transaction_locked(
        pairs,
        absent_after=absent_after,
        carryover_after=carryover_after,
        absent_path=absent_path,
        carryover_path=carryover_path,
        updates_path=updates_path,
        progress_path=progress_path,
        log_repository_factory=_repository_factory(log_repository_factory),
        journal_dir=journal_dir,
        kind=kind,
        failure_injector=failure_injector,
    )


def recover_pending_absence_transactions(
    *,
    absent_path: Any = ABS_PATH,
    carryover_path: Any = MAKEUP_CARRYOVER_PATH,
    updates_path: Any = UPD_PATH,
    progress_path: Any = PRG_PATH,
    log_repository_factory: Callable[[], Any] | None = None,
    journal_dir: Any | None = None,
    lock_timeout_sec: float = 15.0,
) -> str | None:
    return recover_pending_absence_transaction(
        absent_path=absent_path,
        carryover_path=carryover_path,
        updates_path=updates_path,
        progress_path=progress_path,
        log_repository_factory=_repository_factory(log_repository_factory),
        journal_dir=journal_dir,
        lock_timeout_sec=lock_timeout_sec,
    )


@contextmanager
def absence_read_barrier(
    *,
    absent_path: Any = ABS_PATH,
    journal_dir: Any | None = None,
    lock_timeout_sec: float = 30.0,
) -> Iterator[None]:
    with absence_consistency_barrier(
        absent_path=absent_path,
        journal_dir=journal_dir,
        lock_timeout_sec=lock_timeout_sec,
    ):
        yield


__all__ = (
    "AbsenceRecoveryRequiredError",
    "absence_read_barrier",
    "absence_write_scope",
    "clear_assignments_for_new_absences",
    "commit_new_absences_locked",
    "recover_pending_absence_transactions",
)
