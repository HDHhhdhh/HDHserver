"""Pure classification of request-level absence snapshot ownership."""

import json

from core.date_rules import is_iso_date_key

POST_DATE_ENDPOINTS = frozenset({
    "/api/progress/patch", "/api/logs/patch", "/api/logs/patch-batch", "/api/updates/patch",
    "/api/updates/self-study", "/api/watch", "/api/watch-status", "/api/absent/recover",
})


def request_has_invalid_scoped_date(path: str, method: str, query, body) -> bool:
    """Skip the lease only for inputs the owning route rejects before I/O."""
    path = str(path or "").rstrip("/") or "/"

    def invalid(value) -> bool:
        return not is_iso_date_key(str(value or "").strip())

    if method in {"GET", "HEAD"}:
        if path == "/api/logs/entry":
            return invalid(query.get("date"))
        if path == "/api/student/bootstrap":
            value = query.get("date")
            return bool(value) and invalid(value)
        if path in {"/api/attend", "/api/attendance", "/api/contact"}:
            value = query.get("date")
            return bool(value) and invalid(value)
        if path in {"/api/progress", "/api/logs", "/api/watch/latest"}:
            value = str(query.get("date") or "").strip()
            if value and invalid(value):
                return True
        if path == "/api/logs/unarchived-summary":
            value = str(query.get("exclude_date") or query.get("excludeDate") or "").strip()
            return bool(value) and invalid(value)
        if path == "/api/logs" and query.get("exportTargets") is not None:
            try:
                rows = json.loads(query.get("exportTargets"))
            except (TypeError, ValueError):
                return False
            return isinstance(rows, list) and any(
                isinstance(row, list) and len(row) == 2 and invalid(row[1]) for row in rows
            )
        return False

    if method != "POST" or not isinstance(body, dict):
        return False
    if path in POST_DATE_ENDPOINTS and path != "/api/logs/patch-batch":
        return invalid(body.get("date"))
    if path == "/api/logs/patch-batch":
        rows = body.get("patches")
        return isinstance(rows, list) and any(
            isinstance(row, dict) and invalid(row.get("date")) for row in rows
        )
    return False


def absence_barrier_mode(path: str, method: str, query=None) -> str | None:
    path = str(path or "").rstrip("/") or "/"
    if method == "POST" and path in {"/api/absent", "/api/makeup-sheet-sync"}:
        return None  # These routes acquire the exclusive transaction scope.
    exact = {
        "/api/absent", "/api/absent/recover", "/api/attend", "/api/homework-books",
        "/api/kollus/lms-callback", "/api/makeup-carryover", "/api/student/bootstrap",
        "/api/tests-records", "/api/tests-stats", "/api/today", "/api/watch", "/api/watch-status",
        "/api/tests/quick-printer-export", "/api/tests/quick-printer-export/preview",
        "/api/arrive-time/missing-leave-summary",
    }
    prefixes = ("/api/admin/student-homework", "/api/logs", "/api/mobile/student/homework",
                "/api/progress", "/api/updates", "/api/student-test-ocr")
    if path not in exact and not path.startswith(prefixes):
        return None
    # Explicit storage-only GETs can share a lease. Bootstrap and bare updates
    # can initialize assignments, so must never acquire an upgradable read lease.
    shared = {"/api/absent", "/api/homework-books", "/api/tests-records", "/api/tests-stats",
              "/api/arrive-time/missing-leave-summary", "/api/makeup-carryover"}
    read_only_updates = path == "/api/updates" and query is not None and (
        str(query.get("readOnly") or "").strip().lower() in {"1", "true", "yes"}
    )
    if method in {"GET", "HEAD"} and (path in shared or read_only_updates
                                     or path.startswith(("/api/logs", "/api/progress"))):
        return "shared"
    return "exclusive"
