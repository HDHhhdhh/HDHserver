"""Pure projections and restoration of retired subject-specific student rows."""

from __future__ import annotations

import copy

from core.person_identity import (
    PERSON_PROFILE_FIELDS,
    PersonIdentityConflictError,
    PersonIdentityNotFoundError,
    PersonIdentityValidationError,
    course_snapshot,
    normalized_text,
    validate_identity_state,
)


def _student_snapshot(person_id: str, person: dict, sid: str, link: dict) -> dict:
    snapshot = link.get("studentSnapshot")
    if "studentSnapshot" in link:
        if (
            not isinstance(snapshot, dict)
            or normalized_text(snapshot.get("id")) != sid
            or snapshot.get("personId") != person_id
        ):
            raise PersonIdentityValidationError("retired student snapshot identity mismatch")
        row = copy.deepcopy(snapshot)
    else:
        previous_course = link.get("lastKnownCourse") or {}
        if not isinstance(previous_course, dict):
            raise PersonIdentityValidationError("retired student course must be an object")
        row = {"id": sid, "personId": person_id, **course_snapshot(previous_course)}
    # Shared profile changes made through another active subject remain authoritative.
    for field in PERSON_PROFILE_FIELDS:
        row[field] = person["profile"][field]
    return row


def retired_student_rows(directory: dict, students: list) -> list[dict]:
    validate_identity_state(directory, students)
    rows = []
    for person_id, person in directory["persons"].items():
        active_courses = [
            {"id": row["id"], **course_snapshot(row)}
            for row in students if row.get("personId") == person_id
        ]
        for sid, link in person["sidLinks"].items():
            if link["status"] != "retired":
                continue
            rows.append({
                "student": _student_snapshot(person_id, person, sid, link),
                "retiredAt": link.get("retiredAt"),
                "snapshotComplete": "studentSnapshot" in link,
                "activeCourses": copy.deepcopy(active_courses),
                "restorable": person["status"] != "merged",
            })
    return sorted(rows, key=lambda row: (str(row["retiredAt"] or ""), normalized_text(row["student"]["id"])), reverse=True)


def restore_student_in_identity_state(
    directory: dict, students: list, sid: str, *, expected_revision: int, now: str,
) -> tuple[dict, list, dict]:
    sid_index = validate_identity_state(directory, students)
    if directory["revision"] != expected_revision:
        raise PersonIdentityConflictError("명단이 변경되었습니다. 무덤 목록을 새로고침한 뒤 다시 복원하세요.")
    person_id = sid_index.get(sid)
    if not person_id:
        raise PersonIdentityNotFoundError("보관된 학생 기록을 찾을 수 없습니다.")
    person = directory["persons"][person_id]
    link = person["sidLinks"][sid]
    if link["status"] != "retired" or person["status"] == "merged":
        raise PersonIdentityConflictError("현재 복원할 수 없는 기록입니다. 무덤 목록을 새로고침하세요.")
    restored = _student_snapshot(person_id, person, sid, link)
    next_directory, next_students = copy.deepcopy(directory), copy.deepcopy(students)
    next_person = next_directory["persons"][person_id]
    next_link = next_person["sidLinks"][sid]
    next_link.update(status="active", retiredAt=None, restoredAt=now)
    next_person.update(status="active", updatedAt=now)
    next_students.append(restored)
    next_directory.update(revision=directory["revision"] + 1, updatedAt=now)
    validate_identity_state(next_directory, next_students)
    return next_directory, next_students, restored
