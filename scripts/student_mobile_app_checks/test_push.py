"""Network-free safety checks for the exact development test-Push tool."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import traceback
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final


ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_push_sender import PushResultStatus, PushSendResult  # noqa: E402
from scripts.send_student_test_push import (  # noqa: E402
    DEV_SID,
    TestPushBlocked,
    prepare_test_push,
    run_test_push,
)


NOW: Final = 1_800_000_000.0
TARGET_SUBSCRIPTION_ID: Final = 987_654_321
TARGET_SESSION_ID: Final = 246_813_579
TARGET_AID: Final = "private-test-account"
TARGET_ENDPOINT: Final = "https://fcm.googleapis.com/fcm/send/private-endpoint-token"
TARGET_P256DH: Final = base64.urlsafe_b64encode(b"\x04" + b"\x11" * 64).rstrip(b"=").decode("ascii")
TARGET_AUTH: Final = base64.urlsafe_b64encode(b"\x22" * 16).rstrip(b"=").decode("ascii")
DECOY_SUBSCRIPTION_ID: Final = 123_456_789
DECOY_ENDPOINT: Final = "https://updates.push.services.mozilla.com/wpush/v2/revoked-decoy-token"
DECOY_P256DH: Final = base64.urlsafe_b64encode(b"\x04" + b"\x33" * 64).rstrip(b"=").decode("ascii")
DECOY_AUTH: Final = base64.urlsafe_b64encode(b"\x44" * 16).rstrip(b"=").decode("ascii")


_SCHEMA: Final = """
CREATE TABLE student_app_sessions (
    id INTEGER PRIMARY KEY,
    aid TEXT NOT NULL,
    active_sid TEXT NOT NULL,
    allowed_sids_json TEXT NOT NULL,
    expires_at REAL NOT NULL,
    revoked_at REAL
);
CREATE TABLE student_push_subscriptions (
    id INTEGER PRIMARY KEY,
    aid TEXT NOT NULL,
    sid TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    session_id INTEGER,
    revoked_at REAL
);
CREATE TABLE student_push_outbox (
    id INTEGER PRIMARY KEY,
    state TEXT NOT NULL
);
CREATE TABLE student_notification_events (
    id INTEGER PRIMARY KEY,
    state TEXT NOT NULL
);
CREATE TABLE student_notification_deliveries (
    id INTEGER PRIMARY KEY
);
CREATE TABLE student_notification_schedule_state (
    sid TEXT PRIMARY KEY,
    pending INTEGER NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class _Fixture:
    root: Path
    database: Path
    students: Path
    accounts: Path


class _FakeSender:
    def __init__(self, result: PushSendResult | BaseException) -> None:
        self.result = result
        self.calls: list[tuple[dict[str, object], str]] = []

    def send_test(self, subscription: object, event_id: str) -> PushSendResult:
        if not isinstance(subscription, dict):
            raise AssertionError("test tool passed a non-object subscription")
        self.calls.append((subscription, event_id))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _assert(condition: bool, message: str, count: list[int]) -> None:
    count[0] += 1
    if not condition:
        raise AssertionError(message)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _make_fixture(root: Path) -> _Fixture:
    root.mkdir(parents=True)
    database = root / "app.sqlite"
    students = root / "students.json"
    accounts = root / "auth_accounts.json"
    _write_json(
        students,
        [{"id": DEV_SID, "name": "Synthetic Push Student", "synthetic": True}],
    )
    _write_json(
        accounts,
        {
            TARGET_AID: {
                "sids": [DEV_SID],
                "disabled": False,
                "must_change_credentials": False,
                "synthetic": True,
            }
        },
    )
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript(_SCHEMA)
        db.execute(
            "INSERT INTO student_app_sessions(id,aid,active_sid,allowed_sids_json,expires_at,revoked_at) "
            "VALUES(?,?,?,?,?,NULL)",
            (TARGET_SESSION_ID, TARGET_AID, DEV_SID, json.dumps([DEV_SID]), NOW + 3600.0),
        )
        db.execute(
            "INSERT INTO student_push_subscriptions(id,aid,sid,endpoint,p256dh,auth,session_id,revoked_at) "
            "VALUES(?,?,?,?,?,?,?,NULL)",
            (
                TARGET_SUBSCRIPTION_ID,
                TARGET_AID,
                DEV_SID,
                TARGET_ENDPOINT,
                TARGET_P256DH,
                TARGET_AUTH,
                TARGET_SESSION_ID,
            ),
        )
        db.execute(
            "INSERT INTO student_push_subscriptions(id,aid,sid,endpoint,p256dh,auth,session_id,revoked_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                DECOY_SUBSCRIPTION_ID,
                "revoked-decoy-account",
                "revoked-decoy-student",
                DECOY_ENDPOINT,
                DECOY_P256DH,
                DECOY_AUTH,
                135_792_468,
                NOW - 100.0,
            ),
        )
    return _Fixture(root, database, students, accounts)


