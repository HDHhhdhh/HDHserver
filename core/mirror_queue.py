"""Captured-byte mirror jobs; no Flask, runtime paths, or source-file reads."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MirrorJob:
    source: str
    mirror_file: Path
    snapshot_dir: Path
    stem: str
    data: bytes
    atime_ns: int
    mtime_ns: int
    mode: int
    device: int
    inode: int
    snapshots_enabled: bool
    max_keep: int
    min_sec: int

    @property
    def key(self) -> str:
        # Physical destination ownership also protects two sources sharing a name.
        return os.path.normcase(str(self.mirror_file))


@dataclass
class _Lane:
    key: str
    generation: int = 0
    pending: tuple[int, MirrorJob] | None = None
    queued: bool = False
    in_flight: bool = False
    synchronous: int = 0
    commit_lock: threading.Lock = field(default_factory=threading.Lock)


class MirrorQueue:
    def __init__(self, writer: Callable[[MirrorJob], None]) -> None:
        self._writer = writer
        self._condition = threading.Condition()
        self._lanes: dict[str, _Lane] = {}
        self._ready: deque[_Lane] = deque()
        self._thread: threading.Thread | None = None
        self._closing = False
        self._worker_starts = 0

    def _lane(self, job: MirrorJob) -> _Lane:
        return self._lanes.setdefault(job.key, _Lane(job.key))

    def _retire_idle(self, lane: _Lane) -> None:
        if lane.pending is None and not lane.queued and not lane.in_flight and not lane.synchronous:
            if self._lanes.get(lane.key) is lane:
                del self._lanes[lane.key]

    def _start_worker(self) -> None:
        if self._thread is None:
            worker = threading.Thread(target=self._run, name="json-mirror", daemon=True)
            self._thread = worker
            try:
                worker.start()
            except Exception:
                self._thread = None
                raise
            self._worker_starts += 1

    def submit(self, job: MirrorJob, *, synchronous: bool = False) -> bool:
        with self._condition:
            if self._closing:
                return False
            lane = self._lane(job)
            lane.generation += 1
            generation = lane.generation
            if synchronous:
                # A sync commit supersedes every older pending destination job.
                lane.pending = None
                lane.synchronous += 1
            else:
                lane.pending = (generation, job)
                if not lane.queued and not lane.in_flight:
                    lane.queued = True
                    self._ready.append(lane)
                self._start_worker()
                self._condition.notify_all()
                return True

        try:
            self._publish(lane, generation, job)
        finally:
            with self._condition:
                lane.synchronous -= 1
                self._retire_idle(lane)
                self._condition.notify_all()
        return True

    def _publish(self, lane: _Lane, generation: int, job: MirrorJob) -> None:
        # No file I/O holds the queue condition. Async acknowledgement can enqueue
        # a new generation while a slow destination writer owns its commit lock.
        with lane.commit_lock:
            with self._condition:
                if generation != lane.generation:
                    return
            try:
                self._writer(job)
            except Exception:
                log.exception("Mirror failed for %s", job.source)

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._ready:
                    if self._closing:
                        return
                    self._condition.wait()
                lane = self._ready.popleft()
                lane.queued = False
                pending = lane.pending
                lane.pending = None
                if pending is None:
                    self._retire_idle(lane)
                    self._condition.notify_all()
                    continue
                lane.in_flight = True
            generation, job = pending
            try:
                self._publish(lane, generation, job)
            finally:
                with self._condition:
                    lane.in_flight = False
                    # A newer async save during work replays only its latest bytes.
                    if lane.pending is not None and not lane.queued:
                        lane.queued = True
                        self._ready.append(lane)
                    self._retire_idle(lane)
                    self._condition.notify_all()

    def _unfinished(self) -> bool:
        return bool(self._ready) or any(
            lane.pending is not None or lane.in_flight or lane.synchronous
            for lane in self._lanes.values()
        )

    def drain(self, timeout_sec: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_sec)
        with self._condition:
            while self._unfinished():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def shutdown(self, timeout_sec: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_sec)
        with self._condition:
            self._closing = True
            self._condition.notify_all()
        drained = self.drain(max(0.0, deadline - time.monotonic()))
        worker = self._thread
        if worker is not None and worker is not threading.current_thread():
            worker.join(max(0.0, deadline - time.monotonic()))
        return drained and (worker is None or not worker.is_alive())

    def status(self) -> dict:
        with self._condition:
            return {
                "worker_starts": self._worker_starts,
                "daemon": bool(self._thread and self._thread.daemon),
                "queued": len(self._ready),
                "in_flight": sum(lane.in_flight for lane in self._lanes.values()),
                "lanes": len(self._lanes),
                "closing": self._closing,
            }
