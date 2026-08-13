"""Lease and deliver generic student notification events with fresh authority checks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Protocol, TypedDict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_account_repository import StudentAccountRepository
from core.student_app_config import load_student_app_config
from core.student_homework_repository import StudentHomeworkRepository
from core.student_notification_authority import FileNotificationAuthority
from core.student_notification_repository import StudentNotificationRepository
from core.student_push_repository import StudentPushRepository
from core.student_push_sender import PushResultStatus, PushSendResult, StudentPushConfig, StudentPushSender
from core.student_sessions import StudentSessionRepository


class EventSender(Protocol):
    def send_event(self, subscription: object, event_type: str, event_id: str) -> PushSendResult: ...


class EventAuthority(Protocol):
    def allowed(self, lease: object, subscription: object) -> bool: ...


class DeliverySummary(TypedDict):
    leased: int
    sent: int
    retried: int
    failed: int
    cancelled: int
    revoked: int
    deliveries: int
    rowIds: list[int]


def _retry_reason(result: PushSendResult) -> str:
    if result.reason == "timeout":
        return "timeout"
    if result.http_status == 429:
        return "429"
    return "5xx" if result.http_status is not None and result.http_status >= 500 else "delivery_failed"


def _retry_exhausted(repository: object, lease: object) -> bool:
    max_attempts = getattr(repository, "MAX_ATTEMPTS", None)
    attempts = lease.get("attempts") if isinstance(lease, dict) else None
    return (
        isinstance(max_attempts, int)
        and not isinstance(max_attempts, bool)
        and isinstance(attempts, int)
        and not isinstance(attempts, bool)
        and attempts + 1 >= max_attempts
    )


def _finish_one(repository, push, sender, authority, lease, summary: DeliverySummary,
                lease_seconds: float) -> None:
    row_id, token = lease["event_row_id"], lease["lease_token"]
    if not lease["payload_valid"]:
        if repository.cancel(row_id, token, code="payload_invalid"):
            summary["cancelled"] += 1
            summary["rowIds"].append(row_id)
        return
    finished = repository.finished_subscription_ids(row_id)
    subscriptions = [row for row in push.active_subscriptions(lease["sid"]) if row["subscription_id"] not in finished]
    eligible = [row for row in subscriptions if authority.allowed(lease, row)]
    if not eligible:
        if finished:
            completed = repository.complete(row_id, token, success=True)
            summary["sent"] += int(completed)
        else:
            completed = repository.cancel(row_id, token, code="authority_changed" if subscriptions else "no_subscription")
            summary["cancelled"] += int(completed)
        if completed:
            summary["rowIds"].append(row_id)
        return
    transient, delivered, permanent = None, 0, 0
    for subscription in eligible:
        if not repository.renew_lease(row_id, token, lease_seconds=lease_seconds):
            return
        try:
            result = sender.send_event(
                {"endpoint": subscription["endpoint"], "keys": subscription["keys"]},
                lease["event_type"], lease["event_id"],
            )
        except TimeoutError:
            result = PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="timeout")
        except Exception:
            result = PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="transport_unavailable")
        if result.status is PushResultStatus.SUCCESS:
            if not repository.record_delivery(
                row_id, token, subscription["subscription_id"], state="sent",
            ):
                return
            delivered += 1
        elif result.status in {PushResultStatus.PERMANENT_FAILURE, PushResultStatus.INVALID_INPUT}:
            if not repository.record_delivery(
                row_id, token, subscription["subscription_id"], state="permanent_failure",
            ):
                return
            if result.http_status in {404, 410} or result.status is PushResultStatus.INVALID_INPUT:
                summary["revoked"] += push.revoke_subscription(subscription["subscription_id"])
            permanent += 1
        else:
            transient = transient or _retry_reason(result)
    summary["deliveries"] += delivered
    if transient is not None:
        completed = repository.complete(row_id, token, success=False, error=transient)
        if completed:
            summary["failed" if _retry_exhausted(repository, lease) else "retried"] += 1
    elif delivered or finished:
        completed = repository.complete(row_id, token, success=True)
        summary["sent"] += int(completed)
    else:
        completed = repository.complete(row_id, token, success=False, permanent=True)
        summary["failed"] += int(completed)
    if completed:
        summary["rowIds"].append(row_id)


def run_once(repository, push, sender, authority, *, limit: int = 100, lease_seconds: float = 180.0) -> DeliverySummary:
    if not 1 <= int(limit) <= 100:
        raise ValueError("limit must be between 1 and 100")
    summary: DeliverySummary = {
        "leased": 0, "sent": 0, "retried": 0, "failed": 0, "cancelled": 0,
        "revoked": 0, "deliveries": 0, "rowIds": [],
    }
    worker_id = secrets.token_hex(8)
    for _ in range(int(limit)):
        lease = repository.lease(lease_seconds=lease_seconds, worker_id=worker_id)
        if lease is None:
            break
        summary["leased"] += 1
        _finish_one(repository, push, sender, authority, lease, summary, lease_seconds)
    return summary


def _runtime():
    config = load_student_app_config()
    if not config.public_enabled or not config.reminders_enabled:
        return None
    db = Path(os.environ.get("STUDENT_APP_DB_PATH", ROOT / "app.sqlite"))
    students = Path(os.environ.get("STUDENT_APP_STUDENTS_PATH", ROOT / "students.json"))
    accounts_path = Path(os.environ.get("STUDENT_APP_ACCOUNTS_PATH", ROOT / "auth_accounts.json"))
    notifications, homework = StudentNotificationRepository(db), StudentHomeworkRepository(db)
    sessions, push = StudentSessionRepository(db), StudentPushRepository(db)
    accounts = StudentAccountRepository(accounts_path, students)
    sender = StudentPushSender(StudentPushConfig(True, config.vapid_subject, config.vapid_private_key_path))
    sender.public_key()
    authority = FileNotificationAuthority(
        notifications, homework, sessions, accounts, students_path=students, accounts_path=accounts_path,
        announcements_path=os.environ.get("STUDENT_APP_ANNOUNCEMENTS_PATH", ROOT / "announcements.json"),
        absent_path=os.environ.get("STUDENT_APP_ABSENT_PATH", ROOT / "absent.json"),
        extra_path=os.environ.get("STUDENT_APP_EXTRA_PATH", ROOT / "extra_attend.json"),
        weekend_path=os.environ.get("STUDENT_APP_WEEKEND_PATH", ROOT / "weekend_slots.json"),
        makeup_path=os.environ.get("STUDENT_APP_MAKEUP_PATH", ROOT / "makeup_carryover.json"),
    )
    return notifications, push, sender, authority


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    if not args.once or not 1 <= args.limit <= 100:
        print(json.dumps({"ok": False, "code": "invalid_invocation"}, separators=(",", ":")))
        return 2
    try:
        runtime = _runtime()
        if runtime is None:
            empty: DeliverySummary = {"leased": 0, "sent": 0, "retried": 0, "failed": 0,
                                      "cancelled": 0, "revoked": 0, "deliveries": 0, "rowIds": []}
            print(json.dumps({"ok": True, "disabled": True, **empty}, separators=(",", ":")))
            return 0
        summary = run_once(*runtime, limit=args.limit)
    except Exception:
        print(json.dumps({"ok": False, "code": "worker_failed"}, separators=(",", ":")))
        return 1
    print(json.dumps({"ok": True, **summary}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
