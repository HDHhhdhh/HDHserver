"""Student completion uses the administrator's exact reconciliation protocol."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

from .contracts import ApiError, request_id
from .ledger import Ledger, canonical


def complete(sid: str, assignment_id: str, client_id: str) -> dict:
    from routes.api_basic import get_log_repository
    from routes.api_student_homework import _build_dependencies, _commit
    from core.student_homework_service import public_projection
    request_id(client_id)
    deps, ledger = _build_dependencies(), Ledger()
    if not deps.config.homework_enabled:
        raise ApiError("not_found", 404)
    with ledger.lock():
        row = deps.repository.get(sid, assignment_id)
        if row is None:
            raise ApiError("not_found", 404)
        with ledger.connect() as con:
            receipt = con.execute("SELECT * FROM homework_requests WHERE sid=? AND client_id=?",
                                  (sid, client_id)).fetchone()
        if receipt:
            if receipt["assignment"] != assignment_id:
                raise ApiError("idempotency_conflict", 409)
            body = json.loads(receipt["body"])
            target = next(item for item in body["homeworkRows"] if item["assignmentId"] == assignment_id)
            # A later administrator cancellation/reopen must not be resurrected
            # by an old mobile retry, even when the old operation completed.
            if (row["status"] == "cancelled" or row["revision"] > target["expectedRevision"] + 1
                    or (row["status"] == "assigned" and row["revision"] != target["expectedRevision"])):
                raise ApiError("invalid_state", 409)
        else:
            if row["status"] != "assigned":
                raise ApiError("invalid_state", 409)
            date = row["source_log_date"]
            rows = deps.repository.list_for_log_date(sid, date)
            entry = get_log_repository().read_entry(date, sid).entry
            table = deepcopy(entry.get("homeworkTable") or [])
            by_id = {item["id"]: item for item in rows}
            payloads = []
            matched = False
            timestamp = deps.clock().replace(microsecond=0).isoformat()
            for index, item in enumerate(table):
                current = by_id.get(item.get("assignmentId")) if isinstance(item, dict) else None
                if current is None or current["status"] == "cancelled":
                    raise ApiError("revision_conflict", 409)
                payload = {"rowIndex": index, "assignmentId": current["id"],
                           "expectedRevision": current["revision"]}
                if current["id"] == assignment_id:
                    matched = True
                    payload.update(status="completed", completedAt=timestamp)
                    item.update(status="completed", completedAt=timestamp, completedBy="student")
                payloads.append(payload)
            if not matched:
                raise ApiError("revision_conflict", 409)
            body = {
                "operationId": f"student-{client_id}", "sid": sid, "date": date,
                "logPatch": {"entry": {"homeworkTable": table}, "base": {},
                             "baseHomeworkTableExact": entry.get("homeworkTable") or []},
                "homeworkRows": payloads, "removedAssignmentIds": [],
            }
            with ledger.connect() as con:
                con.execute("INSERT INTO homework_requests VALUES(?,?,?,?)",
                            (sid, client_id, assignment_id, canonical(body)))
        response = _commit(deps, body)
        if isinstance(response, tuple):
            payload = response[0].get_json()
            raise ApiError(payload.get("code", "partial_failure"), response[1])
        saved = deps.repository.get(sid, assignment_id)
        if saved["status"] != "completed":
            raise ApiError("invalid_state", 409)
        return {"ok": True, "item": {**public_projection(saved, now=deps.clock()), "completedBy": "student"}}


def completed_by(repository, sid: str, assignment_id: str) -> str | None:
    row = repository.get(sid, assignment_id)
    if not row or row["status"] != "completed":
        return None
    path = Path(os.environ.get("STUDENT_APP_V2_DB_PATH", Path(repository.db_path).parent / "student-app-v2.sqlite"))
    if not path.exists():
        return "teacher"
    ledger = Ledger(path)
    with ledger.connect() as con:
        bodies = [json.loads(record[0]) for record in con.execute(
            "SELECT body FROM homework_requests WHERE sid=? AND assignment=?", (sid, assignment_id))]
    for body in bodies:
        for item in body["homeworkRows"]:
            if (item["assignmentId"] == assignment_id and item.get("status") == "completed"
                    and item.get("completedAt") == row["completed_at"]
                    and item["expectedRevision"] + 1 == row["revision"]):
                return "student"
    return "teacher"
