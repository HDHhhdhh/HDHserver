"""Stable JSON content revisions shared by persistence owners."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def json_revision(data: Any) -> str:
    encoded = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
