"""One grading reservation, durable result, independently repeatable sinks."""
from __future__ import annotations

import hashlib
from core.storage import load, save_atomic, utc_now_isoz
from .contracts import ApiError, answers_text, now, request_id
from .ledger import Ledger, canonical
from .locks import recovery_lock
from .projections import assignment_id, historical_result


def append_once(entry: dict, record: dict) -> dict:
    result = dict(entry) if isinstance(entry, dict) else {}
    rows = [row for row in result.get("tests", []) if isinstance(row, dict)]
    if not any(row.get("submissionId") == record["submissionId"] for row in rows):
        rows.append(record)
    result["tests"] = rows
    return result


def _reconcile(ledger: Ledger, saved: dict) -> dict:
    from routes import api_basic, api_tests
    if not saved.get("payload"):
        # No invocation can prove whether a killed process finished grading.
        raise ApiError("submission_indeterminate", 503)
    payload = saved["payload"]
    assignment, record = payload["assignment"], payload["record"]
    date, sid = assignment["date"], assignment["sid"]
    try:
        api_basic.get_log_repository().reconcile_submission(date, sid, record, append_once)
        with recovery_lock(api_tests.TESTS_PATH):
            data = load(api_tests.TESTS_PATH)
            if not isinstance(data, dict):
                raise ValueError("invalid test store")
            day = data.setdefault(date, {})
            rows = day.setdefault(sid, [])
            if not any(isinstance(row, dict) and row.get("submissionId") == record["submissionId"] for row in rows):
                rows.append({**record, "submittedAnswers": payload["answers"]})
                save_atomic(api_tests.TESTS_PATH, data)
        progress_result = payload["progress"]
        if progress_result["attempted"] and saved["state"] != "complete":
            with recovery_lock(api_tests.PRG_PATH):
                data = api_basic._load_progress_strict(api_tests.PRG_PATH)
                tests = ((data.get(date) or {}).get(sid) or {}).get("tests") or {}
                label = assignment["metadata"].get("label")
                labels = [label] if label in tests else api_tests._matching_submitted_assignment_labels(
                    tests, record, record["testMeta"])
                completed = False
                changed = False
                for name in labels:
                    status = api_tests._test_assignment_status_name(tests[name])
                    if status in {"assigned", "interrupted"}:
                        tests[name] = api_tests._test_assignment_done_value(tests[name])
                        changed = True
                        completed = True
                    elif status == "done":
                        completed = True
                if changed:
                    api_basic._save_progress_strict(data, api_tests.PRG_PATH)
                progress_result = {
                    **progress_result, "completed": completed,
                    "status": "done" if completed else "not_matched",
                    "reason": "progress_status_marked_done" if completed else "no_matching_active_assignment",
                }
        response = saved["response"] or {
            **payload["result"], "assignmentCompleted": bool(progress_result["completed"]),
            "assignmentProgress": progress_result,
        }
        if saved["state"] != "complete":
            ledger.complete(saved["identity"], response)
        return response
    except ApiError:
        raise
    except Exception:
        # Never expose raw paths, answer keys or a graded-success body here.
        raise ApiError("submission_pending", 503) from None


def replay(ledger: Ledger, identifier: str) -> dict:
    with ledger.lock():
        saved = ledger.get(identifier)
        if saved is None:
            raise ApiError("not_submitted", 404)
        return _reconcile(ledger, saved)


