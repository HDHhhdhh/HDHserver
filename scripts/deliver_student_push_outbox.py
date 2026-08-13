"""Lease and deliver privacy-minimal student Push outbox rows."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path
import sys
import time
from collections.abc import Callable
from typing import Protocol, TypedDict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_app_config import StudentAppConfig, load_student_app_config
from core.student_push_authority import eligible_push_account_ids
from core.student_push_repository import OutboxLease, StudentPushRepository
from core.student_push_sender import PushResultStatus, PushSendResult, StudentPushConfig, StudentPushSender


class PushSender(Protocol):
    def send(self, subscription: object, announcement_id: str) -> PushSendResult: ...


class DeliveryAuthority(Protocol):
    def eligible_account_ids(self, announcement_id: str, sid: str) -> frozenset[str]: ...


class FileDeliveryAuthority:
    """Reload explicit JSON/config authorities immediately before each send."""

    def __init__(
        self,
        announcements_path: str | Path,
        students_path: str | Path,
        accounts_path: str | Path,
        *,
        config_loader: Callable[[], StudentAppConfig] = load_student_app_config,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.announcements_path = Path(announcements_path)
        self.students_path = Path(students_path)
        self.accounts_path = Path(accounts_path)
        self.config_loader = config_loader
        self.clock = clock

    @staticmethod
    def _load(path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def eligible_account_ids(self, announcement_id: str, sid: str) -> frozenset[str]:
        try:
            return eligible_push_account_ids(
                self.config_loader(),
                self._load(self.announcements_path),
                self._load(self.students_path),
                self._load(self.accounts_path),
                announcement_id,
                sid,
                now=self.clock(),
            )
        except Exception:  # noqa: BROAD_EXCEPT_OK - missing/malformed authority fails closed
            return frozenset()


class DeliverySummary(TypedDict):
    leased: int
    sent: int
    retried: int
    failed: int
    revoked: int
    deliveries: int
    rowIds: list[int]


def _retry_reason(result: PushSendResult) -> str:
    if result.reason == "timeout":
        return "timeout"
    if result.http_status == 429:
        return "429"
    if result.http_status is not None and result.http_status >= 500:
        return "5xx"
    return "delivery_failed"


def _cancel_one(repository: StudentPushRepository, lease: OutboxLease, summary: DeliverySummary) -> None:
    completed = repository.cancel(lease["outbox_id"], lease["lease_token"])
    summary["failed"] += int(completed)
    if completed:
        summary["rowIds"].append(lease["outbox_id"])


def _finish_one(repository: StudentPushRepository, sender: PushSender, authority: DeliveryAuthority, lease: OutboxLease, summary: DeliverySummary) -> None:
    allowed_aids = authority.eligible_account_ids(lease["announcement_id"], lease["sid"])
    if not allowed_aids:
        _cancel_one(repository, lease, summary)
        return
    subscriptions = [
        subscription
        for subscription in repository.active_subscriptions(lease["sid"], lease["subscription_id"])
        if subscription["aid"] in allowed_aids
    ]
    if not subscriptions:
        _cancel_one(repository, lease, summary)
        return
    transient: str | None = None
    permanent = False
    for subscription in subscriptions:
        try:
            result = sender.send(
                {"endpoint": subscription["endpoint"], "keys": subscription["keys"]},
                lease["announcement_id"],
            )
        except TimeoutError:
            result = PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="timeout")
        except Exception:  # noqa: BROAD_EXCEPT_OK - provider details must not reach stdout
            result = PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="transport_unavailable")
        if result.status is PushResultStatus.SUCCESS:
            summary["deliveries"] += 1
            continue
        if result.status in {PushResultStatus.PERMANENT_FAILURE, PushResultStatus.INVALID_INPUT}:
            if result.http_status in {404, 410}:
                summary["revoked"] += repository.revoke_subscription(subscription["subscription_id"])
            else:
                if result.status is PushResultStatus.INVALID_INPUT:
                    summary["revoked"] += repository.revoke_subscription(subscription["subscription_id"])
                permanent = True
            continue
        transient = transient or _retry_reason(result)

    if permanent:
        completed = repository.complete(lease["outbox_id"], lease["lease_token"], success=False, permanent=True, error="permanent")
        summary["failed"] += int(completed)
    elif transient is not None:
        completed = repository.complete(lease["outbox_id"], lease["lease_token"], success=False, error=transient)
        if completed and lease["attempts"] + 1 >= repository.MAX_ATTEMPTS:
            summary["failed"] += 1
        else:
            summary["retried"] += int(completed)
    else:
        completed = repository.complete(lease["outbox_id"], lease["lease_token"], success=True)
        summary["sent"] += int(completed)
    if completed:
        summary["rowIds"].append(lease["outbox_id"])


def run_once(
    repository: StudentPushRepository,
    sender: PushSender,
    *,
    authority: DeliveryAuthority | None = None,
    limit: int = 100,
    lease_seconds: float = 30.0,
) -> DeliverySummary:
    """Process at most ``limit`` rows; dependencies are fully injectable."""
    if not 1 <= int(limit) <= 100:
        raise ValueError("limit must be between 1 and 100")
    selected_authority = _runtime_authority() if authority is None else authority
    summary: DeliverySummary = {"leased": 0, "sent": 0, "retried": 0, "failed": 0, "revoked": 0, "deliveries": 0, "rowIds": []}
    worker_id = secrets.token_hex(8)
    for _ in range(int(limit)):
        lease = repository.lease(lease_seconds=lease_seconds, worker_id=worker_id)
        if lease is None:
            break
        summary["leased"] += 1
        _finish_one(repository, sender, selected_authority, lease, summary)
    return summary


def _runtime_authority() -> FileDeliveryAuthority:
    return FileDeliveryAuthority(
        Path(os.environ.get("STUDENT_APP_ANNOUNCEMENTS_PATH", ROOT / "announcements.json")),
        Path(os.environ.get("STUDENT_APP_STUDENTS_PATH", ROOT / "students.json")),
        Path(os.environ.get("STUDENT_APP_ACCOUNTS_PATH", ROOT / "auth_accounts.json")),
    )


def _runtime_dependencies() -> tuple[StudentPushRepository, StudentPushSender, DeliveryAuthority] | None:
    config = load_student_app_config()
    if not config.public_enabled:
        return None
    db_path = Path(os.environ.get("STUDENT_APP_DB_PATH", ROOT / "app.sqlite"))
    sender = StudentPushSender(StudentPushConfig(config.public_enabled, config.vapid_subject, config.vapid_private_key_path))
    sender.public_key()
    return StudentPushRepository(db_path), sender, _runtime_authority()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process one bounded batch")
    parser.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.once:
        print(json.dumps({"ok": False, "code": "once_required"}, sort_keys=True))
        return 2
    if not 1 <= args.limit <= 100:
        print(json.dumps({"ok": False, "code": "invalid_limit"}, sort_keys=True))
        return 2
    try:
        runtime = _runtime_dependencies()
        if runtime is None:
            empty: DeliverySummary = {"leased": 0, "sent": 0, "retried": 0, "failed": 0, "revoked": 0, "deliveries": 0, "rowIds": []}
            print(json.dumps({"ok": True, "disabled": True, **empty}, sort_keys=True, separators=(",", ":")))
            return 0
        repository, sender, authority = runtime
        summary = run_once(repository, sender, authority=authority, limit=args.limit)
    except Exception:  # noqa: BROAD_EXCEPT_OK - operational output is deliberately opaque
        print(json.dumps({"ok": False, "code": "worker_failed"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **summary}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
