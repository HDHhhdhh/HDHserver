from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class FileLockBusy(RuntimeError):
    def __init__(self, lock_path: Path) -> None:
        super().__init__(display_path(lock_path))
        self.lock_path = lock_path

    def __str__(self) -> str:
        return f"provider-free handoff refresh already running: {display_path(self.lock_path)}"


@contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise FileLockBusy(lock_path) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\n")
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"