def submit(assignment: dict, body: dict, *, legacy=False) -> dict:
    from routes import api_tests
    ledger = Ledger()
    identifier = assignment["assignmentId"]
    client_id = body.get("clientSubmissionId")
    if legacy and client_id is None:
        client_id = "legacy-" + hashlib.sha256(canonical(body).encode()).hexdigest()
    else:
        client_id = request_id(client_id)
    with ledger.lock():
        saved = ledger.get(identifier)
        if saved:
            if saved["client_id"] != client_id:
                raise ApiError("already_submitted", 409)
            return _reconcile(ledger, saved)
        if historical_result(assignment) is not None:
            raise ApiError("already_submitted", 409)
        definition = assignment["definition"]
        count = definition.get("problems")
        if type(count) is not int or not 1 <= count <= 999:
            raise ApiError("test_unavailable", 503)
        key = api_tests._get_answer_key_for_round(definition, count, assignment["round"])
        if not key:
            raise ApiError("test_unavailable", 503)
        if body.get("round") != assignment["round"] or type(body.get("round")) is not int:
            raise ApiError("invalid_round")
        text = body.get("answersText") if legacy else answers_text(body, count)
        if not isinstance(text, str) or len(text) > 512000:
            raise ApiError("invalid_answers")
        memo = body.get("memo", "")
        if not isinstance(memo, str) or len(memo) > 2000:
            raise ApiError("invalid_memo")
        acknowledge = body.get("acknowledgeOffsetWarning", False)
        if type(acknowledge) is not bool:
            raise ApiError("invalid_payload")
        answers = api_tests._parse_answer_spec(text, count)
        # Offset detection needs only the direct-match count, not a grading
        # invocation. Rejected previews therefore do not consume the UUID.
        direct = sum(bool(k) and a.strip() == k.strip() for a, k in zip(answers, key))
        if api_tests._detect_shifted_answer_mapping(answers, key, direct) and not acknowledge:
            raise ApiError("possible_answer_offset", 409)
        ledger.reserve(identifier, assignment["sid"], client_id)
        correct, total, wrong, pct = api_tests._grade_answers(answers, key)
        timestamp = utc_now_isoz()
        meta = api_tests._resolve_test_meta(
            str(definition.get("name") or assignment["title"]), assignment["testId"],
            api_tests._build_test_catalog(api_tests._load_tests_cfg()))
        record = {
            "submissionId": client_id, "assignmentId": identifier,
            "testId": assignment["testId"], "round": assignment["round"],
            "name": str(definition.get("name") or assignment["title"]),
            "score": f"{correct}/{total}", "wrong": wrong, "memo": memo,
            "pct": pct, "createdAt": timestamp, "testMeta": meta,
            "type": meta.get("type", ""), "curriculum": meta.get("curriculum", ""),
            "testName": meta.get("test_name", ""), "unitName": meta.get("unit_name", ""),
            "testLevel": meta.get("test_level"), "difficulty": meta.get("difficulty", ""),
            "term": meta.get("term", ""), "sourceId": meta.get("source_id", ""),
        }
        result = {
            "ok": True, "status": "graded", "score": record["score"], "wrong": wrong,
            # Results outside the academy contain numbers only, never keys or
            # question/answer content. Legacy response details stay internal.
            "wrongDetails": [{"questionNo": n} for n in wrong],
            "pct": pct, "submittedAt": timestamp, "solutionAvailable": True,
        }
        payload = {
            "assignment": assignment, "record": record, "answers": answers,
            "result": result, "progress": api_tests._submit_progress_status_policy(body),
            "legacyWrongDetails": api_tests._wrong_answer_details(answers, key, wrong),
        }
        ledger.graded(identifier, payload)
        return _reconcile(ledger, ledger.get(identifier))


def legacy_submit(body: dict, definition: dict):
    from routes import api_basic
    sid = str(body.get("sid") or "").strip()
    date = now().date().isoformat()
    round_no = body.get("round", 1)
    try:
        round_no = int(round_no)
    except (ValueError, TypeError):
        round_no = 1
    if round_no not in (1, 2, 3):
        round_no = 1
    identifier = assignment_id(date, sid, "test", str(definition["id"]), round_no)
    raw = api_basic.get_log_repository().read_entry(date, sid).entry
    metadata = next((item for item in raw.get("assignedTests", [])
                     if isinstance(item, dict) and str(item.get("testId") or item.get("id")) == str(definition["id"])
                     and str(item.get("round") or 1) == str(round_no)), {})
    assignment = {"assignmentId": identifier, "date": date, "sid": sid,
                  "testId": str(definition["id"]), "round": round_no,
                  "title": str(definition.get("name") or ""), "metadata": metadata,
                  "definition": definition, "blocked": False}
    result = submit(assignment, {**body, "round": round_no}, legacy=True)
    saved = Ledger().get(identifier)
    result = {key: result[key] for key in (
        "ok", "score", "wrong", "wrongDetails", "pct", "assignmentCompleted", "assignmentProgress")}
    result["wrongDetails"] = saved["payload"]["legacyWrongDetails"]
    return result
