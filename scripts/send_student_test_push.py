"""Send one exact development-only Push without touching operational queues."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Protocol, Sequence


ROOT: Final = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_push_sender import (  # noqa: E402
    PushResultStatus,
    PushSendResult,
    StudentPushConfig,
    StudentPushSender,
    parse_subscription,
)


DEV_PUBLIC_HOST: Final = "dev-app.5a-math.com"
DEV_SID: Final = "dev-student-001"
DEV_VAPID_SUBJECT: Final = f"https://{DEV_PUBLIC_HOST}"
SEND_CONFIRMATION: Final = "SEND_DEV_TEST_PUSH_ONCE"
COMMITMENT_PREFIX: Final = "target-v1-"
APPROVAL_ID_PREFIX: Final = "approve-v1-"
APPROVAL_MAX_AGE_SECONDS: Final = 300.0
_PUSH_TASK_NAMES: Final = (
    "Academy Dev Student Push Delivery",
    "Academy Student Push Delivery",
)
_WORKER_MUTEX_NAME: Final = r"Global\AcademyStudentPushDelivery-v1"
_APPROVAL_ID_RE: Final = re.compile(r"^approve-v1-[A-Za-z0-9_-]{32}$")
_REQUIRED_TABLES: Final = frozenset(
    {
        "student_app_sessions",
        "student_push_subscriptions",
        "student_push_outbox",
        "student_notification_events",
        "student_notification_deliveries",
        "student_notification_schedule_state",
    }
)


class TestPushBlocked(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    def __str__(self) -> str:
        return self.code


@dataclass(frozen=True, slots=True, repr=False)
class TestPushTarget:
    subscription_id: int
    aid: str
    sid: str
    session_id: int
    endpoint: str
    p256dh: str
    auth: str
    authority_digest: str

    def subscription(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "keys": {"p256dh": self.p256dh, "auth": self.auth},
        }


class TestPushSender(Protocol):
    def send_test(self, subscription: Mapping[str, object], event_id: str) -> PushSendResult: ...


def _block(code: str) -> None:
    raise TestPushBlocked(code)


def _load_json(path: Path, expected: type) -> object:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _block("authority_unavailable")
    if not isinstance(value, expected):
        _block("authority_unavailable")
    return value


def _connect_readonly(path: Path) -> sqlite3.Connection:
    try:
        resolved = path.resolve(strict=True)
        connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True, timeout=5.0)
    except (OSError, sqlite3.Error):
        raise TestPushBlocked("database_unavailable") from None
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA query_only=ON")
    return connection


def _required_schema(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {str(row[0]) for row in rows}
    if not _REQUIRED_TABLES.issubset(names):
        _block("schema_not_ready")


def _queues_empty(db: sqlite3.Connection) -> bool:
    return _queue_counts(db) == (0, 0, 0)


def _queue_counts(db: sqlite3.Connection) -> tuple[int, int, int]:
    legacy = int(
        db.execute(
            "SELECT COUNT(*) FROM student_push_outbox WHERE state IN ('pending','leased')"
        ).fetchone()[0]
    )
    generic = int(
        db.execute(
            "SELECT COUNT(*) FROM student_notification_events WHERE state IN ('pending','leased')"
        ).fetchone()[0]
    )
    scheduled = int(
        db.execute(
            "SELECT COUNT(*) FROM student_notification_schedule_state WHERE pending=1"
        ).fetchone()[0]
    )
    return legacy, generic, scheduled


def _authority_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        _block("authority_unavailable")
    return hashlib.sha256(encoded).hexdigest()


def _valid_student(students: object, sid: str) -> bool:
    if not isinstance(students, list):
        return False
    matches = [row for row in students if isinstance(row, dict) and row.get("id") == sid]
    return len(matches) == 1 and matches[0].get("synthetic") is True


def _valid_account(accounts: object, aid: str, sid: str) -> bool:
    if not isinstance(accounts, dict):
        return False
    record = accounts.get(aid)
    if not isinstance(record, dict):
        return False
    linked = record.get("sids")
    return (
        record.get("synthetic") is True
        and record.get("disabled") is False
        and record.get("must_change_credentials") is False
        and isinstance(linked, list)
        and all(isinstance(item, str) and item.strip() == item and item for item in linked)
        and linked == [sid]
    )


def prepare_test_push(
    db_path: Path,
    students_path: Path,
    accounts_path: Path,
    subscription_id: int | None,
    *,
    sid: str = DEV_SID,
    now: float | None = None,
) -> TestPushTarget:
    """Resolve one current synthetic target without initializing or mutating storage."""

    if sid != DEV_SID:
        _block("development_sid_required")
    if subscription_id is not None and (
        isinstance(subscription_id, bool)
        or not isinstance(subscription_id, int)
        or subscription_id <= 0
    ):
        _block("invalid_subscription_id")
    students = _load_json(Path(students_path), list)
    accounts = _load_json(Path(accounts_path), dict)
    if not _valid_student(students, sid):
        _block("synthetic_student_required")

    try:
        current = time.time() if now is None else float(now)
    except (OverflowError, TypeError, ValueError):
        _block("invalid_clock")
    if not math.isfinite(current) or current < 0:
        _block("invalid_clock")
    try:
        with closing(_connect_readonly(Path(db_path))) as db:
            _required_schema(db)
            queue_counts = _queue_counts(db)
            if queue_counts != (0, 0, 0):
                _block("queue_not_empty")
            rows = db.execute(
                "SELECT id,aid,sid,endpoint,p256dh,auth,session_id "
                "FROM student_push_subscriptions WHERE revoked_at IS NULL ORDER BY id"
            ).fetchall()
            if len(rows) == 0:
                _block("no_active_subscription")
            if len(rows) != 1:
                _block("active_subscription_count_invalid")
            row = rows[0]
            selected_id = int(row["id"])
            if (subscription_id is not None and selected_id != subscription_id) or str(row["sid"]) != sid:
                _block("subscription_target_mismatch")
            aid = str(row["aid"])
            if not _valid_account(accounts, aid, sid):
                _block("account_not_authorized")
            session_id = row["session_id"]
            if isinstance(session_id, bool) or not isinstance(session_id, int) or session_id <= 0:
                _block("session_binding_invalid")
            session = db.execute(
                "SELECT aid,active_sid,allowed_sids_json,expires_at,revoked_at "
                "FROM student_app_sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if session is None:
                _block("session_binding_invalid")
            try:
                allowed = json.loads(str(session["allowed_sids_json"]))
                expires_at = float(session["expires_at"])
            except (TypeError, ValueError, json.JSONDecodeError):
                _block("session_binding_invalid")
            if (
                str(session["aid"]) != aid
                or str(session["active_sid"]) != sid
                or not isinstance(allowed, list)
                or not all(isinstance(item, str) and item.strip() == item and item for item in allowed)
                or sid not in allowed
                or session["revoked_at"] is not None
                or not math.isfinite(expires_at)
                or expires_at <= current
            ):
                _block("session_binding_invalid")
            target = TestPushTarget(
                subscription_id=selected_id,
                aid=aid,
                sid=sid,
                session_id=session_id,
                endpoint=str(row["endpoint"]),
                p256dh=str(row["p256dh"]),
                auth=str(row["auth"]),
                authority_digest=_authority_digest(
                    {
                        "student": next(
                            item for item in students
                            if isinstance(item, dict) and item.get("id") == sid
                        ),
                        "account": accounts[aid],
                        "session": {
                            "aid": session["aid"],
                            "activeSid": session["active_sid"],
                            "allowedSids": allowed,
                            "expiresAt": expires_at,
                            "revokedAt": session["revoked_at"],
                        },
                        "queueCounts": queue_counts,
                    }
                ),
            )
            try:
                parse_subscription(target.subscription())
            except Exception:
                raise TestPushBlocked("subscription_invalid") from None
            return target
    except TestPushBlocked:
        raise
    except (OverflowError, sqlite3.Error, TypeError, ValueError):
        raise TestPushBlocked("database_unavailable") from None


def revoke_exact_subscription(db_path: Path, target: TestPushTarget, *, now: float | None = None) -> bool:
    """Revoke only the provider-confirmed stale target, guarded by its full binding."""

    try:
        current = time.time() if now is None else float(now)
    except (OverflowError, TypeError, ValueError):
        _block("invalid_clock")
    if not math.isfinite(current) or current < 0:
        _block("invalid_clock")
    try:
        with closing(sqlite3.connect(str(Path(db_path)), timeout=5.0)) as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE student_push_subscriptions SET revoked_at=? "
                "WHERE id=? AND aid=? AND sid=? AND session_id=? AND endpoint=? "
                "AND p256dh=? AND auth=? AND revoked_at IS NULL",
                (
                    current,
                    target.subscription_id,
                    target.aid,
                    target.sid,
                    target.session_id,
                    target.endpoint,
                    target.p256dh,
                    target.auth,
                ),
            ).rowcount
            if changed != 1:
                db.execute("ROLLBACK")
                return False
            db.execute("COMMIT")
            return True
    except sqlite3.Error:
        raise TestPushBlocked("revoke_failed") from None


def target_commitment(target: TestPushTarget) -> str:
    """Bind approval to the exact secret target without disclosing its fields."""

    material = json.dumps(
        [
            target.subscription_id,
            target.aid,
            target.sid,
            target.session_id,
            target.endpoint,
            target.p256dh,
            target.auth,
            target.authority_digest,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return COMMITMENT_PREFIX + hashlib.sha256(material).hexdigest()[:24]


def _approval_clock(now: float | None) -> float:
    try:
        current = time.time() if now is None else float(now)
    except (OverflowError, TypeError, ValueError):
        _block("invalid_clock")
    if not math.isfinite(current) or current < 0:
        _block("invalid_clock")
    return current


def _approval_destination(path: Path) -> Path:
    selected = Path(path).resolve(strict=False)
    if selected.name != "student-test-push-approval.json":
        _block("approval_path_invalid")
    selected.parent.mkdir(parents=True, exist_ok=True)
    if selected.parent.is_symlink():
        _block("approval_path_invalid")
    return selected


def issue_test_push_approval(
    target: TestPushTarget,
    approval_path: Path,
    *,
    now: float | None = None,
) -> dict[str, object]:
    """Replace any prior grant with one short-lived target-bound capability."""

    current = _approval_clock(now)
    approval_id = APPROVAL_ID_PREFIX + secrets.token_urlsafe(24)
    record = {
        "schemaVersion": 1,
        "targetCommitment": target_commitment(target),
        "approvalId": approval_id,
        "expiresAt": current + APPROVAL_MAX_AGE_SECONDS,
    }
    destination = _approval_destination(approval_path)
    temporary = destination.with_name(
        destination.name + "." + secrets.token_hex(12) + ".tmp"
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = None
            json.dump(record, stream, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    except OSError:
        _block("approval_unavailable")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "approvalId": approval_id,
        "approvalExpiresAt": record["expiresAt"],
        "targetCommitment": record["targetCommitment"],
    }


def consume_test_push_approval(
    target: TestPushTarget,
    approval_path: Path,
    approval_id: str,
    *,
    now: float | None = None,
) -> None:
    """Atomically claim and consume one current approval before provider access."""

    current = _approval_clock(now)
    selected_id = approval_id.strip() if isinstance(approval_id, str) else ""
    if _APPROVAL_ID_RE.fullmatch(selected_id) is None:
        _block("approval_required")
    source = _approval_destination(approval_path)
    if source.is_symlink():
        _block("approval_unavailable")
    try:
        candidate = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _block("approval_unavailable")
    if not isinstance(candidate, dict) or set(candidate) != {
        "schemaVersion", "targetCommitment", "approvalId", "expiresAt"
    }:
        _block("approval_invalid")
    try:
        expires_at = float(candidate["expiresAt"])
    except (OverflowError, TypeError, ValueError):
        _block("approval_invalid")
    if (
        candidate.get("schemaVersion") != 1
        or candidate.get("targetCommitment") != target_commitment(target)
        or not isinstance(candidate.get("approvalId"), str)
        or not hmac.compare_digest(str(candidate["approvalId"]), selected_id)
        or not math.isfinite(expires_at)
        or expires_at <= current
        or expires_at > current + APPROVAL_MAX_AGE_SECONDS
    ):
        _block("approval_invalid")
    claimed = source.with_name(source.name + ".consumed." + secrets.token_hex(12))
    try:
        os.replace(source, claimed)
        claimed_record = json.loads(claimed.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _block("approval_unavailable")
    finally:
        try:
            claimed.unlink(missing_ok=True)
        except OSError:
            pass
    if claimed_record != candidate:
        _block("approval_invalid")


def run_test_push(
    db_path: Path,
    students_path: Path,
    accounts_path: Path,
    subscription_id: int | None,
    *,
    sender: TestPushSender | None = None,
    dry_run: bool,
    approval_path: Path,
    approval_id: str | None = None,
    now: float | None = None,
    expected_commitment: str | None = None,
    pre_send_check: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Run a dry preflight or one direct send; never leases an operational row."""

    if not dry_run and (
        expected_commitment is None
        or approval_id is None
        or pre_send_check is None
    ):
        _block("target_confirmation_required")
    target = prepare_test_push(
        db_path,
        students_path,
        accounts_path,
        subscription_id,
        now=now,
    )
    commitment = target_commitment(target)
    if dry_run:
        approval = issue_test_push_approval(target, approval_path, now=now)
        return {
            "ok": True,
            "mode": "prepared",
            "ready": True,
            "queuesEmpty": True,
            "targetCount": 1,
            **approval,
        }
    if expected_commitment != commitment:
        _block("target_confirmation_required")
    revalidated = prepare_test_push(
        db_path,
        students_path,
        accounts_path,
        subscription_id,
        now=now,
    )
    if target_commitment(revalidated) != commitment:
        _block("authority_changed")
    try:
        allowed_to_send = pre_send_check() if pre_send_check is not None else False
    except Exception:
        allowed_to_send = False
    if allowed_to_send is not True:
        _block("pre_send_check_failed")
    consume_test_push_approval(
        revalidated,
        approval_path,
        approval_id or "",
        now=now,
    )
    final_target = prepare_test_push(
        db_path,
        students_path,
        accounts_path,
        subscription_id,
        now=now,
    )
    if target_commitment(final_target) != commitment:
        _block("authority_changed")
    target = final_target
    selected_sender = sender or StudentPushSender(
        StudentPushConfig(
            enabled=True,
            vapid_subject=DEV_VAPID_SUBJECT,
            vapid_private_key_path=ROOT / "instance" / "student-app-vapid-private.pem",
        )
    )
    event_id = "evt_" + secrets.token_urlsafe(24)
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = selected_sender.send_test(target.subscription(), event_id)
    except Exception:
        raise TestPushBlocked("delivery_failed") from None
    if not isinstance(result, PushSendResult):
        _block("delivery_failed")
    revoked = False
    if result.status is PushResultStatus.PERMANENT_FAILURE and result.http_status in {404, 410}:
        revoked = revoke_exact_subscription(db_path, target, now=now)
        if not revoked:
            _block("subscription_changed")
    return {
        "ok": result.status is PushResultStatus.SUCCESS,
        "mode": "send",
        "outcome": result.status.value,
        "httpStatus": result.http_status,
        "retryable": result.status is PushResultStatus.TRANSIENT_FAILURE,
        "subscriptionRevoked": revoked,
        "receiptId": event_id,
    }


