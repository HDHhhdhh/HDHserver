"""Recoverable persistence for the person directory and active student roster."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import logging
import os
import pathlib
import secrets
import uuid
from contextlib import ExitStack, contextmanager
from typing import Any, Callable, Iterator

from core.person_identity import (
    PersonIdentityConflictError,
    PersonIdentityNotFoundError,
    PersonIdentityValidationError,
    add_student_to_identity_state,
    allocate_unique_sid,
    new_person_id,
    normalized_text,
    retire_student_from_identity_state,
    update_person_profile_in_state,
    validate_identity_state,
)
from core.storage import file_lock, save_atomic


log = logging.getLogger(__name__)
JOURNAL_VERSION = 1


class PersonIdentityUnavailableError(RuntimeError):
    """Raised when identity-backed writes must stop instead of falling back."""


class PersonIdentityRecoveryRequiredError(PersonIdentityUnavailableError):
    """Raised when an interrupted identity transaction cannot be recovered."""


def utc_now_isoz() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Any) -> str:
    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity_is_configured(
    persons_path: Any,
    journal_path: Any,
    students_path: Any | None = None,
) -> bool:
    """Detect configured or partially lost identity state without falling back."""

    if pathlib.Path(persons_path).exists() or pathlib.Path(journal_path).exists():
        return True
    if students_path is None:
        return False
    try:
        students = json.loads(pathlib.Path(students_path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError, json.JSONDecodeError):
        # An unreadable roster must not be treated as a safe legacy install.
        return True
    if not isinstance(students, list):
        return True
    return any(
        isinstance(row, dict) and bool(normalized_text(row.get("personId")))
        for row in students
    )


def _load_json_strict(path: Any) -> Any:
    source = pathlib.Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PersonIdentityRecoveryRequiredError(
            f"identity store is unreadable: {source}"
        ) from exc


def load_identity_state_strict(persons_path: Any, students_path: Any) -> tuple[dict, list]:
    try:
        directory = _load_json_strict(persons_path)
    except FileNotFoundError as exc:
        raise PersonIdentityUnavailableError("person directory is not initialized") from exc
    try:
        students = _load_json_strict(students_path)
    except FileNotFoundError as exc:
        raise PersonIdentityRecoveryRequiredError("students store is missing") from exc
    try:
        validate_identity_state(directory, students)
    except PersonIdentityValidationError as exc:
        raise PersonIdentityRecoveryRequiredError(str(exc)) from exc
    return directory, students


def _coordinator_target(journal_path: pathlib.Path) -> pathlib.Path:
    return journal_path.parent / "coordinator"


def _ordered_unique_paths(*paths: Any) -> list[pathlib.Path]:
    unique: dict[str, pathlib.Path] = {}
    for value in paths:
        path = pathlib.Path(value)
        unique.setdefault(os.path.normcase(str(path.resolve())), path)
    return [unique[key] for key in sorted(unique)]


@contextmanager
def identity_state_lock(
    persons_path: Any,
    students_path: Any,
    journal_path: Any,
) -> Iterator[None]:
    journal = pathlib.Path(journal_path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(_coordinator_target(journal)):
        with ExitStack() as stack:
            for path in _ordered_unique_paths(persons_path, students_path):
                stack.enter_context(file_lock(path))
            yield


def _write_journal(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updatedAt"] = utc_now_isoz()
    save_atomic(path, payload, compact=True, mirror=False)


def _read_journal(path: pathlib.Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PersonIdentityRecoveryRequiredError(
            f"identity transaction journal is unreadable: {path}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("version") != JOURNAL_VERSION:
        raise PersonIdentityRecoveryRequiredError("identity transaction journal is invalid")
    before = payload.get("before")
    after = payload.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise PersonIdentityRecoveryRequiredError("identity transaction snapshots are invalid")
    if not isinstance(before.get("students"), list):
        raise PersonIdentityRecoveryRequiredError("identity before-students snapshot is invalid")
    if before.get("personsExists") is True and not isinstance(before.get("persons"), dict):
        raise PersonIdentityRecoveryRequiredError("identity before-persons snapshot is invalid")
    if not isinstance(after.get("persons"), dict) or not isinstance(after.get("students"), list):
        raise PersonIdentityRecoveryRequiredError("identity after-state snapshot is invalid")
    return payload


def _clear_journal(path: pathlib.Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.warning("Could not clear committed person identity journal: %s", exc)


def _write_after_state(
    persons_path: pathlib.Path,
    students_path: pathlib.Path,
    snapshot: dict,
    *,
    failure_injector: Callable[[str], None] | None = None,
) -> None:
    save_atomic(persons_path, snapshot["persons"])
    if failure_injector is not None:
        failure_injector("after_persons")
    save_atomic(students_path, snapshot["students"])
    if failure_injector is not None:
        failure_injector("after_students")
    persisted_directory = _load_json_strict(persons_path)
    persisted_students = _load_json_strict(students_path)
    validate_identity_state(persisted_directory, persisted_students)


def _restore_before_state(
    persons_path: pathlib.Path,
    students_path: pathlib.Path,
    snapshot: dict,
) -> None:
    save_atomic(students_path, snapshot["students"])
    if snapshot.get("personsExists") is True:
        save_atomic(persons_path, snapshot["persons"])
        validate_identity_state(snapshot["persons"], snapshot["students"])
    else:
        try:
            persons_path.unlink()
        except FileNotFoundError:
            pass


def _commit_identity_state_locked(
    persons_path: pathlib.Path,
    students_path: pathlib.Path,
    journal_path: pathlib.Path,
    before: dict,
    next_directory: dict,
    next_students: list,
    *,
    failure_injector: Callable[[str], None] | None = None,
) -> None:
    validate_identity_state(next_directory, next_students)
    journal = {
        "version": JOURNAL_VERSION,
        "transactionId": uuid.uuid4().hex,
        "state": "PREPARED",
        "createdAt": utc_now_isoz(),
        "before": copy.deepcopy(before),
        "after": {
            "persons": copy.deepcopy(next_directory),
            "students": copy.deepcopy(next_students),
        },
    }
    _write_journal(journal_path, journal)
    try:
        journal["state"] = "APPLYING"
        _write_journal(journal_path, journal)
        _write_after_state(
            persons_path,
            students_path,
            journal["after"],
            failure_injector=failure_injector,
        )
        if failure_injector is not None:
            failure_injector("before_commit")
        journal["state"] = "COMMITTED"
        _write_journal(journal_path, journal)
    except Exception as original_error:
        try:
            journal["state"] = "ROLLING_BACK"
            journal["error"] = f"{type(original_error).__name__}: {original_error}"
            _write_journal(journal_path, journal)
            _restore_before_state(persons_path, students_path, journal["before"])
            journal["state"] = "ROLLED_BACK"
            _write_journal(journal_path, journal)
            _clear_journal(journal_path)
        except Exception as rollback_error:
            journal["state"] = "RECOVERY_REQUIRED"
            journal["recoveryError"] = f"{type(rollback_error).__name__}: {rollback_error}"
            try:
                _write_journal(journal_path, journal)
            except Exception:
                pass
            raise PersonIdentityRecoveryRequiredError(
                f"identity write failed and rollback failed: {rollback_error}"
            ) from original_error
        raise
    _clear_journal(journal_path)


def _recover_identity_state_locked(
    persons_path: pathlib.Path,
    students_path: pathlib.Path,
    journal_path: pathlib.Path,
) -> bool:
    if not journal_path.exists():
        return False
    journal = _read_journal(journal_path)
    state = normalized_text(journal.get("state"))
    try:
        if state == "COMMITTED":
            _write_after_state(persons_path, students_path, journal["after"])
        elif state == "ROLLED_BACK":
            pass
        else:
            journal["state"] = "ROLLING_BACK"
            _write_journal(journal_path, journal)
            _restore_before_state(persons_path, students_path, journal["before"])
            journal["state"] = "ROLLED_BACK"
            _write_journal(journal_path, journal)
    except Exception as exc:
        journal["state"] = "RECOVERY_REQUIRED"
        journal["recoveryError"] = f"{type(exc).__name__}: {exc}"
        try:
            _write_journal(journal_path, journal)
        except Exception:
            pass
        raise PersonIdentityRecoveryRequiredError(
            f"person identity recovery failed: {exc}"
        ) from exc
    _clear_journal(journal_path)
    return True


def recover_identity_state_if_needed(
    persons_path: Any,
    students_path: Any,
    journal_path: Any,
) -> bool:
    pending = pathlib.Path(journal_path)
    if not pending.exists():
        return False
    with identity_state_lock(persons_path, students_path, pending):
        return _recover_identity_state_locked(
            pathlib.Path(persons_path),
            pathlib.Path(students_path),
            pending,
        )


def initialize_identity_state(
    persons_path: Any,
    students_path: Any,
    journal_path: Any,
    directory: dict,
    students: list,
    *,
    expected_students_sha256: str,
    require_persons_absent: bool = True,
    failure_injector: Callable[[str], None] | None = None,
) -> None:
    persons_file = pathlib.Path(persons_path)
    students_file = pathlib.Path(students_path)
    pending = pathlib.Path(journal_path)
    validate_identity_state(directory, students)
    with identity_state_lock(persons_file, students_file, pending):
        _recover_identity_state_locked(persons_file, students_file, pending)
        if require_persons_absent and persons_file.exists():
            raise PersonIdentityConflictError("person directory already exists")
        if sha256_file(students_file) != normalized_text(expected_students_sha256).lower():
            raise PersonIdentityConflictError("students store changed after the migration plan")
        current_students = _load_json_strict(students_file)
        if not isinstance(current_students, list):
            raise PersonIdentityRecoveryRequiredError("students store must be an array")
        before = {
            "personsExists": persons_file.exists(),
            "persons": _load_json_strict(persons_file) if persons_file.exists() else None,
            "students": current_students,
        }
        _commit_identity_state_locked(
            persons_file,
            students_file,
            pending,
            before,
            directory,
            students,
            failure_injector=failure_injector,
        )


def mutate_identity_state(
    persons_path: Any,
    students_path: Any,
    journal_path: Any,
    mutator: Callable[[dict, list], tuple[dict, list, Any]],
    *,
    failure_injector: Callable[[str], None] | None = None,
) -> Any:
    persons_file = pathlib.Path(persons_path)
    students_file = pathlib.Path(students_path)
    pending = pathlib.Path(journal_path)
    with identity_state_lock(persons_file, students_file, pending):
        _recover_identity_state_locked(persons_file, students_file, pending)
        directory, students = load_identity_state_strict(persons_file, students_file)
        next_directory, next_students, result = mutator(directory, students)
        before = {
            "personsExists": True,
            "persons": directory,
            "students": students,
        }
        _commit_identity_state_locked(
            persons_file,
            students_file,
            pending,
            before,
            next_directory,
            next_students,
            failure_injector=failure_injector,
        )
        return result


def create_student_with_identity(
    persons_path: Any,
    students_path: Any,
    journal_path: Any,
    student: dict,
    *,
    sid_prefix: str,
    clone_from_sid: str = "",
    suffix_factory: Callable[[], int] | None = None,
    id_factory: Callable[[], str] = new_person_id,
    now: str | None = None,
) -> dict:
    timestamp = now or utc_now_isoz()
    next_suffix = suffix_factory or (lambda: secrets.randbelow(1000))

    def mutation(directory: dict, students: list) -> tuple[dict, list, dict]:
        existing_sids = [normalized_text(row.get("id")) for row in students if isinstance(row, dict)]
        sid = allocate_unique_sid(sid_prefix, existing_sids, suffix_factory=next_suffix)
        draft = copy.deepcopy(student)
        draft.pop("id", None)
        draft.pop("personId", None)
        draft.pop("cloneFromSid", None)
        draft["id"] = sid

        requested_person_id = ""
        source_sid = normalized_text(clone_from_sid)
        if source_sid:
            source = next(
                (row for row in students if normalized_text(row.get("id")) == source_sid),
                None,
            )
            if not isinstance(source, dict):
                raise PersonIdentityNotFoundError("clone source SID was not found")
            requested_person_id = normalized_text(source.get("personId"))
            if not requested_person_id:
                raise PersonIdentityValidationError("clone source has no personId")

        return add_student_to_identity_state(
            directory,
            students,
            draft,
            now=timestamp,
            person_id=requested_person_id,
            id_factory=id_factory,
        )

    return mutate_identity_state(persons_path, students_path, journal_path, mutation)


def update_person_profile_field(
    persons_path: Any,
    students_path: Any,
    journal_path: Any,
    sid: str,
    field: str,
    value: Any,
    *,
    now: str | None = None,
) -> tuple[str, ...]:
    timestamp = now or utc_now_isoz()

    def mutation(directory: dict, students: list) -> tuple[dict, list, tuple[str, ...]]:
        return update_person_profile_in_state(
            directory,
            students,
            sid,
            field,
            value,
            now=timestamp,
        )

    return mutate_identity_state(persons_path, students_path, journal_path, mutation)


def retire_student_identity(
    persons_path: Any,
    students_path: Any,
    journal_path: Any,
    sid: str,
    *,
    now: str | None = None,
) -> dict:
    timestamp = now or utc_now_isoz()

    def mutation(directory: dict, students: list) -> tuple[dict, list, dict]:
        return retire_student_from_identity_state(
            directory,
            students,
            sid,
            now=timestamp,
        )

    return mutate_identity_state(persons_path, students_path, journal_path, mutation)


__all__ = [
    "PersonIdentityRecoveryRequiredError",
    "PersonIdentityUnavailableError",
    "create_student_with_identity",
    "identity_is_configured",
    "identity_state_lock",
    "initialize_identity_state",
    "load_identity_state_strict",
    "mutate_identity_state",
    "recover_identity_state_if_needed",
    "retire_student_identity",
    "sha256_file",
    "update_person_profile_field",
    "utc_now_isoz",
]
