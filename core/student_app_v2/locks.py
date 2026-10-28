"""Compatibility locks that recover a known dead owner without an age delay."""
import re

from core.storage import InterProcessFileLock


class RecoveryFileLock(InterProcessFileLock):
    def _try_break_stale_lock(self):
        # An empty just-created lock may belong to a live process that has not
        # written its PID yet. Keep the existing grace period in that case.
        self.stale_sec = 0 if re.search(r"\bpid=\d+", self._read_lock_text()) else 30
        super()._try_break_stale_lock()


def recovery_lock(path):
    return RecoveryFileLock(str(path) + ".lock", timeout_sec=30)
