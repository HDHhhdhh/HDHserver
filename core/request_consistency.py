"""Pure classification of request-level absence snapshot ownership."""


def absence_barrier_mode(path: str, method: str) -> str | None:
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
              "/api/arrive-time/missing-leave-summary"}
    if method in {"GET", "HEAD"} and (path in shared or path.startswith(("/api/logs", "/api/progress"))):
        return "shared"
    return "exclusive"
