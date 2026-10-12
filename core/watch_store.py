"""Strict watch reads for callers owning the runtime path and write lock."""
from __future__ import annotations

import json
from pathlib import Path


class WatchStoreReadError(RuntimeError):
    pass


def load_watch_strict(path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
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