def _db_execute(fixture: _Fixture, sql: str, parameters: tuple[object, ...] = ()) -> None:
    with closing(sqlite3.connect(fixture.database)) as db, db:
        db.execute(sql, parameters)


def _db_rows(fixture: _Fixture, sql: str, parameters: tuple[object, ...] = ()) -> tuple[tuple[object, ...], ...]:
    with closing(sqlite3.connect(fixture.database)) as db:
        return tuple(tuple(row) for row in db.execute(sql, parameters).fetchall())


def _file_fingerprints(fixture: _Fixture) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (fixture.database, fixture.students, fixture.accounts)
    }


def _approval_path(fixture: _Fixture) -> Path:
    return fixture.root / "instance" / "student-test-push-approval.json"


def _prepare(fixture: _Fixture, sender: _FakeSender) -> dict[str, object]:
    return run_test_push(
        fixture.database,
        fixture.students,
        fixture.accounts,
        TARGET_SUBSCRIPTION_ID,
        sender=sender,
        dry_run=True,
        approval_path=_approval_path(fixture),
        now=NOW,
    )


def _send(
    fixture: _Fixture,
    sender: _FakeSender,
    prepared: dict[str, object] | None = None,
) -> dict[str, object]:
    approval = _prepare(fixture, sender) if prepared is None else prepared
    return run_test_push(
        fixture.database,
        fixture.students,
        fixture.accounts,
        TARGET_SUBSCRIPTION_ID,
        sender=sender,
        dry_run=False,
        approval_path=_approval_path(fixture),
        approval_id=str(approval["approvalId"]),
        now=NOW,
        expected_commitment=str(approval["targetCommitment"]),
        pre_send_check=lambda: True,
    )


def _private_values() -> tuple[str, ...]:
    return (
        TARGET_ENDPOINT,
        TARGET_P256DH,
        TARGET_AUTH,
        TARGET_AID,
        DEV_SID,
        str(TARGET_SUBSCRIPTION_ID),
        str(TARGET_SESSION_ID),
    )


def _assert_private_output(value: object, label: str, count: list[int]) -> None:
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    for secret in _private_values():
        _assert(secret not in rendered, f"{label} exposed private target data", count)
    _assert("subscriptionId" not in rendered, f"{label} exposed a subscription identifier field", count)


def _assert_private_exception(error: BaseException, label: str, count: list[int]) -> None:
    rendered = "".join(traceback.format_exception(error))
    _assert_private_output(rendered, label, count)


def _expect_block(
    fixture: _Fixture,
    expected_code: str,
    count: list[int],
    *,
    subscription_id: int = TARGET_SUBSCRIPTION_ID,
    sid: str = DEV_SID,
) -> None:
    sender = _FakeSender(PushSendResult(PushResultStatus.SUCCESS, http_status=201))
    try:
        run_test_push(
            fixture.database,
            fixture.students,
            fixture.accounts,
            subscription_id,
            sender=sender,
            dry_run=True,
            approval_path=_approval_path(fixture),
            now=NOW,
        ) if sid == DEV_SID else prepare_test_push(
            fixture.database,
            fixture.students,
            fixture.accounts,
            subscription_id,
            sid=sid,
            now=NOW,
        )
    except TestPushBlocked as exc:
        _assert(exc.code == expected_code, f"wrong block code: {exc.code}", count)
        _assert_private_exception(exc, expected_code, count)
    else:
        raise AssertionError(f"unsafe fixture was not blocked: {expected_code}")
    _assert(len(sender.calls) == 0, f"blocked case called sender: {expected_code}", count)


