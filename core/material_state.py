from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import uuid
from contextlib import ExitStack, contextmanager
from typing import Any, Callable, Iterator

from core.file_material_transaction import (
    FileMaterialTransactionError,
    cleanup_staging,
    rollback_prepared,
    validate_plan,
    verify_applied,
)
from core.storage import file_lock, save_atomic
from core.stores import get_store
from core.json_store import StoreError


log = logging.getLogger(__name__)

MATERIAL_STATE_JOURNAL_NAME = "material_state_transaction.json"
MATERIAL_STATE_LAST_GOOD_NAME = "material_state_last_good.json"
_STATE_KEYS = ("materials", "assignments", "pageFolders")


class MaterialStateRecoveryRequiredError(RuntimeError):
    """Raised when material/file writes cannot safely choose a state."""


class MaterialStateConflictError(RuntimeError):
    """Raised when a whole-component writer is based on a stale snapshot."""

    def __init__(self, current_revision: str):
        super().__init__("material state changed; reload before saving")
        self.current_revision = current_revision



def material_state_journal_path(materials_path) -> pathlib.Path:
    return pathlib.Path(materials_path).parent / MATERIAL_STATE_JOURNAL_NAME


def material_state_last_good_path(materials_path) -> pathlib.Path:
    return pathlib.Path(materials_path).parent / "instance" / MATERIAL_STATE_LAST_GOOD_NAME


def _validated_state(materials: Any, assignments: Any, page_folders: Any) -> dict:
    state = {
        "materials": materials,
        "assignments": assignments,
        "pageFolders": page_folders,
    }
    invalid = [key for key, value in state.items() if not isinstance(value, dict)]
    if invalid:
        raise MaterialStateRecoveryRequiredError(
            "material state stores must be objects: " + ", ".join(invalid)
        )
    return state


def material_state_revision(materials: Any, assignments: Any, page_folders: Any) -> str:
    state = _validated_state(materials, assignments, page_folders)
    serialized = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load_store_strict(path) -> Any:
    source = pathlib.Path(path)
    try:
        return get_store("legacy", source).read_data_locked()
    except StoreError as exc:
        raise MaterialStateRecoveryRequiredError(
            f"material state store is unreadable: {source}"
        ) from exc


def _ordered_unique_paths(*paths) -> list[pathlib.Path]:
    unique: dict[str, pathlib.Path] = {}
    for value in paths:
        path = pathlib.Path(value)
        key = os.path.normcase(str(path.resolve()))
        unique.setdefault(key, path)
    return [unique[key] for key in sorted(unique)]


@contextmanager
def material_state_lock(
    materials_path,
    assignments_path,
    page_folders_path,
    *,
    files_dir=None,
) -> Iterator[None]:
    """Acquire the file-tree lock before every material metadata lock."""
    with ExitStack() as stack:
        stack.enter_context(file_lock(_files_root(materials_path, files_dir)))
        for path in _ordered_unique_paths(
            materials_path,
            assignments_path,
            page_folders_path,
        ):
            stack.enter_context(file_lock(path))
        yield


def _files_root(materials_path, files_dir=None) -> pathlib.Path:
    return pathlib.Path(files_dir) if files_dir is not None else pathlib.Path(materials_path).parent / "files"


def _journal_payload(materials: Any, assignments: Any, page_folders: Any) -> dict:
    return {
        "version": 1,
        "state": _validated_state(materials, assignments, page_folders),
    }


