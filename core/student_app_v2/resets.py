"""Authorized, archived reset saga sharing the submission process gate."""
from __future__ import annotations

import json

from core.storage import save_atomic, utc_now_isoz
from core.student_public_surface_paths import strict_sid
from .contracts import ApiError, request_id
from .ledger import Ledger
from .locks import recovery_lock
from .projections import parse_assignment, record_matches


def identity(value) -> tuple[str, str, str, int]:
    if not isinstance(value, str) or len(value) > 512:
        raise ApiError("invalid_assignment")
    parts = value.split(":")
    if len(parts) != 5 or strict_sid(parts[1]) is None or strict_sid(parts[3]) is None:
        raise ApiError("invalid_assignment")
    date, test_id, round_no = parse_assignment(value, parts[1])
    return date, parts[1], test_id, round_no


def _assignment(saved: dict) -> dict:
    from routes import api_basic, api_tests
    if saved.get("payload"):
        return saved["payload"]["assignment"]
    date, sid, test_id, round_no = identity(saved["identity"])
    definition = api_tests._find_test_def_by_id(api_tests._load_tests_cfg(), test_id) or {"id": test_id}
    entry = api_basic.get_log_repository().read_entry(date, sid).entry
    metadata = next((item for item in entry.get("assignedTests", [])
                     if isinstance(item, dict) and str(item.get("testId") or item.get("id")) == test_id
                     and str(item.get("round") or 1) == str(round_no)), {})
    return {"assignmentId": saved["identity"], "date": date, "sid": sid, "testId": test_id,
            "round": round_no, "definition": definition, "metadata": metadata}


def _tests_store(path) -> dict:
    try:
        value = json.loads(path.read_text("utf-8-sig"))
    except FileNotFoundError:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("invalid tests store")
    return value


def _snapshot(saved: dict, assignment: dict) -> dict:
    from routes import api_basic, api_tests
    date, sid = assignment["date"], assignment["sid"]
    matches = lambda row: record_matches(row, assignment)
    result = api_basic.get_log_repository().submission_reset_snapshot(date, sid, matches)
    with recovery_lock(api_tests.TESTS_PATH):
        result["testsJson"] = [row for row in (_tests_store(api_tests.TESTS_PATH).get(date) or {}).get(sid, [])
                               if matches(row)]
    with recovery_lock(api_tests.PRG_PATH):
        progress = api_basic._load_progress_strict(api_tests.PRG_PATH)
        tests = ((progress.get(date) or {}).get(sid) or {}).get("tests") or {}
        eligible = {name: value for name, value in tests.items()
                    if not isinstance(value, dict) or value.get("round") is None
                    or str(value["round"]) == str(assignment["round"])}
        label = assignment["metadata"].get("label")
        # Legacy progress may contain only a display label and "done", with
        # no assignedTests metadata or embedded ID. Invert the same matching
        # rule that completed those rows rather than inventing another label
        # grammar for reset.
        record = (saved.get("payload") or {}).get("record") or {
            "name": assignment["definition"].get("name", ""), "testId": assignment["testId"]}
        meta = record.get("testMeta") or api_tests._resolve_test_meta(
            record["name"], record["testId"], api_tests._build_test_catalog(api_tests._load_tests_cfg()))
        record = {**record, "sourceId": record.get("sourceId") or meta.get("source_id", "")}
        meta = {**meta, "round": str(assignment["round"])}
        active_view = {
            name: ({**value, "status": "assigned"} if isinstance(value, dict) else "assigned")
            if api_tests._test_assignment_status_name(value) == "done" else value
            for name, value in eligible.items()
        }
        matched_labels = api_tests._matching_submitted_assignment_labels(active_view, record, meta)
        result["progress"] = {}
        for name, value in eligible.items():
            same_id = (isinstance(value, dict)
                       and str(value.get("testId") or value.get("id") or "") == assignment["testId"]
                       and str(value.get("round") or assignment["round"]) == str(assignment["round"]))
            if name == label or same_id or name in matched_labels:
                result["progress"][name] = value
    result["assignment"] = assignment
    return result