def _check_dry_run(root: Path, count: list[int]) -> None:
    fixture = _make_fixture(root)
    sender = _FakeSender(PushSendResult(PushResultStatus.SUCCESS, http_status=201))
    before = _file_fingerprints(fixture)
    receipt = _prepare(fixture, sender)
    _assert(
        receipt.get("ok") is True
        and receipt.get("mode") == "prepared"
        and receipt.get("ready") is True
        and receipt.get("queuesEmpty") is True
        and receipt.get("targetCount") == 1
        and re.fullmatch(r"target-v1-[a-f0-9]{24}", str(receipt.get("targetCommitment"))) is not None,
        "dry-run receipt changed",
        count,
    )
    _assert(len(sender.calls) == 0, "dry-run called the sender", count)
    _assert(_file_fingerprints(fixture) == before, "dry-run changed fixture files", count)
    _assert(re.fullmatch(r"approve-v1-[A-Za-z0-9_-]{32}", str(receipt.get("approvalId"))) is not None, "approval id missing", count)
    _assert(_approval_path(fixture).is_file(), "approval record was not created", count)
    _assert_private_output(_approval_path(fixture).read_text(encoding="utf-8"), "approval record", count)
    _assert_private_output(receipt, "dry-run receipt", count)


def _check_success(root: Path, count: list[int]) -> None:
    fixture = _make_fixture(root)
    sender = _FakeSender(PushSendResult(PushResultStatus.SUCCESS, reason="delivered", http_status=201))
    before = _file_fingerprints(fixture)
    receipt = _send(fixture, sender)
    _assert(len(sender.calls) == 1, "successful test Push was not sent exactly once", count)
    subscription, event_id = sender.calls[0]
    _assert(subscription["endpoint"] == TARGET_ENDPOINT, "sender did not receive the exact endpoint", count)
    _assert(
        subscription["keys"] == {"p256dh": TARGET_P256DH, "auth": TARGET_AUTH},
        "sender did not receive the exact subscription keys",
        count,
    )
    _assert(re.fullmatch(r"evt_[A-Za-z0-9_-]{32}", event_id) is not None, "test event id was not opaque", count)
    _assert(receipt["ok"] is True and receipt["outcome"] == "success", "successful receipt was not successful", count)
    _assert(receipt["retryable"] is False and receipt["subscriptionRevoked"] is False, "successful receipt had failure flags", count)
    _assert(receipt["receiptId"] == event_id, "receipt id did not match the one sent", count)
    _assert(_file_fingerprints(fixture) == before, "successful direct send mutated local stores", count)
    _assert_private_output(receipt, "success receipt", count)


def _check_gone_revoke(root: Path, count: list[int]) -> None:
    fixture = _make_fixture(root)
    before = _db_rows(
        fixture,
        "SELECT id,aid,sid,endpoint,p256dh,auth,session_id,revoked_at "
        "FROM student_push_subscriptions ORDER BY id",
    )
    sender = _FakeSender(PushSendResult(PushResultStatus.PERMANENT_FAILURE, reason="transport_error", http_status=410))
    receipt = _send(fixture, sender)
    after = _db_rows(
        fixture,
        "SELECT id,aid,sid,endpoint,p256dh,auth,session_id,revoked_at "
        "FROM student_push_subscriptions ORDER BY id",
    )
    before_by_id = {int(row[0]): row for row in before}
    after_by_id = {int(row[0]): row for row in after}
    _assert(len(sender.calls) == 1, "410 path did not make exactly one send", count)
    _assert(receipt["ok"] is False and receipt["subscriptionRevoked"] is True, "410 did not report exact revocation", count)
    _assert(receipt["retryable"] is False and receipt["httpStatus"] == 410, "410 receipt was misclassified", count)
    _assert(after_by_id[TARGET_SUBSCRIPTION_ID][1:-1] == before_by_id[TARGET_SUBSCRIPTION_ID][1:-1], "410 changed target identity fields", count)
    _assert(after_by_id[TARGET_SUBSCRIPTION_ID][-1] == NOW, "410 did not set the target revoke timestamp", count)
    _assert(after_by_id[DECOY_SUBSCRIPTION_ID] == before_by_id[DECOY_SUBSCRIPTION_ID], "410 changed a non-target subscription", count)
    _assert_private_output(receipt, "410 receipt", count)


