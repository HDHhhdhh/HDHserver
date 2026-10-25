"""Temporary real-route/store regression for student graveyard and restoration."""

from __future__ import annotations

import copy
import pathlib
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verify_person_identity_routes import (
    SOURCE_PERSON_ID, byte_fingerprints, literal_identity_fixture, make_app, read_json, write_json,
)
from core.person_identity_store import create_student_with_identity, mutate_identity_state, recover_identity_state_if_needed
from core.student_graveyard import retired_student_rows, restore_student_in_identity_state
from routes import api_students


def verify(root: pathlib.Path) -> None:
    students_path, persons_path = root / "students.json", root / "persons.json"
    journal = root / "instance" / "identity" / "pending.json"
    api_students.STU_PATH, api_students.PERSONS_PATH = students_path, persons_path
    api_students.PERSON_IDENTITY_JOURNAL_PATH = journal
    notifications = []
    api_students.enqueue_current_schedule_changes = lambda sids: notifications.append(sids)
    directory, students = literal_identity_fixture()
    students[1].update(day1="토", visitTime1="13:00", registeredOn="2026-08-01", privateExtra={"keep": [1, "한글"]})
    other_person = "per_0000000000000000000000000000000b"
    other = copy.deepcopy(directory["persons"][SOURCE_PERSON_ID])
    other["profile"]["name"] = "별개학생"
    other["sidLinks"] = {"별개303": copy.deepcopy(other["sidLinks"]["소망101"])}
    directory["persons"][other_person] = other
    students.append({**students[0], "id": "별개303", "personId": other_person, "name": "별개학생"})
    write_json(persons_path, directory)
    write_json(students_path, students)
    operational = []
    for name in ("logs.json", "progress.json", "updates.json", "watch.json", "attendance.json"):
        path = root / name
        write_json(path, {"2026-08-25": {"소망202": {"unknown": "운영 기록 유지"}}})
        operational.append(path)
    db = root / "app.sqlite"
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("CREATE TABLE logs (sid TEXT, notes TEXT)")
        connection.execute("INSERT INTO logs VALUES (?, ?)", ("소망202", "과거 기록"))
    operational.append(db)
    original_ops = byte_fingerprints(*operational)
    initialize, reconcile = [], []
    app = make_app(api_students, initialize, reconcile)
    client = app.test_client()
    before = byte_fingerprints(persons_path, students_path)
    response = client.get('/api/students/graveyard')
    assert response.status_code == 200 and response.json["students"] == []
    assert "no-store" in response.headers["Cache-Control"]
    assert before == byte_fingerprints(persons_path, students_path)

    retired = client.delete('/api/students/소망202')
    assert retired.status_code == 204 and retired.headers["X-Student-Graveyard"] == "1"
    listing = client.get('/api/students/graveyard').json
    row = listing["students"][0]
    assert row["student"] == students[1] and row["snapshotComplete"] is True
    assert row["activeCourses"] == [{"id": "소망101", "curriculum": "대수", "subCurriculum": "APEX", "level": ""}]
    assert read_json(students_path) == [students[0], students[2]]
    pure_directory, pure_students = read_json(persons_path), read_json(students_path)
    pure_before = copy.deepcopy((pure_directory, pure_students))
    retired_student_rows(pure_directory, pure_students)[0]["student"]["privateExtra"]["keep"].append("caller mutation")
    assert (pure_directory, pure_students) == pure_before
    revision = listing["revision"]
    before = byte_fingerprints(persons_path, students_path)
    for body in (None, [], {}, {"revision": True}, {"revision": "2"}, {"revision": 0}):
        assert client.post('/api/students/소망202/restore', json=body).status_code == 400
    assert client.post('/api/students/소망202/restore', json={"revision": revision - 1}).status_code == 409
    assert client.post('/api/students/missing/restore', json={"revision": revision}).status_code == 404
    assert client.post('/api/students/소망101/restore', json={"revision": revision}).status_code == 409
    assert before == byte_fingerprints(persons_path, students_path)

    for stage in ("after_persons", "after_students", "before_commit"):
        before_values = (read_json(persons_path), read_json(students_path))
        def fail(point):
            if point == stage:
                raise OSError("injected restoration failure")
        try:
            mutate_identity_state(persons_path, students_path, journal,
                lambda d, s: restore_student_in_identity_state(d, s, "소망202", expected_revision=revision, now="2026-10-24T00:00:00Z"),
                failure_injector=fail)
            raise AssertionError("injected failure did not fire")
        except OSError:
            pass
        assert before_values == (read_json(persons_path), read_json(students_path))
        assert not journal.exists()

    class Crash(BaseException):
        pass
    def crash(point):
        if point == "after_persons":
            raise Crash()
    try:
        mutate_identity_state(persons_path, students_path, journal,
            lambda d, s: restore_student_in_identity_state(d, s, "소망202", expected_revision=revision, now="2026-10-24T00:00:00Z"),
            failure_injector=crash)
    except Crash:
        pass
    assert client.get('/api/students/graveyard').status_code == 503
    recover_identity_state_if_needed(persons_path, students_path, journal)
    assert read_json(persons_path)["persons"][SOURCE_PERSON_ID]["sidLinks"]["소망202"]["status"] == "retired"

    assert client.post('/api/update', json={"id": "소망101", "field": "school", "value": "새학교"}).status_code == 200
    new_listing = client.get('/api/students/graveyard').json
    assert new_listing["students"][0]["student"]["school"] == "새학교"
    assert client.post('/api/students/소망202/restore', json={"revision": revision}).status_code == 409
    def restore(_):
        return app.test_client().post('/api/students/소망202/restore', json={"revision": new_listing["revision"]}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(restore, range(2))) == [200, 409]
    actual = next(row for row in read_json(students_path) if row["id"] == "소망202")
    assert actual == {**students[1], "school": "새학교"}
    assert client.get('/api/students/graveyard').json["students"] == []
    assert read_json(persons_path)["persons"][other_person] == other
    assert original_ops == byte_fingerprints(*operational)
    assert not notifications and not initialize and not reconcile

    # Older links have no full snapshot. Never guess schedule or unknown settings.
    assert client.delete('/api/students/소망202').status_code == 204
    d = read_json(persons_path)
    del d["persons"][SOURCE_PERSON_ID]["sidLinks"]["소망202"]["studentSnapshot"]
    write_json(persons_path, d)
    old = client.get('/api/students/graveyard').json
    assert old["students"][0]["snapshotComplete"] is False
    assert "day1" not in old["students"][0]["student"]
    suffixes = iter((202, 404))
    created = create_student_with_identity(persons_path, students_path, journal,
        {"name": "새사람"}, sid_prefix="소망", suffix_factory=lambda: next(suffixes))
    assert created["id"] == "소망404", "retired SIDs must remain reserved"
    old = client.get('/api/students/graveyard').json
    restored = client.post('/api/students/소망202/restore', json={"revision": old["revision"]})
    assert restored.status_code == 200 and "day1" not in restored.json["student"]
    assert restored.json["student"]["personId"] == SOURCE_PERSON_ID

    # Retiring all subject rows makes the person inactive; restore reactivates only one.
    assert client.delete('/api/students/소망101').status_code == 204
    assert client.delete('/api/students/소망202').status_code == 204
    d = read_json(persons_path)
    assert d["persons"][SOURCE_PERSON_ID]["status"] == "inactive"
    current = client.get('/api/students/graveyard').json
    assert all(not row["activeCourses"] for row in current["students"])
    assert client.post('/api/students/소망101/restore', json={"revision": current["revision"]}).status_code == 200
    assert len(client.get('/api/students/graveyard').json["students"]) == 1
    assert original_ops == byte_fingerprints(*operational)

    d = read_json(persons_path)
    d["persons"][SOURCE_PERSON_ID]["sidLinks"]["소망202"]["studentSnapshot"]["id"] = "wrong"
    write_json(persons_path, d)
    before = byte_fingerprints(persons_path, students_path)
    assert client.get('/api/students/graveyard').status_code == 503
    assert client.post('/api/students/소망202/restore', json={"revision": d["revision"]}).status_code == 503
    assert before == byte_fingerprints(persons_path, students_path)
    persons_path.unlink()
    assert client.get('/api/students/graveyard').status_code == 503
    assert client.post('/api/students/소망202/restore', json={"revision": d["revision"]}).status_code == 503
    assert not persons_path.exists()
    write_json(students_path, [{"id": "legacy", "name": "레거시"}])
    assert client.get('/api/students/graveyard').json["configured"] is False
    assert not persons_path.exists()

    numeric_directory, numeric_students = literal_identity_fixture()
    numeric_students[1]["id"] = 202
    links = numeric_directory["persons"][SOURCE_PERSON_ID]["sidLinks"]
    links["202"] = links.pop("소망202")
    write_json(persons_path, numeric_directory)
    write_json(students_path, numeric_students)
    assert client.delete('/api/students/202').status_code == 204
    numeric_listing = client.get('/api/students/graveyard').json
    assert numeric_listing["students"][0]["student"]["id"] == 202
    numeric_restore = client.post('/api/students/202/restore', json={"revision": numeric_listing["revision"]})
    assert numeric_restore.status_code == 200 and numeric_restore.json["student"]["id"] == 202


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="student-graveyard-") as temp:
        verify(pathlib.Path(temp))
    print("student graveyard route/store verification: OK")


if __name__ == '__main__':
    main()
