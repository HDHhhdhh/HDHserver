from __future__ import annotations

import json
from .contracts import ApiError, date_key, network, now
from .ledger import Ledger


def assignment_id(date: str, sid: str, kind: str, item: str, round_no=0) -> str:
    return ":".join((date, sid, kind, item, str(round_no)))


def parse_assignment(value: str, sid: str):
    parts = value.split(":")
    if len(parts) != 5 or parts[1] != sid or parts[2] != "test" or parts[4] not in {"1", "2", "3"}:
        raise ApiError("not_found", 404)
    date_key(parts[0])
    return parts[0], parts[3], int(parts[4])


def bootstrap(sid: str, date: str) -> dict:
    from routes.api_basic import api_student_bootstrap
    response = api_student_bootstrap(student_sid=sid, date_key=date)
    if isinstance(response, tuple):
        response, status = response
        if status != 200:
            raise ApiError("not_found", status)
    return response.get_json()


def test_definition(item: dict) -> dict:
    from routes import api_basic, api_tests
    cfg = api_tests._load_tests_cfg()
    for candidate in api_basic._candidate_test_ids(item):
        found = api_tests._find_test_def_by_id(cfg, candidate)
        if found:
            return found
    return api_basic._find_test_config_for_assignment(item)


def test_assignments(sid: str, date: str, snapshot: dict) -> list[dict]:
    from routes import api_basic
    raw = api_basic.get_log_repository().read_entry(date, sid).entry
    fallback = api_basic.get_log_repository().read_json_map()
    progress = api_basic._load_progress_strict()
    items = api_basic._student_assigned_tests_for_date(
        progress, {date: {sid: raw}}, date, sid, fallback)
    # Bootstrap intentionally hides completed/skipped tests from its legacy
    # work queue. The native history adds only explicit current-day statuses;
    # cleared/missing assignments are never revived from old log metadata.
    by_label, log_labels, daily_labels = {}, [], []
    api_basic._collect_assigned_test_metadata({date: {sid: raw}}, date, sid, by_label, log_labels, daily_labels)
    if not log_labels:
        api_basic._collect_assigned_test_metadata(fallback, date, sid, by_label, log_labels, daily_labels)
    status_map = ((progress.get(date) or {}).get(sid) or {}).get("tests") or {}
    for label, value in status_map.items():
        status = api_basic._normalize_test_assignment_status(value)
        if status in {"done", "skip"} and label in by_label:
            items.append({**by_label[label], "status": status})
    items = api_basic._filter_assigned_tests_for_student_curriculum(items, snapshot.get("student", {}))
    result = []
    if not snapshot.get("courseBlocked"):
        for item in items:
            definition = test_definition(item)
            if not definition:
                continue
            round_no = int(api_basic._normalize_test_answer_round(item.get("round")) or "1")
            identifier = assignment_id(date, sid, "test", str(definition["id"]), round_no)
            result.append({"assignmentId": identifier, "date": date, "sid": sid,
                           "testId": str(definition["id"]), "round": round_no,
                           "title": str(item.get("label") or definition.get("name") or ""),
                           "metadata": item, "definition": definition, "blocked": False})
    # Completed assignments disappear from legacy bootstrap. The journal keeps
    # their stable identity, not a second scheduling policy.
    known = {row["assignmentId"] for row in result}
    for submission in Ledger().list(sid):
        payload = submission.get("payload") or {}
        assignment = payload.get("assignment")
        if assignment and assignment["date"] == date and assignment["assignmentId"] not in known:
            result.append({**assignment, "blocked": bool(snapshot.get("courseBlocked"))})
    return result


def resolve_test(identifier: str, sid: str, *, allow_stored=True) -> dict:
    date, test_id, round_no = parse_assignment(identifier, sid)
    if allow_stored:
        saved = Ledger().get(identifier)
        if saved and saved["sid"] == sid and saved.get("payload"):
            return saved["payload"]["assignment"]
    snapshot = bootstrap(sid, date)
    for row in test_assignments(sid, date, snapshot):
        if row["testId"] == test_id and row["round"] == round_no:
            if row.get("blocked"):
                raise ApiError("course_blocked", 403)
            if row["metadata"].get("status") == "skip":
                raise ApiError("invalid_state", 409)
            return row
    raise ApiError("not_found", 404)


def solution_available(assignment: dict, submission: dict | None = None) -> bool:
    if assignment["metadata"].get("solutionOpen") is True:
        return True
    return submission["state"] == "complete" if submission else bool(historical_result(assignment))


