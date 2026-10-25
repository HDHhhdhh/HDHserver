"""Temp-path Flask checks for person-aware student CRUD and legacy fallback."""

from __future__ import annotations

import json
import hashlib
import pathlib
import sys
import tempfile
from urllib.parse import quote

from flask import Flask


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE_PERSON_ID = "per_0000000000000000000000000000000a"
INITIALIZED_AT = "2026-08-26T00:00:00Z"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_json(path: pathlib.Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def initial_rows() -> list[dict]:
    return [
        {
            "id": "소망101",
            "name": "소망",
            "school": "바다고",
            "grade": "고1",
            "docUrl": "https://example.invalid/s",
            "curriculum": "대수",
            "subCurriculum": "APEX",
        },
        {
            "id": "소망202",
            "name": "소망",
            "school": "바다고",
            "grade": "고1",
            "docUrl": "https://example.invalid/s",
            "curriculum": "기하",
            "subCurriculum": "APEX",
        },
    ]


def literal_identity_fixture() -> tuple[dict, list[dict]]:
    rows = [
        {**row, "personId": SOURCE_PERSON_ID, "externalMarker": f"keep-{index}"}
        for index, row in enumerate(initial_rows(), start=1)
    ]
    directory = {
        "schemaVersion": 1,
        "revision": 1,
        "persons": {
            SOURCE_PERSON_ID: {
                "status": "active",
                "profile": {
                    "name": "소망",
                    "school": "바다고",
                    "grade": "고1",
                    "docUrl": "https://example.invalid/s",
                },
                "profileHistory": [],
                "sidLinks": {
                    "소망101": {
                        "status": "active",
                        "linkedAt": INITIALIZED_AT,
                        "retiredAt": None,
                        "lastKnownCourse": {
                            "curriculum": "대수",
                            "subCurriculum": "APEX",
                            "level": "",
                        },
                    },
                    "소망202": {
                        "status": "active",
                        "linkedAt": INITIALIZED_AT,
                        "retiredAt": None,
                        "lastKnownCourse": {
                            "curriculum": "기하",
                            "subCurriculum": "APEX",
                            "level": "",
                        },
                    },
                },
                "redirectTo": None,
                "createdAt": INITIALIZED_AT,
                "updatedAt": INITIALIZED_AT,
                "externalDirectoryMarker": "keep-directory",
            }
        },
        "createdAt": INITIALIZED_AT,
        "updatedAt": INITIALIZED_AT,
        "externalRootMarker": "keep-root",
    }
    return directory, rows


def byte_fingerprints(*paths: pathlib.Path) -> dict[str, tuple[int, str]]:
    fingerprints = {}
    for path in paths:
        payload = path.read_bytes() if path.exists() else b""
        fingerprints[str(path)] = (len(payload), hashlib.sha256(payload).hexdigest())
    return fingerprints


def make_app(api_students, initialize_calls=None, reconcile_calls=None) -> Flask:
    initialize_calls = initialize_calls if initialize_calls is not None else []
    reconcile_calls = reconcile_calls if reconcile_calls is not None else []
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.config["PERSON_IDENTITY_WRITES_DEGRADED"] = False
    api_students.configure_student_identity_assignment_hooks(
        app,
        initialize_today=lambda **kwargs: initialize_calls.append(kwargs),
        reconcile_today=lambda *args, **kwargs: reconcile_calls.append((args, kwargs)) or False,
    )
    app.register_blueprint(api_students.bp_api_students)
    return app


def verify_identity_routes(api_students, api_auth, root: pathlib.Path) -> None:
    students_path = root / "students.json"
    persons_path = root / "persons.json"
    journal_path = root / "instance" / "person_identity_transactions" / "pending.json"
    directory, students = literal_identity_fixture()
    students[0]["registeredOn"] = "2026-08-01"
    write_json(students_path, students)
    write_json(persons_path, directory)

    notifications = []
    api_students.STU_PATH = students_path
    api_students.PERSONS_PATH = persons_path
    api_students.PERSON_IDENTITY_JOURNAL_PATH = journal_path
    api_students.enqueue_current_schedule_changes = lambda sids: notifications.append(
        tuple(str(sid) for sid in sids)
    )
    api_students._today_kst_iso = lambda: "2026-08-26"
    suffixes = iter((303, 404, 505))
    api_students.random.randint = lambda _low, _high: next(suffixes)
    api_auth.STU_PATH = students_path

    initialize_calls = []
    reconcile_calls = []
    app = make_app(api_students, initialize_calls, reconcile_calls)
    client = app.test_client()
    source_person_id = SOURCE_PERSON_ID
    roster_response = client.get("/api/students")
    check(roster_response.status_code == 200, "student collection GET")
    check(roster_response.get_json() == students, "student collection literal oracle")

    before_invalid_date = byte_fingerprints(students_path, persons_path, journal_path)
    for invalid in ("2026-08-25", "2027-02-29", "2026-02-30", "20260827", "2026-08-27T00:00:00Z", "", None, False):
        rejected = client.post("/api/add-student", json={"name": "날짜검증", "firstAttendanceDate": invalid})
        check(rejected.status_code == 400, f"invalid first attendance rejected: {invalid!r}")
        check(byte_fingerprints(students_path, persons_path, journal_path) == before_invalid_date,
              "invalid first attendance never writes identity stores or journal")
    check(not notifications, "invalid first attendance never sends schedule notifications")

    clone_response = client.post(
        f"/api/add-student?cloneFromSid={quote('소망101', safe='')}",
        json={
            "name": "소망",
            "school": "바다고",
            "grade": "고1",
            "docUrl": "https://example.invalid/s",
            "curriculum": "미적분1",
            "subCurriculum": "APEX",
            "registeredOn": "2026-08-01",
        },
    )
    check(clone_response.status_code == 200, "identity clone route")
    clone_payload = clone_response.get_json()
    check(clone_payload["personId"] == source_person_id, "clone response personId")
    check(clone_payload["id"] == "소망303", "clone response SID")
    check(notifications[-1] == ("소망303",), "clone notification SID")
    clone_row = next(row for row in client.get("/api/students").get_json() if row["id"] == "소망303")
    check(clone_row["registeredOn"] == "2026-08-26", "clone starts on its own server registration day")
    check(clone_row["firstAttendanceDate"] == "2026-08-26", "clone without a first date starts today")
    check(read_json(students_path)[:2] == students, "adding a clone preserves existing registration metadata")

    before_rejected_clone = byte_fingerprints(students_path, persons_path)
    conflicting_source = client.post(
        f"/api/add-student?cloneFromSid={quote('소망101', safe='')}",
        headers={"X-Clone-From-Sid": quote("소망202", safe="")},
        json={"name": "소망", "curriculum": "확통"},
    )
    check(conflicting_source.status_code == 400, "conflicting clone source channels fail closed")
    check(
        byte_fingerprints(students_path, persons_path) == before_rejected_clone,
        "conflicting clone source leaves both stores byte-identical",
    )

    missing_source = client.post(
        "/api/add-student?cloneFromSid=missing-source",
        json={"name": "누락", "curriculum": "확통"},
    )
    check(missing_source.status_code == 404, "missing clone source route")
    check(
        byte_fingerprints(students_path, persons_path) == before_rejected_clone,
        "missing clone source leaves both stores byte-identical",
    )

    add_response = client.post(
        "/api/add-student",
        json={
            "name": "새롬",
            "school": "하늘고",
            "grade": "고2",
            "docUrl": "https://example.invalid/new",
            "curriculum": "대수",
            "subCurriculum": "A:Ble",
            "registeredOn": "2099-01-01",
            "firstAttendanceDate": "2028-02-29",
        },
    )
    check(add_response.status_code == 200, "identity normal add route")
    check(add_response.get_json()["personId"] != source_person_id, "normal add gets new personId")
    added_row = next(
        row for row in read_json(students_path) if row["id"] == add_response.get_json()["id"]
    )
    check(added_row["autoVideoAssignCount"] == 1, "A:Ble add literal default count")
    check(added_row["registeredOn"] == "2026-08-26", "normal add overrides a client registration date")
    check(added_row["firstAttendanceDate"] == "2028-02-29", "chosen future leap day persists separately from registration")
    check(notifications[-1] == (added_row["id"],), "normal add notification SID")

    update_response = client.post(
        "/api/update",
        json={"id": "소망101", "field": "grade", "value": "고2"},
    )
    check(update_response.status_code == 200, "person profile update route")
    linked = [row for row in read_json(students_path) if row.get("personId") == source_person_id]
    check(len(linked) == 3 and all(row.get("grade") == "고2" for row in linked), "profile propagation")
    check(
        {row.get("externalMarker") for row in linked if row["id"] in {"소망101", "소망202"}}
        == {"keep-1", "keep-2"},
        "profile propagation preserves unrelated student fields",
    )
    check(
        {row["id"]: row.get("registeredOn") for row in linked}
        == {"소망101": "2026-08-01", "소망202": None, "소망303": "2026-08-26"},
        "shared profile updates preserve each SID's own registration date and missing legacy dates",
    )
    stored_directory = read_json(persons_path)
    check(stored_directory["externalRootMarker"] == "keep-root", "root directory field preserved")
    check(
        stored_directory["persons"][source_person_id]["externalDirectoryMarker"]
        == "keep-directory",
        "person directory field preserved",
    )

    subject_update = client.post(
        "/api/update",
        json={"id": "소망101", "field": "level", "value": "상"},
    )
    check(subject_update.status_code == 200, "subject field update uses identity transaction")
    subject_rows = read_json(students_path)
    check(
        next(row for row in subject_rows if row["id"] == "소망101").get("level") == "상",
        "subject field update persists",
    )
    check(
        next(row for row in subject_rows if row["id"] == "소망202").get("level") != "상",
        "subject field remains SID scoped",
    )

    initialize_before_white_review = len(initialize_calls)
    reconcile_before_white_review = len(reconcile_calls)
    notifications_before_white_review = len(notifications)
    white_review_update = client.post(
        "/api/update",
        json={"id": "소망101", "field": "whiteReviewPending", "value": True},
    )
    check(white_review_update.status_code == 200, "white-review pending update route")
    white_review_rows = read_json(students_path)
    check(
        next(row for row in white_review_rows if row["id"] == "소망101").get("whiteReviewPending") is True,
        "white-review pending persists as an exact boolean",
    )
    check(
        next(row for row in white_review_rows if row["id"] == "소망202").get("whiteReviewPending") is not True,
        "white-review pending remains SID scoped",
    )
    check(
        len(initialize_calls) == initialize_before_white_review
        and len(reconcile_calls) == reconcile_before_white_review
        and len(notifications) == notifications_before_white_review,
        "white-review pending does not trigger schedule or assignment effects",
    )

    before_invalid_white_review = byte_fingerprints(students_path, persons_path)
    for invalid_value in ("true", 1, 0, None, {}, []):
        invalid_white_review = client.post(
            "/api/update",
            json={
                "id": "소망101",
                "field": "whiteReviewPending",
                "value": invalid_value,
            },
        )
        check(invalid_white_review.status_code == 400, "white-review pending rejects non-booleans")
        check(
            byte_fingerprints(students_path, persons_path) == before_invalid_white_review,
            "invalid white-review pending leaves identity stores byte-identical",
        )

    schedule_update = client.post(
        "/api/update",
        json={"id": "소망101", "field": "day1", "value": "수2"},
    )
    check(schedule_update.status_code == 200, "regular schedule update route")
    check(
        reconcile_calls[-1][0] == ("2026-08-26", "소망101"),
        "schedule reconcile uses literal today and SID",
    )
    check(
        reconcile_calls[-1][1]["students"] == read_json(students_path),
        "schedule reconcile receives the persisted roster",
    )
    check(
        initialize_calls[-1]["students"] == read_json(students_path),
        "schedule update initializes from the persisted roster",
    )
    check(notifications[-1] == ("소망101",), "schedule update notification SID")

    initialize_count = len(initialize_calls)
    curriculum_update = client.post(
        "/api/update",
        json={"id": "소망101", "field": "subCurriculum", "value": "A:Ble"},
    )
    check(curriculum_update.status_code == 200, "curriculum update route")
    curriculum_rows = read_json(students_path)
    curriculum_row = next(row for row in curriculum_rows if row["id"] == "소망101")
    check(curriculum_row["autoVideoAssignCount"] == 1, "A:Ble edit literal default count")
    check(len(initialize_calls) == initialize_count + 1, "curriculum update initializes once")
    check(
        next(row for row in read_json(students_path) if row["id"] == "소망101").get("whiteReviewPending") is True,
        "unrelated schedule and curriculum writes preserve white-review pending",
    )

    hook_bundle = app.extensions[api_students._ASSIGNMENT_HOOKS_EXTENSION]
    original_initializer = hook_bundle["initialize_today"]
    retry_initializer_calls: list[dict] = []
    retry_state = {"failures_remaining": 1}

    def fail_once_initializer(**kwargs):
        retry_initializer_calls.append(kwargs)
        if retry_state["failures_remaining"]:
            retry_state["failures_remaining"] -= 1
            raise OSError("injected student post-commit initializer failure")
        return {}

    hook_bundle["initialize_today"] = fail_once_initializer
    retry_payload = {
        "id": "소망101",
        "field": "selfStudyDays",
        "value": ["금"],
    }
    first_post_commit = client.post("/api/update", json=retry_payload)
    check(
        first_post_commit.status_code == 500,
        "student post-commit initializer failure is surfaced",
    )
    rows_after_failure = read_json(students_path)
    check(
        next(
            row for row in rows_after_failure
            if row["id"] == "소망101"
        )["selfStudyDays"] == ["금"],
        "student source edit remains committed after post-commit failure",
    )
    identical_post_commit_retry = client.post(
        "/api/update",
        json=retry_payload,
    )
    check(
        identical_post_commit_retry.status_code == 200,
        "identical student edit retries the initializer",
    )
    check(
        len(retry_initializer_calls) == 2
        and retry_initializer_calls[-1]["students"]
        == read_json(students_path),
        "student retry initializes from the persisted roster",
    )
    hook_bundle["initialize_today"] = original_initializer

    white_review_clear = client.post(
        "/api/update",
        json={"id": "소망101", "field": "whiteReviewPending", "value": False},
    )
    check(white_review_clear.status_code == 200, "white-review pending explicit clear route")
    check(
        next(row for row in read_json(students_path) if row["id"] == "소망101").get("whiteReviewPending") is False,
        "white-review pending clears only through an explicit false boolean",
    )

    before_immutable = byte_fingerprints(students_path, persons_path)
    immutable_response = client.post(
        "/api/update",
        json={"id": "소망101", "field": "personId", "value": "per_ffffffffffffffffffffffffffffffff"},
    )
    check(immutable_response.status_code == 400, "personId field is immutable")
    check(
        byte_fingerprints(students_path, persons_path) == before_immutable,
        "immutable field rejection leaves both stores byte-identical",
    )
    for value in ("2020-01-01", "2099-01-01", "", None):
        response = client.post(
            "/api/update",
            json={"id": "소망303", "field": "registeredOn", "value": value},
        )
        check(response.status_code == 400, "registration date cannot be rewritten or cleared")
        check(byte_fingerprints(students_path, persons_path) == before_immutable,
              "rejected registration edit preserves both identity stores")
    response = client.post("/api/update", json={"id": "소망303", "field": "firstAttendanceDate", "value": "2020-01-01"})
    check(response.status_code == 400, "first attendance cannot silently rewrite historical membership")
    check(byte_fingerprints(students_path, persons_path) == before_immutable,
          "rejected first-attendance rewrite preserves both identity stores")

    delete_response = client.delete("/api/students/소망303")
    check(delete_response.status_code == 204, "person-aware delete route")
    stored_directory = read_json(persons_path)
    check(
        stored_directory["persons"][source_person_id]["sidLinks"]["소망303"]["status"] == "retired",
        "delete retires the SID link",
    )
    check(
        api_auth._group_sids_for_same_person("소망101") == ["소망101", "소망202"],
        "legacy auth uses stable personId grouping",
    )


def verify_identity_read_failures(api_students, root: pathlib.Path) -> None:
    directory, students = literal_identity_fixture()
    for damage in ("missing-students", "missing-persons", "corrupt-students", "corrupt-persons", "pending", "degraded"):
        case_root = root / damage
        students_path = case_root / "students.json"
        persons_path = case_root / "persons.json"
        journal_path = case_root / "instance" / "person_identity_transactions" / "pending.json"
        write_json(students_path, students)
        write_json(persons_path, directory)
        api_students.STU_PATH = students_path
        api_students.PERSONS_PATH = persons_path
        api_students.PERSON_IDENTITY_JOURNAL_PATH = journal_path
        app = make_app(api_students)
        client = app.test_client()
        check(client.get("/api/students").get_json() == students, "configured complete roster remains readable")
        if damage == "missing-students":
            students_path.unlink()
        elif damage == "missing-persons":
            persons_path.unlink()
        elif damage == "corrupt-students":
            students_path.write_bytes(b'[{"truncated":')
        elif damage == "corrupt-persons":
            persons_path.write_bytes(b'{"truncated":')
        elif damage == "pending":
            write_json(journal_path, {"recovery": "required"})
        else:
            app.config["PERSON_IDENTITY_WRITES_DEGRADED"] = True
        paths = (students_path, persons_path, journal_path)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) if path.exists() else None for path in paths}
        check(client.get("/api/students").status_code == 503, f"{damage} blocks roster reads")
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns) if path.exists() else None for path in paths}
        check(after == before, f"{damage} roster read never replaces or repairs runtime bytes")


