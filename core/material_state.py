from __future__ import annotations

import json
import logging
import os
import pathlib
import uuid
from contextlib import ExitStack, contextmanager
from typing import Any, Callable, Iterator

from core.storage import file_lock, load, save_atomic


log = logging.getLogger(__name__)

MATERIAL_STATE_JOURNAL_NAME = "material_state_transaction.json"
_STATE_KEYS = ("materials", "assignments", "pageFolders")


def material_state_journal_path(materials_path) -> pathlib.Path:
    return pathlib.Path(materials_path).parent / MATERIAL_STATE_JOURNAL_NAME


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
) -> Iterator[None]:
    """Lock every material metadata store in one deterministic order."""
    with ExitStack() as stack:
        for path in _ordered_unique_paths(
            materials_path,
            assignments_path,
            page_folders_path,
        ):
            stack.enter_context(file_lock(path))
        yield


def _journal_payload(materials: Any, assignments: Any, page_folders: Any) -> dict:
    return {
        "version": 1,
        "state": {
            "materials": materials,
            "assignments": assignments,
            "pageFolders": page_folders,
        },
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
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"material state recovery journal is unreadable: {path}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"material state recovery journal is invalid: {path}")
    state = payload.get("state")
    if (
        payload.get("version") != 1
        or not isinstance(state, dict)
        or set(state) != set(_STATE_KEYS)
    ):
        raise RuntimeError(f"material state recovery journal is invalid: {path}")
    return state["materials"], state["assignments"], state["pageFolders"]


def _clear_journal(path: pathlib.Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        # The committed journal is idempotent. Keeping it is safer than
        # reporting a failed write after all three primary stores succeeded.
        log.warning("Could not clear material state recovery journal: %s", path)


def recover_material_state_locked(
    materials_path,
    assignments_path,
    page_folders_path,
) -> bool:
    """Finish an interrupted three-file commit while the caller holds all locks."""
    journal_path = material_state_journal_path(materials_path)
    if not journal_path.exists():
        return False

    materials, assignments, page_folders = _read_journal(journal_path)
    for path, value in (
        (materials_path, materials),
        (assignments_path, assignments),
        (page_folders_path, page_folders),
    ):
        save_atomic(pathlib.Path(path), value)
    _clear_journal(journal_path)
    return True


def recover_material_state_if_needed(
    materials_path,
    assignments_path,
    page_folders_path,
) -> bool:
    """Recover only when a journal exists, avoiding locks on the normal read path."""
    journal_path = material_state_journal_path(materials_path)
    if not journal_path.exists():
        return False
    with material_state_lock(materials_path, assignments_path, page_folders_path):
        return recover_material_state_locked(
            materials_path,
            assignments_path,
            page_folders_path,
        )


def load_material_state_locked(
    materials_path,
    assignments_path,
    page_folders_path,
    *,
    _loader: Callable[[Any], Any] | None = None,
) -> tuple[Any, Any, Any]:
    recover_material_state_locked(
        materials_path,
        assignments_path,
        page_folders_path,
    )
    loader = _loader or load
    return loader(materials_path), loader(assignments_path), loader(page_folders_path)


def load_material_state(
    materials_path,
    assignments_path,
    page_folders_path,
    *,
    _loader: Callable[[Any], Any] | None = None,
) -> tuple[Any, Any, Any]:
    with material_state_lock(materials_path, assignments_path, page_folders_path):
        return load_material_state_locked(
            materials_path,
            assignments_path,
            page_folders_path,
            _loader=_loader,
        )


def save_material_state_locked(
    materials_path,
    assignments_path,
    page_folders_path,
    materials: Any,
    assignments: Any,
    page_folders: Any,
    *,
    _target_writer: Callable[[pathlib.Path, Any], None] | None = None,
) -> None:
    """Commit one recoverable snapshot while the caller holds all locks."""
    journal_path = material_state_journal_path(materials_path)
    _write_journal_atomic(
        journal_path,
        _journal_payload(materials, assignments, page_folders),
    )
    writer = _target_writer or save_atomic
    for path, value in (
        (materials_path, materials),
        (assignments_path, assignments),
        (page_folders_path, page_folders),
    ):
        writer(pathlib.Path(path), value)
    _clear_journal(journal_path)


def replace_material_state_component(
    materials_path,
    assignments_path,
    page_folders_path,
    component: str,
    value: Any,
) -> None:
    if component not in _STATE_KEYS:
        raise ValueError(f"unknown material state component: {component}")

    with material_state_lock(materials_path, assignments_path, page_folders_path):
        materials, assignments, page_folders = load_material_state_locked(
            materials_path,
            assignments_path,
            page_folders_path,
        )
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
        )