def _check_transient(root: Path, count: list[int]) -> None:
    fixture = _make_fixture(root)
    sender = _FakeSender(PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="transport_error", http_status=429))
    before = _file_fingerprints(fixture)
    receipt = _send(fixture, sender)
    _assert(len(sender.calls) == 1, "429 path did not make exactly one send", count)
    _assert(receipt["ok"] is False and receipt["retryable"] is True, "429 was not reported retryable", count)
    _assert(receipt["subscriptionRevoked"] is False and receipt["httpStatus"] == 429, "429 had destructive flags", count)
    _assert(_file_fingerprints(fixture) == before, "429 changed local state or queued a retry", count)
    _assert_private_output(receipt, "429 receipt", count)


def _check_target_blocks(root: Path, count: list[int]) -> None:
    no_active = _make_fixture(root / "no-active")
    _db_execute(no_active, "UPDATE student_push_subscriptions SET revoked_at=? WHERE id=?", (NOW, TARGET_SUBSCRIPTION_ID))
    _expect_block(no_active, "no_active_subscription", count)

    multiple = _make_fixture(root / "multiple")
    _db_execute(
        multiple,
        "INSERT INTO student_push_subscriptions(id,aid,sid,endpoint,p256dh,auth,session_id,revoked_at) "
        "VALUES(?,?,?,?,?,?,?,NULL)",
        (
            TARGET_SUBSCRIPTION_ID + 1,
            TARGET_AID,
            DEV_SID,
            "https://web.push.apple.com/QE/second-private-token",
            TARGET_P256DH,
            TARGET_AUTH,
            TARGET_SESSION_ID,
        ),
    )
    _expect_block(multiple, "active_subscription_count_invalid", count)

    wrong_id = _make_fixture(root / "wrong-id")
    _expect_block(wrong_id, "subscription_target_mismatch", count, subscription_id=TARGET_SUBSCRIPTION_ID + 10)

    wrong_sid = _make_fixture(root / "wrong-sid")
    _db_execute(wrong_sid, "UPDATE student_push_subscriptions SET sid='wrong-target' WHERE id=?", (TARGET_SUBSCRIPTION_ID,))
    _expect_block(wrong_sid, "subscription_target_mismatch", count)

    wrong_requested_sid = _make_fixture(root / "wrong-requested-sid")
    _expect_block(wrong_requested_sid, "development_sid_required", count, sid="real-student")


def _check_authority_blocks(root: Path, count: list[int]) -> None:
    non_synthetic = _make_fixture(root / "non-synthetic")
    _write_json(non_synthetic.students, [{"id": DEV_SID, "synthetic": False}])
    _expect_block(non_synthetic, "synthetic_student_required", count)

    disabled = _make_fixture(root / "disabled")
    _write_json(disabled.accounts, {TARGET_AID: {"sids": [DEV_SID], "disabled": True, "must_change_credentials": False, "synthetic": True}})
    _expect_block(disabled, "account_not_authorized", count)

    must_change = _make_fixture(root / "must-change")
    _write_json(must_change.accounts, {TARGET_AID: {"sids": [DEV_SID], "disabled": False, "must_change_credentials": True, "synthetic": True}})
    _expect_block(must_change, "account_not_authorized", count)

    unlinked = _make_fixture(root / "unlinked")
    _write_json(unlinked.accounts, {TARGET_AID: {"sids": ["another-student"], "disabled": False, "must_change_credentials": False, "synthetic": True}})
    _expect_block(unlinked, "account_not_authorized", count)

    non_synthetic_account = _make_fixture(root / "non-synthetic-account")
    _write_json(non_synthetic_account.accounts, {TARGET_AID: {"sids": [DEV_SID], "disabled": False, "must_change_credentials": False, "synthetic": False}})
    _expect_block(non_synthetic_account, "account_not_authorized", count)

    multi_sid = _make_fixture(root / "multi-sid")
    _write_json(multi_sid.accounts, {TARGET_AID: {"sids": [DEV_SID, "another-student"], "disabled": False, "must_change_credentials": False, "synthetic": True}})
    _expect_block(multi_sid, "account_not_authorized", count)

    malformed_flags = _make_fixture(root / "malformed-flags")
    _write_json(malformed_flags.accounts, {TARGET_AID: {"sids": [DEV_SID], "disabled": 0, "must_change_credentials": None, "synthetic": True}})
    _expect_block(malformed_flags, "account_not_authorized", count)


