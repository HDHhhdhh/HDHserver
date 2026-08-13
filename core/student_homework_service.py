from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
import secrets
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OPAQUE_RE = re.compile(r"^hw_[A-Za-z0-9_-]{16,80}$")
_LIMITS = {"sid": 128, "curriculumSid": 128, "title": 200, "book": 200, "scope": 1000,
           "sourceRowId": 128, "operationId": 96}

class HomeworkValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
def kst_iso(value: dt.datetime) -> str:
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() != dt.timedelta(hours=9):
        raise HomeworkValidationError("invalid_payload", "now must be a KST-aware datetime")
    return value.replace(microsecond=0).isoformat(timespec="seconds")
def _iso(value, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise HomeworkValidationError("invalid_payload", f"{field} must be text")
    text = str(value or "").strip()
    if not _ISO_RE.fullmatch(text):
        raise HomeworkValidationError("invalid_payload", f"{field} must be strict KST ISO")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise HomeworkValidationError("invalid_payload", f"{field} is invalid") from exc
    if parsed.utcoffset() != dt.timedelta(hours=9):
        raise HomeworkValidationError("invalid_payload", f"{field} must use KST")
    return text
def _date(value, field: str = "sourceLogDate") -> str:
    if not isinstance(value, str):
        raise HomeworkValidationError("invalid_payload", f"{field} must be text")
    text = str(value or "").strip()
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise HomeworkValidationError("invalid_payload", f"{field} is invalid") from exc
    if not _DATE_RE.fullmatch(text) or parsed.isoformat() != text:
        raise HomeworkValidationError("invalid_payload", f"{field} must be YYYY-MM-DD")
    return text

def _text(value, field: str, *, required: bool = False) -> str:
    if value is not None and not isinstance(value, str):
        raise HomeworkValidationError("invalid_payload", f"{field} must be text")
    text = str(value or "").strip()
    if required and not text:
        raise HomeworkValidationError("invalid_payload", f"{field} is required")
    if len(text) > _LIMITS[field]:
        raise HomeworkValidationError("invalid_payload", f"{field} is too long")
    return text

def _new_id(prefix: str = "hw") -> str:
    return f"{prefix}_{secrets.token_urlsafe(18)}"
def prepare_assignment(payload: dict, *, sid: str, source_log_date: str,
                       now: dt.datetime, assignment_id: str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise HomeworkValidationError("invalid_payload", "homework assignment must be an object")
    sid = _text(sid, "sid", required=True)
    source_log_date = _date(source_log_date)
    now_text = kst_iso(now)
    status = str(payload.get("status") or "assigned").strip()
    if status not in {"assigned", "completed", "cancelled"}:
        raise HomeworkValidationError("invalid_payload", "invalid stored homework status")
    completed = _iso(payload.get("completedAt"), "completedAt", nullable=True)
    if status == "completed" and completed is None:
        completed = now_text
    if status != "completed" and completed is not None:
        raise HomeworkValidationError("invalid_payload", "completedAt requires completed status")
    item_id = assignment_id or payload.get("assignmentId") or _new_id()
    if not _OPAQUE_RE.fullmatch(str(item_id)):
        raise HomeworkValidationError("invalid_payload", "assignmentId is not opaque")
    source_row_id = _text(payload.get("sourceRowId"), "sourceRowId", required=True)
    revision = payload.get("expectedRevision")
    if revision is not None and (not isinstance(revision, int) or isinstance(revision, bool) or revision < 1):
        raise HomeworkValidationError("invalid_payload", "expectedRevision must be a positive integer")
    row_index = payload.get("rowIndex")
    if row_index is not None and (not isinstance(row_index, int) or isinstance(row_index, bool) or row_index < 0):
        raise HomeworkValidationError("invalid_payload", "rowIndex must be a non-negative integer")
    return {
        "id": str(item_id), "sid": sid,
        "curriculum_sid": _text(payload.get("curriculumSid"), "curriculumSid") or None,
        "title": _text(payload.get("title"), "title", required=True),
        "book": _text(payload.get("book"), "book"), "scope": _text(payload.get("scope"), "scope"),
        "assigned_at": _iso(payload.get("assignedAt") or now_text, "assignedAt"),
        "due_at": _iso(payload.get("dueAt"), "dueAt", nullable=True), "status": status,
        "completed_at": completed, "source_log_date": source_log_date, "source_row_id": source_row_id,
        "expected_revision": revision, "row_index": row_index,
    }
def _existing_payload(row: dict, payload: dict) -> dict:
    defaults = {
        "assignmentId": row["id"], "curriculumSid": row.get("curriculum_sid"), "title": row["title"],
        "book": row["book"], "scope": row["scope"], "assignedAt": row["assigned_at"],
        "dueAt": row["due_at"], "status": row["status"], "completedAt": row["completed_at"],
        "sourceRowId": row["source_row_id"],
    }
    status = payload.get("status")
    clear_completed = isinstance(status, str) and status in ("assigned", "cancelled")
    return {**defaults, **payload, **({"completedAt": None} if clear_completed else {})}
def prepare_batch(payloads, *, sid: str, source_log_date: str, now: dt.datetime, existing=()) -> list[dict]:
    if not isinstance(payloads, list) or len(payloads) > 50:
        raise HomeworkValidationError("invalid_payload", "homework batch must contain at most 50 rows")
    current = {str(row["source_row_id"]): row for row in existing if row.get("sid") == sid}
    prepared, seen = [], set()
    for payload in payloads:
        source_row_id = _text((payload or {}).get("sourceRowId"), "sourceRowId", required=True)
        if source_row_id in seen:
            raise HomeworkValidationError("invalid_payload", "duplicate sourceRowId")
        seen.add(source_row_id)
        old = current.get(source_row_id)
        merged = _existing_payload(old, payload) if old else payload
        prepared.append(prepare_assignment(merged, sid=sid, source_log_date=source_log_date, now=now,
                                           assignment_id=old["id"] if old else None))
    for source_row_id, old in current.items():
        if source_row_id in seen or old["status"] == "cancelled":
            continue
        payload = _existing_payload(old, {"status": "cancelled", "completedAt": None,
                                          "expectedRevision": old["revision"]})
        prepared.append(prepare_assignment(payload, sid=sid, source_log_date=source_log_date,
                                           now=now, assignment_id=old["id"]))
    return prepared

def attach_assignment_ids(homework_table, prepared: list[dict]) -> list:
    rows = [dict(row) if isinstance(row, dict) else row for row in (homework_table or [])]
    for item in prepared:
        index = item.get("row_index")
        if item["status"] != "cancelled" and isinstance(index, int) and index < len(rows) and isinstance(rows[index], dict):
            rows[index]["assignmentId"] = item["id"]
    return rows
def public_projection(row: dict, *, now: dt.datetime) -> dict:
    kst_iso(now)
    due_at = row.get("due_at")
    eligible = row["status"] == "assigned" and due_at is not None and dt.datetime.fromisoformat(due_at) > now
    return {
        "id": row["id"], "title": row["title"], "book": row["book"], "scope": row["scope"],
        "assignedAt": row["assigned_at"],
        "dueAt": due_at, "status": row["status"], "completedAt": row.get("completed_at"),
        "notificationEligible": eligible, "legacy": False,
    }
def _cursor_values(row: dict):
    return [1 if row.get("due_at") is None else 0, row.get("due_at") or "", row["assigned_at"], row["id"]]

def encode_cursor(row: dict) -> str:
    raw = json.dumps(_cursor_values(row), separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")
def decode_cursor(value: str | None):
    if not value:
        return None
    try:
        raw = base64.urlsafe_b64decode(str(value) + "=" * (-len(str(value)) % 4))
        parts = json.loads(raw)
        if (not isinstance(parts, list) or len(parts) != 4 or parts[0] not in {0, 1}
                or not all(isinstance(item, str) for item in parts[1:])):
            raise ValueError
        _iso(parts[2], "assignedAt")
        if parts[0] == 0:
            _iso(parts[1], "dueAt")
        elif parts[1] != "":
            raise ValueError
        if not _OPAQUE_RE.fullmatch(parts[3]):
            raise ValueError
        return tuple(parts)
    except Exception as exc:
        if isinstance(exc, HomeworkValidationError):
            pass
        raise HomeworkValidationError("invalid_cursor", "invalid homework cursor") from exc

def public_page(repository, *, sid: str, status: str = "open", cursor: str | None = None,
                page_size: int = 50, now: dt.datetime) -> dict:
    if status not in {"open", "all"} or not isinstance(page_size, int) or not 1 <= page_size <= 50:
        raise HomeworkValidationError("invalid_payload", "invalid homework list options")
    kst_iso(now)
    rows, more = repository.list_for_sid(_text(sid, "sid", required=True), status=status,
                                         cursor=decode_cursor(cursor), page_size=page_size)
    return {"items": [public_projection(row, now=now) for row in rows],
            "nextCursor": encode_cursor(rows[-1]) if more and rows else None}
def legacy_homework_projection(homework_table, *, sid: str, source_log_date: str) -> list[dict]:
    sid, source_log_date = _text(sid, "sid", required=True), _date(source_log_date)
    assigned_at = f"{source_log_date}T00:00:00+09:00"
    items = []
    for index, row in enumerate(homework_table if isinstance(homework_table, list) else []):
        if not isinstance(row, dict) or row.get("_deleted"):
            continue
        book, scope = str(row.get("book") or "").strip()[:200], str(row.get("next") or "").strip()[:1000]
        title = (scope or str(row.get("this") or "").strip()
                 or str(row.get("comment") or "").strip() or book or "숙제")[:200]
        linked_id = str(row.get("assignmentId") or "").strip()
        digest = hashlib.sha256(f"{sid}\0{source_log_date}\0{index}".encode()).hexdigest()[:24]
        item_id = linked_id if _OPAQUE_RE.fullmatch(linked_id) else f"hw_{digest}"
        items.append({"id": item_id, "title": title, "book": book, "scope": scope,
                      "assignedAt": assigned_at, "dueAt": None, "status": "assigned",
                      "completedAt": None, "notificationEligible": False, "legacy": True})
    return items
def read_legacy_homework(logs_path, *, sid: str, source_log_date: str) -> list[dict]:
    with Path(logs_path).open("r", encoding="utf-8-sig") as handle:
        logs = json.load(handle)
    sid, ceiling = _text(sid, "sid", required=True), _date(source_log_date)
    for date_key in sorted((key for key in logs if isinstance(key, str) and _DATE_RE.fullmatch(key) and key <= ceiling), reverse=True):
        entry = (logs.get(date_key) or {}).get(sid) or {}
        items = legacy_homework_projection(entry.get("homeworkTable"), sid=sid, source_log_date=date_key)
        if items:
            return items
    return []
def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def _without_assignment_ids(value):
    if isinstance(value, dict):
        return {key: _without_assignment_ids(item) for key, item in value.items() if key != "assignmentId"}
    return [_without_assignment_ids(item) for item in value] if isinstance(value, list) else value
def request_hash(*, sid: str, source_log_date: str, desired_log: dict, assignments: list[dict]) -> str:
    clean = [{key: value for key, value in item.items() if key not in {"id", "row_index"}} for item in assignments]
    payload = {"sid": sid, "sourceLogDate": source_log_date,
               "log": _without_assignment_ids(desired_log), "assignments": clean}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
def prepare_reconciliation(*, sid: str, source_log_date: str, desired_log: dict,
                           assignments: list[dict], now: dt.datetime, operation_id: str | None = None) -> dict:
    sid, source_log_date, now_text = _text(sid, "sid", required=True), _date(source_log_date), kst_iso(now)
    operation_id = operation_id or _new_id("hwo")
    if not isinstance(operation_id, str) or not 8 <= len(operation_id) <= _LIMITS["operationId"]:
        raise HomeworkValidationError("invalid_payload", "operationId is invalid")
    desired = [{key: value for key, value in item.items() if key != "row_index"} for item in assignments]
    return {
        "id": _new_id("hwr"), "operation_id": operation_id, "sid": sid,
        "source_log_date": source_log_date,
        "request_hash": request_hash(sid=sid, source_log_date=source_log_date,
                                     desired_log=desired_log, assignments=assignments),
        "desired_log_json": _canonical(desired_log), "desired_assignments_json": _canonical(desired),
        "log_state": "pending", "homework_state": "pending", "state": "prepared", "attempts": 0,
        "last_error_code": "", "created_at": now_text, "updated_at": now_text,
    }

def reconciliation_result(row: dict) -> dict:
    return {"operationId": row["operation_id"], "state": row["state"],
            "partialFailure": row["state"] == "partial_failure",
            "retryable": row["state"] in {"prepared", "partial_failure"},
            "errorCode": row.get("last_error_code") or None}

def audit_orphans(assignments, log_rows) -> dict:
    canonical = {row["id"]: row for row in assignments}
    linked = {str(row.get("assignmentId")) for row in log_rows if isinstance(row, dict) and row.get("assignmentId")}
    return {"orphanAssignmentIds": sorted(set(canonical) - linked),
            "missingCanonicalIds": sorted(linked - set(canonical)), "repairAttempted": False}