def _write_journal_atomic(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _read_journal(path: pathlib.Path) -> tuple[Any, Any, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaterialStateRecoveryRequiredError(
            f"material state snapshot is unreadable: {path}"
        ) from exc

    if not isinstance(payload, dict):
        raise MaterialStateRecoveryRequiredError(f"material state snapshot is invalid: {path}")
    state = payload.get("state")
    if (
        payload.get("version") != 1
        or not isinstance(state, dict)
        or set(state) != set(_STATE_KEYS)
    ):
        raise MaterialStateRecoveryRequiredError(f"material state snapshot is invalid: {path}")
    validated = _validated_state(
        state["materials"],
        state["assignments"],
        state["pageFolders"],
    )
    return validated["materials"], validated["assignments"], validated["pageFolders"]


def _clear_journal(path: pathlib.Path, *, required: bool = False) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        if required:
            raise MaterialStateRecoveryRequiredError("file/material journal could not be cleared") from exc
        log.warning("Could not clear material state recovery journal: %s", path)


def _read_transaction(materials_path, assignments_path, page_folders_path, files_dir=None) -> dict:
    path = material_state_journal_path(materials_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("transaction must be an object")
        state = payload.get("state")
        if not isinstance(state, dict) or set(state) != set(_STATE_KEYS):
            raise ValueError("invalid transaction state")
        _validated_state(state["materials"], state["assignments"], state["pageFolders"])
        if type(payload.get("version")) is not int:
            raise ValueError("invalid transaction version")
        if payload["version"] == 1:
            return payload
        if payload["version"] != 2 or payload.get("phase") not in {"prepared", "committing"}:
            raise ValueError("invalid file transaction phase")
        validate_plan(
            payload.get("fileTransaction"),
            _files_root(materials_path, files_dir),
            (materials_path, assignments_path, page_folders_path),
        )
        return payload
    except MaterialStateRecoveryRequiredError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, FileMaterialTransactionError) as exc:
        raise MaterialStateRecoveryRequiredError(f"material state transaction is unreadable or invalid: {path}") from exc


def prepare_file_material_state_locked(
    materials_path, assignments_path, page_folders_path,
    materials: dict, assignments: dict, page_folders: dict, plan: dict,
    *, files_dir=None,
) -> str:
    """Record undo intent before any live filesystem mutation, under all locks."""
    recover_material_state_locked(materials_path, assignments_path, page_folders_path, files_dir=files_dir)
    state = _validated_state(materials, assignments, page_folders)
    try:
        validate_plan(plan, _files_root(materials_path, files_dir),
                      (materials_path, assignments_path, page_folders_path))
    except FileMaterialTransactionError as exc:
        raise MaterialStateRecoveryRequiredError(str(exc)) from exc
    _write_journal_atomic(material_state_last_good_path(materials_path), _journal_payload(materials, assignments, page_folders))
    payload = {"version": 2, "phase": "prepared", "state": state, "fileTransaction": plan}
    _write_journal_atomic(material_state_journal_path(materials_path), payload)
    return plan["id"]


def update_prepared_file_material_state_locked(
    materials_path, assignments_path, page_folders_path, plan: dict, *, files_dir=None,
) -> None:
    payload = _read_transaction(materials_path, assignments_path, page_folders_path, files_dir)
    if payload.get("phase") != "prepared" or payload["fileTransaction"]["id"] != plan["id"]:
        raise MaterialStateRecoveryRequiredError("file transaction is no longer prepared")
    try:
        validate_plan(plan, _files_root(materials_path, files_dir),
                      (materials_path, assignments_path, page_folders_path))
    except FileMaterialTransactionError as exc:
        raise MaterialStateRecoveryRequiredError(str(exc)) from exc
    payload["fileTransaction"] = plan
    _write_journal_atomic(material_state_journal_path(materials_path), payload)


def rollback_file_material_state_if_prepared_locked(
    materials_path, assignments_path, page_folders_path, transaction_id: str, *, files_dir=None,
) -> bool:
    journal_path = material_state_journal_path(materials_path)
    if not journal_path.exists():
        return False
    payload = _read_transaction(materials_path, assignments_path, page_folders_path, files_dir)
    if payload.get("phase") != "prepared" or payload["fileTransaction"]["id"] != transaction_id:
        return False
    return recover_material_state_locked(materials_path, assignments_path, page_folders_path, files_dir=files_dir)


def recover_material_state_locked(
    materials_path, assignments_path, page_folders_path, *, files_dir=None,
) -> bool:
    """Undo a prepared filesystem intent or finish an interrupted metadata commit."""
    journal_path = material_state_journal_path(materials_path)
    if not journal_path.exists():
        return False

    payload = _read_transaction(materials_path, assignments_path, page_folders_path, files_dir)
    plan = payload.get("fileTransaction") if payload["version"] == 2 else None
    try:
        if plan is not None and payload["phase"] == "prepared":
            rollback_prepared(plan)
            _clear_journal(journal_path, required=True)
            return True
        if plan is not None:
            verify_applied(plan)
        state = payload["state"]
        for path, key in ((materials_path, "materials"), (assignments_path, "assignments"),
                          (page_folders_path, "pageFolders")):
            get_store(key, path).write_data_locked(state[key], writer=save_atomic)
        _write_journal_atomic(material_state_last_good_path(materials_path),
                              _journal_payload(state["materials"], state["assignments"], state["pageFolders"]))
        if plan is not None:
            cleanup_staging(plan)
        _clear_journal(journal_path, required=plan is not None)
    except (OSError, FileMaterialTransactionError) as exc:
        raise MaterialStateRecoveryRequiredError("file/material transaction recovery is incomplete") from exc
    return True


def recover_material_state_if_needed(
    materials_path, assignments_path, page_folders_path, *, files_dir=None,
) -> bool:
    """Recover the shared filesystem/metadata journal at startup or read boundaries."""
    if not material_state_journal_path(materials_path).exists():
        return False
    with material_state_lock(materials_path, assignments_path, page_folders_path, files_dir=files_dir):
        return recover_material_state_locked(materials_path, assignments_path, page_folders_path, files_dir=files_dir)


def load_material_state_last_good(materials_path) -> tuple[dict, dict, dict]:
    """Return the last committed snapshot for read-only degraded operation."""
    return _read_journal(material_state_last_good_path(materials_path))



def load_material_state_locked(
    materials_path,
    assignments_path,
    page_folders_path,
    *,
    _loader: Callable[[Any], Any] | None = None,
    files_dir=None,
) -> tuple[Any, Any, Any]:
    recover_material_state_locked(
        materials_path,
        assignments_path,
        page_folders_path,
        files_dir=files_dir,
    )
    loader = _loader or _load_store_strict
    state = _validated_state(
        loader(materials_path),
        loader(assignments_path),
        loader(page_folders_path),
    )
    return state["materials"], state["assignments"], state["pageFolders"]


def load_material_state(
    materials_path,
    assignments_path,
    page_folders_path,
    *,
    _loader: Callable[[Any], Any] | None = None,
    files_dir=None,
) -> tuple[Any, Any, Any]:
    with material_state_lock(materials_path, assignments_path, page_folders_path, files_dir=files_dir):
        return load_material_state_locked(
            materials_path,
            assignments_path,
            page_folders_path,
            _loader=_loader,
            files_dir=files_dir,
        )


def save_material_state_locked(
    materials_path, assignments_path, page_folders_path,
    materials: Any, assignments: Any, page_folders: Any,
    *,
    _target_writer: Callable[[pathlib.Path, Any], None] | None = None,
    file_transaction_id: str | None = None,
    files_dir=None,
) -> None:
    """Begin forward recovery only after the filesystem plan is fully applied."""
    next_state = _validated_state(materials, assignments, page_folders)
    journal_path = material_state_journal_path(materials_path)
    last_good_path = material_state_last_good_path(materials_path)
    plan = None
    if file_transaction_id is not None:
        payload = _read_transaction(materials_path, assignments_path, page_folders_path, files_dir)
        if payload.get("phase") != "prepared" or payload["fileTransaction"]["id"] != file_transaction_id:
            raise MaterialStateRecoveryRequiredError("file transaction is no longer prepared")
        plan = payload["fileTransaction"]
        _validated_state(
            _load_store_strict(materials_path),
            _load_store_strict(assignments_path),
            _load_store_strict(page_folders_path),
        )
        try:
            verify_applied(plan)
        except (OSError, FileMaterialTransactionError) as exc:
            raise MaterialStateRecoveryRequiredError("file transaction is not fully applied") from exc
        payload["phase"] = "committing"
        payload["state"] = next_state
    else:
        recover_material_state_locked(materials_path, assignments_path, page_folders_path, files_dir=files_dir)
        current_state = _validated_state(
            _load_store_strict(materials_path), _load_store_strict(assignments_path), _load_store_strict(page_folders_path),
        )
        _write_journal_atomic(last_good_path, _journal_payload(
            current_state["materials"], current_state["assignments"], current_state["pageFolders"],
        ))
        payload = _journal_payload(materials, assignments, page_folders)
    _write_journal_atomic(journal_path, payload)
    writer = _target_writer or save_atomic
    for path, key in ((materials_path, "materials"), (assignments_path, "assignments"),
                      (page_folders_path, "pageFolders")):
        writer(pathlib.Path(path), next_state[key])
    _write_journal_atomic(last_good_path, _journal_payload(materials, assignments, page_folders))
    if plan is not None:
        try:
            cleanup_staging(plan)
        except OSError as exc:
            raise MaterialStateRecoveryRequiredError("committed file transaction cleanup is incomplete") from exc
    _clear_journal(journal_path, required=plan is not None)


def replace_material_state_component(
    materials_path,
    assignments_path,
    page_folders_path,
    component: str,
    value: Any,
    *,
    expected_revision: str | None = None,
    files_dir=None,
) -> str:
    if component not in _STATE_KEYS:
        raise ValueError(f"unknown material state component: {component}")
    if not isinstance(value, dict):
        raise ValueError("material state component must be an object")

    with material_state_lock(materials_path, assignments_path, page_folders_path, files_dir=files_dir):
        materials, assignments, page_folders = load_material_state_locked(
            materials_path,
            assignments_path,
            page_folders_path,
            files_dir=files_dir,
        )
        current_revision = material_state_revision(materials, assignments, page_folders)
        if expected_revision is not None and expected_revision != current_revision:
            raise MaterialStateConflictError(current_revision)

        state = {
            "materials": materials,
            "assignments": assignments,
            "pageFolders": page_folders,
        }
        state[component] = value
        save_material_state_locked(
            materials_path,
            assignments_path,
            page_folders_path,
            state["materials"],
            state["assignments"],
            state["pageFolders"],
            files_dir=files_dir,
        )
        return material_state_revision(state["materials"], state["assignments"], state["pageFolders"])
