"""Fresh fail-closed authority checks for generic student notification delivery."""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
import time
from collections.abc import Callable, Mapping

from core.student_account_repository import StudentAccountRepository
from core.student_app_config import StudentAppConfig, load_student_app_config
from core.student_homework_repository import StudentHomeworkRepository
from core.student_notification_events import EVENT_CATEGORY, deterministic_event_id
from core.student_notification_repository import StudentNotificationRepository
from core.student_notification_hooks import schedule_snapshot_event_id
from core.student_push_authority import eligible_push_account_ids
from core.student_reminder_projection import KST, class_reminder_candidates
from core.student_schedule_projection import project_student_schedule
from core.student_sessions import StudentSessionRepository


class FileNotificationAuthority:
    """Reload mutable authorities before every provider call."""

    _IMMEDIATE_EVENT_MAX_AGE_SECONDS = 24 * 60 * 60

    def __init__(
        self,
        notifications: StudentNotificationRepository,
        homework: StudentHomeworkRepository,
        sessions: StudentSessionRepository,
        accounts: StudentAccountRepository,
        *,
        students_path: str | Path,
        accounts_path: str | Path,
        announcements_path: str | Path,
        absent_path: str | Path,
        extra_path: str | Path,
        weekend_path: str | Path,
        makeup_path: str | Path,
        config_loader: Callable[[], StudentAppConfig] = load_student_app_config,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.notifications, self.homework, self.sessions, self.accounts = notifications, homework, sessions, accounts
        self.students_path, self.accounts_path = Path(students_path), Path(accounts_path)
        self.announcements_path, self.absent_path = Path(announcements_path), Path(absent_path)
        self.extra_path, self.weekend_path, self.makeup_path = Path(extra_path), Path(weekend_path), Path(makeup_path)
        self.config_loader, self.clock = config_loader, clock

    @staticmethod
    def _load(path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _base_allowed(self, lease: Mapping[str, object], subscription: Mapping[str, object]) -> bool:
        config = self.config_loader()
        sid, aid = str(lease.get("sid") or ""), str(subscription.get("aid") or "")
        session_id = subscription.get("session_id")
        now = float(self.clock())
        event_type = str(lease.get("event_type") or "")
        scheduled_at = lease.get("scheduled_at")
        if event_type in {"homework_assigned", "schedule_changed", "progress_milestone"}:
            if isinstance(scheduled_at, bool) or not isinstance(scheduled_at, (int, float)) \
                    or not math.isfinite(float(scheduled_at)) or not 0 <= now - float(scheduled_at) <= self._IMMEDIATE_EVENT_MAX_AGE_SECONDS:
                return False
        if not config.public_enabled or not config.reminders_enabled or not config.allows_canary_sid(sid):
            return False
        if not isinstance(session_id, int) or not self.sessions.is_active_binding(session_id, aid, sid, now=now):
            return False
        account = self.accounts.get(aid)
        linked = account.get("sids") if isinstance(account, dict) else None
        if not isinstance(account, dict) or account.get("disabled") is True or account.get("must_change_credentials") is True:
            return False
        if not isinstance(linked, list) or sid not in linked:
            return False
        category = EVENT_CATEGORY.get(str(lease.get("event_type") or ""))
        preferences = self.notifications.get_preferences(aid)["categories"]
        return isinstance(category, str) and preferences.get(category) is True

    def _homework_current(self, event_type: str, event_id: str, sid: str, now: float) -> bool:
        cursor = None
        for _ in range(10):
            rows, more = self.homework.list_for_sid(sid, status="all", cursor=cursor, page_size=50)
            for row in rows:
                if row.get("status") != "assigned":
                    continue
                assignment_id, due = str(row.get("id") or ""), row.get("due_at")
                if event_type == "homework_assigned":
                    current = deterministic_event_id(event_type, assignment_id)
                elif isinstance(due, str):
                    try:
                        parsed = dt.datetime.fromisoformat(due)
                    except ValueError:
                        continue
                    if parsed.tzinfo is None or parsed.timestamp() <= now:
                        continue
                    current = deterministic_event_id(event_type, assignment_id, due)
                else:
                    continue
                if current == event_id:
                    return True
            if not more or not rows:
                return False
            last = rows[-1]
            cursor = (1 if last.get("due_at") is None else 0, last.get("due_at") or "",
                      last.get("assigned_at") or "", last.get("id") or "")
        return False

    def _announcement_current(self, event_id: str, sid: str, aid: str, now: float) -> bool:
        announcements = self._load(self.announcements_path)
        rows = announcements if isinstance(announcements, list) else []
        source_id = next((
            str(row.get("id") or "") for row in rows if isinstance(row, dict)
            and deterministic_event_id("announcement_published", str(row.get("id") or "")) == event_id
        ), "")
        if not source_id:
            return False
        allowed = eligible_push_account_ids(
            self.config_loader(), announcements, self._load(self.students_path), self._load(self.accounts_path),
            source_id, sid, now=now,
        )
        return aid in allowed

    def _schedule_current(
        self,
        event_type: str,
        event_id: str,
        sid: str,
        now: float,
        scheduled_at: object = None,
    ) -> bool:
        students = self._load(self.students_path)
        student = next((row for row in students if isinstance(row, dict) and str(row.get("id") or "") == sid), None) \
            if isinstance(students, list) else None
        if not isinstance(student, dict):
            return False
        current = dt.datetime.fromtimestamp(now, KST)
        anchor = current
        if event_type == "schedule_changed" and isinstance(scheduled_at, (int, float)) \
                and not isinstance(scheduled_at, bool) and math.isfinite(float(scheduled_at)):
            anchor = dt.datetime.fromtimestamp(float(scheduled_at), KST)
        schedule = project_student_schedule(
            student, sid=sid, start_date=anchor.date().isoformat(),
            end_date=(anchor.date() + dt.timedelta(days=45)).isoformat(),
            absence=self._load(self.absent_path), extra=self._load(self.extra_path),
            weekend=self._load(self.weekend_path), makeup=self._load(self.makeup_path),
        )
        if event_type == "schedule_changed":
            snapshot_key = schedule_snapshot_event_id(sid, schedule)
            return self.notifications.schedule_event_current(sid, event_id, snapshot_key)
        return any(row["event_id"] == event_id for row in class_reminder_candidates(sid, schedule, now=current))

    def allowed(self, lease: Mapping[str, object], subscription: Mapping[str, object]) -> bool:
        """Return true only when account, session, preference, and source remain current."""
        try:
            if not self._base_allowed(lease, subscription):
                return False
            event_type, event_id = str(lease.get("event_type") or ""), str(lease.get("event_id") or "")
            sid, aid, now = str(lease.get("sid") or ""), str(subscription.get("aid") or ""), self.clock()
            if event_type in {"homework_assigned", "homework_due"}:
                return self._homework_current(event_type, event_id, sid, now)
            if event_type == "progress_milestone":
                return self.notifications.milestone_event_current(sid, event_id)
            if event_type == "announcement_published":
                return self._announcement_current(event_id, sid, aid, now)
            if event_type in {"class_reminder", "schedule_changed"}:
                return self._schedule_current(event_type, event_id, sid, now, lease.get("scheduled_at"))
            return False
        except Exception:
            return False


__all__ = ["FileNotificationAuthority"]
