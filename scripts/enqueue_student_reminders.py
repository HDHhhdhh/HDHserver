"""Enqueue bounded KST class and homework reminders from fresh projections."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_app_config import load_student_app_config
from core.student_homework_repository import StudentHomeworkRepository
from core.student_notification_repository import StudentNotificationRepository
from core.student_notification_hooks import schedule_snapshot_event_id
from core.student_reminder_projection import KST, build_reminder_candidates
from core.student_schedule_projection import project_student_schedule


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _homework_rows(repository: StudentHomeworkRepository, sid: str) -> list[dict]:
    rows, cursor = [], None
    while len(rows) < 500:
        page, more = repository.list_for_sid(sid, status="open", cursor=cursor, page_size=50)
        rows.extend(page)
        if not more or not page:
            break
        last = page[-1]
        cursor = (1 if last.get("due_at") is None else 0, last.get("due_at") or "",
                  last.get("assigned_at") or "", last.get("id") or "")
    return rows[:500]


def run_once(
    repository: StudentNotificationRepository,
    homework_repository: StudentHomeworkRepository,
    *,
    students: object,
    absence: object,
    extra: object,
    weekend: object,
    makeup: object,
    now: dt.datetime,
    limit: int = 500,
) -> dict[str, int]:
    if not isinstance(students, list) or not 1 <= int(limit) <= 500:
        raise ValueError("invalid reminder input")
    by_sid = {
        str(row.get("id") or "").strip(): row for row in students
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    inserted, reconciled = 0, 0
    for pending in repository.pending_schedule_revisions(limit=int(limit)):
        sid, revision = str(pending["sid"]), int(pending["revision"])
        student = by_sid.get(sid)
        if not isinstance(student, dict):
            repository.discard_schedule_projection(sid, revision, now=now.timestamp())
            reconciled += 1
            continue
        try:
            schedule = project_student_schedule(
                student, sid=sid, start_date=now.date().isoformat(),
                end_date=(now.date() + dt.timedelta(days=45)).isoformat(),
                absence=absence, extra=extra, weekend=weekend, makeup=makeup,
            )
            result = repository.commit_schedule_projection(
                sid, revision, schedule_snapshot_event_id(sid, schedule),
                scheduled_at=now.timestamp() + 10.0, now=now.timestamp(),
            )
        except Exception:
            continue
        inserted += int(bool(result["inserted"]))
        reconciled += 1
    candidates = []
    reminder_end = (now.date() + dt.timedelta(days=1)).isoformat()
    for student in students:
        if not isinstance(student, dict):
            continue
        sid = str(student.get("id") or "").strip()
        if not sid:
            continue
        schedule = project_student_schedule(
            student, sid=sid, start_date=now.date().isoformat(), end_date=reminder_end,
            absence=absence, extra=extra, weekend=weekend, makeup=makeup,
        )
        homework = _homework_rows(homework_repository, sid)
        candidates.extend(build_reminder_candidates(
            sid=sid, schedule=schedule, homework=homework, now=now,
            max_events=min(500, int(limit)),
        ))
        if len(candidates) + reconciled >= int(limit):
            break
    unique = {
        (row["event_type"], row["event_id"], row["sid"]): row
        for row in candidates
    }
    selected = sorted(
        unique.values(), key=lambda row: (row["scheduled_at"], row["event_type"], row["event_id"]),
    )[:max(0, int(limit) - reconciled)]
    for row in selected:
        result = repository.enqueue(
            row["event_type"], row["event_id"], row["sid"],
            scheduled_at=row["scheduled_at"], now=now.timestamp(),
        )
        inserted += int(bool(result["inserted"]))
    return {"candidates": reconciled + len(selected), "inserted": inserted}


def _runtime() -> tuple[StudentNotificationRepository, StudentHomeworkRepository, dict[str, object]] | None:
    config = load_student_app_config()
    if not config.public_enabled or not config.reminders_enabled:
        return None
    db_path = Path(os.environ.get("STUDENT_APP_DB_PATH", ROOT / "app.sqlite"))
    paths = {
        "students": Path(os.environ.get("STUDENT_APP_STUDENTS_PATH", ROOT / "students.json")),
        "absence": Path(os.environ.get("STUDENT_APP_ABSENT_PATH", ROOT / "absent.json")),
        "extra": Path(os.environ.get("STUDENT_APP_EXTRA_PATH", ROOT / "extra_attend.json")),
        "weekend": Path(os.environ.get("STUDENT_APP_WEEKEND_PATH", ROOT / "weekend_slots.json")),
        "makeup": Path(os.environ.get("STUDENT_APP_MAKEUP_PATH", ROOT / "makeup_carryover.json")),
    }
    return StudentNotificationRepository(db_path), StudentHomeworkRepository(db_path), {
        key: _load(path) for key, path in paths.items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)
    if not args.once or not 1 <= args.limit <= 500:
        print(json.dumps({"ok": False, "code": "invalid_invocation"}, separators=(",", ":")))
        return 2
    try:
        runtime = _runtime()
        if runtime is None:
            print(json.dumps({"ok": True, "disabled": True, "candidates": 0, "inserted": 0}, separators=(",", ":")))
            return 0
        repository, homework, data = runtime
        result = run_once(repository, homework, now=dt.datetime.now(KST), limit=args.limit, **data)
    except Exception:  # noqa: BROAD_EXCEPT_OK - operational output stays opaque
        print(json.dumps({"ok": False, "code": "scanner_failed"}, separators=(",", ":")))
        return 1
    print(json.dumps({"ok": True, **result}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
