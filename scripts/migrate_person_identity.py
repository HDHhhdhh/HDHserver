"""Plan and apply the initial personId directory migration.

Dry-run is the default. Live apply requires a reviewed plan, a matching runtime
backup, an explicit confirmation phrase, and a stopped production listener.
This script intentionally does not import ``core.paths`` or ``app``.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import pathlib
import socket
import sys
import zipfile
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.person_identity import (  # noqa: E402
    PersonIdentityConflictError,
    build_initial_backfill,
    validate_identity_state,
)
from core.person_identity_store import (  # noqa: E402
    initialize_identity_state,
    load_identity_state_strict,
    sha256_file,
)


PLAN_VERSION = 1
ALGORITHM = "strict-profile-shared-doc/v1"
CONFIRMATION = "APPLY_PERSON_IDENTITY_V1"


def utc_now_isoz() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_strict(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"unreadable JSON: {path}") from exc


def build_plan(root: pathlib.Path) -> dict[str, Any]:
    students_path = root / "students.json"
    persons_path = root / "persons.json"
    if persons_path.exists():
        directory, students = load_identity_state_strict(persons_path, students_path)
        return {
            "version": PLAN_VERSION,
            "algorithm": ALGORITHM,
            "generatedAt": utc_now_isoz(),
            "alreadyInitialized": True,
            "sourceStudentsSha256": sha256_file(students_path),
            "summary": {
                "students": len(students),
                "persons": len(directory["persons"]),
                "multiSidPersons": sum(
                    1
                    for record in directory["persons"].values()
                    if sum(
                        1
                        for link in record.get("sidLinks", {}).values()
                        if isinstance(link, dict) and link.get("status") == "active"
                    ) > 1
                ),
            },
        }

    students = load_json_strict(students_path)
    generated_at = utc_now_isoz()
    directory, next_students, assignments = build_initial_backfill(
        students,
        now=generated_at,
    )
    person_ids = {
        str(row.get("id") or "").strip(): str(row.get("personId") or "").strip()
        for row in next_students
    }
    multi = sum(1 for assignment in assignments if len(assignment["sids"]) > 1)
    return {
        "version": PLAN_VERSION,
        "algorithm": ALGORITHM,
        "generatedAt": generated_at,
        "alreadyInitialized": False,
        "sourceStudentsSha256": sha256_file(students_path),
        "requiresPersonsAbsent": True,
        "summary": {
            "students": len(next_students),
            "persons": len(assignments),
            "multiSidPersons": multi,
            "singletonPersons": len(assignments) - multi,
        },
        "assignments": assignments,
        "studentPersonIds": person_ids,
        "directory": directory,
    }


def validate_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise RuntimeError("migration plan must be an object")
    if plan.get("version") != PLAN_VERSION or plan.get("algorithm") != ALGORITHM:
        raise RuntimeError("migration plan version or algorithm is unsupported")
    if plan.get("alreadyInitialized") is True:
        raise RuntimeError("the supplied plan reports an already initialized directory")
    if not isinstance(plan.get("sourceStudentsSha256"), str):
        raise RuntimeError("migration plan source hash is missing")
    if not isinstance(plan.get("directory"), dict):
        raise RuntimeError("migration plan directory is missing")
    mapping = plan.get("studentPersonIds")
    if not isinstance(mapping, dict) or not mapping:
        raise RuntimeError("migration plan SID mapping is missing")
    return plan


def students_from_plan(current_students: Any, plan: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(current_students, list):
        raise RuntimeError("students store must be an array")
    mapping = plan["studentPersonIds"]
    next_students = copy.deepcopy(current_students)
    seen: set[str] = set()
    for row in next_students:
        if not isinstance(row, dict):
            raise RuntimeError("every student row must be an object")
        sid = str(row.get("id") or "").strip()
        person_id = mapping.get(sid)
        if not isinstance(person_id, str) or not person_id:
            raise RuntimeError(f"migration plan does not cover SID: {sid}")
        row["personId"] = person_id
        seen.add(sid)
    extra = set(mapping) - seen
    if extra:
        raise RuntimeError("migration plan contains unknown SIDs: " + ", ".join(sorted(extra)))
    validate_identity_state(plan["directory"], next_students)
    return next_students


def verify_backup(archive: pathlib.Path, expected_students_sha256: str) -> dict[str, Any]:
    if not archive.is_file():
        raise RuntimeError(f"backup archive does not exist: {archive}")
    try:
        with zipfile.ZipFile(archive, "r") as bundle:
            manifest = json.loads(bundle.read("MANIFEST.json").decode("utf-8"))
    except (OSError, KeyError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise RuntimeError("backup archive or manifest is unreadable") from exc
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        raise RuntimeError("backup manifest file list is invalid")
    student_entry = next(
        (entry for entry in files if isinstance(entry, dict) and entry.get("path") == "students.json"),
        None,
    )
    if not student_entry or str(student_entry.get("sha256") or "").lower() != expected_students_sha256.lower():
        raise RuntimeError("backup students.json hash does not match the reviewed plan")
    return manifest


def production_listener_available(port: int = 8003) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def write_plan(path: pathlib.Path, plan: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise RuntimeError(f"plan already exists; pass --overwrite-plan to replace it: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_plan(root: pathlib.Path, plan: dict[str, Any], backup_archive: pathlib.Path) -> dict[str, Any]:
    students_path = root / "students.json"
    persons_path = root / "persons.json"
    journal_path = root / "instance" / "person_identity_transactions" / "pending.json"
    if production_listener_available():
        raise RuntimeError("production port 8003 is listening; stop the server before applying")
    if persons_path.exists():
        raise RuntimeError("persons.json already exists; refusing an initial migration")
    source_hash = str(plan["sourceStudentsSha256"]).lower()
    if sha256_file(students_path) != source_hash:
        raise RuntimeError("students.json changed after the reviewed plan was created")
    verify_backup(backup_archive, source_hash)
    current_students = load_json_strict(students_path)
    next_students = students_from_plan(current_students, plan)
    initialize_identity_state(
        persons_path,
        students_path,
        journal_path,
        plan["directory"],
        next_students,
        expected_students_sha256=source_hash,
        require_persons_absent=True,
    )
    directory, persisted_students = load_identity_state_strict(persons_path, students_path)
    return {
        "ok": True,
        "students": len(persisted_students),
        "persons": len(directory["persons"]),
        "revision": directory["revision"],
        "studentsSha256": sha256_file(students_path),
        "personsSha256": sha256_file(persons_path),
        "backup": str(backup_archive.resolve()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan or apply stable personId backfill.")
    parser.add_argument("--root", type=pathlib.Path, default=ROOT)
    parser.add_argument("--write-plan", type=pathlib.Path)
    parser.add_argument("--overwrite-plan", action="store_true")
    parser.add_argument("--plan", type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-archive", type=pathlib.Path)
    parser.add_argument("--confirm", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        if args.apply:
            if args.confirm != CONFIRMATION:
                raise RuntimeError(f"live apply requires --confirm {CONFIRMATION}")
            if args.plan is None or args.backup_archive is None:
                raise RuntimeError("live apply requires --plan and --backup-archive")
            plan = validate_plan(load_json_strict(args.plan))
            result = apply_plan(root, plan, args.backup_archive)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        plan = build_plan(root)
        if args.write_plan is not None:
            write_plan(args.write_plan, plan, overwrite=args.overwrite_plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    except PersonIdentityConflictError as exc:
        payload = {
            "ok": False,
            "error": str(exc),
            "conflicts": list(exc.conflicts),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