def _check_session_blocks(root: Path, count: list[int]) -> None:
    invalid = _make_fixture(root / "invalid")
    _db_execute(invalid, "UPDATE student_push_subscriptions SET session_id=? WHERE id=?", (999_999_999, TARGET_SUBSCRIPTION_ID))
    _expect_block(invalid, "session_binding_invalid", count)

    expired = _make_fixture(root / "expired")
    _db_execute(expired, "UPDATE student_app_sessions SET expires_at=? WHERE id=?", (NOW, TARGET_SESSION_ID))
    _expect_block(expired, "session_binding_invalid", count)

    revoked = _make_fixture(root / "revoked")
    _db_execute(revoked, "UPDATE student_app_sessions SET revoked_at=? WHERE id=?", (NOW - 1.0, TARGET_SESSION_ID))
    _expect_block(revoked, "session_binding_invalid", count)

    malformed = _make_fixture(root / "malformed")
    _db_execute(malformed, "UPDATE student_app_sessions SET allowed_sids_json='not-json' WHERE id=?", (TARGET_SESSION_ID,))
    _expect_block(malformed, "session_binding_invalid", count)

    infinite = _make_fixture(root / "infinite")
    _db_execute(infinite, "UPDATE student_app_sessions SET expires_at=? WHERE id=?", (float("inf"), TARGET_SESSION_ID))
    _expect_block(infinite, "session_binding_invalid", count)


def _check_commitment(root: Path, count: list[int]) -> None:
    fixture = _make_fixture(root)
    sender = _FakeSender(PushSendResult(PushResultStatus.SUCCESS, http_status=201))
    dry_run = _prepare(fixture, sender)
    commitment = dry_run["targetCommitment"]
    _assert(isinstance(commitment, str), "dry-run commitment missing", count)
    try:
        run_test_push(
            fixture.database,
            fixture.students,
            fixture.accounts,
            None,
            sender=sender,
            dry_run=False,
            approval_path=_approval_path(fixture),
            approval_id=str(dry_run["approvalId"]),
            now=NOW,
            expected_commitment="target-v1-000000000000000000000000",
            pre_send_check=lambda: True,
        )
    except TestPushBlocked as exc:
        _assert(exc.code == "target_confirmation_required", "stale commitment used wrong code", count)
    else:
        raise AssertionError("stale commitment was accepted")
    _assert(len(sender.calls) == 0, "stale commitment reached sender", count)
    receipt = _send(fixture, sender, dry_run)
    _assert(receipt["ok"] is True and len(sender.calls) == 1, "current commitment was rejected", count)
    try:
        _send(fixture, sender, dry_run)
    except TestPushBlocked as exc:
        _assert(exc.code == "approval_unavailable", "consumed approval used wrong code", count)
    else:
        raise AssertionError("consumed approval was replayed")
    _assert(len(sender.calls) == 1, "approval replay reached sender", count)

    expired = _make_fixture(root / "expired-approval")
    expired_sender = _FakeSender(PushSendResult(PushResultStatus.SUCCESS, http_status=201))
    expired_prepared = _prepare(expired, expired_sender)
    try:
        run_test_push(
            expired.database,
            expired.students,
            expired.accounts,
            TARGET_SUBSCRIPTION_ID,
            sender=expired_sender,
            dry_run=False,
            approval_path=_approval_path(expired),
            approval_id=str(expired_prepared["approvalId"]),
            now=NOW + 301.0,
            expected_commitment=str(expired_prepared["targetCommitment"]),
            pre_send_check=lambda: True,
        )
    except TestPushBlocked as exc:
        _assert(exc.code == "approval_invalid", "expired approval used wrong code", count)
    else:
        raise AssertionError("expired approval was accepted")
    _assert(len(expired_sender.calls) == 0, "expired approval reached sender", count)

    precheck = _make_fixture(root / "precheck")
    precheck_sender = _FakeSender(PushSendResult(PushResultStatus.SUCCESS, http_status=201))
    precheck_prepared = _prepare(precheck, precheck_sender)
    try:
        run_test_push(
            precheck.database,
            precheck.students,
            precheck.accounts,
            TARGET_SUBSCRIPTION_ID,
            sender=precheck_sender,
            dry_run=False,
            approval_path=_approval_path(precheck),
            approval_id=str(precheck_prepared["approvalId"]),
            now=NOW,
            expected_commitment=str(precheck_prepared["targetCommitment"]),
            pre_send_check=lambda: False,
        )
    except TestPushBlocked as exc:
        _assert(exc.code == "pre_send_check_failed", "failed final precheck used wrong code", count)
    else:
        raise AssertionError("failed final precheck reached sender")
    _assert(len(precheck_sender.calls) == 0, "failed final precheck reached sender", count)
    _assert(_approval_path(precheck).exists(), "failed precheck consumed an unused approval", count)


