from __future__ import annotations

import datetime as dt
from typing import Any


def parse_iso_date_key(value: Any) -> dt.date | None:
    """Return a real canonical ``YYYY-MM-DD`` date, otherwise ``None``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def is_iso_date_key(value: Any) -> bool:
    return parse_iso_date_key(value) is not None


__all__ = ("is_iso_date_key", "parse_iso_date_key")
