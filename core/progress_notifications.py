from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from typing import Any

from core.progress_rules import latest_video_status_by_sid
from core.storage import load
from core.student_curriculum_progress import build_curriculum_progress
from core.student_notification_hooks import enqueue_progress_milestones, runtime_repository


KST = dt.timezone(dt.timedelta(hours=9))


def progress_notification_snapshot(
    progress: dict,
    sid: str,
    *,
    students_path: Any,
    videos_path: Any,
):
    """Build a best-effort, default-off milestone snapshot around one progress write."""
    repository = runtime_repository()
    if repository is None:
        return None
    try:
        students, videos = load(students_path), load(videos_path)
        student = next(
            (row for row in students if isinstance(row, dict) and str(row.get("id") or "") == str(sid)),
            None,
        ) if isinstance(students, list) else None
        if not isinstance(student, dict) or not isinstance(videos, list):
            return None
        statuses = latest_video_status_by_sid(progress).get(str(sid), {})
        summary = build_curriculum_progress(
            student,
            videos,
            statuses,
            calculated_at=dt.datetime.now(KST).replace(microsecond=0).isoformat(),
        )
        percent = summary.get("percent")
        if not isinstance(percent, int):
            return None
        identity = json.dumps(
            [summary.get("basis"), summary.get("scope"), summary.get("curriculum"), summary.get("subCurriculum")],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        return repository, key, percent
    except Exception:
        return None


def commit_progress_notifications(before, after, sid: str) -> int:
    """Enqueue crossed milestones after a successful progress commit."""
    if before is None or after is None or before[1] != after[1]:
        return 0
    try:
        return enqueue_progress_milestones(
            after[0],
            str(sid),
            after[1],
            before[2],
            after[2],
            now=time.time(),
        )
    except Exception:
        return 0


__all__ = ("commit_progress_notifications", "progress_notification_snapshot")
