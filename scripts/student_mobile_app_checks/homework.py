"""Temp-SQLite contract checks for canonical student homework."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
IMPORT_STATE = {name: name in sys.modules for name in ("app", "core.paths")}

from core.student_homework_repository import (  # noqa: E402
    HomeworkConflictError,
    HomeworkNotInitializedError,
    StudentHomeworkRepository,
)
from core.student_homework_service import (  # noqa: E402
    HomeworkValidationError,
    attach_assignment_ids,
    audit_orphans,
    kst_iso,
    legacy_homework_projection,
    prepare_assignment,
    prepare_batch,
    prepare_reconciliation,
    public_page,
    public_projection,
    read_legacy_homework,
    reconciliation_result,
)


KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime(2026, 8, 9, 12, 0, 0, tzinfo=KST)
MIGRATION = ROOT / "scripts/migrations/20260809_create_student_homework.sql"


def _check(state: dict, condition: bool, label: str) -> None:
    state["assertions"] += 1
    if not condition:
        raise AssertionError(label)


def _raises(state: dict, error_type, code: str, action, label: str) -> None:
    try:
        action()
    except error_type as exc:
        _check(state, getattr(exc, "code", None) == code, f"{label}: wrong error code")
    else:
        raise AssertionError(label)


def _payload(source: str, title: str, *, due=None, status="assigned", revision=None, row_index=None):
    payload = {
        "sourceRowId": source, "title": title, "book": "개념원리", "scope": "10~12쪽",
        "assignedAt": "2026-08-09T09:00:00+09:00", "dueAt": due, "status": status,
    }
    if revision is not None:
        payload["expectedRevision"] = revision
    if row_index is not None:
        payload["rowIndex"] = row_index
    return payload


def _apply(repo, sid: str, date: str, payloads, *, existing=()):
    items = prepare_batch(payloads, sid=sid, source_log_date=date, now=NOW, existing=existing)
    return repo.apply_batch(sid, date, items, now=kst_iso(NOW)), items


def _side_effect_checks(state: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="student-homework-side-effect-") as tmp:
        db_path = Path(tmp) / "must-not-exist.sqlite"
        before = tuple(Path(tmp).iterdir())
        env = dict(os.environ, PYTHONPATH=str(ROOT), STUDENT_APP_HOMEWORK_ENABLED="0")
        probe = "from core.student_homework_repository import StudentHomeworkRepository as R; R('must-not-exist.sqlite')"
        subprocess.run([sys.executable, "-c", probe], cwd=tmp, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _check(state, tuple(Path(tmp).iterdir()) == before, "import/constructor/flag-off created storage")
        repo = StudentHomeworkRepository(str(db_path))
        _check(state, repo.schema_ready() is False and not db_path.exists(), "schema probe created a missing database")
        _raises(state, HomeworkNotInitializedError, "homework_not_initialized",
                lambda: repo.list_for_sid("sid-a"), "missing database read did not fail typed")
        _check(state, not db_path.exists() and not Path(f"{db_path}-wal").exists(), "missing read created DB/WAL")

        empty = Path(tmp) / "empty.sqlite"
        sqlite3.connect(empty).close()
        empty_repo = StudentHomeworkRepository(str(empty))
        _raises(state, HomeworkNotInitializedError, "homework_not_initialized",
                lambda: empty_repo.count_open("sid-a"), "missing table read did not fail typed")
        with closing(sqlite3.connect(empty)) as con:
            tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        _check(state, tables == [] and not Path(f"{empty}-wal").exists(), "GET-style read migrated or enabled WAL")


def _schema_checks(state: dict, repo: StudentHomeworkRepository, db_path: Path) -> None:
    sql = MIGRATION.read_text("utf-8")
    repo.apply_migration(sql)
    repo.apply_migration(sql)
    _check(state, repo.schema_ready(), "explicit migration did not initialize schema")
    expected_assignments = [
        "id", "sid", "curriculum_sid", "title", "book", "scope", "assigned_at", "due_at",
        "status", "completed_at", "source_log_date", "source_row_id", "revision", "created_at", "updated_at",
    ]
    expected_reconciliations = [
        "id", "operation_id", "sid", "source_log_date", "request_hash", "desired_log_json",
        "desired_assignments_json", "log_state", "homework_state", "state", "attempts",
        "last_error_code", "created_at", "updated_at",
    ]
    with closing(sqlite3.connect(db_path)) as con:
        columns_a = [row[1] for row in con.execute("PRAGMA table_info(student_homework_assignments)")]
        columns_r = [row[1] for row in con.execute("PRAGMA table_info(student_homework_reconciliations)")]
        indexes = {row[1] for row in con.execute("PRAGMA index_list(student_homework_assignments)")}
        recon_indexes = {row[1]: row[4] for row in con.execute("PRAGMA index_list(student_homework_reconciliations)")}
        due_index = [row[2] for row in con.execute("PRAGMA index_info(idx_student_homework_sid_status_due_assigned_id)")]
        source_index = [row[2] for row in con.execute("PRAGMA index_info(idx_student_homework_sid_source)")]
        assignment_sql = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='student_homework_assignments'"
        ).fetchone()[0]
        active_index_sql = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_student_homework_reconciliation_active_source'"
        ).fetchone()[0]
    _check(state, columns_a == expected_assignments, "assignment migration columns drifted")
    _check(state, columns_r == expected_reconciliations, "reconciliation migration columns drifted")
    _check(state, {"idx_student_homework_sid_status_due_assigned_id", "idx_student_homework_sid_source"} <= indexes,
           "assignment indexes are incomplete")
    _check(state, due_index == ["sid", "status", "due_at", "assigned_at", "id"]
           and source_index == ["sid", "source_log_date", "source_row_id"], "assignment index columns drifted")
    _check(state, recon_indexes.get("idx_student_homework_reconciliation_active_source") == 1,
           "active-source reconciliation index is not partial")
    _check(state, "idx_student_homework_reconciliation_state" in recon_indexes, "state index is missing")
    _check(state, "WHERE state IN ('prepared', 'partial_failure')" in active_index_sql,
           "active-source partial index predicate drifted")
    _check(state, "completed_at IS NOT NULL" in assignment_sql and "revision >= 1" in assignment_sql,
           "assignment CHECK constraints drifted")
    with closing(sqlite3.connect(db_path)) as con:
        try:
            con.execute(
                "INSERT INTO student_homework_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("bad", "sid", None, "bad", "", "", kst_iso(NOW), None, "overdue", None,
                 "2026-08-09", "bad", 1, kst_iso(NOW), kst_iso(NOW)),
            )
        except sqlite3.IntegrityError:
            _check(state, True, "")
        else:
            raise AssertionError("database accepted stored overdue status")


def _assignment_checks(state: dict, repo: StudentHomeworkRepository) -> list[dict]:
    due = "2026-08-10T12:00:00+09:00"
    first, prepared = _apply(repo, "sid-a", "2026-08-09", [_payload("row-1", "첫 숙제", due=due, row_index=0)])
    _check(state, len(first) == 1 and first[0]["revision"] == 1, "initial assignment insert failed")
    replay, replay_prepared = _apply(repo, "sid-a", "2026-08-09", [_payload("row-1", "첫 숙제", due=due)])
    _check(state, replay[0]["id"] == first[0]["id"] and replay[0]["revision"] == 1,
           "same source/payload retry duplicated or bumped revision")
    _check(state, replay_prepared[0]["id"] != first[0]["id"], "retry fixture did not exercise generated-id replacement")
    _raises(state, HomeworkConflictError, "revision_conflict",
            lambda: _apply(repo, "sid-a", "2026-08-09", [_payload("row-1", "changed", due=due)]),
            "changed payload without expected revision succeeded")
    changed, _ = _apply(repo, "sid-a", "2026-08-09", [_payload("row-1", "수정 숙제", due=due, revision=1)])
    _check(state, changed[0]["revision"] == 2 and changed[0]["title"] == "수정 숙제", "optimistic update failed")
    _raises(state, HomeworkConflictError, "revision_conflict",
            lambda: _apply(repo, "sid-a", "2026-08-09", [_payload("row-1", "stale", due=due, revision=1)]),
            "stale revision succeeded")

    barrier_payloads = [_payload("row-1", title, due=due, revision=2) for title in ("동시 A", "동시 B")]
    def compete(payload):
        try:
            return _apply(StudentHomeworkRepository(repo.db_path), "sid-a", "2026-08-09", [payload])[0][0]
        except HomeworkConflictError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, barrier_payloads))
    _check(state, sum(isinstance(item, dict) for item in results) == 1 and results.count("revision_conflict") == 1,
           "concurrent writers did not produce exactly one revision conflict")
    current = repo.list_for_log_date("sid-a", "2026-08-09")
    _check(state, len(current) == 1 and current[0]["revision"] == 3, "concurrent update lost or duplicated a row")

    rows = [{"book": "개념원리", "next": "10쪽", "unknown": "preserve"}]
    attached = attach_assignment_ids(rows, prepared)
    _check(state, attached[0]["assignmentId"] == first[0]["id"] and attached[0]["unknown"] == "preserve",
           "assignment ID attachment did not preserve legacy fields")
    _check(state, "assignmentId" not in rows[0], "assignment ID attachment mutated caller rows")

    cancellation = prepare_batch([], sid="sid-a", source_log_date="2026-08-09", now=NOW, existing=current)
    _check(state, len(cancellation) == 1 and cancellation[0]["status"] == "cancelled",
           "removed homework row was not projected as cancelled")
    cancelled = repo.apply_batch("sid-a", "2026-08-09", cancellation, now=kst_iso(NOW))[0]
    _check(state, cancelled["status"] == "cancelled" and cancelled["revision"] == 4,
           "removed homework row was deleted or not revisioned")
    return repo.list_for_log_date("sid-a", "2026-08-09")


def _projection_checks(state: dict, repo: StudentHomeworkRepository) -> None:
    cases = [
        ("null", None, "assigned"),
        ("future", "2026-08-09T12:00:01+09:00", "assigned"),
        ("now", "2026-08-09T12:00:00+09:00", "assigned"),
        ("past", "2026-08-09T11:59:59+09:00", "assigned"),
        ("completed", "2026-08-09T12:00:01+09:00", "completed"),
        ("cancelled", "2026-08-09T12:00:01+09:00", "cancelled"),
    ]
    rows = []
    for index, (label, due, status) in enumerate(cases):
        payload = _payload(f"case-{label}", f"case-{label}", due=due, status=status)
        item = prepare_assignment(payload, sid="sid-a", source_log_date="2026-08-10", now=NOW)
        rows.extend(repo.apply_batch("sid-a", "2026-08-10", [item], now=kst_iso(NOW)))
    projections = {row["title"]: public_projection(row, now=NOW) for row in rows}
    completed_row = next(row for row in rows if row["title"] == "case-completed")
    reopened = prepare_batch(
        [_payload("case-completed", "case-completed", due=None, status="assigned", revision=1)],
        sid="sid-a", source_log_date="2026-08-10", now=NOW, existing=[completed_row],
    )[0]
    _check(state, reopened["status"] == "assigned" and reopened["completed_at"] is None,
           "reopening a completed assignment retained completedAt")
    malformed_status = _payload("case-completed", "case-completed", status=["assigned"], revision=1)
    _raises(state, HomeworkValidationError, "invalid_payload",
            lambda: prepare_batch([malformed_status], sid="sid-a", source_log_date="2026-08-10",
                                  now=NOW, existing=[completed_row]),
            "non-string status escaped typed validation")
    _check(state, projections["case-future"]["notificationEligible"] is True,
           "future assigned homework was not notification eligible")
    for label in ("null", "now", "past", "completed", "cancelled"):
        _check(state, projections[f"case-{label}"]["notificationEligible"] is False,
               f"{label} homework was incorrectly notification eligible")
    _check(state, projections["case-now"]["status"] == "assigned" and projections["case-past"]["status"] == "assigned",
           "read projection changed stored status instead of leaving overdue derivation to client")
    _check(state, all(item["legacy"] is False for item in projections.values()), "canonical projection omitted legacy=false")
    dumped = json.dumps(projections, ensure_ascii=False)
    _check(state, all(key not in dumped for key in ('"sid"', "curriculumSid", "source_log_date", "source_row_id", "revision")),
           "public projection leaked SID/source/revision")

    _apply(repo, "sid-b", "2026-08-11", [_payload("sid-b-row", "SID-B-MARKER", due=None)])
    page = public_page(repo, sid="sid-a", status="all", page_size=2, now=NOW)
    _check(state, len(page["items"]) == 2 and page["nextCursor"], "bounded first page/cursor failed")
    page2 = public_page(repo, sid="sid-a", status="all", cursor=page["nextCursor"], page_size=50, now=NOW)
    _check(state, "SID-B-MARKER" not in json.dumps(page) + json.dumps(page2), "SID-B marker leaked into SID-A page")
    sid_b = repo.list_for_log_date("sid-b", "2026-08-11")[0]
    _check(state, repo.get("sid-a", sid_b["id"]) is None, "cross-SID get succeeded")
    _raises(state, HomeworkValidationError, "invalid_cursor",
            lambda: public_page(repo, sid="sid-a", cursor="evil", now=NOW), "malformed cursor succeeded")
    _raises(state, HomeworkValidationError, "invalid_payload",
            lambda: public_page(repo, sid="sid-a", page_size=51, now=NOW), "page size above 50 succeeded")


def _legacy_checks(state: dict, tmp: Path) -> None:
    table = [{"book": "쎈", "next": "20쪽", "comment": "풀이", "assignmentId": "hw_abcdefghijklmnop",
              "_deleted": False}, {"_deleted": True}]
    projected = legacy_homework_projection(table, sid="sid-a", source_log_date="2026-08-08")
    _check(state, len(projected) == 1 and projected[0]["dueAt"] is None, "legacy projection invented a due date")
    _check(state, projected[0]["notificationEligible"] is False and projected[0]["legacy"] is True,
           "legacy projection became notification eligible or lost marker")
    _check(state, projected[0]["id"] == "hw_abcdefghijklmnop", "legacy projection lost its canonical link ID")
    logs_path = tmp / "legacy.json"
    logs_path.write_text(json.dumps({"2026-08-08": {"sid-a": {"homeworkTable": table}},
                                     "2026-08-09": {"sid-a": {"homeworkTable": []}}}, ensure_ascii=False), "utf-8")
    before = logs_path.read_bytes()
    loaded = read_legacy_homework(logs_path, sid="sid-a", source_log_date="2026-08-09")
    _check(state, loaded == projected and logs_path.read_bytes() == before, "legacy direct read changed data or shape")


def _reconciliation_checks(state: dict, repo: StudentHomeworkRepository, assignments: list[dict]) -> None:
    desired = [{"rowIndex": 0, "book": "쎈", "assignmentId": assignments[0]["id"]}]
    prepared = prepare_reconciliation(sid="sid-a", source_log_date="2026-08-09", desired_log={"homeworkTable": desired},
                                      assignments=assignments, now=NOW, operation_id="operation-0001")
    first = repo.begin_operation(prepared)
    regenerated = [{**assignments[0], "id": "hw_ABCDEFGHIJKLMNOP"}]
    replay_operation = prepare_reconciliation(
        sid="sid-a", source_log_date="2026-08-09",
        desired_log={"homeworkTable": [{**desired[0], "assignmentId": "hw_ABCDEFGHIJKLMNOP"}]},
        assignments=regenerated, now=NOW, operation_id="operation-0001",
    )
    _check(state, replay_operation["request_hash"] == prepared["request_hash"],
           "generated assignment IDs changed the request hash")
    replay = repo.begin_operation(replay_operation)
    _check(state, first["id"] == replay["id"], "same operation/hash replay was not idempotent")
    altered = {**prepared, "request_hash": "0" * 64}
    _raises(state, HomeworkConflictError, "idempotency_conflict", lambda: repo.begin_operation(altered),
            "operation ID accepted a different request hash")
    competing = prepare_reconciliation(sid="sid-a", source_log_date="2026-08-09", desired_log={},
                                       assignments=[], now=NOW, operation_id="operation-0002")
    _raises(state, HomeworkConflictError, "revision_conflict", lambda: repo.begin_operation(competing),
            "active source accepted a second reconciliation")
    after_log = repo.record_log_outcome("operation-0001", "succeeded", now=kst_iso(NOW))
    _check(state, after_log["state"] == "prepared", "one successful side completed reconciliation early")
    failed = repo.record_homework_outcome("operation-0001", "failed", error_code="homework_write_failed", now=kst_iso(NOW))
    _check(state, failed["state"] == "partial_failure" and failed["last_error_code"] == "homework_write_failed",
           "log-success/homework-failure was hidden")
    _check(state, repo.pending_for_source("sid-a", "2026-08-09")["operation_id"] == "operation-0001",
           "partial reconciliation was not retryable")
    completed = repo.record_homework_outcome("operation-0001", "succeeded", now=kst_iso(NOW))
    _check(state, completed["state"] == "completed" and reconciliation_result(completed)["partialFailure"] is False,
           "fault retry did not complete reconciliation")
    _check(state, repo.pending_for_source("sid-a", "2026-08-09") is None, "completed operation remained active")

    opposite = prepare_reconciliation(sid="sid-a", source_log_date="2026-08-10", desired_log={},
                                      assignments=[], now=NOW, operation_id="operation-0003")
    repo.begin_operation(opposite)
    repo.record_homework_outcome("operation-0003", "succeeded", now=kst_iso(NOW))
    failed_log = repo.record_log_outcome("operation-0003", "failed", error_code="log_write_failed", now=kst_iso(NOW))
    _check(state, failed_log["state"] == "partial_failure", "homework-success/log-failure was hidden")
    recovered = repo.record_log_outcome("operation-0003", "succeeded", now=kst_iso(NOW))
    _check(state, recovered["state"] == "completed", "log fault retry did not complete")
    _raises(state, ValueError, None,
            lambda: repo.record_log_outcome("operation-0003", "failed", error_code="raw traceback", now=kst_iso(NOW)),
            "free-form reconciliation error text was accepted")

    all_rows, _ = repo.list_for_sid("sid-a", status="all", page_size=50)
    linked = [{"assignmentId": all_rows[0]["id"]}, {"assignmentId": "hw_missingcanonical000"}]
    before = repo.list_for_log_date("sid-a", "2026-08-10")
    audit = audit_orphans(all_rows, linked)
    after = repo.list_for_log_date("sid-a", "2026-08-10")
    _check(state, audit["repairAttempted"] is False and "hw_missingcanonical000" in audit["missingCanonicalIds"],
           "orphan audit repaired or hid a missing canonical row")
    _check(state, audit["orphanAssignmentIds"] and before == after, "orphan audit mutated canonical assignments")


def _validation_checks(state: dict) -> None:
    _raises(state, HomeworkValidationError, "invalid_payload",
            lambda: kst_iso(dt.datetime(2026, 8, 9, 12)), "naive clock succeeded")
    _raises(state, HomeworkValidationError, "invalid_payload",
            lambda: prepare_assignment(_payload("bad", "x", due="2026-08-10T00:00:00Z"),
                                       sid="sid-a", source_log_date="2026-08-09", now=NOW),
            "non-KST dueAt succeeded")
    _raises(state, HomeworkValidationError, "invalid_payload",
            lambda: prepare_assignment(_payload("bad", "x", status="overdue"),
                                       sid="sid-a", source_log_date="2026-08-09", now=NOW),
            "stored overdue status succeeded")
    _raises(state, HomeworkValidationError, "invalid_payload",
            lambda: prepare_assignment(_payload("bad", "x" * 201), sid="sid-a",
                                       source_log_date="2026-08-09", now=NOW), "oversized title succeeded")
    numeric = _payload("bad", "x")
    numeric["title"] = 123
    _raises(state, HomeworkValidationError, "invalid_payload",
            lambda: prepare_assignment(numeric, sid="sid-a", source_log_date="2026-08-09", now=NOW),
            "non-text title was coerced")


def run_checks() -> dict[str, object]:
    state = {"assertions": 0}
    _side_effect_checks(state)
    with tempfile.TemporaryDirectory(prefix="student-homework-check-") as tmp_name:
        tmp, db_path = Path(tmp_name), Path(tmp_name) / "homework.sqlite"
        repo = StudentHomeworkRepository(str(db_path))
        _schema_checks(state, repo, db_path)
        assignments = _assignment_checks(state, repo)
        _projection_checks(state, repo)
        _legacy_checks(state, tmp)
        _reconciliation_checks(state, repo, assignments)
        _validation_checks(state)
    from scripts.student_mobile_app_checks.homework_routes import run_checks as run_route_checks
    route_result = run_route_checks()
    if route_result.get("passed") is not True:
        raise AssertionError("homework route checks failed")
    state["assertions"] += int(route_result["assertions"])
    _check(state, IMPORT_STATE == {name: name in sys.modules for name in IMPORT_STATE},
           "homework modules imported app or core.paths")
    return {"name": "homework", "assertions": state["assertions"], "passed": True,
            "runtimeIsolation": "temporary SQLite/JSON only; no live app or core.paths"}


def main() -> int:
    result = run_checks()
    print(f"homework checks passed: {result['assertions']} assertions")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_checks"]
