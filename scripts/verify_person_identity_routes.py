"""Temp-path Flask checks for person-aware student CRUD and legacy fallback."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
from urllib.parse import quote

from flask import Flask


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.person_identity import build_initial_backfill  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_json(path: pathlib.Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def deterministic_ids():
    values = iter(("a", "b"))
    return lambda: f"per_{next(values):0>32}"


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


def make_app(api_basic) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.config["PERSON_IDENTITY_WRITES_DEGRADED"] = False
    app.register_blueprint(api_basic.bp_api_basic)
    return app


def verify_identity_routes(api_basic, api_auth, root: pathlib.Path) -> None:
    students_path = root / "students.json"
    persons_path = root / "persons.json"
    journal_path = root / "instance" / "person_identity_transactions" / "pending.json"
    directory, students, _ = build_initial_backfill(
        initial_rows(),
        now="2026-08-26T00:00:00Z",
        id_factory=deterministic_ids(),
    )
    write_json(students_path, students)
    write_json(persons_path, directory)

    api_basic.STU_PATH = students_path
    api_basic.PERSONS_PATH = persons_path
    api_basic.PERSON_IDENTITY_JOURNAL_PATH = journal_path
    api_basic.enqueue_current_schedule_changes = lambda _sids: None
    suffixes = iter((303, 404))
    api_basic.random.randint = lambda _low, _high: next(suffixes)
    api_auth.STU_PATH = students_path

    app = make_app(api_basic)
    client = app.test_client()
    source_person_id = students[0]["personId"]
    clone_response = client.post(
        f"/api/add-student?cloneFromSid={quote('소망101', safe='')}",
        json={
            "name": "소망",
            "school": "바다고",
            "grade": "고1",
            "docUrl": "https://example.invalid/s",
            "curriculum": "미적분1",
            "subCurriculum": "APEX",
        },
    )
    check(clone_response.status_code == 200, "identity clone route")
    clone_payload = clone_response.get_json()
    check(clone_payload["personId"] == source_person_id, "clone response personId")
    check(clone_payload["id"] == "소망303", "clone response SID")

    conflicting_source = client.post(
        f"/api/add-student?cloneFromSid={quote('소망101', safe='')}",
        headers={"X-Clone-From-Sid": quote("소망202", safe="")},
        json={"name": "소망", "curriculum": "확통"},
    )
    check(conflicting_source.status_code == 400, "conflicting clone source channels fail closed")

    add_response = client.post(
        "/api/add-student",
        json={
            "name": "새롬",
            "school": "하늘고",
            "grade": "고2",
            "docUrl": "https://example.invalid/new",
            "curriculum": "대수",
        },
    )
    check(add_response.status_code == 200, "identity normal add route")
    check(add_response.get_json()["personId"] != source_person_id, "normal add gets new personId")

    update_response = client.post(
        "/api/update",
        json={"id": "소망101", "field": "grade", "value": "고2"},
    )
    check(update_response.status_code == 200, "person profile update route")
    linked = [row for row in read_json(students_path) if row.get("personId") == source_person_id]
    check(len(linked) == 3 and all(row.get("grade") == "고2" for row in linked), "profile propagation")

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

    immutable_response = client.post(
        "/api/update",
        json={"id": "소망101", "field": "personId", "value": "per_ffffffffffffffffffffffffffffffff"},
    )
    check(immutable_response.status_code == 400, "personId field is immutable")

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


def verify_legacy_fallback(api_basic, root: pathlib.Path) -> None:
    students_path = root / "students.json"
    persons_path = root / "persons.json"
    journal_path = root / "instance" / "person_identity_transactions" / "pending.json"
    write_json(students_path, [])
    api_basic.STU_PATH = students_path
    api_basic.PERSONS_PATH = persons_path
    api_basic.PERSON_IDENTITY_JOURNAL_PATH = journal_path
    api_basic.enqueue_current_schedule_changes = lambda _sids: None
    api_basic.random.randint = lambda _low, _high: 505

    app = make_app(api_basic)
    response = app.test_client().post(
        "/api/add-student",
        json={"name": "레거시", "curriculum": "대수"},
    )
    check(response.status_code == 200, "legacy add remains available before migration")
    stored = read_json(students_path)
    check(stored[0]["id"] == "레거시505", "legacy SID shape")
    check("personId" not in stored[0], "legacy mode does not partially initialize identity")
    check(not persons_path.exists(), "legacy mode does not create persons.json")

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
    from routes import api_auth, api_basic

    original = {
        "basic_students": api_basic.STU_PATH,
        "basic_persons": api_basic.PERSONS_PATH,
        "basic_journal": api_basic.PERSON_IDENTITY_JOURNAL_PATH,
        "basic_enqueue": api_basic.enqueue_current_schedule_changes,
        "basic_randint": api_basic.random.randint,
        "auth_students": api_auth.STU_PATH,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="person-identity-routes-") as tmp:
            verify_identity_routes(api_basic, api_auth, pathlib.Path(tmp) / "identity")
            verify_legacy_fallback(api_basic, pathlib.Path(tmp) / "legacy")
    finally:
        api_basic.STU_PATH = original["basic_students"]
        api_basic.PERSONS_PATH = original["basic_persons"]
        api_basic.PERSON_IDENTITY_JOURNAL_PATH = original["basic_journal"]
        api_basic.enqueue_current_schedule_changes = original["basic_enqueue"]
        api_basic.random.randint = original["basic_randint"]
        api_auth.STU_PATH = original["auth_students"]
    print("person identity route verification: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
