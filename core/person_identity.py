"""Pure person identity rules for linking one person to subject-specific SIDs."""

from __future__ import annotations

import copy
import re
import unicodedata
import uuid
from collections import OrderedDict
from typing import Any, Callable, Mapping, Sequence


PERSON_ID_PATTERN = re.compile(r"^per_[0-9a-f]{32}$")
PERSON_IDENTITY_SCHEMA_VERSION = 1
PERSON_PROFILE_FIELDS = ("name", "school", "grade", "docUrl")
PERSON_STATUSES = frozenset({"active", "inactive", "merged"})
SID_LINK_STATUSES = frozenset({"active", "retired"})


class PersonIdentityError(ValueError):
    """Base error for invalid or conflicting identity state."""


class PersonIdentityValidationError(PersonIdentityError):
    """Raised when a person directory and roster violate an invariant."""


class PersonIdentityConflictError(PersonIdentityError):
    """Raised when a requested link cannot be chosen without guessing."""

    def __init__(self, message: str, *, conflicts: Sequence[Mapping[str, Any]] | None = None):
        super().__init__(message)
        self.conflicts = tuple(dict(item) for item in (conflicts or ()))


class PersonIdentityNotFoundError(PersonIdentityConflictError):
    """Raised when an explicitly selected SID or person does not exist."""


def normalized_text(value: Any) -> str:
    """Return the NFKC/trimmed form used only for identity comparisons."""

    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def student_school(student: Mapping[str, Any]) -> str:
    for key in ("school", "highSchool", "middleSchool"):
        value = normalized_text(student.get(key))
        if value:
            return value
    return ""


def profile_from_student(student: Mapping[str, Any]) -> dict[str, str]:
    return {
        "name": normalized_text(student.get("name")),
        "school": student_school(student),
        "grade": normalized_text(student.get("grade")),
        "docUrl": normalized_text(student.get("docUrl")),
    }


def course_snapshot(student: Mapping[str, Any]) -> dict[str, str]:
    return {
        "curriculum": normalized_text(student.get("curriculum")),
        "subCurriculum": normalized_text(student.get("subCurriculum")),
        "level": normalized_text(student.get("level")),
    }


def new_person_id() -> str:
    return f"per_{uuid.uuid4().hex}"


def is_valid_person_id(value: Any) -> bool:
    return bool(PERSON_ID_PATTERN.fullmatch(normalized_text(value)))


def new_directory(*, now: str) -> dict[str, Any]:
    return {
        "schemaVersion": PERSON_IDENTITY_SCHEMA_VERSION,
        "revision": 1,
        "persons": {},
        "createdAt": now,
        "updatedAt": now,
    }


def _new_person_record(
    person_id: str,
    profile: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    now: str,
) -> dict[str, Any]:
    links: dict[str, Any] = {}
    for row in rows:
        sid = normalized_text(row.get("id"))
        links[sid] = {
            "status": "active",
            "linkedAt": now,
            "retiredAt": None,
            "lastKnownCourse": course_snapshot(row),
        }
    return {
        "status": "active",
        "profile": {key: normalized_text(profile.get(key)) for key in PERSON_PROFILE_FIELDS},
        "profileHistory": [],
        "sidLinks": links,
        "redirectTo": None,
        "createdAt": now,
        "updatedAt": now,
    }


def _directory_persons(directory: Mapping[str, Any]) -> Mapping[str, Any]:
    persons = directory.get("persons")
    if not isinstance(persons, Mapping):
        raise PersonIdentityValidationError("person directory persons must be an object")
    return persons


