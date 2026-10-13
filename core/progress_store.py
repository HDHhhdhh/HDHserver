from __future__ import annotations

from typing import Any

from core.storage import InterProcessFileLock, file_lock, save_atomic
from core.stores import get_store, invalidate_stores


def reset_progress_cache() -> None:
    """Discard the process-local read cache without changing the progress file."""
    invalidate_stores("progress")


def load_progress_strict(path: Any) -> dict:
    """Read an object-shaped progress store and reuse it while its signature is stable."""
    try:
        data, _revision = get_store("progress", path).read()
        return data
    except Exception as exc:
        raise RuntimeError(f"progress.json read failed: {exc}") from exc


def save_progress_strict(path: Any, data: dict) -> None:
    """Atomically save compact progress JSON without exposing mutable cache data."""

    if not isinstance(data, dict):
        raise RuntimeError("progress.json must be an object")

    get_store("progress", path).write_data_locked(data, writer=save_atomic)


def progress_file_lock(path: Any) -> InterProcessFileLock:
    """Return the canonical cross-process lock for one progress store."""
    return file_lock(path, timeout_sec=30.0, poll_sec=0.05, stale_sec=30.0)


__all__ = (
    "load_progress_strict",
    "progress_file_lock",
    "reset_progress_cache",
    "save_progress_strict",
)
