"""Feature-gated student homework read and academy administration APIs."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, Response, g, jsonify, make_response, request

from core.admin_basic_auth import ADMIN_AUTH_CHALLENGE, admin_network_allowed, verify_admin_authorization
from core.student_app_config import StudentAppConfig, load_student_app_config
from core.student_homework_repository import (
    HomeworkConflictError,
    HomeworkNotInitializedError,
    StudentHomeworkRepository,
)
from core.student_homework_service import (
    KST,
    HomeworkValidationError,
    attach_assignment_ids,
    kst_iso,
    prepare_batch,
    prepare_reconciliation,
    public_page,
    read_legacy_homework,
    reconciliation_result,
)
from core.student_notification_events import deterministic_event_id
from core.student_notification_hooks import enqueue_homework_events
from core.student_notification_repository import StudentNotificationRepository
from core.student_public_proxy import public_host_matches
from core.student_public_surface_paths import strict_sid


LogPatcher = Callable[[str, str, dict, dict], Any]


@dataclass(slots=True)
class StudentHomeworkApiDependencies:
    config: StudentAppConfig
    repository: StudentHomeworkRepository
    logs_path: Path
    log_patcher: LogPatcher
    clock: Callable[[], dt.datetime]
    notifications: StudentNotificationRepository | None = None


@dataclass(slots=True)
class _Provider:
    dependencies: StudentHomeworkApiDependencies | None = None

    def get(self) -> StudentHomeworkApiDependencies:
        if self.dependencies is None:
            self.dependencies = _build_dependencies()
        return self.dependencies

    def config(self) -> StudentAppConfig:
        return self.get().config


def _patch_class_log(date_key: str, sid: str, entry: dict, base: dict):
    # Import lazily: importing the log repository can initialize runtime paths.
    from routes.api_basic import get_log_repository

    return get_log_repository().patch_entry(date_key, sid, entry, base)


def _build_dependencies() -> StudentHomeworkApiDependencies:
    base = Path(__file__).resolve().parents[1]
    config = load_student_app_config()
    database = Path(os.environ.get("STUDENT_APP_DB_PATH", base / "app.sqlite"))
    logs_path = Path(os.environ.get("STUDENT_APP_LOGS_PATH", base / "logs.json"))
    return StudentHomeworkApiDependencies(
        config,
        StudentHomeworkRepository(database),
        logs_path,
        _patch_class_log,
        lambda: dt.datetime.now(KST),
        StudentNotificationRepository(database) if config.reminders_enabled else None,
    )


def _reply(payload: Mapping[str, Any], status: int = 200):
    response = jsonify(dict(payload))
    response.headers["Cache-Control"] = "no-store"
    return response if status == 200 else (response, status)


def _empty_404() -> Response:
    response = make_response("", 404)
    response.headers["Cache-Control"] = "no-store"
    return response


def _exception_reply(exc: Exception):
    code = getattr(exc, "code", "homework_unavailable")
    if isinstance(exc, HomeworkValidationError):
        return _reply({"ok": False, "code": code}, 400)
    if isinstance(exc, HomeworkConflictError):
        return _reply({"ok": False, "code": code, "retryable": False}, 409)
    if isinstance(exc, HomeworkNotInitializedError):
        return _reply({"ok": False, "code": code}, 503)
    return _reply({"ok": False, "code": "homework_unavailable"}, 503)


def _strict_date_key(value: object) -> str:
    text = str(value or "").strip()
    try:
        parsed = dt.date.fromisoformat(text)
    except (TypeError, ValueError):
        raise HomeworkValidationError("invalid_payload", "invalid log date") from None
    if parsed.isoformat() != text:
        raise HomeworkValidationError("invalid_payload", "invalid log date")
    return text


def _same_origin() -> bool:
    expected = (request.scheme.lower(), request.host.lower())
    supplied = [request.headers.get(name) for name in ("Origin", "Referer")]
    supplied = [value.strip() for value in supplied if isinstance(value, str) and value.strip()]
    if not supplied:
        return False
    for value in supplied:
        try:
            parsed = urlparse(value)
        except ValueError:
            return False
        if (parsed.scheme.lower(), parsed.netloc.lower()) != expected:
            return False
    return True


def _public_assignment_ids(operation_id: str, rows: list[dict], existing: list[dict]) -> list[dict]:
    by_id = {str(row["id"]): row for row in existing}
    prepared = []
    for index, source in enumerate(rows):
        if not isinstance(source, dict):
            raise HomeworkValidationError("invalid_payload", "homework row must be an object")
        row = dict(source)
        row_index = row.get("rowIndex")
        if row_index != index:
            raise HomeworkValidationError("invalid_payload", "rowIndex must match homework table order")
        assignment_id = str(row.get("assignmentId") or "").strip()
        if assignment_id:
            current = by_id.get(assignment_id)
            if current is None:
                raise HomeworkValidationError("invalid_payload", "assignmentId is not linked to this log")
            row["sourceRowId"] = current["source_row_id"]
        else:
            source_id = str(row.get("sourceRowId") or "").strip()
            if not source_id:
                source_id = f"row_{hashlib.sha256(f'{operation_id}:{index}'.encode()).hexdigest()[:32]}"
            row["sourceRowId"] = source_id
            row["assignmentId"] = f"hw_{hashlib.sha256(f'{operation_id}:{source_id}'.encode()).hexdigest()[:32]}"
        prepared.append(row)
    return prepared


def _admin_assignment(row: dict, now: dt.datetime) -> dict:
    effective = row["status"]
    if effective == "assigned" and row.get("due_at") and dt.datetime.fromisoformat(row["due_at"]) <= now:
        effective = "overdue"
    return {
        "id": row["id"],
        "sourceRowId": row["source_row_id"],
        "title": row["title"],
        "book": row["book"],
        "scope": row["scope"],
        "assignedAt": row["assigned_at"],
        "dueAt": row.get("due_at"),
        "status": row["status"],
        "effectiveStatus": effective,
        "revision": row["revision"],
    }


def _log_patch_already_applied(current: object, desired: dict) -> bool:
    if not isinstance(current, dict):
        return False
    clear_keys = desired.get("__clear", [])
    if not isinstance(clear_keys, list):
        return False
    for key, value in desired.items():
        if key == "__clear":
            continue
        if current.get(key) != value:
            return False
    return all(key not in current for key in clear_keys if isinstance(key, str))


def _enqueue_committed_homework(
    deps: StudentHomeworkApiDependencies,
    sid: str,
    rows: list[dict],
    now: dt.datetime,
) -> int:
    if not deps.config.public_enabled or not deps.config.reminders_enabled or deps.notifications is None:
        return 0
    try:
        return enqueue_homework_events(deps.notifications, sid, rows, now=now)
    except Exception:  # noqa: BROAD_EXCEPT_OK - canonical save remains authoritative
        return 0


def _add_notification_event_ids(items: list[dict]) -> None:
    """Add opaque deep-link aliases without exposing assignment authority in Push."""
    for item in items:
        event_ids: list[str] = []
        assignment_id = str(item.get("id") or "").strip() if isinstance(item, dict) else ""
        if assignment_id and item.get("legacy") is False:
            event_ids.append(deterministic_event_id("homework_assigned", assignment_id))
            due_at = item.get("dueAt")
            if isinstance(due_at, str) and due_at:
                event_ids.append(deterministic_event_id("homework_due", assignment_id, due_at))
        item["notificationEventIds"] = event_ids


def create_public_blueprint(provider: _Provider) -> Blueprint:
    blueprint = Blueprint("student_homework_public", __name__)

    @blueprint.get("/api/mobile/student/homework")
    def list_homework():
        deps = provider.get()
        if not deps.config.homework_enabled or getattr(g, "student_app_public_request", False) is not True:
            return _empty_404()
        sid = strict_sid(getattr(g, "student_app_active_sid", None))
        if sid is None:
            return _reply({"ok": False, "code": "unauthenticated"}, 401)
        if set(request.args) - {"status", "cursor"}:
            return _reply({"ok": False, "code": "invalid_payload"}, 400)
        now = deps.clock()
        try:
            result = public_page(
                deps.repository,
                sid=sid,
                status=request.args.get("status", "open"),
                cursor=request.args.get("cursor"),
                page_size=50,
                now=now,
            )
            if not request.args.get("cursor") and result["nextCursor"] is None and len(result["items"]) < 50:
                legacy = read_legacy_homework(deps.logs_path, sid=sid, source_log_date=now.date().isoformat())
                known = {item["id"] for item in result["items"]}
                for item in legacy:
                    if item["id"] in known or deps.repository.get(sid, item["id"]) is not None:
                        continue
                    result["items"].append(item)
                result["items"] = result["items"][:50]
            _add_notification_event_ids(result["items"])
            return _reply({"ok": True, **result})
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - storage details stay private
            return _exception_reply(exc)

    return blueprint


def create_admin_blueprint(
    provider: _Provider,
    *,
    admin_authorizer: Callable[[str | None], bool] | None = None,
) -> Blueprint:
    blueprint = Blueprint("student_homework_admin", __name__, url_prefix="/api/admin/student-homework")
    authorize = admin_authorizer or verify_admin_authorization

    @blueprint.before_request
    def gate_admin():
        deps = provider.get()
        if not deps.config.homework_enabled:
            return _empty_404()
        if public_host_matches(request.environ, deps.config.public_host, deps.config.trusted_proxy_networks):
            return _empty_404()
        if not admin_network_allowed(request):
            return _reply({"ok": False, "code": "academy_network_required"}, 403)
        if not authorize(request.headers.get("Authorization")):
            response, status = _reply({"ok": False, "code": "admin_auth_required"}, 401)
            response.headers["WWW-Authenticate"] = ADMIN_AUTH_CHALLENGE
            return response, status
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not _same_origin():
            return _reply({"ok": False, "code": "origin_required"}, 403)
        return None

    @blueprint.get("")
    def admin_list():
        sid = strict_sid(request.args.get("sid"))
        if sid is None or set(request.args) != {"sid", "date"}:
            return _reply({"ok": False, "code": "invalid_payload"}, 400)
        try:
            date_key = _strict_date_key(request.args.get("date"))
            deps, now = provider.get(), provider.get().clock()
            rows = deps.repository.list_for_log_date(sid, date_key)
            pending = deps.repository.pending_for_source(sid, date_key)
            return _reply({
                "ok": True,
                "assignments": [_admin_assignment(row, now) for row in rows if row["status"] != "cancelled"],
                "pendingOperation": reconciliation_result(pending) if pending else None,
            })
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - storage details stay private
            return _exception_reply(exc)

    @blueprint.post("/commit")
    def commit():
        if request.content_length is not None and request.content_length > 256 * 1024:
            return _reply({"ok": False, "code": "invalid_payload"}, 400)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _reply({"ok": False, "code": "invalid_payload"}, 400)
        try:
            return _commit(provider.get(), body)
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - storage details stay private
            return _exception_reply(exc)

    return blueprint


def _commit(deps: StudentHomeworkApiDependencies, body: dict):
    allowed = {"operationId", "date", "sid", "logPatch", "homeworkRows", "removedAssignmentIds"}
    if set(body) - allowed:
        raise HomeworkValidationError("invalid_payload", "unexpected commit field")
    sid = strict_sid(body.get("sid"))
    date_key = _strict_date_key(body.get("date"))
    operation_id = str(body.get("operationId") or "").strip()
    log_patch, rows = body.get("logPatch"), body.get("homeworkRows")
    removed = body.get("removedAssignmentIds", [])
    if sid is None or not isinstance(log_patch, dict) or not isinstance(rows, list) or not isinstance(removed, list):
        raise HomeworkValidationError("invalid_payload", "invalid commit payload")
    if set(log_patch) - {"entry", "base", "clearKeys", "baseHomeworkTableExact"}:
        raise HomeworkValidationError("invalid_payload", "invalid log patch")
    entry, base = log_patch.get("entry"), log_patch.get("base")
    exact = log_patch.get("baseHomeworkTableExact")
    clear = log_patch.get("clearKeys", [])
    if not isinstance(entry, dict) or not isinstance(base, dict) or not isinstance(exact, list) or not isinstance(clear, list):
        raise HomeworkValidationError("invalid_payload", "invalid log patch")
    homework_table = entry.get("homeworkTable")
    if not isinstance(homework_table, list) or len(homework_table) != len(rows):
        raise HomeworkValidationError("invalid_payload", "homework rows do not match the log")
    now, now_text = deps.clock(), None
    now_text = kst_iso(now)
    existing = deps.repository.list_for_log_date(sid, date_key)
    row_payloads = _public_assignment_ids(operation_id, rows, existing)
    prepared = prepare_batch(row_payloads, sid=sid, source_log_date=date_key, now=now, existing=existing)
    existing_ids = {row["id"] for row in existing if row["status"] != "cancelled"}
    kept_ids = {item["id"] for item in prepared if item["status"] != "cancelled"}
    removed_ids = {str(value) for value in removed}
    if removed_ids != existing_ids - kept_ids:
        raise HomeworkValidationError("invalid_payload", "removed assignments do not match")
    desired_entry = dict(entry)
    desired_entry["homeworkTable"] = attach_assignment_ids(homework_table, prepared)
    if clear:
        desired_entry["__clear"] = clear
    desired_base = {**base, "__homeworkTableExact": exact}
    desired_log = {"entry": desired_entry, "base": desired_base}
    operation = prepare_reconciliation(
        sid=sid,
        source_log_date=date_key,
        desired_log=desired_log,
        assignments=prepared,
        now=now,
        operation_id=operation_id,
    )
    reconciliation = deps.repository.begin_operation(operation)
    if reconciliation["id"] != operation["id"]:
        stored_log = json.loads(reconciliation["desired_log_json"])
        stored_assignments = json.loads(reconciliation["desired_assignments_json"])
        if not isinstance(stored_log, dict) or not isinstance(stored_assignments, list):
            raise HomeworkConflictError("idempotency_conflict", "stored reconciliation is malformed")
        desired_entry = stored_log.get("entry")
        desired_base = stored_log.get("base")
        if not isinstance(desired_entry, dict) or not isinstance(desired_base, dict):
            raise HomeworkConflictError("idempotency_conflict", "stored log operation is malformed")
        prepared = stored_assignments
    if reconciliation["state"] == "completed":
        saved = deps.repository.list_for_log_date(sid, date_key)
        queued = _enqueue_committed_homework(deps, sid, saved, now)
        return _reply({"ok": True, "state": "committed", "operationId": operation_id,
                       "reconciliationId": reconciliation["id"], "entry": desired_entry,
                       "homework": {"ok": True, "assignments": [_admin_assignment(row, now) for row in saved]},
                       "notificationEventsQueued": queued})
    if reconciliation["state"] == "blocked":
        return _reply({"ok": False, "code": "revision_conflict", "retryable": False,
                       "operationId": operation_id, "reconciliationId": reconciliation["id"]}, 409)

    log_result, semantic_conflict = None, False
    if reconciliation["log_state"] in {"pending", "failed"}:
        try:
            log_result = deps.log_patcher(date_key, sid, desired_entry, desired_base)
            conflict_entry = getattr(log_result, "json_conflict_entry", None)
            sqlite_conflict = bool(getattr(log_result, "sqlite_base_conflict", False))
            sqlite_entry = getattr(log_result, "sqlite_conflict_entry", None)
            semantic_conflict = bool(sqlite_conflict or conflict_entry is not None)
            sqlite_side_ok = bool(
                getattr(log_result, "sqlite_ok", False)
                or (sqlite_conflict and _log_patch_already_applied(sqlite_entry, desired_entry))
            )
            json_side_ok = bool(
                getattr(log_result, "json_ok", False)
                or _log_patch_already_applied(conflict_entry, desired_entry)
            )
            already_applied = sqlite_side_ok and json_side_ok
            if semantic_conflict and already_applied:
                semantic_conflict = False
                reconciliation = deps.repository.record_log_outcome(operation_id, "succeeded", now=now_text)
            elif semantic_conflict:
                reconciliation = deps.repository.record_log_outcome(
                    operation_id, "conflict", error_code="revision_conflict", now=now_text
                )
            elif sqlite_side_ok and json_side_ok:
                reconciliation = deps.repository.record_log_outcome(operation_id, "succeeded", now=now_text)
            else:
                reconciliation = deps.repository.record_log_outcome(
                    operation_id, "failed", error_code="log_write_failed", now=now_text
                )
        except Exception:  # noqa: BROAD_EXCEPT_OK - reconciliation stores only a typed code
            reconciliation = deps.repository.record_log_outcome(
                operation_id, "failed", error_code="log_write_failed", now=now_text
            )

    homework_rows = deps.repository.list_for_log_date(sid, date_key)
    if not semantic_conflict and reconciliation["homework_state"] in {"pending", "failed"}:
        try:
            homework_rows = deps.repository.apply_batch(sid, date_key, prepared, now=now_text)
            reconciliation = deps.repository.record_homework_outcome(operation_id, "succeeded", now=now_text)
        except HomeworkConflictError as exc:
            code = exc.code if exc.code in {"revision_conflict", "idempotency_conflict"} else "revision_conflict"
            reconciliation = deps.repository.record_homework_outcome(
                operation_id, "conflict", error_code=code, now=now_text
            )
        except Exception:  # noqa: BROAD_EXCEPT_OK - reconciliation stores only a typed code
            reconciliation = deps.repository.record_homework_outcome(
                operation_id, "failed", error_code="homework_write_failed", now=now_text
            )

    if reconciliation["state"] == "completed":
        queued = _enqueue_committed_homework(deps, sid, homework_rows, now)
        return _reply({
            "ok": True, "state": "committed", "operationId": operation_id,
            "reconciliationId": reconciliation["id"], "entry": desired_entry,
            "log": {"ok": True, "sqlite": True, "json": True},
            "homework": {"ok": True, "assignments": [_admin_assignment(row, now) for row in homework_rows]},
            "notificationEventsQueued": queued,
        })
    latest_entry = getattr(log_result, "json_conflict_entry", None) if log_result is not None else None
    code = "revision_conflict" if reconciliation["state"] == "blocked" else "partial_failure"
    return _reply({
        "ok": False, "code": code, "retryable": reconciliation["state"] == "partial_failure",
        "operationId": operation_id, "reconciliationId": reconciliation["id"],
        "entry": latest_entry or desired_entry,
        "log": {"ok": reconciliation["log_state"] == "succeeded"},
        "homework": {"ok": reconciliation["homework_state"] == "succeeded"},
    }, 409)


def create_blueprints(
    dependencies: StudentHomeworkApiDependencies | None = None,
    *,
    admin_authorizer: Callable[[str | None], bool] | None = None,
) -> tuple[Blueprint, Blueprint]:
    provider = _Provider(dependencies)
    return create_public_blueprint(provider), create_admin_blueprint(provider, admin_authorizer=admin_authorizer)


bp_api_student_homework, bp_api_student_homework_admin = create_blueprints()


__all__ = (
    "StudentHomeworkApiDependencies",
    "bp_api_student_homework",
    "bp_api_student_homework_admin",
    "create_blueprints",
)
