"""Content revisions for administrator projections and historical warnings."""
from __future__ import annotations

from collections import OrderedDict
import threading

from core.json_revision import json_revision
from core.json_store import StoreBusy

_LOG_REVISIONS = OrderedDict()
_LOG_REVISION_LOCK = threading.RLock()


def log_revision(repository, date=""):
    key = (*repository.cache_identity(), date)
    if repository.store_mode == 'sqlite':
        repository.verify_available()
    with _LOG_REVISION_LOCK:
        for _attempt in range(3):
            signature = repository.cache_signature()
            cached = _LOG_REVISIONS.get(key)
            if cached is not None and cached[0] == signature:
                _LOG_REVISIONS.move_to_end(key)
                return cached[1]
            revision = repository.revision(date)
            if signature != repository.cache_signature():
                continue
            _LOG_REVISIONS[key] = (signature, revision)
            _LOG_REVISIONS.move_to_end(key)
            while len(_LOG_REVISIONS) > 64:
                _LOG_REVISIONS.popitem(last=False)
            return revision
    raise StoreBusy('Class-log storage changed during revision reads')


def date_revision(store, date):
    return json_revision(store.read_nested(outer_keys=[date]))
