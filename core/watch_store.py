"""Strict watch reads for callers owning the runtime path and write lock."""
from __future__ import annotations

from core.json_store import StoreError
from core.stores import get_store


class WatchStoreReadError(RuntimeError):
    pass


def load_watch_strict(path) -> dict:
    try:
        value = get_store("watch", path).read_data_locked()
    except StoreError as exc:
        raise WatchStoreReadError("unreadable_watch") from exc
    if not isinstance(value, dict):
        raise WatchStoreReadError("malformed_watch")
    return value


def watch_object_member(parent: dict, key: str) -> dict:
    if key not in parent:
        return {}
    value = parent[key]
    if not isinstance(value, dict):
        raise WatchStoreReadError("malformed_watch_branch")
    return value
