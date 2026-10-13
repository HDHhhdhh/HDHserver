"""Compare approved standalone snapshots; never apply to source runtime data."""
from __future__ import annotations

import argparse
import copy
from contextlib import closing
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fingerprint(path: Path) -> tuple:
    before = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise RuntimeError("Input changed while fingerprinting")
    return after.st_mtime_ns, after.st_size, digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--students", type=Path, required=True)
    parser.add_argument("--exercise-copy", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    inputs = [path.resolve(strict=True) for path in (args.database, args.logs, args.students)]
    database, logs_path, students = inputs
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        parser.error("Use a verified standalone native backup without sidecars")
    if args.report and (args.report.resolve() in inputs or args.report.exists()):
        parser.error("Report must be a new file outside the inputs")
    before = [fingerprint(path) for path in inputs]
    report = {"source_runtime_modified": False, "copy_exercised": False}
    from core.log_repository import LogRepository, _public_map
    from core import log_reconcile
    from routes import log_repository_provider as provider
    with tempfile.TemporaryDirectory(prefix="p5-offline-eval-") as temp:
        temp_root = Path(temp)
        copy_db, copy_logs = temp_root / "app.sqlite", temp_root / "logs.json"
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as source:
            source.execute("PRAGMA query_only=ON")
            with closing(sqlite3.connect(copy_db)) as target:
                source.backup(target)
        copy_logs.write_bytes(logs_path.read_bytes())
        provider.STU_PATH = students
        books = provider._load_student_homework_books_by_sid()
        provider._student_homework_books = lambda sid: list(books.get(str(sid), []))
        dual = LogRepository(logs_path=copy_logs, db_path=str(copy_db), store_mode="dual",
                             repair_entry=provider.repair_log_entry_placeholders)
        sqlite_only = LogRepository(logs_path=copy_logs, db_path=str(copy_db), store_mode="sqlite",
                                    json_export=False, repair_entry=provider.repair_log_entry_placeholders)
        with closing(sqlite3.connect(copy_db, isolation_level=None)) as connection:
            rows = log_reconcile.read_rows(connection)
            compatibility = json.loads(copy_logs.read_text("utf-8-sig"))
            plan = log_reconcile.build_plan(rows, compatibility, dual,
                      inserted_updated_at=dt.datetime.now(dt.timezone.utc).isoformat())
            report.update(plan.report())
            if args.exercise_copy:
                log_reconcile.apply_plan(connection, plan, dual, owned_root=temp_root)
                report["copy_exercised"] = True
            elif plan.mutations:
                report["scope_parity_pending_reconciliation"] = True
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 1
            expected = dual.read_logs()
            failures, comparisons = [], 0

            def compare(label, left, right):
                nonlocal comparisons
                comparisons += 1
                if not log_reconcile.same(left, right):
                    failures.append(label)

            compare("full", expected, sqlite_only.read_logs())
            sids = sorted({sid for day in expected.values() if isinstance(day, dict) for sid in day})
            for date in sorted(expected):
                compare("date", dual.read_logs(date), sqlite_only.read_logs(date))
                compare("date_sids", dual.read_logs(date, sid_filters=sids),
                        sqlite_only.read_logs(date, sid_filters=sids))
            for sid in sids:
                compare("sid", dual.read_logs(sid_filter=sid), sqlite_only.read_logs(sid_filter=sid))
            compare("sids", dual.read_logs(sid_filters=sids), sqlite_only.read_logs(sid_filters=sids))
            targets = {sid: max(date for date, day in expected.items() if sid in day) for sid in sids}
            compare("export_history", dual.read_export_history(targets), sqlite_only.read_export_history(targets))
            compare("unarchived_summary", dual.summarize_unarchived_done(), sqlite_only.summarize_unarchived_done())
            report.update(scoped_comparisons=comparisons, scoped_failure_count=len(failures),
                          scoped_failure_kinds=sorted(set(failures)), all_scoped_public_map_parity=not failures)
            if args.exercise_copy:
                log_reconcile.rollback_plan(connection, plan, owned_root=temp_root)
                report["exact_log_row_rollback"] = log_reconcile.row_digest(log_reconcile.read_rows(connection)) == log_reconcile.row_digest(rows)
    after = [fingerprint(path) for path in inputs]
    if before != after:
        raise RuntimeError("Input snapshot changed during verification")
    report["source_fingerprints_preserved"] = True
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        with args.report.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    print(payload)
    return 0 if report.get("full_public_map_parity") and report.get("all_scoped_public_map_parity") else 1


if __name__ == "__main__":
    raise SystemExit(main())
