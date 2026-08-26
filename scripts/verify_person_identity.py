"""Temp-only regression checks for stable personId rules and persistence."""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.person_identity import (  # noqa: E402
    PersonIdentityConflictError,
    active_sids_for_person,
    build_initial_backfill,
    same_person,
    update_person_profile_in_state,
    validate_identity_state,
)
from core.person_identity_store import (  # noqa: E402
    create_student_with_identity,
    identity_is_configured,
    initialize_identity_state,
    load_identity_state_strict,
    mutate_identity_state,
    recover_identity_state_if_needed,
    retire_student_identity,
    sha256_file,
    update_person_profile_field,
)
from core.student_account_rules import identity_groups  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_json(path: pathlib.Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def id_factory(*suffixes: str):
    values = iter(suffixes)
    return lambda: f"per_{next(values):0>32}"


def sample_students() -> list[dict]:
    return [
        {
            "id": "가람101",
            "name": "가람",
            "school": "한빛고",
            "grade": "고2",
            "docUrl": "https://example.invalid/g",
            "curriculum": "대수",
            "subCurriculum": "APEX",
            "level": "상",
        },
        {
            "id": "가람202",
            "name": "가람",
            "school": "한빛고",
            "grade": "고2",
            "docUrl": "https://example.invalid/g",
            "curriculum": "미적분1",
            "subCurriculum": "APEX",
            "level": "중상",
        },
        {
            "id": "나래303",
            "name": "나래",
            "school": "새봄중",
            "grade": "중3",
            "docUrl": "https://example.invalid/n",
            "curriculum": "공수1",
            "subCurriculum": "A:Ble",
            "level": "중",
        },
    ]


def verify_pure_backfill() -> tuple[dict, list]:
    students = sample_students()
    directory, next_students, assignments = build_initial_backfill(
        students,
        now="2026-08-26T00:00:00Z",
        id_factory=id_factory("1", "2"),
    )
    check("personId" not in students[0], "backfill must not mutate its input")
    check(len(directory["persons"]) == 2, "backfill person count")
    check(len(assignments) == 2, "backfill assignment count")
    check(assignments[0]["sids"] == ["가람101", "가람202"], "shared-doc subjects must link")
    check(next_students[0]["personId"] == next_students[1]["personId"], "linked SIDs share personId")
    check(next_students[2]["personId"] != next_students[0]["personId"], "singleton is separate")
    validate_identity_state(directory, next_students)
    check(
        active_sids_for_person(next_students, next_students[0]["personId"]) == ("가람101", "가람202"),
        "person-to-SID lookup order",
    )
    check(same_person(next_students[0], next_students[1]) is True, "authoritative same-person")
    check(same_person(next_students[0], next_students[2]) is False, "authoritative different-person")
    check(same_person(students[0], students[1]) is None, "legacy rows defer to compatibility logic")

    distinct_people = [dict(next_students[0]), dict(next_students[0])]
    distinct_people[1]["id"] = "가람999"
    distinct_people[1]["personId"] = next_students[2]["personId"]
    check(len(identity_groups(distinct_people)) == 2, "account grouping must respect distinct personIds")
    check(len(identity_groups(next_students[:2])) == 1, "account grouping must join shared personId")

    conflicting = sample_students()
    conflicting[1]["docUrl"] = "https://example.invalid/other"
    try:
        build_initial_backfill(
            conflicting,
            now="2026-08-26T00:00:00Z",
            id_factory=id_factory("3", "4"),
        )
    except PersonIdentityConflictError as exc:
        check(
            any(item.get("code") == "duplicate_identity_doc_conflict" for item in exc.conflicts),
            "doc conflict classification",
        )
    else:
        raise AssertionError("conflicting duplicate identity must fail closed")
    return directory, next_students


def verify_store_lifecycle(directory: dict, next_students: list) -> None:
    with tempfile.TemporaryDirectory(prefix="person-identity-") as tmp:
        root = pathlib.Path(tmp)
        students_path = root / "students.json"
        persons_path = root / "persons.json"
        journal_path = root / "instance" / "person_identity_transactions" / "pending.json"
        original = sample_students()
        write_json(students_path, original)
        source_hash = sha256_file(students_path)

        initialize_identity_state(
            persons_path,
            students_path,
            journal_path,
            directory,
            next_students,
            expected_students_sha256=source_hash,
        )
        persisted_directory, persisted_students = load_identity_state_strict(persons_path, students_path)
        check(len(persisted_directory["persons"]) == 2, "initialized directory")
        shared_person_id = persisted_students[0]["personId"]

        before_students = students_path.read_bytes()
        before_persons = persons_path.read_bytes()

        def failing_profile_mutation(current_directory: dict, current_students: list):
            return update_person_profile_in_state(
                current_directory,
                current_students,
                "가람101",
                "name",
                "실패하면안됨",
                now="2026-08-26T00:30:00Z",
            )

        def fail_after_persons(stage: str) -> None:
            if stage == "after_persons":
                raise RuntimeError("injected profile failure")

        try:
            mutate_identity_state(
                persons_path,
                students_path,
                journal_path,
                failing_profile_mutation,
                failure_injector=fail_after_persons,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("existing identity mutation failure must be surfaced")
        check(students_path.read_bytes() == before_students, "failed mutation restores students bytes")
        check(persons_path.read_bytes() == before_persons, "failed mutation restores persons bytes")
        check(not journal_path.exists(), "failed mutation clears a successful rollback journal")

        clone = create_student_with_identity(
            persons_path,
            students_path,
            journal_path,
            {
                "name": "가람",
                "school": "한빛고",
                "grade": "고2",
                "docUrl": "https://example.invalid/g",
                "curriculum": "기하",
                "subCurriculum": "APEX",
            },
            sid_prefix="가람",
            clone_from_sid="가람101",
            suffix_factory=lambda: 7,
            now="2026-08-26T01:00:00Z",
        )
        check(clone["id"] == "가람007", "clone SID allocation")
        check(clone["personId"] == shared_person_id, "clone must reuse personId")

        created = create_student_with_identity(
            persons_path,
            students_path,
            journal_path,
            {
                "name": "다온",
                "school": "푸른고",
                "grade": "고1",
                "docUrl": "https://example.invalid/d",
                "curriculum": "대수",
            },
            sid_prefix="다온",
            suffix_factory=lambda: 8,
            id_factory=id_factory("5"),
            now="2026-08-26T02:00:00Z",
        )
        check(created["personId"] != shared_person_id, "normal add creates a person")

        affected = update_person_profile_field(
            persons_path,
            students_path,
            journal_path,
            "가람101",
            "grade",
            "고3",
            now="2026-08-26T03:00:00Z",
        )
        check(set(affected) == {"가람101", "가람202", "가람007"}, "profile update propagation")
        persisted_directory, persisted_students = load_identity_state_strict(persons_path, students_path)
        linked_rows = [row for row in persisted_students if row["personId"] == shared_person_id]
        check(all(row["grade"] == "고3" for row in linked_rows), "all linked snapshots updated")

        removed = retire_student_identity(
            persons_path,
            students_path,
            journal_path,
            "가람007",
            now="2026-08-26T04:00:00Z",
        )
        check(removed["id"] == "가람007", "retire returns origin row")
        persisted_directory, persisted_students = load_identity_state_strict(persons_path, students_path)
        check(all(row["id"] != "가람007" for row in persisted_students), "retired SID leaves active roster")
        check(
            persisted_directory["persons"][shared_person_id]["sidLinks"]["가람007"]["status"] == "retired",
            "retired SID history remains in directory",
        )


def verify_rollback_and_crash_recovery() -> None:
    class SimulatedCrash(BaseException):
        pass

    for crash in (False, True):
        with tempfile.TemporaryDirectory(prefix="person-identity-failure-") as tmp:
            root = pathlib.Path(tmp)
            students_path = root / "students.json"
            persons_path = root / "persons.json"
            journal_path = root / "instance" / "person_identity_transactions" / "pending.json"
            original = sample_students()
            directory, next_students, _ = build_initial_backfill(
                original,
                now="2026-08-26T00:00:00Z",
                id_factory=id_factory("6", "7"),
            )
            write_json(students_path, original)
            source_hash = sha256_file(students_path)

            def fail(stage: str) -> None:
                if stage == "after_persons":
                    if crash:
                        raise SimulatedCrash()
                    raise RuntimeError("injected write failure")

            try:
                initialize_identity_state(
                    persons_path,
                    students_path,
                    journal_path,
                    directory,
                    next_students,
                    expected_students_sha256=source_hash,
                    failure_injector=fail,
                )
            except SimulatedCrash:
                check(crash, "only crash case raises BaseException")
            except RuntimeError:
                check(not crash, "ordinary failure must be surfaced")
            else:
                raise AssertionError("injected identity write must fail")

            if crash:
                check(journal_path.exists(), "crash leaves recovery journal")
                check(recover_identity_state_if_needed(persons_path, students_path, journal_path), "crash recovery")
            check(not persons_path.exists(), "failed initial migration restores absent persons.json")
            check(load_json(students_path) == original, "failed initial migration restores students")
            check(not journal_path.exists(), "resolved transaction clears journal")


def verify_partial_state_detection() -> None:
    with tempfile.TemporaryDirectory(prefix="person-identity-detection-") as tmp:
        root = pathlib.Path(tmp)
        persons_path = root / "persons.json"
        students_path = root / "students.json"
        journal_path = root / "instance" / "person_identity_transactions" / "pending.json"
        write_json(students_path, [])
        check(
            not identity_is_configured(persons_path, journal_path, students_path),
            "empty legacy roster remains legacy",
        )
        write_json(
            students_path,
            [{"id": "부분101", "personId": "per_11111111111111111111111111111111"}],
        )
        check(
            identity_is_configured(persons_path, journal_path, students_path),
            "tagged roster requires a person directory",
        )
        students_path.write_text("{broken", encoding="utf-8")
        check(
            identity_is_configured(persons_path, journal_path, students_path),
            "unreadable roster fails closed",
        )


def load_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_source_contracts() -> None:
    api_basic = (ROOT / "routes" / "api_basic.py").read_text(encoding="utf-8")
    api_auth = (ROOT / "routes" / "api_auth.py").read_text(encoding="utf-8")
    clone_js = (ROOT / "static" / "js" / "all" / "features" / "cloneButtons.js").read_text(
        encoding="utf-8"
    )
    check('field in {"id", "personId"}' in api_basic, "immutable route fields")
    check("create_student_with_identity(" in api_basic, "identity-backed add route")
    check("retire_student_identity(" in api_basic, "identity-backed delete route")
    check("identity_mode = same_person(base, base)" in api_auth, "legacy auth prefers personId")
    check("X-Clone-From-Sid" in api_basic, "legacy clone header compatibility")
    check(
        "cloneFromSid=${encodeURIComponent(sid)}" in clone_js,
        "clone query carries the explicit source SID",
    )
    check(
        "PERSON_IDENTITY_JOURNAL_PATH,\n        STU_PATH," in api_basic,
        "student writes detect a partially lost identity registry",
    )


def main() -> int:
    directory, students = verify_pure_backfill()
    verify_store_lifecycle(directory, students)
    verify_rollback_and_crash_recovery()
    verify_partial_state_detection()
    verify_source_contracts()
    print("person identity verification: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