def _check_queue_blocks(root: Path, count: list[int]) -> None:
    legacy = _make_fixture(root / "legacy")
    _db_execute(legacy, "INSERT INTO student_push_outbox(state) VALUES('pending')")
    _expect_block(legacy, "queue_not_empty", count)

    generic = _make_fixture(root / "generic")
    _db_execute(generic, "INSERT INTO student_notification_events(state) VALUES('pending')")
    _expect_block(generic, "queue_not_empty", count)

    schedule = _make_fixture(root / "schedule")
    _db_execute(schedule, "INSERT INTO student_notification_schedule_state(sid,pending) VALUES(?,1)", (DEV_SID,))
    _expect_block(schedule, "queue_not_empty", count)


def _check_exception_privacy(root: Path, count: list[int]) -> None:
    fixture = _make_fixture(root)
    private_message = " | ".join(_private_values())
    sender = _FakeSender(RuntimeError(private_message))
    before = _file_fingerprints(fixture)
    try:
        _send(fixture, sender)
    except TestPushBlocked as exc:
        _assert(exc.code == "delivery_failed", "unexpected sender exception used the wrong public code", count)
        _assert_private_exception(exc, "unexpected sender exception", count)
    except Exception as exc:
        raise AssertionError("unexpected sender exception was not sanitized") from exc
    else:
        raise AssertionError("unexpected sender exception was treated as delivery")
    _assert(len(sender.calls) == 1, "exception path retried the send", count)
    _assert(_file_fingerprints(fixture) == before, "exception path changed local state", count)


def run_checks() -> dict[str, str | int | bool]:
    """Exercise every fail-closed precondition without a provider connection."""

    count = [0]
    with tempfile.TemporaryDirectory(prefix="student-test-push-") as temp:
        root = Path(temp)
        _check_dry_run(root / "dry-run", count)
        _check_success(root / "success", count)
        _check_gone_revoke(root / "gone", count)
        _check_transient(root / "transient", count)
        _check_target_blocks(root / "target-blocks", count)
        _check_authority_blocks(root / "authority-blocks", count)
        _check_session_blocks(root / "session-blocks", count)
        _check_queue_blocks(root / "queue-blocks", count)
        _check_commitment(root / "commitment", count)
        _check_exception_privacy(root / "exception-privacy", count)
    _assert(count[0] > 0, "test-Push suite did not execute", count)
    return {"name": "test-push", "assertions": count[0], "passed": True}


def main() -> int:
    try:
        result = run_checks()
    except AssertionError as exc:
        print(f"test-push checks failed: {exc}", file=sys.stderr)
        return 1
    print(f"test-push checks passed: {result['assertions']} assertions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
