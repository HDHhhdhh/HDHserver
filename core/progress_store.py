from __future__ import annotations

import json
import threading
from typing import Any

from core.storage import InterProcessFileLock, file_lock, save_atomic


_CACHE_LOCK = threading.Lock()
_CACHE_SIGNATURE: tuple[str, int, int] | None = None
_CACHE_DATA: dict | None = None


def _file_signature(path: Any) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return str(path), stat.st_mtime_ns, stat.st_size


def reset_progress_cache() -> None:
    """Discard the process-local read cache without changing the progress file."""
    global _CACHE_DATA, _CACHE_SIGNATURE
    with _CACHE_LOCK:
        _CACHE_SIGNATURE = None
        _CACHE_DATA = None


def load_progress_strict(path: Any) -> dict:
    """Read an object-shaped progress store and reuse it while its signature is stable."""
    global _CACHE_DATA, _CACHE_SIGNATURE

    signature = _file_signature(path)
    with _CACHE_LOCK:
        if _CACHE_SIGNATURE == signature and _CACHE_DATA is not None:
            return _CACHE_DATA

        try:
            data = {} if signature is None else json.loads(path.read_text("utf-8-sig"))
        except Exception as exc:
            raise RuntimeError(f"progress.json read failed: {exc}") from exc

        if not isinstance(data, dict):
            raise RuntimeError("progress.json must be an object")

        _CACHE_SIGNATURE = signature
        _CACHE_DATA = data
        return data


def save_progress_strict(path: Any, data: dict) -> None:
    """Atomically save compact progress JSON and publish it to the read cache."""
    global _CACHE_DATA, _CACHE_SIGNATURE

    if not isinstance(data, dict):
        raise RuntimeError("progress.json must be an object")

    save_atomic(path, data, compact=True)
    signature = _file_signature(path)
    with _CACHE_LOCK:
        _CACHE_SIGNATURE = signature
        _CACHE_DATA = data


def progress_file_lock(path: Any) -> InterProcessFileLock:
    """Return the canonical cross-process lock for one progress store."""
    return file_lock(path, timeout_sec=30.0, poll_sec=0.05, stale_sec=30.0)


__all__ = (
    "load_progress_strict",
    "progress_file_lock",
    "reset_progress_cache",
    "save_progress_strict",
)
