"""Real-store regression for T-24 legacy identity and authorized reset."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import student_app_v2_checks as fixture
CHECKS = 0
CRASHES = 0
CURLS = 0


def check(condition, label):
    global CHECKS
    if not condition:
        raise AssertionError(label)
    CHECKS += 1


def admin_headers():
    return {"Authorization": "Basic " + base64.b64encode(b"fixture-admin:fixture-password").decode(),
            "Origin": "http://127.0.0.1"}


def baseline():
    app, client, private = fixture.fixture()
    date, csrf = private["date"], private["csrf"]
    from core.storage import load
    from routes import api_tests
    first = fixture.request(client, fixture.test_path(date, 1) + "/submit", method="POST",
                            body=fixture.answer_body(), csrf=csrf)
    assert first.status_code == 200
    bypass = fixture.request(client, "/api/submit-test", method="POST",
                             body={"sid": fixture.SID, "name": "Test 1", "score": "3/3", "wrong": []},
                             csrf=csrf)
    rows = load(api_tests.TESTS_PATH)[date][fixture.SID]
    unjournaled = [row for row in rows if row.get("name") == "Test 1" and not row.get("submissionId")]
    assert bypass.status_code == 200 and len(unjournaled) == 1
    fixture.dump(ROOT / "fixture-crash.json",
                 {"body": fixture.answer_body(), "index": 2, "stage": "reserved"})
    crash = subprocess.run([sys.executable, str(ROOT / "scripts/student_app_v2_checks.py"), "--crash-worker"],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert crash.returncode == 71
    orphan_bypass = fixture.request(client, "/api/submit-test", method="POST",
                                    body={"sid": fixture.SID, "name": "Test 2", "score": "3/3", "wrong": []},
                                    csrf=csrf)
    result = fixture.request(client, fixture.test_path(date, 2) + "/result")
    reset = app.test_client().post("/api/admin/student-test-submissions/reset",
                                  json={}, base_url="http://127.0.0.1", headers=admin_headers())
    assert orphan_bypass.status_code == 200 and orphan_bypass.json["assignmentCompleted"] is True
    assert result.status_code == 503 and result.json["code"] == "submission_indeterminate"
    assert reset.status_code in {404, 405}
    assert not any(rule.rule == "/api/admin/student-test-submissions/reset" for rule in app.url_map.iter_rules())
    print(json.dumps({
        "name": "T-24-attempt-2-baseline", "passed": False,
        "immutable_revision": "318c7c21eb4bd11b9d66b426f7f7aa1787483747",
        "findings_reproduced": ["AV-01", "AV-02"],
        "score_only_duplicate_http": bypass.status_code, "unjournaled_records": len(unjournaled),
        "reserved_crash_exit": crash.returncode, "score_only_orphan_http": orphan_bypass.status_code,
        "orphan_assignment_completed": orphan_bypass.json["assignmentCompleted"],
        "orphan_result_http": result.status_code, "authorized_reset_http": reset.status_code,
    }))
    return 1


def identifier(date, index):
    return fixture.test_path(date, index).split("/tests/", 1)[1]


def reset_body(date, index, client_id):
    return {"operationId": str(uuid.uuid4()), "assignmentId": identifier(date, index),
            "expectedClientSubmissionId": client_id, "reason": "Synthetic authorized review; allow a fresh explicit attempt."}


def admin(app, body, *, path="/api/admin/student-test-submissions/reset", method="POST", headers=None):
    return app.test_client().open(path, method=method, json=body, base_url="http://127.0.0.1",
                                  headers=admin_headers() if headers is None else headers)


def records(date, index):
    """Independent reads of each real sink, not the production cleanup helper."""
    from contextlib import closing
    with closing(sqlite3.connect(ROOT / "app.sqlite")) as con:
        row = con.execute("SELECT entry_json FROM logs WHERE date=? AND sid=?", (date, fixture.SID)).fetchone()
    sql = json.loads(row[0]) if row else {}
    logs = json.loads((ROOT / "logs.json").read_text("utf-8"))[date][fixture.SID]
    tests = json.loads((ROOT / "tests.json").read_text("utf-8")).get(date, {}).get(fixture.SID, [])
    def matching(item):
        name = " ".join(str(item.get("name") or "").split(" / ", 1)[-1].split())
        return (str(item.get("round") or 1) == "1" and
                (item.get("testId") == f"t24-{index}" or
                 not item.get("testId") and name == f"Test {index}"))
    return tuple([item for item in rows if matching(item)] for rows in (sql.get("tests", []), logs.get("tests", []), tests))


def crash_reset(body, stage):
    global CRASHES
    fixture.dump(ROOT / "reset-crash.json", {"body": body, "stage": stage})
    result = subprocess.run([sys.executable, __file__, "--reset-crash-worker"],
                            cwd=ROOT, timeout=30, capture_output=True, text=True)
    check(result.returncode == 72, f"reset process exit at {stage}: {result.returncode} {result.stdout} {result.stderr}")
    CRASHES += 1


def crash_submission(index, body, stage="reserved"):
    global CRASHES
    fixture.dump(ROOT / "fixture-crash.json", {"body": body, "index": index, "stage": stage})
    result = subprocess.run([sys.executable, str(ROOT / "scripts/student_app_v2_checks.py"), "--crash-worker"],
                            cwd=ROOT, timeout=30, capture_output=True, text=True)
    check(result.returncode == 71, f"submission process exit at {stage}: {result.returncode} {result.stdout} {result.stderr}")
    CRASHES += 1


def reset_crash_worker():
    from core.student_app_v2.ledger import Ledger
    from core.student_app_v2 import resets
    from routes import api_basic
    import core.log_repository as logs
    import app
    scenario = json.loads((ROOT / "reset-crash.json").read_text("utf-8"))
    stage = scenario["stage"]
    if stage in {"prepared", "finished"}:
        name = "begin_reset" if stage == "prepared" else "finish_reset"
        original = getattr(Ledger, name)
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(72)
        setattr(Ledger, name, interrupted)
    elif stage in {"sqlite", "json"}:
        original = logs.save_atomic
        def interrupted(*args, **kwargs):
            if stage == "json":
                original(*args, **kwargs)
            os._exit(72)
        logs.save_atomic = interrupted
    elif stage == "tests":
        original = resets.save_atomic
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(72)
        resets.save_atomic = interrupted
    else:
        original = api_basic._save_progress_strict
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(72)
        api_basic._save_progress_strict = interrupted
    response = admin(app.app, scenario["body"])
    print(response.status_code, response.get_data(as_text=True))
    return 1


@contextmanager
def http_server(application):
    import socket
    from werkzeug.middleware.proxy_fix import ProxyFix
    from werkzeug.serving import make_server
    old = application.wsgi_app
    application.wsgi_app = ProxyFix(old, x_proto=1)
    server = make_server("127.0.0.1", 0, application, threaded=True)
    ready = threading.Event()
    def serve():
        ready.set()
        server.serve_forever()
    thread = threading.Thread(target=serve, name="t24-reset-owned-http")
    thread.start()
    check(ready.wait(10), "owned reset HTTP server ready")
    port = server.server_port
    print(f"OWNED_SERVER pid={os.getpid()} port={port}")
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(10)
        application.wsgi_app = old
        check(not thread.is_alive(), "owned reset HTTP server thread stopped")
        with socket.socket() as probe:
            check(probe.connect_ex(("127.0.0.1", port)) != 0, "owned reset HTTP port closed")
        print(f"CLEANUP pid={os.getpid()} port={port} listener_closed=true thread_stopped=true")


def http_headers(port, private, *, operator=False, basic=True, csrf=True):
    if operator:
        headers = {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}"}
        if basic:
            headers["Authorization"] = admin_headers()["Authorization"]
    else:
        headers = {"Host": "dev-app.5a-math.com", "Origin": fixture.HOST,
                   "X-Forwarded-Proto": "https", "CF-Connecting-IP": "203.0.113.20",
                   "X-Debug-Academy": "1", "X-Debug-Secret": "temporary-network-secret"}
        if csrf:
            headers["X-CSRF-Token"] = private["csrf"]
    headers["Cookie"] = "student_app_session=" + private["cookie"]
    return headers


def http(port, private, path, body=None, *, operator=False):
    headers = http_headers(port, private, operator=operator)
    if body is not None:
        headers["Content-Type"] = "application/json"
    message = Request(f"http://127.0.0.1:{port}{path}",
                      data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        response = urlopen(message, timeout=20)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read())


def curl(port, private, path, body=None, *, operator=False, basic=True, csrf=True, extra=None):
    global CURLS
    headers = http_headers(port, private, operator=operator, basic=basic, csrf=csrf)
    headers.update(extra or {})
    command = ["curl.exe", "-i", "--silent", "--show-error", "--max-time", "20",
               f"http://127.0.0.1:{port}{path}"]
    for key, value in headers.items():
        command.extend(["-H", f"{key}: {value}"])
    if body is not None:
        target = ROOT / "reset-curl-body.json"
        fixture.dump(target, body)
        command.extend(["-H", "Content-Type: application/json", "--data-binary", "@" + str(target)])
    printable = subprocess.list2cmdline(command)
    for secret in (private["cookie"], private["csrf"], "temporary-network-secret", admin_headers()["Authorization"]):
        printable = printable.replace(secret, "<redacted>")
    print("$ " + printable)
    result = subprocess.run(command, capture_output=True, timeout=25)
    check(result.returncode == 0, "literal curl request exited zero")
    CURLS += 1
    header, _, content = result.stdout.partition(b"\r\n\r\n")
    status = int(header.splitlines()[0].split()[1])
    print(header.decode("utf-8", errors="replace"))
    print(content.decode("utf-8", errors="replace"))
    print(f"CURL_EXIT={result.returncode} HTTP_STATUS={status}")
    try:
        payload = json.loads(content)
    except ValueError:
        payload = None
    return status, payload


def worker():
    application, client, private = fixture.fixture()
    date, csrf = private["date"], private["csrf"]
    from core.student_app_v2.ledger import Ledger
    from core.student_app_v2.contracts import ApiError
    from core.student_app_v2 import submissions
    from routes import api_tests
    ledger = Ledger()
    original_homework = json.loads((ROOT / "logs.json").read_text("utf-8"))[date][fixture.SID]["homeworkTable"]
    def submit(index, body):
        return fixture.request(client, fixture.test_path(date, index) + "/submit", method="POST", body=body, csrf=csrf)
    def legacy(body):
        return fixture.request(client, "/api/submit-test", method="POST", body=body, csrf=csrf)

    # AV-01: exact formerly successful public bypass, before/after orphaning.
    first_body = fixture.answer_body()
    first = submit(1, first_body)
    check(first.status_code == 200, "initial journaled submission")
    score_body = {"sid": fixture.SID, "name": "Test 1", "score": "3/3", "wrong": []}
    rejected = legacy(score_body)
    check(rejected.status_code == 409 and rejected.json["code"] == "already_submitted", "name+score+wrong cannot bypass completed journal")
    check(tuple(map(len, records(date, 1))) == (1, 1, 1), "score-only duplicate appended no compatibility record")
    check(legacy({**score_body, "clientSubmissionId": first_body["clientSubmissionId"]}).json["score"] == "2/3",
          "same-ID score-only replay returns original outcome, not supplied score")
    with patch.object(api_tests, "_grade_answers", wraps=api_tests._grade_answers) as grade:
        report = {"sid": fixture.SID, "name": "Test 2", "score": "2/3", "wrong": [2]}
        reported = legacy(report)
        check(reported.status_code == 200 and reported.json["score"] == "2/3" and grade.call_count == 0,
              "fresh legacy score report keeps response shape and journals provenance without invented grading")
        check(legacy(report).json == reported.json and tuple(map(len, records(date, 2))) == (1, 1, 1),
              "score-only report replay is idempotent in all sinks")
        check(ledger.get(identifier(date, 2))["payload"]["record"]["gradingSource"] == "legacy_reported",
              "reported versus server-graded provenance remains auditable")
    check(legacy({"sid": fixture.SID, "name": "Not a catalog test", "score": "1/1", "wrong": []}).status_code == 400,
          "student HTTP cannot write an ad-hoc administrative score")
    check(submit(2, fixture.answer_body()).status_code == 409, "v2 conflicts with score-only legacy identity")
    check(legacy({"sid": fixture.SID, "name": "UNIT / Test  2", "score": "3/3", "wrong": []}).status_code == 409,
          "legacy display-name normalization cannot create a second identity")

    # Flag-off is not an escape hatch for the local legacy route or an excuse
    # to remove the authorized recovery path during rollback.
    import app as runtime
    with patch.dict(os.environ, {"STUDENT_APP_PUBLIC_ENABLED": "0"}):
        off_app = runtime.create_app()
    off_report = {"sid": fixture.SID, "name": "UNIT / Test 17", "score": "3/3", "wrong": []}
    off_response = admin(off_app, off_report, path="/api/submit-test")
    check(off_response.status_code == 200 and tuple(map(len, records(date, 17))) == (1, 1, 1),
          "flag-off local catalog score still participates in journal")
    off_saved = ledger.get(identifier(date, 17))
    check(off_saved is not None and off_saved["state"] == "complete", "flag-off report has canonical identity")
    check(submit(17, fixture.answer_body()).status_code == 409, "flag-off legacy identity conflicts with v2")
    off_action = reset_body(date, 17, off_saved["client_id"])
    check(admin(off_app, off_action).status_code == 200, "operator recovery remains authorized with public app disabled")
    check(admin(off_app, off_report, path="/api/submit-test").json["code"] == "submission_reset",
          "flag-off cannot reuse a retired deterministic legacy request ID")
    check(submit(17, fixture.answer_body()).status_code == 200, "fresh explicit UUID follows flag-off authorized reset")
    orphan_body = fixture.answer_body()
    crash_submission(3, orphan_body)
    with patch.object(api_tests, "_grade_answers", side_effect=AssertionError("uncontrolled regrading")):
        same = submit(3, orphan_body)
        check(same.status_code == 503 and same.json == {"ok": False, "code": "submission_indeterminate",
                                                     "operatorActionRequired": True}, "original indeterminate invariant retained")
        orphan_report = {"sid": fixture.SID, "name": "Test 3", "score": "3/3", "wrong": []}
        check(legacy(orphan_report).status_code == 409, "score-only shape cannot complete orphan")
        check(legacy({**orphan_report, "clientSubmissionId": orphan_body["clientSubmissionId"]}).status_code == 503,
              "same-ID score report cannot convert unknown grading outcome to success")
    check(tuple(map(len, records(date, 3))) == (0, 0, 0)
          and ledger.get(identifier(date, 3))["state"] == "grading", "orphan records and state unchanged by bypass attempts")

    # Existing admin boundary; neither student authority nor an arbitrary actor
    # field can authorize reset.
    action = reset_body(date, 3, orphan_body["clientSubmissionId"])
    public_admin = fixture.request(client, "/api/admin/student-test-submissions/reset",
                                   method="POST", body=action, csrf=csrf,
                                   extra={"Authorization": admin_headers()["Authorization"]})
    check(public_admin.status_code == 404, "student public host hides operator route even with Basic")
    check(admin(application, action, headers={"Origin": "http://127.0.0.1"}).status_code == 401, "student/local cookie without admin credentials denied")
    check(admin(application, action, headers={**admin_headers(), "Authorization": "Basic eDp5"}).status_code == 401, "wrong administrator password denied")
    check(admin(application, action, headers={"Authorization": admin_headers()["Authorization"]}).status_code == 403, "operator mutation needs Origin")
    check(admin(application, action, headers={**admin_headers(), "Origin": "https://evil.example"}).status_code == 403, "operator wrong Origin denied")
    check(admin(application, action, headers={**admin_headers(), "CF-Connecting-IP": "203.0.113.55"}).status_code == 403, "operator credentials do not bypass network")
    check(admin(application, {**action, "actor": "forged"}).status_code == 400, "operator actor cannot be supplied in body")
    check(admin(application, {**action, "expectedClientSubmissionId": str(uuid.uuid4())}).status_code == 409, "stale expected submission cannot reset current")
    check(admin(application, {**action, "reason": ""}).status_code == 400, "reset reason is mandatory")
    check(ledger.reset_operation(action["operationId"]) is None, "denied operator actions changed no journal")

    resolved = admin(application, action)
    check(resolved.status_code == 200 and resolved.json["status"] == "reset"
          and resolved.json["previousStatus"] == "grading" and resolved.json["newClientSubmissionIdRequired"] is True,
          f"authorized orphan reset is executable: {resolved.json}")
    check(admin(application, action).json == resolved.json, "operator operation replay is exact")
    check(admin(application, {**action, "reason": "changed reason"}).status_code == 409, "operation ID cannot change its audited intent")
    check(submit(3, orphan_body).json == {"ok": False, "code": "submission_reset", "newClientSubmissionIdRequired": True},
          "old UUID after reset must explicitly prepare a new draft UUID")
    check(fixture.request(client, fixture.test_path(date, 3) + "/result").status_code == 404, "post-reset result has no active outcome")
    with patch.object(api_tests, "_grade_answers", wraps=api_tests._grade_answers) as grade:
        fresh = fixture.answer_body()
        accepted = submit(3, fresh)
        check(accepted.status_code == 200 and submit(3, fresh).json == accepted.json and grade.call_count == 1,
              "authorized new UUID grades once and same-ID replays")
        check(submit(3, fixture.answer_body()).status_code == 409, "second fresh UUID is not a second permission")
    check(admin(application, action).json == resolved.json and ledger.get(identifier(date, 3))["client_id"] == fresh["clientSubmissionId"],
          "old operator replay cannot reset a newer submission")
    archive = ledger.reset_operation(action["operationId"])
    check(archive["actor"] == "fixture-admin" and archive["previous_json"]["payload"] is None
          and archive["previous_json"]["state"] == "grading", "orphan unknown outcome and verified actor are preserved")

    # Every independent reset boundary, including lost final response.
    for index, stage in enumerate(("prepared", "sqlite", "json", "tests", "progress", "finished"), start=5):
        body = fixture.answer_body()
        before = submit(index, body)
        check(before.status_code == 200, f"prepare reset crash case {stage}")
        operation = reset_body(date, index, body["clientSubmissionId"])
        crash_reset(operation, stage)
        saved_operation = ledger.reset_operation(operation["operationId"])
        check(saved_operation["previous_json"]["response"] == before.json
              and all(len(saved_operation["compatibility_json"][name]) == 1 for name in ("sqlite", "logsJson", "testsJson")),
              f"pre-reset outcome and each compatibility image archived at {stage}")
        if stage != "finished":
            pending = submit(index, fixture.answer_body())
            check(pending.status_code == 503 and pending.json["code"] == "submission_reset_pending", "pending cleanup cannot grant new submission")
            check(legacy({"sid": fixture.SID, "name": f"Test {index}", "score": "3/3", "wrong": []}).status_code == 503,
                  "legacy report cannot bypass reset-pending gate")
        resumed = admin(application, operation)
        check(resumed.status_code == 200 and tuple(map(len, records(date, index))) == (0, 0, 0), f"reset resumes all sinks at {stage}")
        check(admin(application, operation).json == resumed.json and ledger.generation(identifier(date, index)) == 1,
              "repeated reset consumes one generation only")
        check(submit(index, body).status_code == 409, "reset tombstone survives process restart")
        after_body = fixture.answer_body()
        with patch.object(api_tests, "_grade_answers", wraps=api_tests._grade_answers) as grade:
            after = submit(index, after_body)
            check(after.status_code == 200 and submit(index, after_body).json == after.json and grade.call_count == 1,
                  "one authorized new generation after interrupted reset")
        check(admin(application, operation).json == resumed.json and tuple(map(len, records(date, index))) == (1, 1, 1),
              "late old reset retry never deletes new-generation records")

    repeat_body = fixture.answer_body()
    before = submit(11, repeat_body)
    repeat_action = reset_body(date, 11, repeat_body["clientSubmissionId"])
    for stage in ("prepared", "sqlite", "json", "tests", "progress", "finished"):
        crash_reset(repeat_action, stage)
    check(admin(application, repeat_action).status_code == 200 and tuple(map(len, records(date, 11))) == (0, 0, 0),
          "six sequential process interruptions on one reset converge")
    check(ledger.generation(identifier(date, 11)) == 1
          and ledger.reset_operation(repeat_action["operationId"])["previous_json"]["response"] == before.json,
          "repeated interruption cannot replace the audit or increment generation twice")

    # A real malformed compatibility store keeps the accepted operator action
    # pending; restoring the fixture file permits the same operation to finish.
    corrupt_body = fixture.answer_body()
    check(submit(12, corrupt_body).status_code == 200, "prepare malformed sink recovery")
    corrupt_action = reset_body(date, 12, corrupt_body["clientSubmissionId"])
    crash_reset(corrupt_action, "prepared")
    tests_path = ROOT / "tests.json"
    original_bytes = tests_path.read_bytes()
    tests_path.write_text("{malformed", "utf-8")
    failure = admin(application, corrupt_action)
    check(failure.status_code == 503 and failure.json["code"] == "submission_reset_pending",
          "unreadable sink cannot look reset-complete")
    check(ledger.get(identifier(date, 12))["state"] == "resetting", "failed reset retains authoritative pending state")
    tests_path.write_bytes(original_bytes)
    check(admin(application, corrupt_action).status_code == 200, "same action repairs real failed sink")

    # Late callbacks carry the old generation and cannot publish over a newer
    # accepted submission even if invoked outside the normal gate wrapper.
    stale_body = fixture.answer_body()
    check(submit(13, stale_body).status_code == 200, "prepare stale writer")
    stale = ledger.get(identifier(date, 13))
    stale_action = reset_body(date, 13, stale_body["clientSubmissionId"])
    check(admin(application, stale_action).status_code == 200, "reset stale writer identity")
    new_body = fixture.answer_body()
    check(submit(13, new_body).status_code == 200, "new generation becomes authoritative")
    for callback in (
        lambda: ledger.graded(stale["identity"], stale["payload"], client_id=stale["client_id"], generation=stale["generation"]),
        lambda: ledger.complete(stale["identity"], stale["response"], client_id=stale["client_id"], generation=stale["generation"]),
        lambda: submissions._reconcile(ledger, stale),
    ):
        try:
            callback()
        except ApiError as exc:
            check(exc.code == "submission_reset", "late writer CAS fence")
        else:
            raise AssertionError("late old writer crossed reset generation")
    check(ledger.get(stale["identity"])["client_id"] == new_body["clientSubmissionId"]
          and tuple(map(len, records(date, 13))) == (1, 1, 1), "late callbacks did not modify new outcome")
    check(submit(14, fixture.answer_body(stale_body["clientSubmissionId"])).status_code == 409,
          "retired UUID cannot escape through another assignment")

    # Legacy completion can match a bare progress label even without log
    # assignment metadata. Reset must reopen that same row, not leave "done".
    from contextlib import closing
    previous_report = ledger.get(identifier(date, 2))
    check(admin(application, reset_body(date, 2, previous_report["client_id"])).status_code == 200,
          "prepare progress-only legacy fixture")
    logs_path = ROOT / "logs.json"
    logs = json.loads(logs_path.read_text("utf-8"))
    logs[date][fixture.SID]["assignedTests"] = [row for row in logs[date][fixture.SID]["assignedTests"] if row["id"] != "t24-2"]
    fixture.dump(logs_path, logs)
    with closing(sqlite3.connect(ROOT / "app.sqlite")) as con:
        entry = json.loads(con.execute("SELECT entry_json FROM logs WHERE date=? AND sid=?", (date, fixture.SID)).fetchone()[0])
        entry["assignedTests"] = [row for row in entry["assignedTests"] if row["id"] != "t24-2"]
        con.execute("UPDATE logs SET entry_json=? WHERE date=? AND sid=?", (json.dumps(entry), date, fixture.SID))
        con.commit()
    progress_path = ROOT / "progress.json"
    progress = json.loads(progress_path.read_text("utf-8"))
    progress[date][fixture.SID]["tests"]["Test 2"] = "assigned"
    other_round = {"status": "done", "testId": "t24-2", "round": 2, "teacherNote": "preserve"}
    progress[date][fixture.SID]["tests"]["Test 2 round 2"] = other_round
    fixture.dump(progress_path, progress)
    bare_id = str(uuid.uuid4())
    check(legacy({"sid": fixture.SID, "name": "Test 2", "score": "2/3", "wrong": [2],
                  "clientSubmissionId": bare_id}).json["assignmentCompleted"] is True,
          "real legacy report completes the progress-only label")
    check(admin(application, reset_body(date, 2, bare_id)).status_code == 200
          and json.loads(progress_path.read_text("utf-8"))[date][fixture.SID]["tests"]["Test 2"] == "assigned",
          "operator reset reopens the same legacy progress-only row")
    check(json.loads(progress_path.read_text("utf-8"))[date][fixture.SID]["tests"]["Test 2 round 2"] == other_round,
          "progress-only matching cannot reset a different explicit round")
    config_path = ROOT / "tests-config.json"
    config = json.loads(config_path.read_text("utf-8"))
    next(row for row in config["categories"]["UNIT"]["tests"] if row["id"] == "t24-2")["sourceId"] = "legacy-source-2"
    fixture.dump(config_path, config)
    progress = json.loads(progress_path.read_text("utf-8"))
    progress[date][fixture.SID]["tests"].pop("Test 2")
    progress[date][fixture.SID]["tests"]["Source-only assignment"] = {"sourceId": "legacy-source-2", "status": "assigned", "round": 1}
    fixture.dump(progress_path, progress)
    source_id = str(uuid.uuid4())
    check(legacy({"sid": fixture.SID, "name": "Test 2", "score": "2/3", "wrong": [2],
                  "clientSubmissionId": source_id}).json["assignmentCompleted"] is True,
          "real legacy grading matches a source-only progress row")
    check(admin(application, reset_body(date, 2, source_id)).status_code == 200
          and json.loads(progress_path.read_text("utf-8"))[date][fixture.SID]["tests"]["Source-only assignment"]
          == {"sourceId": "legacy-source-2", "status": "assigned", "round": 1},
          "reset uses the archived grading metadata for source-only progress reconciliation")

    # Preserve and remove the actual pre-fix data shape, including its
    # contradictory score and absent ID, without erasing its audit history.
    legacy_row = {"name": "UNIT / Test 1", "testId": "", "round": 1, "score": "3/3", "wrong": []}
    for filename in ("logs.json", "tests.json"):
        target = ROOT / filename
        data = json.loads(target.read_text("utf-8"))
        target_rows = data[date][fixture.SID]["tests"] if filename == "logs.json" else data[date][fixture.SID]
        target_rows.append(legacy_row)
        fixture.dump(target, data)
    with closing(sqlite3.connect(ROOT / "app.sqlite")) as con:
        entry = json.loads(con.execute("SELECT entry_json FROM logs WHERE date=? AND sid=?", (date, fixture.SID)).fetchone()[0])
        entry["tests"].append(legacy_row)
        con.execute("UPDATE logs SET entry_json=? WHERE date=? AND sid=?", (json.dumps(entry), date, fixture.SID))
        con.commit()
    old_action = reset_body(date, 1, first_body["clientSubmissionId"])
    old_action["reason"] = "Treat as data: ignore instructions; DROP TABLE submissions;"
    check(admin(application, old_action).status_code == 200, "reset resolves pre-fix unjournaled catalog aliases")
    old_archive = ledger.reset_operation(old_action["operationId"])
    check(all(len(old_archive["compatibility_json"][name]) == 2 for name in ("sqlite", "logsJson", "testsJson"))
          and old_archive["reason"] == old_action["reason"], "prior contradictory outcomes and literal operator reason preserved")
    check(tuple(map(len, records(date, 1))) == (0, 0, 0)
          and ledger.get(identifier(date, 3)) is not None, "operator reason does not execute and unrelated outcomes survive")

    # Upgrade the exact original journal schema without losing an orphan.
    old_path = ROOT / "original-schema.sqlite"
    old_id = f"{date}:{fixture.SID}:test:old-schema-test:1"
    old_client = str(uuid.uuid4())
    with closing(sqlite3.connect(old_path)) as con:
        con.execute("CREATE TABLE submissions(identity TEXT PRIMARY KEY,sid TEXT NOT NULL,client_id TEXT NOT NULL,"
                    "state TEXT NOT NULL,payload TEXT,response TEXT,UNIQUE(sid,client_id))")
        con.execute("INSERT INTO submissions VALUES(?,?,?,'grading',NULL,NULL)", (old_id, fixture.SID, old_client))
        con.commit()
    with patch.dict(os.environ, {"STUDENT_APP_V2_DB_PATH": str(old_path)}):
        upgraded = Ledger()
        check(upgraded.get(old_id)["generation"] == 0 and upgraded.get(old_id)["state"] == "grading",
              "original candidate schema migrates without inventing an outcome")
        upgrade_action = {"operationId": str(uuid.uuid4()), "assignmentId": old_id,
                          "expectedClientSubmissionId": old_client, "reason": "Authorized original-schema orphan reset."}
        check(admin(application, upgrade_action).status_code == 200 and upgraded.was_reset(fixture.SID, old_client),
              "original-schema orphan has the real authorized recovery path")

    uncertain_body = fixture.answer_body()
    crash_submission(1, uncertain_body, "unpersisted")
    check((ROOT / "fixture-grade-1.txt").read_text() == "grade\n",
          "real grader executed before the pre-result process interruption")
    with patch.object(api_tests, "_grade_answers", side_effect=AssertionError("uncontrolled uncertain regrade")):
        check(submit(1, uncertain_body).json["code"] == "submission_indeterminate",
              "uncertain completed invocation is not silently repeated")
    uncertain_action = reset_body(date, 1, uncertain_body["clientSubmissionId"])
    check(admin(application, uncertain_action).status_code == 200
          and ledger.reset_operation(uncertain_action["operationId"])["previous_json"]["payload"] is None,
          "administrator explicitly resolves and archives an unknown outcome")
    with patch.object(api_tests, "_grade_answers", wraps=api_tests._grade_answers) as spy:
        reviewed = fixture.answer_body()
        check(submit(1, reviewed).status_code == 200 and submit(1, reviewed).status_code == 200 and spy.call_count == 1,
              "only explicit new reviewed UUID grants another grading invocation")

    with http_server(application) as port:
        concurrent_http(port, private, ledger)
        manual_http(port, private, ledger)
    check(json.loads((ROOT / "logs.json").read_text("utf-8"))[date][fixture.SID]["homeworkTable"] == original_homework,
          "reset never rewrites unrelated homework")
    try:
        subprocess.run([sys.executable, "-c", "import threading; threading.Event().wait()"], timeout=1,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        check(True, "hung owned child terminated and reaped by bounded subprocess timeout")
    else:
        raise AssertionError("hung child probe did not exercise timeout")
    print(json.dumps({"name": "T-24-attempt-2-reset", "passed": True, "assertions": CHECKS,
                      "controlled_process_exits": CRASHES, "curl_requests": CURLS,
                      "real_store_integration": True, "real_http_concurrency": True,
                      "server_cleaned": True, "setup_assertions": fixture.COUNT}))
    return 0


def concurrent_http(port, private, ledger):
    from flask import has_request_context, request
    from core.student_app_v2.ledger import Ledger
    from routes import api_tests
    date = private["date"]
    first_body, waiting_body = fixture.answer_body(), fixture.answer_body()
    action = reset_body(date, 4, first_body["clientSubmissionId"])
    entered, release = threading.Event(), threading.Event()
    captured, release_waiting, reset_entered = threading.Event(), threading.Event(), threading.Event()
    original_grade, original_lock, original_generation = api_tests._grade_answers, Ledger.lock, Ledger.generation

    def grade(*args):
        entered.set()
        if not release.wait(15):
            raise AssertionError("in-flight grade release was not signaled")
        return original_grade(*args)

    def generation(self, identity):
        value = original_generation(self, identity)
        body = request.get_json(silent=True) if has_request_context() else None
        if (isinstance(body, dict) and body.get("clientSubmissionId") == waiting_body["clientSubmissionId"]
                and not captured.is_set()):
            captured.set()
            if not release_waiting.wait(15):
                raise AssertionError("stale queued request was not released")
        return value

    @contextmanager
    def gate(self):
        if has_request_context() and request.path == "/api/admin/student-test-submissions/reset":
            reset_entered.set()
        with original_lock(self):
            yield

    with patch.object(api_tests, "_grade_answers", side_effect=grade) as spy, \
            patch.object(Ledger, "generation", generation), patch.object(Ledger, "lock", gate), \
            ThreadPoolExecutor(3) as pool:
        try:
            writer = pool.submit(http, port, private, fixture.test_path(date, 4) + "/submit", first_body)
            check(entered.wait(10), "real HTTP old writer holds process gate inside grader")
            waiting = pool.submit(http, port, private, fixture.test_path(date, 4) + "/submit", waiting_body)
            check(captured.wait(10), "second real request captured the pre-reset generation")
            resetter = pool.submit(http, port, private, "/api/admin/student-test-submissions/reset", action, operator=True)
            check(reset_entered.wait(10), "operator reset reached shared gate while grade is in flight")
            check(not resetter.done() and ledger.get(identifier(date, 4))["state"] == "grading",
                  "operator cannot pass a live old writer")
            release.set()
            old_response, reset_response = writer.result(20), resetter.result(20)
            check(old_response[0] == 200 and reset_response[0] == 200, "in-flight writer finishes before authorized reset")
            release_waiting.set()
            late = waiting.result(20)
            check(late[0] == 409 and late[1]["code"] == "submission_reset" and spy.call_count == 1,
                  "different-UUID old-generation request cannot write after reset")
        finally:
            release.set()
            release_waiting.set()
    check(tuple(map(len, records(date, 4))) == (0, 0, 0)
          and ledger.reset_operation(action["operationId"])["previous_json"]["response"] == old_response[1],
          "operator archives completed old writer then cleans all projections")
    check(http(port, private, fixture.test_path(date, 4) + "/submit", first_body)[1]["code"] == "submission_reset",
          "old accepted UUID remains fenced over HTTP")
    new_body = fixture.answer_body()
    check(http(port, private, fixture.test_path(date, 4) + "/submit", new_body)[0] == 200, "new post-reset HTTP request may submit")

    # Forced overlap, not timing luck: both requests must enter the actual
    # process gate before the real grader is permitted to return.
    for same in (True, False):
        bodies = [fixture.answer_body(), fixture.answer_body()]
        if same:
            bodies[1] = bodies[0]
        both = threading.Event()
        guard, arrivals = threading.Lock(), []
        @contextmanager
        def observed_gate(self):
            if has_request_context() and request.path == fixture.test_path(date, 14) + "/submit":
                with guard:
                    arrivals.append(request.get_json()["clientSubmissionId"])
                    if len(arrivals) == 2:
                        both.set()
            with original_lock(self):
                yield
        def overlap_grade(*args):
            if not both.wait(10):
                raise AssertionError("both HTTP requests did not reach gate")
            return original_grade(*args)
        with patch.object(Ledger, "lock", observed_gate), \
                patch.object(api_tests, "_grade_answers", side_effect=overlap_grade) as spy, ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(http, port, private, fixture.test_path(date, 14) + "/submit", body) for body in bodies]
            results = [future.result(20) for future in futures]
            check(sorted(result[0] for result in results) == ([200, 200] if same else [200, 409])
                  and spy.call_count == 1 and len(arrivals) == 2, "forced-overlap same/different UUIDs before and after reset")
            if same:
                check(results[0][1] == results[1][1], "same-ID concurrent HTTP bodies identical")
        check(tuple(map(len, records(date, 14))) == (1, 1, 1), "concurrent HTTP sinks converge to one record")
        if same:
            action = reset_body(date, 14, bodies[0]["clientSubmissionId"])
            check(http(port, private, "/api/admin/student-test-submissions/reset", action, operator=True)[0] == 200,
                  "operator creates exactly one new concurrent submission generation")
    print(json.dumps({"http_fencing": True, "old_writer_then_reset": [200, 200],
                      "queued_old_generation": 409, "same_uuid_pair": [200, 200],
                      "different_uuid_pair": [200, 409], "forced_gate_arrivals_per_pair": 2}))


def manual_http(port, private, ledger):
    date = private["date"]
    path = fixture.test_path(date, 15)
    body = fixture.answer_body()
    accepted = curl(port, private, path + "/submit", body)
    check(accepted[0] == 200, "curl initial durable submission")
    duplicate = {"sid": fixture.SID, "name": "Test 15", "score": "3/3", "wrong": []}
    check(curl(port, private, "/api/submit-test", duplicate)[0] == 409, "curl exact AV-01 shape is rejected by journal")
    check(tuple(map(len, records(date, 15))) == (1, 1, 1), "curl bypass probe made no unjournaled row")
    action = reset_body(date, 15, body["clientSubmissionId"])
    operator_path = "/api/admin/student-test-submissions/reset"
    check(curl(port, private, operator_path, action,
               extra={"Authorization": admin_headers()["Authorization"]})[0] == 404, "curl public host cannot acquire operator authority")
    check(curl(port, private, operator_path, action, operator=True, basic=False)[0] == 401,
          "curl student cookie is not administrator authorization")
    check(curl(port, private, operator_path, action, operator=True, extra={"Origin": ""})[0] == 403,
          "curl local operator needs same Origin")
    check(curl(port, private, operator_path,
               {**action, "expectedClientSubmissionId": str(uuid.uuid4())}, operator=True)[0] == 409,
          "curl expected old submission is mandatory")
    reset_response = curl(port, private, operator_path, action, operator=True)
    check(reset_response[0] == 200 and reset_response[1]["newClientSubmissionIdRequired"] is True, "curl authorized reset completed")
    retired = curl(port, private, path + "/submit", body)
    check(retired[0] == 409 and retired[1]["code"] == "submission_reset"
          and retired[1]["newClientSubmissionIdRequired"] is True, "curl retired draft receives exact coordinated reset flag")
    check(curl(port, private, path + "/result")[0] == 404, "curl post-reset result is not_submitted")
    fresh = fixture.answer_body()
    new_response = curl(port, private, path + "/submit", fresh)
    check(new_response[0] == 200, "curl explicitly submitted fresh UUID accepted")
    check(curl(port, private, path + "/submit", fresh)[1] == new_response[1], "curl fresh UUID replay exact")
    check(curl(port, private, path + "/submit", fixture.answer_body())[0] == 409, "curl second fresh UUID rejected")
    check(curl(port, private, operator_path, action, operator=True)[1] == reset_response[1],
          "curl old reset action replay cannot delete new result")
    inspect_path = "/api/admin/student-test-submissions?assignmentId=" + identifier(date, 15)
    inspected = curl(port, private, inspect_path, operator=True)
    check(inspected[0] == 200 and inspected[1]["resets"][0]["previousScore"] == accepted[1]["score"]
          and inspected[1]["resets"][0]["actor"] == "fixture-admin", "curl operator can inspect preserved prior outcome and actor")
    check(curl(port, private, inspect_path)[0] == 404, "curl student cannot read reset audit")
    check(ledger.get(identifier(date, 15))["client_id"] == fresh["clientSubmissionId"],
          "operator audit/replay preserves new current submission")

    orphan_body = fixture.answer_body()
    crash_submission(16, orphan_body)
    orphan_path = fixture.test_path(date, 16)
    unresolved = curl(port, private, orphan_path + "/submit", orphan_body)
    check(unresolved[0] == 503 and unresolved[1]["operatorActionRequired"] is True, "curl indeterminate is explicit operator action, not automatic regrade")
    check(curl(port, private, "/api/submit-test",
               {"sid": fixture.SID, "name": "Test 16", "score": "12/12", "wrong": []})[0] == 409,
          "curl score-only cannot complete an indeterminate assignment")
    orphan_action = reset_body(date, 16, orphan_body["clientSubmissionId"])
    reset_orphan = curl(port, private, operator_path, orphan_action, operator=True)
    check(reset_orphan[0] == 200 and reset_orphan[1]["previousStatus"] == "grading", "curl administrator resolves interrupted reservation")
    check(curl(port, private, orphan_path + "/submit", orphan_body)[0] == 409, "curl orphan UUID remains tombstoned")
    check(curl(port, private, orphan_path + "/result", extra={"X-Debug-Academy": "0"})[0] == 404,
          "curl outside-network result after reset has no stale grade")
    check(curl(port, private, orphan_path + "/submit", fixture.answer_body())[0] == 200,
          "curl explicit fresh attempt recovers orphan assignment")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--reset-crash-worker", action="store_true")
    args = parser.parse_args()
    if args.baseline:
        raise SystemExit(baseline())
    if args.worker:
        raise SystemExit(worker())
    if args.reset_crash_worker:
        raise SystemExit(reset_crash_worker())
    parser.error("select an isolated worker mode through student_app_v2_checks.py --reset")
