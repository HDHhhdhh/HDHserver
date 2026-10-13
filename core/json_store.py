"""Single-file JSON transport; coordinators retain transaction ownership.

Construction performs no I/O. Missing reads use the supplied factory without
creating a file. Callers choose missing-store policy and domain validation.
Recovery and same-signature manual repairs must explicitly invalidate caches.
"""
from __future__ import annotations

from collections.abc import Callable
import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
from typing import Any

from core.storage import file_lock, save_atomic
from core.json_revision import json_revision


class StoreError(RuntimeError):
    pass


class StoreBusy(StoreError):
    pass


class StoreCorrupt(StoreError):
    pass


class RevisionConflict(StoreError):
    def __init__(self, current_revision: str) -> None:
        self.current_revision = current_revision
        super().__init__("JSON store revision changed")


Signature = tuple[int, int, int, int] | None


semantic_revision = json_revision


@dataclass(frozen=True)
class _Snapshot:
    signature: Signature
    data: Any
    revision: str


class JsonStore:
    def __init__(
        self,
        path,
        default_factory: Callable[[], Any],
        validate: Callable[[Any], Any] | None = None,
        compact: bool = False,
        *,
        mirror: bool = True,
    ) -> None:
        if not callable(default_factory):
            raise TypeError("default_factory must be callable")
        if validate is not None and not callable(validate):
            raise TypeError("validate must be callable")
        if type(compact) is not bool or type(mirror) is not bool:
            raise TypeError("compact and mirror must be booleans")
        self._path = Path(os.path.abspath(path))
        self._default_factory = default_factory
        self._validator = validate
        self._compact = compact
        self._mirror = mirror
        self._cache: _Snapshot | None = None
        self._cache_lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def invalidate(self) -> None:
        """Discard cached state after recovery or an externally managed write."""
        with self._cache_lock:
            self._cache = None

    def _signature(self) -> Signature:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StoreCorrupt(f"JSON store stat failed: {self.path}") from exc
        return (
            int(stat.st_mtime_ns),
            int(getattr(stat, "st_ctime_ns", 0)),
            int(stat.st_size),
            int(getattr(stat, "st_ino", 0)),
        )

    def _validate(self, candidate: Any) -> None:
        if self._validator is dict or self._validator is list:
            if not isinstance(candidate, self._validator):
                raise ValueError("JSON store root has the wrong type")
            return
        if self._validator is not None:
            # Validators cannot mutate either the caller's input or the cache.
            if self._validator(copy.deepcopy(candidate)) is False:
                raise ValueError("JSON store validator rejected the value")

    def _prepare(self, data: Any) -> tuple[Any, str]:
        candidate = copy.deepcopy(data)
        self._validate(candidate)
        try:
            revision = semantic_revision(candidate)
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("JSON store value is not serializable") from exc
        return candidate, revision

    def _read_value(self) -> tuple[Signature, Any]:
        for _attempt in range(3):
            before = self._signature()
            try:
                raw = self.path.read_bytes()
            except FileNotFoundError:
                raw = None
            except OSError as exc:
                raise StoreCorrupt(f"JSON store read failed: {self.path}") from exc
            after = self._signature()
            if before != after or (raw is None) != (after is None):
                continue
            try:
                data = copy.deepcopy(self._default_factory()) if raw is None else json.loads(raw.decode("utf-8-sig"))
                self._validate(data)
                if raw is None:
                    semantic_revision(data)
            except Exception as exc:
                raise StoreCorrupt(f"JSON store is unreadable or invalid: {self.path}") from exc
            return after, data
        raise StoreBusy(f"JSON store changed during every read attempt: {self.path}")

    def _read_snapshot(self) -> _Snapshot:
        signature, data = self._read_value()
        try:
            revision = semantic_revision(data)
        except (TypeError, ValueError, UnicodeError) as exc:
            raise StoreCorrupt(f"JSON store cannot produce a revision: {self.path}") from exc
        return _Snapshot(signature, data, revision)

    def _cached_snapshot(self) -> _Snapshot:
        with self._cache_lock:
            try:
                signature = self._signature()
            except StoreError:
                self._cache = None
                raise
            if self._cache is not None and self._cache.signature == signature:
                return self._cache
            self._cache = None
            snapshot = self._read_snapshot()
            self._cache = snapshot
            return snapshot

    def read(self) -> tuple[Any, str]:
        """Read a coherent snapshot and return a defensive copy."""
        snapshot = self._cached_snapshot()
        return copy.deepcopy(snapshot.data), snapshot.revision

    def revision(self) -> str:
        """Reuse a stable cached revision without copying the whole payload."""
        return self._cached_snapshot().revision

    def read_nested(self, *, outer_keys=None, inner_keys=None, min_key=None):
        """Copy only selected branches of an object, without exposing the cache."""
        snapshot = self._cached_snapshot()
        if not isinstance(snapshot.data, dict):
            raise StoreCorrupt(f"JSON store root is not an object: {self.path}")
        outer = snapshot.data.keys() if outer_keys is None else outer_keys
        selected = {}
        for key in outer:
            if key not in snapshot.data or (min_key is not None and str(key) < min_key):
                continue
            value = snapshot.data[key]
            if inner_keys is not None:
                if not isinstance(value, dict):
                    continue
                value = {inner: value[inner] for inner in inner_keys if inner in value}
            selected[key] = value
        return copy.deepcopy(selected)

    def read_locked(self) -> tuple[Any, str]:
        """Read fresh under the caller's native lease; never acquire a lease."""
        with self._cache_lock:
            self._cache = None
            snapshot = self._read_snapshot()
            self._cache = snapshot
            return copy.deepcopy(snapshot.data), snapshot.revision

    def read_data_locked(self) -> Any:
        """Read fresh private data when the caller does not need a revision."""
        with self._cache_lock:
            self._cache = None
            _signature, data = self._read_value()
            return data

    def write_data_locked(self, data: Any, *, compact=None, mirror=None, writer=None) -> None:
        """Validate and save under the caller's lease without unused hashing."""
        candidate = copy.deepcopy(data)
        self._validate(candidate)
        self._write_prepared(candidate, None, compact=compact, mirror=mirror, writer=writer)

    def write_locked(
        self,
        data: Any,
        *,
        expected_revision: str | None = None,
        compact: bool | None = None,
        mirror: bool | None = None,
        writer: Callable | None = None,
    ) -> str:
        """Write under the caller's native lease without nested locking.

        Domain coordinators retain recovery, commit ordering, and notifications.
        This method returns the revision of this commit, even if an unrelated
        external writer changes the file immediately afterward.
        """
        candidate, revision = self._prepare(data)
        if expected_revision is not None:
            _current, current_revision = self.read_locked()
            if expected_revision != current_revision:
                raise RevisionConflict(current_revision)
        return self._write_prepared(candidate, revision, compact=compact, mirror=mirror, writer=writer)

    def _write_prepared(self, candidate, revision, *, compact=None, mirror=None, writer=None) -> str | None:
        compact_value = self._compact if compact is None else compact
        mirror_value = self._mirror if mirror is None else mirror
        if type(compact_value) is not bool or type(mirror_value) is not bool:
            raise TypeError("compact and mirror must be booleans")
        # A save can fail after an uncertain replace. Never reuse a pre-save
        # cache, or stamp our payload with another writer's post-save stat.
        self.invalidate()
        save = save_atomic if writer is None else writer
        options = {}
        if compact_value:
            options["compact"] = True
        if not mirror_value:
            options["mirror"] = False
        save(self.path, candidate, **options)
        return revision

    def update(
        self,
        mutator: Callable[[Any], Any],
        *,
        expected_revision: str | None = None,
        timeout_sec: float = 15.0,
        compact: bool | None = None,
        mirror: bool | None = None,
    ) -> tuple[Any, str]:
        """Read, mutate, validate, and save while holding one canonical lease.

        The mutator may return a replacement or mutate its private value and
        return None. It must not perform external effects or nested updates.
        """
        lease = self._acquire_lease(timeout_sec)
        try:
            current, current_revision = self.read_locked()
            if expected_revision is not None and expected_revision != current_revision:
                raise RevisionConflict(current_revision)
            replacement = mutator(current)
            candidate, revision = self._prepare(current if replacement is None else replacement)
            revision = self._write_prepared(candidate, revision, compact=compact, mirror=mirror)
            return copy.deepcopy(candidate), revision
        finally:
            lease.release()

    def _acquire_lease(self, timeout_sec: float):
        lease = file_lock(self.path, timeout_sec=timeout_sec)
        try:
            lease.acquire()
        except TimeoutError as exc:
            raise StoreBusy(f"JSON store lock timed out: {self.path}") from exc
        return lease

    def replace(
        self,
        data: Any,
        *,
        expected_revision: str | None = None,
        timeout_sec: float = 15.0,
        compact: bool | None = None,
        mirror: bool | None = None,
    ) -> str:
        """Compare and replace under one native lease."""
        # Use a private value even if another thread edits the caller's object.
        candidate = copy.deepcopy(data)
        lease = self._acquire_lease(timeout_sec)
        try:
            _current, current_revision = self.read_locked()
            if expected_revision is not None and expected_revision != current_revision:
                raise RevisionConflict(current_revision)
            return self.write_locked(candidate, compact=compact, mirror=mirror)
        finally:
            lease.release()


__all__ = ("JsonStore", "StoreBusy", "StoreCorrupt", "RevisionConflict", "semantic_revision")
