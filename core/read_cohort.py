"""Process-local read cohorts sharing one unchanged interprocess file lease.

Exclusive writers still use storage.file_lock, including in other processes.
Only explicitly storage-only callers may join; leases cannot be upgraded.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import threading
import time
import weakref

from core.storage import file_lock

@dataclass
class _Cohort:
    condition: threading.Condition = field(default_factory=threading.Condition)
    readers: int = 0
    started: float = 0
    lease: object = None


_registry_guard = threading.Lock()
_cohorts: weakref.WeakValueDictionary = weakref.WeakValueDictionary()


@contextmanager
def shared_file_lease(path, *, timeout_sec=30.0, validate=lambda: None):
    key = str(path)
    deadline = time.monotonic() + timeout_sec
    with _registry_guard:
        group = _cohorts.get(key)
        if group is None:
            group = _Cohort()
            _cohorts[key] = group
    # Never hold a process-wide mutex while waiting on an interprocess lease.
    with group.condition:
        while group.readers and time.monotonic() - group.started > 0.1:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("read cohort timeout")
            group.condition.wait(remaining)
        if not group.readers:
            lease = file_lock(path, timeout_sec=max(0, deadline - time.monotonic()))
            lease.__enter__()
            try:
                validate()
            except BaseException:
                lease.__exit__(None, None, None)
                raise
            group.lease = lease
            group.started = time.monotonic()
        group.readers += 1
    try:
        yield
    finally:
        with group.condition:
            group.readers -= 1
            if group.readers == 0:
                group.lease.__exit__(None, None, None)
                group.lease = None
                group.condition.notify_all()
