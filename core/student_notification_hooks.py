"""Small idempotent adapters from canonical mutations to notification events."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
from typing import Iterable

from core.student_app_config import load_student_app_config
from core.student_notification_events import deterministic_event_id, milestones_crossed
from core.student_notification_repository import StudentNotificationRepository
from core.student_schedule_projection import project_student_schedule


def runtime_repository() -> StudentNotificationRepository | None:
    """Return an unopened repository only while the rollout explicitly enables reminders."""
    config = load_student_app_config()
    if not config.public_enabled or not config.reminders_enabled:
        return None
    root = Path(__file__).resolve().parents[1]
    return StudentNotificationRepository(Path(os.environ.get("STUDENT_APP_DB_PATH", root / "app.sqlite")))


def enqueue_homework_events(
    repository: StudentNotificationRepository,
    sid: str,
    assignments: Iterable[dict],
    *,
    now: dt.datetime,
) -> int:
    """Enqueue assignment and due reminders after canonical reconciliation succeeds."""
    current = now.timestamp()
    inserted = 0
    for row in assignments:
        if not isinstance(row, dict) or row.get("status") != "assigned":
            continue
        assignment_id = str(row.get("id") or "").strip()
        due_text = row.get("due_at")
        if not assignment_id or not isinstance(due_text, str):
            continue
        try:
            due = dt.datetime.fromisoformat(due_text)
        except ValueError:
            continue
        if due.tzinfo is None or due <= now:
            continue
        assigned_id = deterministic_event_id("homework_assigned", assignment_id)
        due_id = deterministic_event_id("homework_due", assignment_id, due_text)
        inserted += int(repository.enqueue("homework_assigned", assigned_id, sid, now=current)["inserted"])
        inserted += int(repository.enqueue(
            "homework_due", due_id, sid,
            scheduled_at=max(current, due.timestamp() - 86_400), now=current,
        )["inserted"])
    return inserted


def enqueue_schedule_change(
    repository: StudentNotificationRepository,
    sid: str,
    schedule: Iterable[dict],
    now: float,
    revision: int,
) -> int:
    snapshot_key = schedule_snapshot_event_id(sid, schedule)
    result = repository.commit_schedule_projection(
        sid, revision, snapshot_key, scheduled_at=now + 10.0, now=now,
    )
    return int(bool(result["inserted"]))


def student_schedule_changed_sids(previous: object, current: object) -> tuple[str, ...]:
    """Return only roster IDs whose regular day/time inputs changed."""
    def rows(value: object) -> dict[str, dict]:
        return {
            str(row.get("id") or "").strip(): row
            for row in (value if isinstance(value, list) else [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }

    def signature(row: dict | None) -> str:
        if row is None:
            return ""
        selected = {
            str(key): value
            for key, value in row.items()
            if re.fullmatch(r"(?:day|visitTime)\d+", str(key))
        }
        return json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    before, after = rows(previous), rows(current)
    return tuple(sorted(
        sid for sid in set(before) | set(after)
        if signature(before.get(sid)) != signature(after.get(sid))
    ))


def schedule_snapshot_event_id(sid: str, schedule: Iterable[dict]) -> str:
    rows = []
    for row in schedule:
        if not isinstance(row, dict):
            continue
        rows.append({
            "kind": row.get("kind"), "status": row.get("status"), "date": row.get("date"),
            "startAt": row.get("startAt"), "slots": row.get("slots"),
        })
    canonical = json.dumps(sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)),
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return deterministic_event_id("schedule_changed", sid, canonical)


def _runtime_json(name: str, default_name: str) -> object:
    root = Path(__file__).resolve().parents[1]
    path = Path(os.environ.get(name, root / default_name))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def enqueue_current_schedule_changes(sids: Iterable[str], *, now: dt.datetime | None = None) -> int:
    """Project fresh schedule snapshots only after a successful schedule mutation."""
    repository = runtime_repository()
    if repository is None:
        return 0
    current = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    selected = tuple(dict.fromkeys(str(value or "").strip() for value in sids if str(value or "").strip()))
    revisions = repository.mark_schedule_pending(selected, now=current.timestamp())
    if not revisions:
        return 0
    try:
        students = _runtime_json("STUDENT_APP_STUDENTS_PATH", "students.json")
        absence = _runtime_json("STUDENT_APP_ABSENT_PATH", "absent.json")
        extra = _runtime_json("STUDENT_APP_EXTRA_PATH", "extra_attend.json")
        weekend = _runtime_json("STUDENT_APP_WEEKEND_PATH", "weekend_slots.json")
        makeup = _runtime_json("STUDENT_APP_MAKEUP_PATH", "makeup_carryover.json")
    except Exception:
        return 0
    by_sid = {
        str(row.get("id") or ""): row for row in students if isinstance(row, dict) and row.get("id")
    } if isinstance(students, list) else {}
    start, end = current.date(), current.date() + dt.timedelta(days=45)
    inserted = 0
    for sid, revision in revisions.items():
        student = by_sid.get(sid)
        if not isinstance(student, dict):
            repository.discard_schedule_projection(sid, revision, now=current.timestamp())
            continue
        try:
            schedule = project_student_schedule(
                student, sid=sid, start_date=start.isoformat(), end_date=end.isoformat(),
                absence=absence, extra=extra, weekend=weekend, makeup=makeup,
            )
            inserted += enqueue_schedule_change(
                repository, sid, schedule, now=current.timestamp(), revision=revision,
            )
        except Exception:
            continue
    return inserted


def enqueue_progress_milestones(
    repository: StudentNotificationRepository,
    sid: str,
    curriculum_key: str,
    previous_percent: int | None,
    current_percent: int | None,
    *,
    now: float,
) -> int:
    inserted = 0
    for milestone in milestones_crossed(previous_percent, current_percent):
        result = repository.record_milestone(sid, curriculum_key, milestone, reached_at=now, now=now)
        inserted += int(bool(result["inserted"]))
    return inserted


def enqueue_announcement_events(
    repository: StudentNotificationRepository,
    announcement_id: str,
    target_sids: Iterable[str],
    *,
    now: float,
) -> list[int]:
    event_id = deterministic_event_id("announcement_published", announcement_id)
    rows = []
    for sid in dict.fromkeys(target_sids):
        if not isinstance(sid, str) or not sid:
            continue
        result = repository.enqueue("announcement_published", event_id, sid, now=now)
        rows.append(int(result["id"]))
    return rows


__all__ = [
    "enqueue_announcement_events", "enqueue_homework_events", "enqueue_progress_milestones",
    "enqueue_current_schedule_changes", "enqueue_schedule_change", "runtime_repository",
    "schedule_snapshot_event_id", "student_schedule_changed_sids",
]