def verify_legacy_fallback(api_students, root: pathlib.Path) -> None:
    students_path = root / "students.json"
    persons_path = root / "persons.json"
    journal_path = root / "instance" / "person_identity_transactions" / "pending.json"
    write_json(students_path, [])
    api_students.STU_PATH = students_path
    api_students.PERSONS_PATH = persons_path
    api_students.PERSON_IDENTITY_JOURNAL_PATH = journal_path
    api_students.enqueue_current_schedule_changes = lambda _sids: None
    api_students.random.randint = lambda _low, _high: 505
    api_students._today_kst_iso = lambda: "2026-08-27"

    app = make_app(api_students)
    response = app.test_client().post(
        "/api/add-student",
        json={"name": "레거시", "curriculum": "대수"},
    )
    check(response.status_code == 200, "legacy add remains available before migration")
    stored = read_json(students_path)
    check(stored[0]["id"] == "레거시505", "legacy SID shape")
    check(stored[0]["registeredOn"] == "2026-08-27", "legacy add stores the server registration day")
    check(stored[0]["firstAttendanceDate"] == "2026-08-27", "omitted first attendance defaults to today in legacy mode")
    check("personId" not in stored[0], "legacy mode does not partially initialize identity")
    check(not persons_path.exists(), "legacy mode does not create persons.json")
    before_registration_edit = byte_fingerprints(students_path, persons_path)
    response = app.test_client().post(
        "/api/update",
        json={"id": "레거시505", "field": "registeredOn", "value": "2020-01-01"},
    )
    check(response.status_code == 400, "legacy registration date is immutable")
    check(byte_fingerprints(students_path, persons_path) == before_registration_edit,
          "legacy registration rejection never writes stores")

    legacy_white_review = app.test_client().post(
        "/api/update",
        json={"id": "레거시505", "field": "whiteReviewPending", "value": True},
    )
    check(legacy_white_review.status_code == 200, "legacy white-review pending update route")
    check(
        read_json(students_path)[0].get("whiteReviewPending") is True,
        "legacy roster persists white-review pending",
    )
    legacy_before_invalid = students_path.read_bytes()
    legacy_invalid_white_review = app.test_client().post(
        "/api/update",
        json={"id": "레거시505", "field": "whiteReviewPending", "value": "false"},
    )
    check(legacy_invalid_white_review.status_code == 400, "legacy white-review pending rejects strings")
    check(
        students_path.read_bytes() == legacy_before_invalid,
        "legacy invalid white-review pending leaves the roster byte-identical",
    )

    stored = read_json(students_path)
    stored[0]["personId"] = "per_11111111111111111111111111111111"
    write_json(students_path, stored)
    tagged_before = students_path.read_bytes()
    blocked_add = app.test_client().post(
        "/api/add-student",
        json={"name": "차단", "curriculum": "기하"},
    )
    blocked_update = app.test_client().post(
        "/api/update",
        json={"id": "레거시505", "field": "level", "value": "상"},
    )
    blocked_delete = app.test_client().delete("/api/students/레거시505")
    check(blocked_add.status_code == 503, "missing registry blocks student add")
    check(blocked_update.status_code == 503, "missing registry blocks subject update")
    check(blocked_delete.status_code == 503, "missing registry blocks student delete")
    check(students_path.read_bytes() == tagged_before, "missing registry makes no roster writes")
    check(not persons_path.exists(), "missing registry is never recreated as an empty directory")


def main() -> int:
    # Delayed imports keep the pure verifier free of runtime path initialization.
    from routes import api_auth, api_students

    original = {
        "students": api_students.STU_PATH,
        "persons": api_students.PERSONS_PATH,
        "journal": api_students.PERSON_IDENTITY_JOURNAL_PATH,
        "enqueue": api_students.enqueue_current_schedule_changes,
        "randint": api_students.random.randint,
        "today": api_students._today_kst_iso,
        "auth_students": api_auth.STU_PATH,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="person-identity-routes-") as tmp:
            verify_identity_routes(api_students, api_auth, pathlib.Path(tmp) / "identity")
            verify_legacy_fallback(api_students, pathlib.Path(tmp) / "legacy")
            verify_identity_read_failures(api_students, pathlib.Path(tmp) / "read-failures")
    finally:
        api_students.STU_PATH = original["students"]
        api_students.PERSONS_PATH = original["persons"]
        api_students.PERSON_IDENTITY_JOURNAL_PATH = original["journal"]
        api_students.enqueue_current_schedule_changes = original["enqueue"]
        api_students.random.randint = original["randint"]
        api_students._today_kst_iso = original["today"]
        api_auth.STU_PATH = original["auth_students"]
    print("person identity route verification: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