def historical_result(assignment: dict) -> dict | None:
    from routes import api_basic, api_tests
    date, sid = assignment["date"], assignment["sid"]
    # Malformed/unreadable history is not evidence of non-submission.
    try:
        data = json.loads(api_tests.TESTS_PATH.read_text("utf-8-sig"))
    except FileNotFoundError:
        data = {}
    records = list((data.get(date) or {}).get(sid) or [])
    records.extend(api_basic.get_log_repository().submission_records(date, sid))
    for row in records:
        if (isinstance(row, dict) and str(row.get("testId") or "") == assignment["testId"]
                and str(row.get("round") or 1) == str(assignment["round"])):
            wrong = [n for n in row.get("wrong", []) if type(n) is int and n > 0]
            return {"submittedAt": row.get("createdAt"), "score": row.get("score"), "pct": row.get("pct"),
                    "wrong": wrong, "wrongDetails": [{"questionNo": n} for n in wrong],
                    "solutionAvailable": True}
    return None


def item_projection(assignment: dict) -> dict:
    saved = Ledger().get(assignment["assignmentId"])
    history = historical_result(assignment) if not saved else None
    result = {
        "assignmentId": assignment["assignmentId"], "kind": "test",
        "title": assignment["title"],
        "status": "cancelled" if assignment["metadata"].get("status") == "skip" else
                  "graded" if history or saved and saved["state"] == "complete" else
                  "submitted" if saved or assignment["metadata"].get("status") == "done" else "in_progress" if
                  assignment["metadata"].get("status") == "interrupted" else "not_started",
        "solutionAvailable": solution_available(assignment, saved),
        "lockedReason": "course_blocked" if assignment.get("blocked") else
                        None if network()["academy"] else "outside_academy",
    }
    if saved and saved["state"] == "complete":
        response = saved["response"]
        result.update(submittedAt=response["submittedAt"],
                      score={"pct": response["pct"], "wrong": response["wrong"]})
    elif history:
        result.update(submittedAt=history["submittedAt"],
                      score={"pct": history["pct"], "wrong": history["wrong"]})
    due = assignment["metadata"].get("dueAt")
    if isinstance(due, str):
        result["dueAt"] = due
    return result


def day_items(sid: str, date: str):
    from routes import api_basic
    snapshot = bootstrap(sid, date)
    items = []
    watch = (snapshot.get("watch") or {}).get("watch") or {}
    progress = (api_basic._load_progress_strict().get(date) or {}).get(sid) or {}
    for kind, field in (("video", "videos"), ("review", "reviewVideos")):
        for video in snapshot.get(field) or []:
            mid = str(video.get("mid") or "")
            state = watch.get(mid) or {}
            value = progress.get(mid, video.get("status"))
            value = value.get("status") if isinstance(value, dict) else value
            fraction = min(1, max(0, float(state.get("last") or 0) / float(state.get("dur") or 1)))
            items.append({
                "assignmentId": assignment_id(date, sid, kind, mid),
                "kind": kind, "title": str(video.get("title") or video.get("name") or ""),
                "status": "watched" if value == "done" or state.get("completed") else
                          "cancelled" if value == "skip" else "in_progress" if fraction else "not_started",
                "progress": fraction, "solutionAvailable": False,
                "lockedReason": None if network()["academy"] else "outside_academy",
            })
    items.extend(item_projection(row) for row in test_assignments(sid, date, snapshot))
    return snapshot, items


def video_assigned(sid: str, mid: str) -> bool:
    snapshot = bootstrap(sid, now().date().isoformat())
    return not snapshot.get("courseBlocked") and any(
        str(row.get("mid") or "") == mid
        for key in ("videos", "reviewVideos") for row in snapshot.get(key) or [])


def homework_summary(sid: str, date: str) -> dict:
    from routes.api_student_homework import _build_dependencies
    deps = _build_dependencies()
    result = {"open": 0, "dueToday": 0, "overdue": 0}
    if not deps.config.homework_enabled:
        return result
    cursor = None
    from core.student_homework_service import _cursor_values
    while True:
        rows, more = deps.repository.list_for_sid(sid, cursor=cursor)
        for row in rows:
            result["open"] += 1
            due = str(row.get("due_at") or "")[:10]
            result["dueToday"] += int(due == date)
            result["overdue"] += int(bool(due) and due < date)
        if not more:
            break
        cursor = _cursor_values(rows[-1])
    return result


def notice(sid: str) -> dict | None:
    from routes.api_announcements import api_announcements, api_announce_status
    response = api_announcements()
    if isinstance(response, tuple):
        response = response[0]
    data = response.get_json()
    rows = data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []
    statuses = api_announce_status().get_json()
    rows = [row for row in rows if isinstance(row, dict)
            and not (statuses.get(str(row.get("id"))) or {}).get("acked")]
    rows.sort(key=lambda row: (bool(row.get("requireCompletion")), str(row.get("createdAt") or "")), reverse=True)
    return {key: rows[0].get(key) for key in ("id", "title", "createdAt", "requireCompletion")} if rows else None