def validate_directory(directory: Any) -> dict[str, str]:
    """Validate the directory itself and return the unique SID-to-person index."""

    if not isinstance(directory, Mapping):
        raise PersonIdentityValidationError("person directory must be an object")
    if directory.get("schemaVersion") != PERSON_IDENTITY_SCHEMA_VERSION:
        raise PersonIdentityValidationError("unsupported person directory schemaVersion")
    revision = directory.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise PersonIdentityValidationError("person directory revision must be a positive integer")

    persons = _directory_persons(directory)
    sid_index: dict[str, str] = {}
    redirects: dict[str, str] = {}
    for raw_person_id, raw_record in persons.items():
        person_id = normalized_text(raw_person_id)
        if person_id != raw_person_id or not is_valid_person_id(person_id):
            raise PersonIdentityValidationError(f"invalid personId: {raw_person_id!r}")
        if not isinstance(raw_record, Mapping):
            raise PersonIdentityValidationError(f"person record must be an object: {person_id}")
        status = normalized_text(raw_record.get("status"))
        if status not in PERSON_STATUSES:
            raise PersonIdentityValidationError(f"invalid person status: {person_id}")
        profile = raw_record.get("profile")
        if not isinstance(profile, Mapping):
            raise PersonIdentityValidationError(f"person profile must be an object: {person_id}")
        for field in PERSON_PROFILE_FIELDS:
            if field not in profile or not isinstance(profile.get(field), str):
                raise PersonIdentityValidationError(
                    f"person profile field must be a string: {person_id}.{field}"
                )

        redirect_to = normalized_text(raw_record.get("redirectTo"))
        if status == "merged":
            if not is_valid_person_id(redirect_to) or redirect_to == person_id:
                raise PersonIdentityValidationError(f"invalid merged redirect: {person_id}")
            redirects[person_id] = redirect_to
        elif redirect_to:
            raise PersonIdentityValidationError(f"non-merged person has redirect: {person_id}")

        links = raw_record.get("sidLinks")
        if not isinstance(links, Mapping):
            raise PersonIdentityValidationError(f"sidLinks must be an object: {person_id}")
        active_count = 0
        for raw_sid, raw_link in links.items():
            sid = normalized_text(raw_sid)
            if not sid or sid != raw_sid:
                raise PersonIdentityValidationError(f"invalid SID link key: {person_id}")
            if sid in sid_index:
                raise PersonIdentityValidationError(
                    f"SID is linked to multiple persons: {sid}"
                )
            if not isinstance(raw_link, Mapping):
                raise PersonIdentityValidationError(f"SID link must be an object: {sid}")
            link_status = normalized_text(raw_link.get("status"))
            if link_status not in SID_LINK_STATUSES:
                raise PersonIdentityValidationError(f"invalid SID link status: {sid}")
            if link_status == "active":
                active_count += 1
            sid_index[sid] = person_id

        if status == "active" and active_count == 0:
            raise PersonIdentityValidationError(f"active person has no active SID: {person_id}")
        if status in {"inactive", "merged"} and active_count:
            raise PersonIdentityValidationError(
                f"{status} person has an active SID: {person_id}"
            )

    for source, target in redirects.items():
        if target not in persons:
            raise PersonIdentityValidationError(f"merged redirect target is missing: {source}")
        if normalized_text(persons[target].get("status")) == "merged":
            raise PersonIdentityValidationError(f"merged redirect chains are not allowed: {source}")
    return sid_index


def validate_identity_state(directory: Any, students: Any) -> dict[str, str]:
    """Validate full active-roster coverage and compatibility snapshots."""

    if not isinstance(students, list):
        raise PersonIdentityValidationError("students store must be an array")
    sid_index = validate_directory(directory)
    persons = _directory_persons(directory)
    roster_sids: set[str] = set()
    active_link_sids: set[str] = set()

    for person_id, record in persons.items():
        for sid, link in record["sidLinks"].items():
            if normalized_text(link.get("status")) == "active":
                active_link_sids.add(sid)

    for row in students:
        if not isinstance(row, Mapping):
            raise PersonIdentityValidationError("every student row must be an object")
        sid = normalized_text(row.get("id"))
        if not sid:
            raise PersonIdentityValidationError("student SID is required")
        if sid in roster_sids:
            raise PersonIdentityValidationError(f"duplicate student SID: {sid}")
        roster_sids.add(sid)

        person_id = normalized_text(row.get("personId"))
        if not is_valid_person_id(person_id):
            raise PersonIdentityValidationError(f"student personId is invalid: {sid}")
        if sid_index.get(sid) != person_id:
            raise PersonIdentityValidationError(f"student SID link mismatch: {sid}")
        record = persons.get(person_id)
        if not isinstance(record, Mapping) or normalized_text(record.get("status")) != "active":
            raise PersonIdentityValidationError(f"student person is not active: {sid}")
        link = record["sidLinks"].get(sid)
        if not isinstance(link, Mapping) or normalized_text(link.get("status")) != "active":
            raise PersonIdentityValidationError(f"student SID link is not active: {sid}")

        expected_profile = profile_from_student(row)
        actual_profile = record["profile"]
        for field in PERSON_PROFILE_FIELDS:
            if normalized_text(actual_profile.get(field)) != expected_profile[field]:
                raise PersonIdentityValidationError(
                    f"student profile snapshot mismatch: {sid}.{field}"
                )

    missing_rows = active_link_sids - roster_sids
    if missing_rows:
        raise PersonIdentityValidationError(
            "active SID links are missing roster rows: " + ", ".join(sorted(missing_rows))
        )
    return sid_index


