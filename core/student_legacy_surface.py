"""Pure path boundary for the legacy public student origin."""

from __future__ import annotations

from typing import Final


APP_ONLY_EXACT_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/student-app.html",
        "/manifest.webmanifest",
        "/sw.js",
        "/offline.html",
        "/css/student-app.css",
        "/js/student-app.js",
        "/js/student-app-api.js",
        "/js/student-app-contract.js",
        "/js/student-app-push.js",
        "/icons/student-app-192.png",
        "/icons/student-app-512.png",
        "/icons/student-app-maskable-512.png",
    }
)


def is_app_only_path(path: str) -> bool:
    """Keep the unfinished app surface isolated from the legacy origin."""
    return path == "/app" or path.startswith("/app/") or path.startswith("/api/mobile/") or path in APP_ONLY_EXACT_PATHS


__all__ = ("APP_ONLY_EXACT_PATHS", "is_app_only_path")
