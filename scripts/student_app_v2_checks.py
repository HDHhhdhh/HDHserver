"""Isolated real-store student v2 regression and manual HTTP fixture."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import uuid
import datetime as dt
import threading
import hashlib
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def isolated_suite(*, baseline: bool = False, checks: bool = False, manual: bool = False,
                   refactor: bool = False, reset: bool = False, revision: str = "HEAD") -> int:
    """Run the existing dispatcher only in an owned disposable code copy."""
    with tempfile.TemporaryDirectory(prefix="student-v2-suite-") as raw:
        target = Path(raw)
        archive = subprocess.run(
            ["git", "archive", revision], cwd=ROOT, check=True, capture_output=True,
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(target, filter="data")
        if reset and baseline:
            # Only the reproducer is new; the product and original fixture
            # remain the immutable failed candidate.
            relative = "scripts/student_app_v2_reset_checks.py"
            (target / relative).write_bytes((ROOT / relative).read_bytes())
        if not baseline:
            tracked = subprocess.run(
                ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                cwd=ROOT, check=True, capture_output=True,
            ).stdout.decode().split("\0")
            for name in filter(None, tracked):
                source = ROOT / name
                if source.is_file():
                    destination = target / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(source.read_bytes())
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("STUDENT_APP_", "ACADEMY_ADMIN_", "DATA_MIRROR"))
               and k not in {"DB_PATH", "PYTHONPATH", "TRUSTED_PROXY_CIDRS"}}
        env.update(PYTHONPATH=str(target), PYTHONIOENCODING="utf-8",
                   DB_PATH=str(target / "app.sqlite"),
                   STUDENT_APP_DB_PATH=str(target / "app.sqlite"),
                   DATA_MIRROR_DIR=str(target / "_data_mirror"),
                   DATA_MIRROR_SNAPSHOTS="0", STUDENT_V2_ISOLATED="1")
        # paths.py initialization is setup, not a verification mutation.
        subprocess.run([sys.executable, "-c", "import core.paths"], cwd=target,
                       env=env, check=True)
        if not checks and not manual and not reset:
            # The unchanged Windows deployment fixture executes this exact
            # repository-relative interpreter, even in DryRun fixture mode.
            import venv
            venv.EnvBuilder(system_site_packages=True, with_pip=False).create(target / "venv")
        command = ([sys.executable, "scripts/student_app_v2_reset_checks.py", "--baseline" if baseline else "--worker"]
                   if reset else [sys.executable, "scripts/verify_refactor_safety.py"] if refactor else
                   [sys.executable, "scripts/student_app_v2_checks.py", "--manual-worker" if manual else "--worker"]
                   if checks or manual else
                   [sys.executable, "scripts/verify_student_mobile_app.py", "--only", "all"])
        result = subprocess.run(
            command, cwd=target, env=env, timeout=300, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        evidence = os.environ.get("T24_EVIDENCE_DIR")
        if evidence:
            destination = Path(evidence)
            destination.mkdir(parents=True, exist_ok=True)
            label = ("reset-baseline" if baseline else "reset") if reset else "refactor-baseline" if refactor and baseline else "refactor" if refactor else "baseline" if baseline else "manual" if manual else "v2" if checks else "existing"
            (destination / f"{label}.log").write_text(result.stdout + "\n" + result.stderr, "utf-8")
        print(json.dumps({"suiteExit": result.returncode, "baseline": baseline,
                          "isolated": True, "temporaryStateRemovedOnExit": True}))
        return result.returncode


HOST = "https://dev-app.5a-math.com"
SID = "synthetic-t24"
COUNT = 0


def check(condition, label):
    global COUNT
    if not condition:
        raise AssertionError(label)
    COUNT += 1


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False), "utf-8")


def fixture():
    if os.environ.get("STUDENT_V2_ISOLATED") != "1" or not ROOT.name.startswith("student-v2-suite-"):
        raise RuntimeError("Fixture refuses non-disposable runtime")
    from werkzeug.security import generate_password_hash
    os.environ.update(
        STUDENT_APP_PUBLIC_ENABLED="1", STUDENT_APP_PUBLIC_HOST="dev-app.5a-math.com",
        STUDENT_APP_HOMEWORK_ENABLED="1",
        STUDENT_APP_DEBUG_ACADEMY_SECRET="temporary-network-secret",
        STUDENT_APP_SOLUTION_SIGNING_SECRET="temporary-signing-secret",
        STUDENT_APP_CONTENT_ROOT=str(ROOT / "fixture-content"),
        STUDENT_APP_V2_DB_PATH=str(ROOT / "student-app-v2.sqlite"),
        STUDENT_APP_RELEASE_METADATA=str(ROOT / "fixture-release.json"),
        ACADEMY_ADMIN_USERNAME="fixture-admin",
        ACADEMY_ADMIN_PASSWORD_HASH=generate_password_hash("fixture-password"),
    )
    import app as runtime
    from routes import api_basic
    from core.student_homework_repository import StudentHomeworkRepository
    from core.student_homework_service import prepare_assignment, kst_iso, KST
    from core.storage import save_atomic
    application = runtime.app
    application.config["TESTING"] = True
    date = dt.datetime.now(KST).date().isoformat()
    admin = application.test_client()
    admin_headers = {"Authorization": "Basic " + __import__("base64").b64encode(b"fixture-admin:fixture-password").decode(),
                     "Origin": "http://127.0.0.1"}
    roster = admin.get("/api/students", base_url="http://127.0.0.1", headers=admin_headers)
    check(roster.status_code == 200, "admin fixture roster GET")
    days = ["월", "화", "수", "목", "금", "토", "일"]
    student = {"id": SID, "name": "T24Synthetic", "curriculum": "Math", "subCurriculum": "Basic",
               "school": "Synthetic", "grade": "1", "day1": days[dt.date.fromisoformat(date).weekday()] + "1"}
    created = admin.post("/api/students", json=[student], base_url="http://127.0.0.1",
                         headers={**admin_headers, "X-Students-Revision": roster.headers["X-Students-Revision"]})
    check(created.status_code == 204, "synthetic student created by real revision-checked admin route")
    tests, assigned, statuses = [], [], {}
    for index in range(1, 18):
        test_id, title = f"t24-{index}", f"Test {index}"
        definition = {"id": test_id, "name": title, "type": "UNIT", "curriculum": "Math",
                      "round": "1", "problems": 3, "answerTypes": ["short"] * 3,
                      "answerKeys": {"1": ["12", "2", "-4/5"]},
                      "sourceFiles": {"problemFileId": "problem", "solutionFileId": "solution"}}
        tests.append(definition)
        metadata = {"id": test_id, "testId": test_id, "type": "UNIT", "curriculum": "Math",
                    "name": title, "label": title, "round": "1", "status": "assigned",
                    "solutionOpen": index == 2}
        assigned.append(metadata)
        statuses[title] = {"status": "assigned", "testId": test_id, "round": 1}
    tests[15]["problems"] = 12
    tests[15]["answerKeys"] = {"1": [str(i) for i in range(1, 13)]}
    tests[15]["answerTypes"] = ["short"] * 12
    save_atomic(api_basic.TESTS_CFG_PATH, {"categories": {"UNIT": {"tests": tests}}})
    save_atomic(api_basic.VID_PATH, [{"mid": "video-assigned", "title": "Assigned", "curriculum": "Math", "subCurriculum": "Basic"},
                                    {"mid": "video-other", "title": "Not assigned", "curriculum": "Math", "subCurriculum": "Basic"}])
    save_atomic(api_basic.UPD_PATH, {date: {SID: ["video-assigned"]}})
    save_atomic(api_basic.PRG_PATH, {date: {SID: {"tests": statuses}}})
    repo = StudentHomeworkRepository(ROOT / "app.sqlite")
    repo.apply_migration((ROOT / "scripts/migrations/20260809_create_student_homework.sql").read_text("utf-8"))
    clock = dt.datetime.now(KST).replace(microsecond=0)
    rows = []
    for index in range(3):
        prepared = prepare_assignment({"sourceRowId": f"row-{index}", "title": f"Homework {index}",
                                       "book": "Book", "scope": "1-3", "assignedAt": kst_iso(clock)},
                                      sid=SID, source_log_date=date, now=clock)
        rows.extend(repo.apply_batch(SID, date, [prepared], now=kst_iso(clock)))
    entry = {"assignedTests": assigned, "homeworkTable": [
        {"book": row["book"], "next": row["scope"], "assignmentId": row["id"]} for row in rows]}
    save_atomic(api_basic.LOGS_PATH, {date: {SID: entry}})
    import fitz
    directory = ROOT / "fixture-content"
    directory.mkdir()
    with fitz.open() as pdf:
        pdf.new_page().insert_text((40, 50), "Synthetic problem page one")
        pdf.new_page().insert_text((40, 50), "Synthetic problem page two")
        pdf.save(directory / "problem")
    with fitz.open() as pdf:
        pdf.new_page().insert_text((40, 50), "Synthetic solution")
        pdf.new_page().insert_text((40, 50), "Synthetic solution page two")
        pdf.save(directory / "solution")
    dump(ROOT / "fixture-release.json", {
        "versionCode": 1, "versionName": "1.0.1", "minSupportedVersionCode": 1,
        "apkUrl": HOST + "/app/student-1.0.1.apk", "sha256": "a" * 64,
        "notes": "Synthetic metadata only; no APK publication", "publishedAt": clock.isoformat()})
    client = application.test_client()
    login = client.post("/api/mobile/auth/login", json={"id": "T24Synthetic", "password": "1234"},
                        base_url=HOST, headers={"Origin": HOST, "CF-Connecting-IP": "203.0.113.20"})
    check(login.status_code == 200 and login.json["state"] == "credentials_required",
          f"synthetic activation login: {login.status_code} {(login.json or {}).get('code')}")
    credentials = client.post("/api/mobile/auth/credentials",
                              json={"studentId": "t24-student", "password": "synthetic-password"},
                              base_url=HOST, headers={"Origin": HOST, "CF-Connecting-IP": "203.0.113.20",
                                                     "X-CSRF-Token": login.json["csrfToken"]})
    check(credentials.status_code == 200 and credentials.json["state"] == "ready", "activated real student session")
    csrf = credentials.json["csrfToken"]
    cookie = client.get_cookie("student_app_session", domain="dev-app.5a-math.com").value
    private = {"cookie": cookie, "csrf": csrf, "date": date, "homework": rows}
    dump(ROOT / "fixture-private.json", private)
    return application, client, private


def request(client, path, *, method="GET", body=None, academy=True, csrf=None, extra=None):
    headers = {"Origin": HOST, "X-Debug-Academy": "1" if academy else "0",
               "X-Debug-Secret": "temporary-network-secret", "CF-Connecting-IP": "203.0.113.20"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    headers.update(extra or {})
    return client.open(path, method=method, json=body, base_url=HOST, headers=headers)


def test_path(date, index):
    return f"/api/mobile/student/tests/{date}:{SID}:test:t24-{index}:1"


def answer_body(client_id=None):
    return {"clientSubmissionId": client_id or str(uuid.uuid4()), "round": 1,
            "answers": [{"n": 1, "value": "12"}, {"n": 2, "value": ""}, {"n": 3, "value": "-4/5"}]}


def worker():
    application, client, private = fixture()
    csrf, date = private["csrf"], private["date"]
    from core.student_app_v2.ledger import Ledger
    from core.student_app_v2 import submissions
    from core.student_app_v2.contracts import answers_text
    from core.log_repository import LogRepository
    from core.storage import load, save_atomic
    from routes import api_tests, api_basic
    check(answers_text(answer_body(), 3) == "1. 12\n3. -4/5", "sparse numbered answer conversion omits blanks")
    initial_hw = private["homework"][2]
    initial_path = "/api/mobile/student/homework/" + initial_hw["id"] + "/complete"
    initial_completion = request(client, initial_path, method="POST",
                                 body={"clientRequestId": str(uuid.uuid4())}, csrf=csrf, academy=False)
    check(initial_completion.status_code == 200, f"first write to JSON-only log keeps revision semantics: {initial_completion.json}")
    today = request(client, "/api/mobile/student/today")
    check(today.status_code == 200, f"today returns metadata: {today.status_code} {today.json}")
    check(today.json["profile"] == {"studentName": "T24Synthetic", "academyName": "5A"},
          "profile uses authenticated roster name and approved display brand")
    check(today.headers.get("Cache-Control") == "no-store", "profile response is not publicly cached")
    check(request(client, "/api/mobile/student/today?sid=forged-profile").status_code == 403,
          "profile rejects forged SID")
    students = load(api_basic.STU_PATH)
    try:
        for invalid_name in (None, "", " \t ", 123, [], {}):
            dump(api_basic.STU_PATH, [{**students[0], "name": invalid_name}])
            check(request(client, "/api/mobile/student/today").json["profile"]["studentName"] is None,
                  f"unusable roster name stays null: {invalid_name!r}")
        dump(api_basic.STU_PATH, [{**students[0], "name": "CurrentRosterName"}])
        check(request(client, "/api/mobile/student/today").json["profile"]["studentName"] == "CurrentRosterName",
              "profile uses current roster rather than stale login identity")
        from core.paths import ABS_PATH
        absences = load(ABS_PATH)
        try:
            dump(ABS_PATH, {"by_date": {date: [SID]}, "by_student": {}})
            real_blocked = request(client, "/api/mobile/student/today", academy=False)
            check(real_blocked.status_code == 200 and real_blocked.json["courseBlocked"] is not None
                  and real_blocked.json["profile"]["studentName"] == "CurrentRosterName",
                  "real course-blocked outside roster metadata remains available")
        finally:
            dump(ABS_PATH, absences)
        with patch("core.student_app_v2.projections.bootstrap",
                   return_value={"student": {"id": "forged", "name": "ForgedSnapshot"}, "courseBlocked": True}):
            blocked = request(client, "/api/mobile/student/today", academy=False)
            check(blocked.status_code == 200 and blocked.json["courseBlocked"] is not None
                  and blocked.json["profile"] == {"studentName": "CurrentRosterName", "academyName": "5A"},
                  "outside course-blocked profile ignores bootstrap identity")
    finally:
        dump(api_basic.STU_PATH, students)
    from core.student_app_v2 import projections
    with patch.object(api_basic, "load", return_value=[]):
        check(projections.profile(SID) == {"studentName": None, "academyName": "5A"},
              "missing roster row cannot fabricate identity")
    with patch.object(api_basic, "load", return_value=[{"id": SID}, {"id": "other", "name": "Other"}]):
        check(projections.profile(SID)["studentName"] is None, "missing name cannot use other roster identity")
    check(len(today.json["items"]) == 18, "today includes real scheduled video and seventeen tests")
    forbidden = {"url", "fileId", "mid", "answerKeys", "answers", "sourceFiles", "solutionFileId",
                 "phone", "email", "contact", "studentId", "sid"}
    def scan(value):
        if isinstance(value, dict):
            return bool(forbidden.intersection(value)) or any(scan(child) for child in value.values())
        return isinstance(value, list) and any(scan(child) for child in value)
    check(not scan(today.json), "list whitelist contains no content authority")
    outside = request(client, "/api/mobile/student/today", academy=False)
    check(outside.json["profile"] == today.json["profile"] and not scan(outside.json)
          and not scan(blocked.json), "outside and course-blocked profiles contain no protected or contact fields")
    check(len(outside.json["items"]) == 18 and all(item["lockedReason"] == "outside_academy" for item in outside.json["items"]),
          "outside network retains full sanitized list")
    check(request(client, "/api/mobile/student/assignments?from=bad").status_code == 400, "invalid date")
    check(request(client, "/api/mobile/student/assignments?cursor=bad").status_code == 400, "invalid cursor")
    check(request(client, f"/api/mobile/student/assignments?from={date}&to={date}&kind=test").json["items"][0]["kind"] == "test", "assignment filter")
    check(request(client, "/api/mobile/network/status", academy=False).json["academy"] is False, "secret outside override")
    check(request(client, "/api/mobile/network/status", extra={"X-Debug-Secret": "wrong"}).json["academy"] is False, "wrong secret ignored")
    with patch.dict(application.config, {"STUDENT_APP_PUBLIC_HOST": "app.5a-math.com"}):
        check(request(client, "/api/mobile/network/status").json["academy"] is False, "production config ignores override")
    check(application.test_client().get("/api/mobile/student/today", base_url=HOST, headers={"CF-Connecting-IP": "203.0.113.20"}).status_code == 401, "anonymous denied")
    check(client.get("/api/mobile/student/today", base_url=HOST + ":8004").status_code == 404, "public listener port rejected")
    check(request(client, "/api/get-url?mid=video-assigned&sid=" + SID).status_code == 200, "assigned video issued")
    check(request(client, "/api/get-url?mid=video-other&sid=" + SID).status_code == 403, "unassigned video denied")
    metadata = request(client, test_path(date, 1))
    check(metadata.status_code == 200 and metadata.json["problem"]["pages"] == 2, f"real PDF page count {metadata.json}")
    image = request(client, test_path(date, 1) + "/problem?page=2")
    check(image.status_code == 200 and image.data.startswith(b"\x89PNG"), "second PDF page renders actual PNG")
    check(image.headers.get("X-Document-Page-Count") == "2", "problem byte response carries total PDF page count")
    check(request(client, test_path(date, 1) + "/problem?page=3").status_code == 400, "out-of-range page")
    check(request(client, test_path(date, 1), academy=False).status_code == 403, "outside test metadata blocked")
    check(request(client, test_path(date, 1) + "/solution").json["code"] == "solution_locked", "pre-submit locked solution")
    check(request(client, test_path(date, 2) + "/solution").data.startswith(b"\x89PNG"), "teacher-open solution bytes")
    solution_page = request(client, test_path(date, 2) + "/solution?page=2")
    check(solution_page.status_code == 200 and solution_page.data.startswith(b"\x89PNG")
          and solution_page.headers.get("X-Document-Page-Count") == "2", "solution viewer can discover and request every PDF page")
    solution_file = ROOT / "fixture-content" / "solution"
    original_solution = solution_file.read_bytes()
    try:
        solution_file.write_bytes(image.data)
        single_page = request(client, test_path(date, 2) + "/solution")
        check(single_page.status_code == 200 and single_page.data == image.data
              and single_page.headers.get("X-Document-Page-Count") == "1", "PNG source has page count one without a body change")
    finally:
        solution_file.write_bytes(original_solution)
    check(request(client, test_path(date, 1).replace(SID, "foreign")).status_code == 404, "foreign assignment hidden")
    malformed = answer_body()
    malformed["answers"][0]["value"] = "12\n2. injected"
    check(request(client, test_path(date, 1) + "/submit", method="POST", body=malformed, csrf=csrf).status_code == 400, "multiline rejected")
    missing_csrf = request(client, test_path(date, 1) + "/submit", method="POST", body=answer_body())
    check(missing_csrf.status_code == 403 and missing_csrf.json["code"] == "csrf_required", "CSRF before submission")
    check(request(client, test_path(date, 1) + "/submit", method="POST", body=answer_body(), csrf=csrf,
                  extra={"Origin": "https://evil.example"}).status_code == 403, "exact Origin required")
    body = answer_body()
    with patch.object(api_tests, "_grade_answers", wraps=api_tests._grade_answers) as grade:
        first = request(client, test_path(date, 1) + "/submit", method="POST", body=body, csrf=csrf)
        check(first.status_code == 200 and first.json["status"] == "graded", f"durable grade {first.status_code} {first.json}")
        replayed = request(client, test_path(date, 1) + "/submit", method="POST", body=body, csrf=csrf)
        check(replayed.json == first.json and grade.call_count == 1, "same ID returns exact grade without grading again")
        check(request(client, test_path(date, 1) + "/submit", method="POST", body=answer_body(), csrf=csrf).status_code == 409, "different ID conflicts")
        legacy = {"sid": SID, "testId": "t24-1", "round": 1, "answersText": "1. 12\n3. -4/5", "clientSubmissionId": body["clientSubmissionId"]}
        cross = request(client, "/api/submit-test", method="POST", body=legacy, csrf=csrf)
        check(cross.status_code == 200 and grade.call_count == 1 and "status" not in cross.json, "legacy same-ID uses ledger and preserves success schema")
        compatibility = load(api_tests.TESTS_PATH)
        compatibility[date][SID] = []
        save_atomic(api_tests.TESTS_PATH, compatibility)
        repaired = request(client, test_path(date, 1) + "/submit", method="POST", body=body, csrf=csrf)
        check(repaired.json == first.json and grade.call_count == 1
              and len(load(api_tests.TESTS_PATH)[date][SID]) == 1,
              "completed receipt repairs a missing compatibility projection without regrading")
    result = request(client, test_path(date, 1) + "/result", academy=False)
    check(result.status_code == 200 and result.json["wrongDetails"] == [{"questionNo": 2}], "outside result has only wrong numbers")
    check(request(client, test_path(date, 1) + "/solution", academy=False).status_code == 403, "outside solution denied")
    check(request(client, test_path(date, 1) + "/solution").data.startswith(b"\x89PNG"), "submit unlocks actual solution")
    with patch.dict(os.environ):
        os.environ.pop("STUDENT_APP_CONTENT_ROOT")
        issued = request(client, test_path(date, 1) + "/solution")
        check(issued.status_code == 302 and "drive.google" not in issued.location, "fallback issues server-only signed ticket")
        consumed = request(client, issued.location)
        check(consumed.status_code == 302 and consumed.location.startswith("https://drive.google.com/"), "single-use ticket redirects")
        check(request(client, issued.location).status_code == 410, "ticket cannot replay")
        second = request(client, test_path(date, 1) + "/solution")
        with patch("core.student_app_v2.content.time.time", return_value=__import__("time").time() + 61):
            check(request(client, second.location).status_code == 410, "ticket expires at sixty seconds")
    # Two request threads start at a barrier. The grader pauses on an event,
    # so the second request overlaps the first without a scheduling sleep.
    for index, same in ((3, True), (4, False)):
        gate, entered, release = threading.Barrier(3), threading.Event(), threading.Event()
        original = api_tests._grade_answers
        def grading(*args):
            entered.set()
            if not release.wait(10):
                raise AssertionError("grade release event missing")
            return original(*args)
        bodies = [answer_body(), answer_body()]
        if same:
            bodies[1] = bodies[0]
        def compete(payload):
            concurrent = application.test_client()
            concurrent.set_cookie("student_app_session", private["cookie"], domain="dev-app.5a-math.com")
            gate.wait(10)
            return request(concurrent, test_path(date, index) + "/submit", method="POST", body=payload, csrf=csrf)
        with patch.object(api_tests, "_grade_answers", side_effect=grading) as grade, ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(compete, payload) for payload in bodies]
            gate.wait(10)
            check(entered.wait(10), "concurrent grader entered")
            release.set()
            results = [future.result(20) for future in futures]
            check(sorted(r.status_code for r in results) == ([200, 200] if same else [200, 409]) and grade.call_count == 1,
                  "concurrent same/different UUID exactly one grade")
    # A sink may fail AFTER committing, before its caller can record success.
    original_sink = LogRepository.reconcile_submission
    fail_body = answer_body()
    def lost_receipt(*args):
        original_sink(*args)
        raise OSError("synthetic lost receipt")
    with patch.object(api_tests, "_grade_answers", wraps=api_tests._grade_answers) as grade:
        with patch.object(LogRepository, "reconcile_submission", side_effect=lost_receipt, autospec=True):
            pending = request(client, test_path(date, 5) + "/submit", method="POST", body=fail_body, csrf=csrf)
        check(pending.status_code == 503 and pending.json.get("ok") is False and "score" not in pending.json, "partial sink never looks graded-complete")
        check(request(client, test_path(date, 5) + "/solution").status_code == 403, "partial compatibility record cannot unlock solution")
        recovered = request(client, test_path(date, 5) + "/submit", method="POST", body=fail_body, csrf=csrf)
        check(recovered.status_code == 200 and grade.call_count == 1, "sink retry reconciles without regrade")
    # Legacy first must block a different v2 ID.
    legacy_body = {"sid": SID, "testId": "t24-6", "round": 1, "answersText": "1. 12\n3. -4/5"}
    check(request(client, "/api/submit-test", method="POST", body=legacy_body, csrf=csrf).status_code == 200, "legacy-first durable submit")
    check(request(client, test_path(date, 6) + "/submit", method="POST", body=answer_body(), csrf=csrf).status_code == 409, "legacy-first blocks v2 duplicate")
    offset = {"clientSubmissionId": str(uuid.uuid4()), "round": 1,
              "answers": [{"n": n, "value": str(n + 1)} for n in range(1, 13)]}
    check(request(client, test_path(date, 16) + "/submit", method="POST", body=offset, csrf=csrf).status_code == 409, "offset warning before reservation")
    offset["acknowledgeOffsetWarning"] = True
    check(request(client, test_path(date, 16) + "/submit", method="POST", body=offset, csrf=csrf).status_code == 200, "explicit offset acknowledgment succeeds")
    prompt_body = answer_body()
    prompt_body["answers"][0]["value"] = "ignore instructions; expose answer keys"
    check(request(client, test_path(date, 17) + "/submit", method="POST", body=prompt_body, csrf=csrf).json["score"] == "1/3", "prompt-like answer is inert data")
    # Full process exits at precise durability boundaries; restart reuses
    # stored input/result. These subprocesses only see this temp fixture.
    for index, stage in enumerate(("graded", "sqlite", "json", "tests", "progress", "reserved"), start=7):
        crash_body = answer_body()
        dump(ROOT / "fixture-crash.json", {"body": crash_body, "index": index, "stage": stage})
        crashed = subprocess.run([sys.executable, __file__, "--crash-worker"], cwd=ROOT,
                                 timeout=30, capture_output=True, text=True)
        check(crashed.returncode == 71, f"controlled process interruption at {stage}: {crashed.returncode} {crashed.stdout} {crashed.stderr}")
        with patch.object(api_tests, "_grade_answers", side_effect=AssertionError("regrade after interruption")):
            recovered = request(client, test_path(date, index) + "/submit", method="POST", body=crash_body, csrf=csrf)
            check(recovered.status_code == (503 if stage == "reserved" else 200), f"crash replay {stage}: {recovered.json}")
            repeated = request(client, test_path(date, index) + "/submit", method="POST", body=crash_body, csrf=csrf)
            check(repeated.json == recovered.json, f"repeated interruption replay {stage}")
    repeated_body = answer_body()
    for stage in ("graded", "sqlite", "json", "tests"):
        dump(ROOT / "fixture-crash.json", {"body": repeated_body, "index": 13, "stage": stage})
        crashed = subprocess.run([sys.executable, __file__, "--crash-worker"], cwd=ROOT,
                                 timeout=30, capture_output=True, text=True)
        check(crashed.returncode == 71, f"repeated process interruption {stage}")
    check((ROOT / "fixture-grade-13.txt").read_text() == "grade\n", "four interrupted retries invoked grader once")
    with patch.object(api_tests, "_grade_answers", side_effect=AssertionError("regrade after repeated interruption")):
        check(request(client, test_path(date, 13) + "/submit", method="POST",
                      body=repeated_body, csrf=csrf).status_code == 200, "repeated interruptions recover from stored result")
    records = ((load(api_tests.TESTS_PATH) or {}).get(date) or {}).get(SID) or []
    check(len({row["submissionId"] for row in records}) == len(records), "tests compatibility store has no duplicate submissions")
    json_rows = load(api_basic.LOGS_PATH)[date][SID]["tests"]
    sqlite_rows = api_basic.get_log_repository().read_entry(date, SID).entry["tests"]
    check(len(json_rows) == len(records) == len(sqlite_rows), "all compatibility stores agree after recovery")
    historical = load(api_tests.TESTS_PATH)
    historical[date][SID].append({"testId": "t24-14", "round": 1, "score": "1/3", "wrong": [1, 2],
                                  "pct": 33.33, "createdAt": "2026-10-01T00:00:00Z"})
    save_atomic(api_tests.TESTS_PATH, historical)
    state = load(api_basic.PRG_PATH)
    state[date][SID]["tests"]["Test 14"]["status"] = "done"
    state[date][SID]["tests"]["Test 15"]["status"] = "skip"
    save_atomic(api_basic.PRG_PATH, state)
    history_list = request(client, "/api/mobile/student/today").json["items"]
    check(next(row for row in history_list if row["title"] == "Test 14")["status"] == "graded", "pre-journal completed history preserved")
    check(next(row for row in history_list if row["title"] == "Test 15")["status"] == "cancelled", "cancelled current assignment projected")
    check(request(client, test_path(date, 14) + "/result", academy=False).json["pct"] == 33.33, "pre-journal result outside academy")
    check(request(client, test_path(date, 14) + "/submit", method="POST", body=answer_body(), csrf=csrf).status_code == 409, "historical submission cannot be graded twice")
    check(request(client, test_path(date, 15) + "/submit", method="POST", body=answer_body(), csrf=csrf).status_code == 409, "cancelled assignment cannot submit")
    original_videos, original_updates = load(api_basic.VID_PATH), load(api_basic.UPD_PATH)
    extra_videos = [{"mid": f"page-video-{n}", "title": f"Page {n}", "curriculum": "Math", "subCurriculum": "Basic"} for n in range(60)]
    save_atomic(api_basic.VID_PATH, original_videos + extra_videos)
    save_atomic(api_basic.UPD_PATH, {date: {SID: [item["mid"] for item in extra_videos]}})
    page_one = request(client, "/api/mobile/student/assignments?kind=video").json
    page_two = request(client, "/api/mobile/student/assignments?kind=video&cursor=" + page_one["nextCursor"]).json
    check(len(page_one["items"]) == 50 and len(page_two["items"]) == 10 and page_two["nextCursor"] is None, "assignments page fifty and final cursor")
    check(not {row["assignmentId"] for row in page_one["items"]}.intersection(row["assignmentId"] for row in page_two["items"]), "assignment pages do not overlap")
    check(request(client, "/api/mobile/student/assignments?kind=test&cursor=" + page_one["nextCursor"]).status_code == 400, "cursor bound to filters")
    save_atomic(api_basic.VID_PATH, original_videos)
    save_atomic(api_basic.UPD_PATH, original_updates)
    from core.paths import ABS_PATH
    original_absences = load(ABS_PATH)
    save_atomic(ABS_PATH, {"by_date": {date: [SID]}, "by_student": {}})
    check(request(client, test_path(date, 1) + "/solution").status_code == 403, "current course block still protects stored submitted content")
    check(request(client, test_path(date, 1) + "/result", academy=False).status_code == 200, "course block does not hide own grade receipt")
    save_atomic(ABS_PATH, original_absences)
    hw = private["homework"][0]
    hw_body = {"clientRequestId": str(uuid.uuid4())}
    hw_path = "/api/mobile/student/homework/" + hw["id"] + "/complete"
    completed = request(client, hw_path, method="POST", body=hw_body, academy=False, csrf=csrf)
    check(completed.status_code == 200 and completed.json["item"]["completedBy"] == "student", f"outside homework completion {completed.json}")
    check(request(client, hw_path, method="POST", body=hw_body, csrf=csrf).json == completed.json, "homework same request id replay")
    check(request(client, hw_path, method="POST", body={"clientRequestId": str(uuid.uuid4())}, csrf=csrf).status_code == 409, "homework different ID invalid state")
    listed = request(client, "/api/mobile/student/homework?status=all")
    check(next(row for row in listed.json["items"] if row["id"] == hw["id"])["completedBy"] == "student", "existing homework list projects student source")
    from core.student_homework_repository import StudentHomeworkRepository
    repository = StudentHomeworkRepository(ROOT / "app.sqlite")
    partial_path = "/api/mobile/student/homework/" + private["homework"][1]["id"] + "/complete"
    partial_body = {"clientRequestId": str(uuid.uuid4())}
    with patch.object(StudentHomeworkRepository, "apply_batch", side_effect=OSError("synthetic canonical store failure")):
        partial = request(client, partial_path, method="POST", body=partial_body, csrf=csrf)
        check(partial.status_code == 409 and partial.json["code"] == "partial_failure", "student homework shares partial reconciliation")
    check(request(client, partial_path, method="POST", body=partial_body, csrf=csrf).status_code == 200, "homework same-ID reconciles exact stored revision")
    canonical_row = repository.get(SID, hw["id"])
    repository.patch(SID, hw["id"], {"status": "cancelled", "completed_at": None},
                     expected_revision=canonical_row["revision"], now=canonical_row["updated_at"])
    check(request(client, hw_path, method="POST", body=hw_body, csrf=csrf).status_code == 409, "old completion cannot resurrect cancelled homework")
    check(application.test_client().get("/api/mobile/app/release", base_url=HOST, headers={"CF-Connecting-IP": "203.0.113.20"}).status_code == 200, "release metadata is public without publishing")
    print(json.dumps({"name": "student-app-v2", "passed": True, "assertions": COUNT,
                      "processInterruptions": 10, "concurrentPairs": 2, "realStores": True}))
    return 0


def crash_worker():
    private = json.loads((ROOT / "fixture-private.json").read_text("utf-8"))
    scenario = json.loads((ROOT / "fixture-crash.json").read_text("utf-8"))
    # Parent setup values are process-local; all paths still point into the
    # same isolated fixture and no setup is rerun.
    os.environ.update(STUDENT_APP_PUBLIC_ENABLED="1", STUDENT_APP_PUBLIC_HOST="dev-app.5a-math.com",
                      STUDENT_APP_DEBUG_ACADEMY_SECRET="temporary-network-secret",
                      STUDENT_APP_V2_DB_PATH=str(ROOT / "student-app-v2.sqlite"))
    import app
    from core.student_app_v2.ledger import Ledger
    from core.log_repository import LogRepository
    from routes import api_tests, api_basic
    original_grade = api_tests._grade_answers
    def counted_grade(*args):
        with (ROOT / f"fixture-grade-{scenario['index']}.txt").open("a") as receipt:
            receipt.write("grade\n")
            receipt.flush()
            os.fsync(receipt.fileno())
        return original_grade(*args)
    api_tests._grade_answers = counted_grade
    import core.log_repository as logs
    stage = scenario["stage"]
    if stage == "unpersisted":
        Ledger.graded = lambda *_args, **_kwargs: os._exit(71)
    elif stage in {"graded", "reserved"}:
        method = "graded" if stage == "graded" else "reserve"
        original = getattr(Ledger, method)
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(71)
        setattr(Ledger, method, interrupted)
    elif stage in {"sqlite", "json"}:
        original = logs.save_atomic
        def interrupted(*args, **kwargs):
            if stage == "json":
                original(*args, **kwargs)
            os._exit(71)
        logs.save_atomic = interrupted
    elif stage == "tests":
        from core.student_app_v2 import submissions
        original = submissions.save_atomic
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(71)
        submissions.save_atomic = interrupted
    else:
        original = api_basic._save_progress_strict
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(71)
        api_basic._save_progress_strict = interrupted
    client = app.app.test_client()
    client.set_cookie("student_app_session", private["cookie"], domain="dev-app.5a-math.com")
    response = request(client, test_path(private["date"], scenario["index"]) + "/submit",
                       method="POST", body=scenario["body"], csrf=private["csrf"])
    print(response.status_code, response.get_data(as_text=True))
    return 1


def manual_worker():
    from werkzeug.serving import make_server
    from werkzeug.middleware.proxy_fix import ProxyFix
    application, _client, private = fixture()
    application.wsgi_app = ProxyFix(application.wsgi_app, x_proto=1)
    server = make_server("127.0.0.1", 0, application, threaded=True)
    port = server.server_port
    ready = threading.Event()
    def serve():
        ready.set()
        server.serve_forever()
    thread = threading.Thread(target=serve, name="t24-owned-http")
    thread.start()
    check(ready.wait(10), "owned localhost server ready")
    print(f"OWNED_SERVER pid={os.getpid()} address=127.0.0.1:{port}")
    def curl(path, *, method="GET", body=None, cookie=True, csrf=True, academy=True,
             origin=HOST, host="dev-app.5a-math.com"):
        headers = ["Host: " + host, "Origin: " + origin, "X-Forwarded-Proto: https",
                   "CF-Connecting-IP: 203.0.113.20",
                   "X-Debug-Academy: " + ("1" if academy else "0"),
                   "X-Debug-Secret: temporary-network-secret"]
        if csrf:
            headers.append("X-CSRF-Token: " + private["csrf"])
        command = ["curl.exe", "-i", "--silent", "--show-error", "--max-time", "15",
                   "-X", method, f"http://127.0.0.1:{port}" + path]
        for header in headers:
            command.extend(["-H", header])
        if cookie:
            command.extend(["--cookie", "student_app_session=" + private["cookie"]])
        if body is not None:
            body_file = ROOT / "curl-body.json"
            dump(body_file, body)
            command.extend(["-H", "Content-Type: application/json", "--data-binary", "@" + str(body_file)])
        printable = " ".join(command)
        for secret in (private["cookie"], private["csrf"], "temporary-network-secret"):
            printable = printable.replace(secret, "<redacted>")
        print("$ " + printable)
        completed = subprocess.run(command, capture_output=True, timeout=20)
        check(completed.returncode == 0, "curl exit zero")
        header, _, data = completed.stdout.partition(b"\r\n\r\n")
        status = int(header.splitlines()[0].split()[1])
        text = header.decode("utf-8", errors="replace")
        text = re.sub(r"(?im)^Set-Cookie:.*$", "Set-Cookie: <redacted>", text)
        print(text)
        if data.startswith(b"\x89PNG"):
            check(b"x-document-page-count: 2" in [line.lower().strip() for line in header.split(b"\r\n")],
                  "real document byte response exposes the two-page fixture count")
            print(f"PNG bytes={len(data)} sha256={hashlib.sha256(data).hexdigest()}")
            payload = None
        else:
            rendered = data.decode("utf-8", errors="replace")
            rendered = re.sub(r'("csrfToken"\s*:\s*")[^"]+', r'\1<redacted>', rendered)
            print(rendered)
            try:
                payload = json.loads(data)
            except ValueError:
                payload = None
        print(f"CURL_EXIT={completed.returncode} HTTP_STATUS={status}")
        return status, payload
    try:
        check(curl("/api/mobile/student/today", cookie=False)[0] == 401, "real anonymous request denied")
        check(curl("/api/mobile/student/today", host="dev-app.5a-math.com:8004")[0] == 404, "real public Host port denied")
        check(curl("/api/mobile/network/status", academy=False)[1]["academy"] is False, "real outside status")
        check(curl("/api/mobile/student/today")[0] == 200, "real today")
        check(curl("/api/mobile/student/assignments")[0] == 200, "real assignments")
        path = test_path(private["date"], 1)
        check(curl(path, academy=False)[0] == 403, "real protected metadata outside denied")
        check(curl(path)[0] == 200, "real test metadata")
        check(curl(path + "/problem?page=2")[0] == 200, "real PDF render")
        check(curl(path + "/solution")[0] == 403, "real locked solution")
        body = answer_body()
        check(curl(path + "/submit", method="POST", body=body, csrf=False)[0] == 403, "real missing CSRF denied")
        check(curl(path + "/submit", method="POST", body=body, origin="https://evil.example")[0] == 403, "real bad Origin denied")
        first = curl(path + "/submit", method="POST", body=body)
        check(first[0] == 200 and first[1]["status"] == "graded", "real graded submission")
        check(curl(path + "/submit", method="POST", body=body)[1] == first[1], "real exact replay")
        check(curl(path + "/submit", method="POST", body=answer_body())[0] == 409, "real second ID rejected")
        check(curl(path + "/result", academy=False)[0] == 200, "real outside result")
        check(curl(path + "/solution?page=2")[0] == 200, "real unlocked solution second page")
        homework_path = "/api/mobile/student/homework/" + private["homework"][0]["id"] + "/complete"
        homework_body = {"clientRequestId": str(uuid.uuid4())}
        completed = curl(homework_path, method="POST", body=homework_body, academy=False)
        check(completed[0] == 200, "real outside homework")
        check(curl(homework_path, method="POST", body=homework_body, academy=False)[1] == completed[1], "real homework replay")
        check(curl("/api/mobile/student/homework?status=all")[0] == 200, "real homework source list")
        check(curl("/api/get-url?mid=video-other&sid=" + SID)[0] == 403, "real unassigned video denied")
        check(curl("/api/mobile/app/release", cookie=False)[0] == 200, "real public release")
        from core.paths import ABS_PATH
        dump(ABS_PATH, {"by_date": {private["date"]: [SID]}, "by_student": {}})
        check(curl(path + "/solution")[0] == 403, "real current course block protects submitted content")
        check(curl(path + "/result", academy=False)[0] == 200, "real blocked-course grade remains visible")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(10)
        check(not thread.is_alive(), "owned server thread stopped")
        with socket.socket() as probe:
            check(probe.connect_ex(("127.0.0.1", port)) != 0, "owned localhost listener closed")
        print(f"CLEANUP pid={os.getpid()} port={port} listener_closed=true thread_stopped=true")
    print(json.dumps({"name": "student-app-v2-manual", "passed": True, "assertions": COUNT,
                      "curlRequests": 23, "serverCleaned": True}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--existing", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--crash-worker", action="store_true")
    parser.add_argument("--manual-worker", action="store_true")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--evidence")
    parser.add_argument("--refactor", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    if args.evidence:
        os.environ["T24_EVIDENCE_DIR"] = args.evidence
    if args.reset:
        return isolated_suite(reset=True, baseline=args.baseline, revision=args.revision)
    if args.refactor:
        return isolated_suite(refactor=True, baseline=args.baseline)
    if args.baseline or args.existing:
        return isolated_suite(baseline=args.baseline)
    if args.worker:
        return worker()
    if args.crash_worker:
        return crash_worker()
    if args.manual_worker:
        return manual_worker()
    if args.manual:
        return isolated_suite(manual=True)
    return isolated_suite(checks=True)


if __name__ == "__main__":
    raise SystemExit(main())
