from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import uuid
from contextlib import ExitStack, contextmanager
from typing import Any, Callable, Iterator

from core.storage import file_lock, save_atomic


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
        return json.loads(source.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
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
    _write_journal_atomic(
        material_state_last_good_path(materials_path),
        _journal_payload(materials, assignments, page_folders),
    )
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

def load_material_state_last_good(materials_path) -> tuple[dict, dict, dict]:
    """Return the last committed snapshot for read-only degraded operation."""
    return _read_journal(material_state_last_good_path(materials_path))



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
    next_state = _validated_state(materials, assignments, page_folders)
    recover_material_state_locked(
        materials_path,
        assignments_path,
        page_folders_path,
    )
    current_state = _validated_state(
        _load_store_strict(materials_path),
        _load_store_strict(assignments_path),
        _load_store_strict(page_folders_path),
    )
    journal_path = material_state_journal_path(materials_path)
    last_good_path = material_state_last_good_path(materials_path)
    _write_journal_atomic(
        last_good_path,
        _journal_payload(
            current_state["materials"],
            current_state["assignments"],
            current_state["pageFolders"],
        ),
    )
    _write_journal_atomic(
        journal_path,
        _journal_payload(
            next_state["materials"],
            next_state["assignments"],
            next_state["pageFolders"],
        ),
    )
    writer = _target_writer or save_atomic
    for path, value in (
        (materials_path, next_state["materials"]),
        (assignments_path, next_state["assignments"]),
        (page_folders_path, next_state["pageFolders"]),
    ):
        writer(pathlib.Path(path), value)
    _write_journal_atomic(
        last_good_path,
        _journal_payload(
            next_state["materials"],
            next_state["assignments"],
            next_state["pageFolders"],
        ),
    )
    _clear_journal(journal_path)


def replace_material_state_component(
    materials_path,
    assignments_path,
    page_folders_path,
    component: str,
    value: Any,
    *,
    expected_revision: str | None = None,
) -> str:
    if component not in _STATE_KEYS:
        raise ValueError(f"unknown material state component: {component}")
    if not isinstance(value, dict):
        raise ValueError("material state component must be an object")

    with material_state_lock(materials_path, assignments_path, page_folders_path):
        materials, assignments, page_folders = load_material_state_locked(
            materials_path,
            assignments_path,
            page_folders_path,
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
        )
        return material_state_revision(state["materials"], state["assignments"], state["pageFolders"])