def person_id_for_sid(students: Sequence[Mapping[str, Any]], sid: Any) -> str:
    target = normalized_text(sid)
    for row in students:
        if normalized_text(row.get("id")) == target:
            person_id = normalized_text(row.get("personId"))
            return person_id if is_valid_person_id(person_id) else ""
    return ""


def active_sids_for_person(students: Sequence[Mapping[str, Any]], person_id: Any) -> tuple[str, ...]:
    target = normalized_text(person_id)
    if not is_valid_person_id(target):
        return ()
    return tuple(
        normalized_text(row.get("id"))
        for row in students
        if normalized_text(row.get("personId")) == target and normalized_text(row.get("id"))
    )


def same_person(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool | None:
    """Return authoritative equality, or None when neither row has personId."""

    left_id = normalized_text(left.get("personId"))
    right_id = normalized_text(right.get("personId"))
    if not left_id and not right_id:
        return None
    return bool(
        is_valid_person_id(left_id)
        and is_valid_person_id(right_id)
        and left_id == right_id
    )


def allocate_unique_sid(
    prefix: str,
    existing_sids: Sequence[str] | set[str],
    *,
    suffix_factory: Callable[[], int],
) -> str:
    existing = {normalized_text(value) for value in existing_sids}
    for _ in range(1000):
        suffix = suffix_factory()
        if isinstance(suffix, bool) or not isinstance(suffix, int) or not 0 <= suffix <= 999:
            raise PersonIdentityConflictError("SID suffix factory returned an invalid value")
        sid = f"{prefix}{suffix:03d}"
        if sid not in existing:
            return sid
    for suffix in range(1000):
        sid = f"{prefix}{suffix:03d}"
        if sid not in existing:
            return sid
    raise PersonIdentityConflictError("no unique SID suffix is available")


def _unique_person_id(persons: Mapping[str, Any], id_factory: Callable[[], str]) -> str:
    for _ in range(1000):
        candidate = normalized_text(id_factory())
        if is_valid_person_id(candidate) and candidate not in persons:
            return candidate
    raise PersonIdentityConflictError("could not allocate a unique personId")


def _subject_key(student: Mapping[str, Any]) -> tuple[str, str]:
    return (
        normalized_text(student.get("curriculum")),
        normalized_text(student.get("subCurriculum")),
    )


def build_initial_backfill(
    students: Any,
    *,
    now: str,
    id_factory: Callable[[], str] = new_person_id,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a conservative initial directory without mutating the supplied roster."""

    if not isinstance(students, list):
        raise PersonIdentityValidationError("students store must be an array")
    rows = copy.deepcopy(students)
    seen_sids: set[str] = set()
    groups: "OrderedDict[tuple[str, str, str], list[dict[str, Any]]]" = OrderedDict()
    conflicts: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            conflicts.append({"code": "invalid_student_row", "sids": []})
            continue
        sid = normalized_text(row.get("id"))
        if not sid or sid in seen_sids:
            conflicts.append({"code": "invalid_or_duplicate_sid", "sids": [sid] if sid else []})
            continue
        seen_sids.add(sid)
        if normalized_text(row.get("personId")):
            conflicts.append({"code": "preexisting_person_id", "sids": [sid]})
            continue
        profile = profile_from_student(row)
        if not profile["name"]:
            conflicts.append({"code": "missing_name", "sids": [sid]})
            continue
        groups.setdefault((profile["name"], profile["school"], profile["grade"]), []).append(row)

    accepted: list[tuple[list[dict[str, Any]], str]] = []
    for identity, grouped_rows in groups.items():
        sids = [normalized_text(row.get("id")) for row in grouped_rows]
        if len(grouped_rows) == 1:
            accepted.append((grouped_rows, "singleton"))
            continue

        docs = [profile_from_student(row)["docUrl"] for row in grouped_rows]
        subjects = [_subject_key(row) for row in grouped_rows]
        curricula = [subject[0] for subject in subjects]
        if not all(identity) or not all(docs):
            conflicts.append({
                "code": "duplicate_identity_missing_evidence",
                "sids": sids,
                "identity": {"name": identity[0], "school": identity[1], "grade": identity[2]},
            })
            continue
        if len(set(docs)) != 1:
            conflicts.append({"code": "duplicate_identity_doc_conflict", "sids": sids})
            continue
        if not all(curricula) or len(set(subjects)) != len(subjects):
            conflicts.append({"code": "duplicate_identity_course_conflict", "sids": sids})
            continue
        accepted.append((grouped_rows, "strict_profile_shared_doc"))

    if conflicts:
        raise PersonIdentityConflictError(
            "personId backfill contains unresolved conflicts",
            conflicts=conflicts,
        )

    directory = new_directory(now=now)
    persons = directory["persons"]
    assignments: list[dict[str, Any]] = []
    row_by_sid = {normalized_text(row.get("id")): row for row in rows}
    for grouped_rows, evidence in accepted:
        person_id = _unique_person_id(persons, id_factory)
        profile = profile_from_student(grouped_rows[0])
        persons[person_id] = _new_person_record(
            person_id,
            profile,
            grouped_rows,
            now=now,
        )
        sids = []
        for row in grouped_rows:
            sid = normalized_text(row.get("id"))
            row_by_sid[sid]["personId"] = person_id
            sids.append(sid)
        assignments.append({
            "personId": person_id,
            "sids": sids,
            "evidence": evidence,
        })

    directory["updatedAt"] = now
    validate_identity_state(directory, rows)
    return directory, rows, assignments


def add_student_to_identity_state(
    directory: Mapping[str, Any],
    students: Sequence[Mapping[str, Any]],
    student: Mapping[str, Any],
    *,
    now: str,
    person_id: str = "",
    id_factory: Callable[[], str] = new_person_id,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    next_directory = copy.deepcopy(dict(directory))
    next_students = copy.deepcopy(list(students))
    persons = next_directory["persons"]
    row = copy.deepcopy(dict(student))
    sid = normalized_text(row.get("id"))
    if not sid or any(normalized_text(item.get("id")) == sid for item in next_students):
        raise PersonIdentityConflictError("student SID is missing or already exists")

    requested = normalized_text(person_id)
    if requested:
        record = persons.get(requested)
        if not isinstance(record, dict) or normalized_text(record.get("status")) != "active":
            raise PersonIdentityConflictError("requested personId is not active")
        profile = record["profile"]
        supplied = profile_from_student(row)
        mismatches = [
            field for field in PERSON_PROFILE_FIELDS
            if supplied[field] and supplied[field] != normalized_text(profile.get(field))
        ]
        if mismatches:
            raise PersonIdentityConflictError(
                "new subject row conflicts with the existing person profile: " + ", ".join(mismatches)
            )
        for field in PERSON_PROFILE_FIELDS:
            row[field] = normalized_text(profile.get(field))
        record["sidLinks"][sid] = {
            "status": "active",
            "linkedAt": now,
            "retiredAt": None,
            "lastKnownCourse": course_snapshot(row),
        }
        record["updatedAt"] = now
        person_id = requested
    else:
        person_id = _unique_person_id(persons, id_factory)
        profile = profile_from_student(row)
        persons[person_id] = _new_person_record(person_id, profile, [row], now=now)

    row["personId"] = person_id
    row.pop("cloneFromSid", None)
    next_students.append(row)
    next_directory["revision"] = int(next_directory["revision"]) + 1
    next_directory["updatedAt"] = now
    validate_identity_state(next_directory, next_students)
    return next_directory, next_students, row


def update_person_profile_in_state(
    directory: Mapping[str, Any],
    students: Sequence[Mapping[str, Any]],
    sid: Any,
    field: str,
    value: Any,
    *,
    now: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], tuple[str, ...]]:
    if field not in PERSON_PROFILE_FIELDS:
        raise PersonIdentityConflictError(f"not a person profile field: {field}")
    next_directory = copy.deepcopy(dict(directory))
    next_students = copy.deepcopy(list(students))
    target_sid = normalized_text(sid)
    target = next((row for row in next_students if normalized_text(row.get("id")) == target_sid), None)
    if not isinstance(target, dict):
        raise PersonIdentityNotFoundError("student SID was not found")
    person_id = normalized_text(target.get("personId"))
    record = next_directory["persons"].get(person_id)
    if not isinstance(record, dict) or normalized_text(record.get("status")) != "active":
        raise PersonIdentityValidationError("student person is not active")

    next_value = normalized_text(value)
    previous = normalized_text(record["profile"].get(field))
    if previous == next_value:
        return next_directory, next_students, active_sids_for_person(next_students, person_id)

    history = record.setdefault("profileHistory", [])
    if not isinstance(history, list):
        raise PersonIdentityValidationError("person profileHistory must be an array")
    history.append({
        "changedAt": now,
        "field": field,
        "previous": previous,
        "next": next_value,
    })
    if len(history) > 100:
        del history[:-100]
    record["profile"][field] = next_value
    record["updatedAt"] = now

    affected: list[str] = []
    for row in next_students:
        if normalized_text(row.get("personId")) != person_id:
            continue
        row[field] = next_value
        affected.append(normalized_text(row.get("id")))

    next_directory["revision"] = int(next_directory["revision"]) + 1
    next_directory["updatedAt"] = now
    validate_identity_state(next_directory, next_students)
    return next_directory, next_students, tuple(affected)


def retire_student_from_identity_state(
    directory: Mapping[str, Any],
    students: Sequence[Mapping[str, Any]],
    sid: Any,
    *,
    now: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    next_directory = copy.deepcopy(dict(directory))
    next_students = copy.deepcopy(list(students))
    target_sid = normalized_text(sid)
    index = next(
        (idx for idx, row in enumerate(next_students) if normalized_text(row.get("id")) == target_sid),
        None,
    )
    if index is None:
        raise PersonIdentityNotFoundError("student SID was not found")
    removed = next_students.pop(index)
    person_id = normalized_text(removed.get("personId"))
    record = next_directory["persons"].get(person_id)
    if not isinstance(record, dict):
        raise PersonIdentityValidationError("student person record is missing")
    link = record.get("sidLinks", {}).get(target_sid)
    if not isinstance(link, dict) or normalized_text(link.get("status")) != "active":
        raise PersonIdentityValidationError("student active SID link is missing")
    link["status"] = "retired"
    link["retiredAt"] = now
    link["lastKnownCourse"] = course_snapshot(removed)
    record["updatedAt"] = now
    if not any(
        normalized_text(item.get("status")) == "active"
        for item in record["sidLinks"].values()
        if isinstance(item, Mapping)
    ):
        record["status"] = "inactive"

    next_directory["revision"] = int(next_directory["revision"]) + 1
    next_directory["updatedAt"] = now
    validate_identity_state(next_directory, next_students)
    return next_directory, next_students, removed


__all__ = [
    "PERSON_IDENTITY_SCHEMA_VERSION",
    "PERSON_PROFILE_FIELDS",
    "PersonIdentityConflictError",
    "PersonIdentityError",
    "PersonIdentityNotFoundError",
    "PersonIdentityValidationError",
    "active_sids_for_person",
    "add_student_to_identity_state",
    "allocate_unique_sid",
    "build_initial_backfill",
    "is_valid_person_id",
    "new_person_id",
    "normalized_text",
    "person_id_for_sid",
    "profile_from_student",
    "retire_student_from_identity_state",
    "same_person",
    "update_person_profile_in_state",
    "validate_directory",
    "validate_identity_state",
]
