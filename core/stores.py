"""Lazy bounded JSON stores; domain owners retain journals and native leases."""
from __future__ import annotations

from collections import OrderedDict
import os
from pathlib import Path
import threading

from core.json_store import JsonStore


_SPECS = {
    "students": ("STU_PATH", list, True),
    "persons": ("PERSONS_PATH", dict, True),
    "videos": ("VID_PATH", list, True),
    "materials": ("MAT_PATH", dict, False),
    "assignments": ("ASN_PATH", dict, False),
    "pageFolders": ("PAGE_FOLDERS_PATH", dict, False),
    "extra": ("EXTRA_PATH", dict, False),
    "weekend": ("WEEKEND_SLOTS_PATH", dict, False),
    "calendar": ("CAL_PATH", dict, False),
    "updates": ("UPD_PATH", dict, False),
    "progress": ("PRG_PATH", dict, False),
    "watch": ("WATCH_PATH", dict, False),
    "absent": ("ABS_PATH", dict, False),
    "testsConfig": ("TESTS_CFG_PATH", dict, False),
    "attendance": ("ATTENDANCE_PATH", dict, False),
    "contact": ("CONTACT_PATH", dict, False),
    "arriveTime": ("ARRIVE_TIME_PATH", dict, False),
    "todayOrder": ("TODAY_ORDER_PATH", dict, False),
    "announcements": ("ANNS_PATH", list, False),
    "accounts": (None, dict, False),
    "legacy": (None, None, False),
}
_STORES: OrderedDict[tuple[str, str], JsonStore] = OrderedDict()
_GUARD = threading.Lock()
_MAX_STORES = 64


def get_store(name: str, path=None) -> JsonStore:
    attribute, shape, required = _SPECS[name]
    if path is None:
        from core import paths
        path = getattr(paths, attribute) if attribute else paths.BASE / "auth_accounts.json"
    target = Path(os.path.abspath(path))
    key = (name, os.path.normcase(os.path.abspath(target)))
    with _GUARD:
        store = _STORES.get(key)
        if store is None:
            def missing():
                if required:
                    raise FileNotFoundError(f"Required JSON store is missing: {target}")
                return ({} if target.suffix == ".json" else None) if shape is None else shape()

            store = JsonStore(
                target, missing, validate=shape,
                compact=name == "progress", mirror=name != "accounts",
            )
            _STORES[key] = store
            while len(_STORES) > _MAX_STORES:
                _STORES.popitem(last=False)
        _STORES.move_to_end(key)
        return store


def load_cached(path):
    """Retain the legacy load shape; endpoint owners validate domain content."""
    return get_store("legacy", path).read()[0]


def invalidate_stores(name: str | None = None) -> None:
    with _GUARD:
        stores = [store for (owner, _path), store in _STORES.items() if name is None or owner == name]
    for store in stores:
        store.invalidate()