def _cleanup(operation: dict) -> None:
    from routes import api_basic, api_tests
    snapshot = operation["compatibility_json"]
    assignment = snapshot["assignment"]
    date, sid = assignment["date"], assignment["sid"]
    matches = lambda row: record_matches(row, assignment)
    api_basic.get_log_repository().reset_submission(date, sid, matches)
    with recovery_lock(api_tests.TESTS_PATH):
        data = _tests_store(api_tests.TESTS_PATH)
        rows = (data.get(date) or {}).get(sid) or []
        remaining = [row for row in rows if not matches(row)]
        if remaining != rows:
            data[date][sid] = remaining
            save_atomic(api_tests.TESTS_PATH, data)
    with recovery_lock(api_tests.PRG_PATH):
        data = api_basic._load_progress_strict(api_tests.PRG_PATH)
        tests = ((data.get(date) or {}).get(sid) or {}).get("tests") or {}
        changed = False
        for label, previous in snapshot["progress"].items():
            # Do not overwrite an administrator's intervening cancellation or
            # metadata edit. An already-applied reopen is an idempotent no-op.
            if tests.get(label) == previous and api_tests._test_assignment_status_name(previous) == "done":
                tests[label] = {**previous, "status": "assigned"} if isinstance(previous, dict) else "assigned"
                changed = True
        if changed:
            api_basic._save_progress_strict(data, api_tests.PRG_PATH)


def reset(body: dict, actor: str) -> dict:
    request_id(body.get("operationId"))
    identity(body.get("assignmentId"))
    expected, reason = body.get("expectedClientSubmissionId"), body.get("reason")
    if (not isinstance(expected, str) or not 1 <= len(expected) <= 128
            or not isinstance(reason, str) or not reason.strip() or len(reason) > 500):
        raise ApiError("invalid_payload")
    body = {**body, "reason": reason.strip()}
    ledger = Ledger()
    with ledger.lock():
        operation = ledger.reset_operation(body["operationId"])
        if operation:
            if operation["request_json"] != body:
                raise ApiError("idempotency_conflict", 409)
            if operation["state"] == "complete":
                return operation["response"]
        else:
            saved = ledger.get(body["assignmentId"])
            if saved is None or saved["client_id"] != expected:
                raise ApiError("submission_changed", 409)
            if saved["state"] == "resetting":
                raise ApiError("reset_in_progress", 409)
            assignment = _assignment(saved)
            snapshot = _snapshot(saved, assignment)
            operation = ledger.begin_reset(body, saved, snapshot, actor, utc_now_isoz())
        try:
            _cleanup(operation)
            response = {
                "ok": True, "status": "reset", "operationId": body["operationId"],
                "assignmentId": body["assignmentId"], "previousClientSubmissionId": operation["client_id"],
                "previousStatus": operation["previous_json"]["state"], "resetAt": utc_now_isoz(),
                "newClientSubmissionIdRequired": True,
            }
            ledger.finish_reset(operation, response)
            return response
        except ApiError:
            raise
        except Exception:
            raise ApiError("submission_reset_pending", 503) from None


def inspect(identifier: str) -> dict:
    identity(identifier)
    ledger = Ledger()
    with ledger.lock():
        current = ledger.get(identifier)
        result = None
        if current:
            outcome = current["response"] or (current["payload"] or {}).get("result") or {}
            result = {"clientSubmissionId": current["client_id"], "state": current["state"],
                      "submittedAt": outcome.get("submittedAt"), "score": outcome.get("score")}
        with ledger.connect() as con:
            operation_ids = [row[0] for row in con.execute(
                "SELECT operation_id FROM submission_resets WHERE identity=? ORDER BY generation", (identifier,))]
        history = []
        for operation_id in operation_ids:
            row = ledger.reset_operation(operation_id)
            previous = row["previous_json"]
            outcome = previous["response"] or (previous["payload"] or {}).get("result") or {}
            history.append({
                "operationId": operation_id, "state": row["state"], "actor": row["actor"],
                "reason": row["reason"], "createdAt": row["created_at"],
                "previousClientSubmissionId": row["client_id"], "previousStatus": previous["state"],
                "previousScore": outcome.get("score"), "resetAt": (row["response"] or {}).get("resetAt"),
            })
        return {"ok": True, "assignmentId": identifier, "current": result, "resets": history}