def _exact_runtime_paths() -> tuple[Path, Path, Path, Path]:
    root = ROOT.resolve()
    if ROOT.name != "server-student-app-dev":
        _block("development_worktree_required")
    paths = (
        ROOT / "app.sqlite",
        ROOT / "students.json",
        ROOT / "auth_accounts.json",
        ROOT / "instance" / "student-app-vapid-private.pem",
    )
    try:
        resolved = tuple(path.resolve(strict=True) for path in paths)
    except OSError:
        _block("development_runtime_unavailable")
    if any(path.parent != root for path in resolved[:3]):
        _block("development_runtime_required")
    if resolved[3].parent != (root / "instance").resolve():
        _block("development_key_required")
    return resolved


def _push_tasks_disabled() -> bool:
    """Require both known delivery tasks to exist and remain disabled."""

    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    command = (
        "$names=@('Academy Dev Student Push Delivery','Academy Student Push Delivery');"
        "$items=@();foreach($name in $names){$tasks=@(Get-ScheduledTask -TaskName $name "
        "-ErrorAction SilentlyContinue);$items+=[pscustomobject]@{name=$name;count=$tasks.Count;"
        "disabled=[bool]($tasks.Count -eq 1 -and $tasks[0].State -eq 'Disabled')}};"
        "$items|ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        rows = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False
    if not isinstance(rows, list):
        return False
    states = {
        row.get("name"): (row.get("count"), row.get("disabled"))
        for row in rows
        if isinstance(row, dict)
    }
    return all(states.get(name) == (1, True) or states.get(name) == [1, True] for name in _PUSH_TASK_NAMES)


@contextmanager
def _worker_mutex(*, required: bool = True):
    """Exclude both scheduled workers while authority is checked and one send runs."""

    if os.name != "nt":
        if required:
            _block("windows_worker_mutex_required")
        yield
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
    kernel32.ReleaseMutex.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.CreateMutexW(None, False, _WORKER_MUTEX_NAME)
    if not handle:
        _block("worker_mutex_unavailable")
    owned = False
    try:
        wait = kernel32.WaitForSingleObject(handle, 0)
        if wait not in {0x00000000, 0x00000080}:
            _block("worker_overlap")
        owned = True
        yield
    finally:
        if owned:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--send", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--target-commitment", default="")
    parser.add_argument("--approval-id", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.send and args.confirm != SEND_CONFIRMATION:
        print(json.dumps({"ok": False, "code": "confirmation_required"}, sort_keys=True))
        return 2
    if args.send and not args.target_commitment.startswith(COMMITMENT_PREFIX):
        print(json.dumps({"ok": False, "code": "target_confirmation_required"}, sort_keys=True))
        return 2
    if args.send and _APPROVAL_ID_RE.fullmatch(args.approval_id) is None:
        print(json.dumps({"ok": False, "code": "approval_required"}, sort_keys=True))
        return 2
    if os.environ.get("STUDENT_APP_PUSH_ENDPOINT_ALLOWLIST", "").strip():
        print(json.dumps({"ok": False, "code": "custom_endpoint_allowlist_forbidden"}, sort_keys=True))
        return 2
    try:
        with _worker_mutex(required=bool(args.send)):
            if not _push_tasks_disabled():
                _block("push_task_must_be_disabled")
            db_path, students_path, accounts_path, private_key = _exact_runtime_paths()
            runtime_sender = StudentPushSender(
                StudentPushConfig(True, DEV_VAPID_SUBJECT, private_key)
            )
            try:
                runtime_sender.public_key()
            except Exception:
                raise TestPushBlocked("vapid_unavailable") from None
            receipt = run_test_push(
                db_path,
                students_path,
                accounts_path,
                None,
                sender=runtime_sender,
                dry_run=bool(args.dry_run),
                approval_path=ROOT / "instance" / "student-test-push-approval.json",
                approval_id=args.approval_id or None,
                expected_commitment=args.target_commitment or None,
                pre_send_check=lambda: (
                    not os.environ.get("STUDENT_APP_PUSH_ENDPOINT_ALLOWLIST", "").strip()
                    and _push_tasks_disabled()
                ),
            )
    except TestPushBlocked as exc:
        print(json.dumps({"ok": False, "code": exc.code}, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"ok": False, "code": "test_push_failed"}, sort_keys=True))
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0 if receipt.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
