# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
# --- How to run ---
# python scripts/verify_proxy_header_safety.py
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.pop("TRUST_PROXY_HEADERS", None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


def run_checks() -> None:
    client = create_app().test_client()
    response = client.post(
        "/api/auth/login",
        json={},
        headers={
            "Host": "academy.local",
            "Origin": "http://evil.example",
            "X-Forwarded-Host": "evil.example",
        },
    )
    if response.status_code != 403:
        raise AssertionError(
            "cross-origin writes must not trust client-supplied X-Forwarded-Host"
        )


if __name__ == "__main__":
    run_checks()
    print("proxy header safety checks passed")
