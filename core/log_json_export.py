"""Best-effort compatibility export from committed class-log rows."""
from __future__ import annotations

import atexit
from contextlib import closing
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Callable, Any

from core.mirror_queue import MirrorQueue
from core.storage import file_lock, save_atomic

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LogExportJob:
    logs_path: Path
    db_path: str
    date: str
    sid: str
    lock_factory: Callable[[], Any] | None

    @property
    def key(self) -> str:
        return json.dumps([os.path.normcase(str(self.logs_path)), self.date, self.sid])

    @property
    def source(self) -> str:
        return str(self.logs_path)


def _publish(job: LogExportJob) -> None:
    context = (job.lock_factory() if job.lock_factory else
               file_lock(job.logs_path, timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0))
    with context:
        # Resolve the current primary after acquiring the original log lease.
        # A delayed job must observe a newer commit or journal rollback.
        uri = Path(job.db_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
            row = connection.execute("SELECT entry_json FROM logs WHERE date=? AND sid=?",
                                     (job.date, job.sid)).fetchone()
        entry = json.loads(row[0]) if row is not None else None
        if entry is not None and not isinstance(entry, dict):
            raise ValueError("invalid SQLite log entry")
        try:
            current = json.loads(job.logs_path.read_text("utf-8-sig"))
        except FileNotFoundError:
            current = {}
        if not isinstance(current, dict):
            raise ValueError("invalid compatibility log map")
        day = current.get(job.date, {})
        if not isinstance(day, dict):
            raise ValueError("invalid compatibility log date")
        day = dict(day)
        if entry is None:
            day.pop(job.sid, None)
        else:
            day[job.sid] = entry
        if day == current.get(job.date, {}) and (day or job.date not in current):
            return
        if day:
            current[job.date] = day
        else:
            current.pop(job.date, None)
        save_atomic(job.logs_path, current, compact=True)


_queue_lock = threading.Lock()
_queue: MirrorQueue | None = None


def enqueue_log_export(logs_path, db_path: str, pairs, lock_factory=None) -> bool:
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = MirrorQueue(_publish)
        queue = _queue
    admitted = True
    for date, sid in sorted(pairs):
        try:
            job = LogExportJob(Path(os.path.abspath(os.fspath(logs_path))),
                               os.path.abspath(db_path), date, sid, lock_factory)
            if not queue.submit(job):
                log.error("Class-log export queue is closed")
                admitted = False
        except Exception:
            log.exception("Class-log export could not be queued")
            admitted = False
    return admitted


def drain_log_exports(timeout_sec: float = 5.0) -> bool:
    with _queue_lock:
        queue = _queue
    return queue is None or queue.drain(timeout_sec)


def shutdown_log_exports(timeout_sec: float = 5.0) -> bool:
    with _queue_lock:
        queue = _queue
    return queue is None or queue.shutdown(timeout_sec)


atexit.register(shutdown_log_exports)
