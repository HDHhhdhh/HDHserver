"""Pure classification of request-level absence snapshot ownership."""

import json
import os

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
        if path in {"/api/admin/bootstrap", "/api/admin/revisions"}:
            return invalid(query.get("date"))
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
        if path == "/api/progress":
            since = str(query.get("since") or "").strip()
            if since and invalid(since):
                return True
            getlist = getattr(query, 'getlist', lambda key: [query.get(key)])
            sids = getlist('sid') + getlist('sids')
            has_sid = bool(str(query.get('sid') or '').strip()) or any(
                part.strip() for raw in sids for part in str(raw or '').split(',')
            )
            return not str(query.get('date') or '').strip() and not has_sid
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


def updates_get_initializes(query=None) -> bool:
    query = query if query is not None else {}
    if str(query.get("readOnly") or "").strip().lower() in {"1", "true", "yes"}:
        return False
    return str(query.get("ensure") or "").strip() == "1" or os.environ.get("UPDATES_GET_ENSURE") == "1"


def absence_barrier_mode(path: str, method: str, query=None) -> str | None:
    path = str(path or "").rstrip("/") or "/"
    if method == "POST" and path in {"/api/absent", "/api/makeup-sheet-sync"}:
        return None  # These routes acquire the exclusive transaction scope.
    exact = {
        "/api/admin/bootstrap", "/api/admin/revisions",
        "/api/absent", "/api/absent/recover", "/api/attend", "/api/homework-books",
        "/api/kollus/lms-callback", "/api/makeup-carryover", "/api/student/bootstrap",
        "/api/tests-records", "/api/tests-stats", "/api/today", "/api/watch", "/api/watch-status",
        "/api/tests/quick-printer-export", "/api/tests/quick-printer-export/preview",
        "/api/arrive-time/missing-leave-summary",
        "/api/payments/evidence",
    }
    prefixes = ("/api/admin/student-homework", "/api/logs", "/api/mobile/student/homework",
                "/api/progress", "/api/updates", "/api/student-test-ocr")
    if path not in exact and not path.startswith(prefixes):
        return None
    # Compatibility GET initialization and bootstrap need an exclusive lease.
    shared = {"/api/absent", "/api/homework-books", "/api/tests-records", "/api/tests-stats",
              "/api/admin/bootstrap", "/api/admin/revisions",
              "/api/arrive-time/missing-leave-summary", "/api/makeup-carryover", "/api/payments/evidence"}
    read_only_updates = path == "/api/updates" and not updates_get_initializes(query)
    if method in {"GET", "HEAD"} and (path in shared or read_only_updates
                                     or path.startswith(("/api/logs", "/api/progress"))):
        return "shared"
    return "exclusive"
