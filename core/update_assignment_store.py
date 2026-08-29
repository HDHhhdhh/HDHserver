from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.storage import InterProcessFileLock, save_atomic


class UpdateAssignmentStoreError(RuntimeError):
    """Raised when the assignment store cannot be read or safely replaced."""


def load_updates_strict(path: Any) -> dict:
    """Load an object-shaped updates store without treating corruption as empty."""
    target = Path(path)
    try:
        data = {} if not target.exists() else json.loads(
            target.read_text(encoding="utf-8-sig")
        )
    except Exception as exc:
        raise UpdateAssignmentStoreError(
            f"updates store read failed: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise UpdateAssignmentStoreError("updates store must be an object")
    return data


def save_updates_strict(path: Any, data: dict) -> None:
    """Atomically save only an object-shaped updates document."""
    if not isinstance(data, dict):
        raise UpdateAssignmentStoreError("updates store must be an object")
    try:
        save_atomic(path, data)
    except Exception as exc:
        raise UpdateAssignmentStoreError(
            f"updates store write failed: {exc}"
        ) from exc


def updates_lock(path, *, lock_factory=InterProcessFileLock):
    lock_path = str(getattr(path, "__fspath__", lambda: str(path))()) + ".lock"
    return lock_factory(
        lock_path,
        timeout_sec=20.0,
        poll_sec=0.05,
        stale_sec=30.0,
    )


__all__ = (
    "UpdateAssignmentStoreError",
    "load_updates_strict",
    "save_updates_strict",
    "updates_lock",
)
