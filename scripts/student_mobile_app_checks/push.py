# Temp-only Push API, announcement outbox, and delivery worker checks.

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask
from werkzeug.security import generate_password_hash

from core.student_account_repository import StudentAccountRepository
from core.student_app_config import load_student_app_config
from core.student_push_repository import StudentPushRepository
from core.student_push_sender import PushResultStatus, PushSendResult
from core.student_public_surface import PUSH_ROUTE_METHODS, classify_public_path
from core.student_sessions import StudentSessionRepository
from routes.api_student_push import StudentPushApiDependencies, create_blueprint, enqueue_announcement
from scripts.deliver_student_push_outbox import main as worker_main, run_once


def _check(state: list[int], condition: bool, label: str) -> None:
    state[0] += 1
    if not condition:
        raise AssertionError(label)


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _subscription(suffix: str) -> dict[str, object]:
    p256dh = base64.urlsafe_b64encode(b"\x04" + b"\x01" * 64).rstrip(b"=").decode()
    auth = base64.urlsafe_b64encode(b"\x02" * 16).rstrip(b"=").decode()
    return {"endpoint": f"https://fcm.googleapis.com/fcm/send/{suffix}", "keys": {"p256dh": p256dh, "auth": auth}}


def _key_provider():
    return types.SimpleNamespace(public_key=lambda: "B" + "A" * 86)


class _Sender:
    def __init__(self, result: PushSendResult | None = None) -> None:
        self.result, self.calls = result or PushSendResult(PushResultStatus.SUCCESS, http_status=201), []

    def send(self, subscription: object, _announcement_id: str) -> PushSendResult:
        if isinstance(subscription, dict):
            self.calls.append(str(subscription.get("endpoint") or ""))
        return self.result


class _Authority:
    def __init__(self, *aids: str) -> None:
        self.aids = frozenset(aids)

    def eligible_account_ids(self, _announcement_id: str, _sid: str) -> frozenset[str]:
        return self.aids


def _route_checks(root: Path, state: list[int]) -> None:
    now, students, accounts, db_path = [1000.0], root / "students.json", root / "accounts.json", root / "api.sqlite"
    public_key_db = root / "public-key-only.sqlite"
    with patch.dict(os.environ, {"STUDENT_APP_DB_PATH": str(public_key_db)}), patch("routes.api_student_push._build_sender", return_value=_key_provider()):
        key_app = Flask("push-public-key-check")
        key_app.register_blueprint(create_blueprint())
        key_response = key_app.test_client().get("/api/mobile/push/public-key")
    _check(state, key_response.status_code == 200 and not public_key_db.exists(), "public-key GET initialized SQLite")
    _write(students, [{"id": "sid-a", "name": "가"}, {"id": "sid-b", "name": "나"}])
    record = lambda sid: {"sids": [sid], "pw_hash": generate_password_hash("secret"), "must_change_credentials": False, "disabled": False}
    _write(accounts, {"account-a": record("sid-a"), "account-b": record("sid-b")})
    config = load_student_app_config({"STUDENT_APP_SESSION_COOKIE_SECURE": "0", "STUDENT_APP_TEST_INSECURE_COOKIE": "1"})
    sessions = StudentSessionRepository(db_path, clock=lambda: now[0])
    push = StudentPushRepository(db_path, clock=lambda: now[0])
    deps = StudentPushApiDependencies(config, StudentAccountRepository(accounts, students), sessions, push, _key_provider(), lambda: now[0])
    app = Flask("push-api-check")
    app.register_blueprint(create_blueprint(deps))
    client = app.test_client()
    created = sessions.create_session("account-a", "sid-a", ["sid-a"], now=now[0])
    headers = {"X-CSRF-Token": created["csrf_token"]}
    _check(state, client.get("/api/mobile/push/public-key").status_code == 200, "public key requires no session")
    _check(state, client.get("/api/mobile/push/status?deviceId=device-a").status_code == 401, "status accepted no session")
    client.set_cookie(config.cookie.name, created["token"])
    _check(state, client.post("/api/mobile/push/subscribe", json={}).status_code == 403, "subscribe accepted missing CSRF")
    malformed = client.post("/api/mobile/push/subscribe", json={"deviceId": "device-a", "subscription": {**_subscription("bad"), "keys": {**_subscription("bad")["keys"], "extra": "not-allowed"}}}, headers=headers)
    _check(state, malformed.status_code == 400, "malformed subscription accepted")
    local = {**_subscription("local"), "endpoint": "https://127.0.0.1/private"}
    local_response = client.post("/api/mobile/push/subscribe", json={"deviceId": "device-local", "subscription": local}, headers=headers)
    _check(state, local_response.status_code == 400 and local_response.get_json() == {"ok": False, "code": "invalid_subscription"}, "local Push endpoint was accepted or leaked details")
    with patch.dict(os.environ, {"STUDENT_APP_PUSH_ENDPOINT_ALLOWLIST": "localhost"}):
        policy_response = client.post("/api/mobile/push/subscribe", json={"deviceId": "device-policy", "subscription": _subscription("policy")}, headers=headers)
    _check(state, policy_response.status_code == 503 and policy_response.get_json() == {"ok": False, "code": "push_unavailable"}, "unsafe provider policy failed open or leaked details")
    body = {"deviceId": "device-a", "subscription": _subscription("a")}
    _check(state, client.post("/api/mobile/push/subscribe", json=body, headers=headers).status_code == 200, "valid subscribe failed")
    replacement = {"deviceId": "device-a", "subscription": _subscription("a-replaced")}
    client.post("/api/mobile/push/subscribe", json=replacement, headers=headers)
    active = push.active_subscriptions("sid-a")
    _check(state, len(active) == 1 and active[0]["endpoint"].endswith("a-replaced"), "subscription upsert duplicated a device")
    status = client.get("/api/mobile/push/status?deviceId=device-a").get_json()
    _check(state, status["subscribed"] is True and status["pushRequired"] is False, "status lost exact binding")
    transferred = client.post(
        "/api/mobile/push/subscribe",
        json={"deviceId": "device-b", "subscription": _subscription("a-replaced")},
        headers=headers,
    )
    _check(state, transferred.status_code == 200 and len(push.active_subscriptions("sid-a")) == 1 and not push.has_active_subscription("account-a", "sid-a", "device-a") and push.has_active_subscription("account-a", "sid-a", "device-b"), "endpoint ownership did not transfer across device IDs")

    other = app.test_client()
    other_session = sessions.create_session("account-b", "sid-b", ["sid-b"], now=now[0])
    other.set_cookie(config.cookie.name, other_session["token"])
    other_headers = {"X-CSRF-Token": other_session["csrf_token"]}
    foreign = other.post("/api/mobile/push/unsubscribe", json={"deviceId": "device-b"}, headers=other_headers).get_json()
    _check(state, foreign["unsubscribed"] is False and push.has_active_subscription("account-a", "sid-a", "device-b"), "foreign session revoked subscription")
    own = client.post("/api/mobile/push/unsubscribe", json={"deviceId": "device-b"}, headers=headers).get_json()
    _check(state, own["unsubscribed"] is True and not push.has_active_subscription("account-a", "sid-a", "device-b"), "owner unsubscribe failed")
    account_rows = json.loads(accounts.read_text(encoding="utf-8"))
    account_rows["account-a"]["disabled"] = True
    _write(accounts, account_rows)
    _check(state, client.get("/api/mobile/push/status?deviceId=device-a").status_code == 401, "disabled account reached Push status")
    account_rows["account-a"]["disabled"] = False
    account_rows["account-a"]["must_change_credentials"] = True
    _write(accounts, account_rows)
    _check(state, client.get("/api/mobile/push/status?deviceId=device-a").status_code == 403, "credential-change gate was bypassed")
    account_rows["account-a"]["must_change_credentials"] = False
    _write(accounts, account_rows)
    cap_statuses = [
        client.post(
            "/api/mobile/push/subscribe",
            json={"deviceId": f"cap-dev-{index}", "subscription": _subscription(f"cap-{index}")},
            headers=headers,
        ).status_code
        for index in range(5)
    ]
    cap_response = client.post(
        "/api/mobile/push/subscribe",
        json={"deviceId": "cap-dev-over", "subscription": _subscription("cap-over")},
        headers=headers,
    )
    _check(state, cap_statuses == [200] * 5 and cap_response.status_code == 503 and cap_response.get_json() == {"ok": False, "code": "push_unavailable"}, "subscription cap failed open or leaked details")
    with patch.object(push, "has_active_subscription", side_effect=RuntimeError("https://private-endpoint")):
        unavailable = client.get("/api/mobile/push/status?deviceId=device-a")
    _check(state, unavailable.status_code == 503 and unavailable.get_json() == {"ok": False, "code": "push_unavailable"} and "private-endpoint" not in unavailable.get_data(as_text=True), "repository failure leaked details")
    supported = client.post("/api/mobile/push/bypass", json={"deviceId": "device-a", "capabilities": {"serviceWorker": True, "pushManager": True, "notification": True, "standalone": True}}, headers=headers)
    malformed_bypass = client.post("/api/mobile/push/bypass", json={"deviceId": "device-a", "capabilities": {"serviceWorker": False}}, headers=headers)
    _check(state, supported.status_code == 409 and malformed_bypass.status_code == 400, "supported or malformed client received bypass")
    capabilities = {"serviceWorker": True, "pushManager": False, "notification": True, "standalone": True}
    granted = client.post("/api/mobile/push/bypass", json={"deviceId": "device-a", "capabilities": capabilities}, headers=headers).get_json()
    _check(state, granted["bypassExpiresAt"] == 87400.0 and client.get("/api/mobile/push/status?deviceId=device-a").get_json()["pushRequired"] is False, "bypass is not exactly 24 hours")
    with closing(sqlite3.connect(db_path)) as db:
        stored = db.execute("SELECT capabilities_json,aid_digest,device_digest FROM student_push_bypasses").fetchone()
    _check(state, stored is not None and json.loads(stored[0]) == capabilities and "account-a" not in stored[1:] and "device-a" not in stored[1:], "capability report or digests are unsafe")
    now[0] = 87400.0
    expired = client.get("/api/mobile/push/status?deviceId=device-a").get_json()
    _check(state, expired["bypassExpiresAt"] is None and expired["pushRequired"] is True, "expired bypass remained active")

    public_key, push_status = (classify_public_path(path, "GET", PUSH_ROUTE_METHODS) for path in ("/api/mobile/push/public-key", "/api/mobile/push/status"))
    _check(state, public_key.allowed and not public_key.requires_session and push_status.requires_session, "surface Push session policy mismatch")
    _check(state, classify_public_path("/js/test_answer_link_map.json", "GET", frozenset()).requires_session, "sensitive static path is not session-bound")


@contextmanager
def _announcement_module(root: Path):
    name = "routes.api_announcements"
    previous_module, previous_paths = sys.modules.get(name), sys.modules.get("core.paths")
    core_package = importlib.import_module("core")
    previous_attr = getattr(core_package, "paths", None)
    paths = types.ModuleType("core.paths")
    for attr, filename in {"ANN_STATUS_PATH": "status.json", "ANNS_PATH": "announcements.json", "STU_PATH": "students.json", "VID_PATH": "videos.json"}.items():
        setattr(paths, attr, root / filename)
    paths.FILES_DIR = root / "files"
    sys.modules.pop(name, None)
    sys.modules["core.paths"] = paths
    core_package.paths = paths
    try:
        yield importlib.import_module(name), paths
    finally:
        sys.modules.pop(name, None)
        if previous_module is not None:
            sys.modules[name] = previous_module
        if previous_paths is None:
            sys.modules.pop("core.paths", None)
            core_package.__dict__.pop("paths", None)
        else:
            sys.modules["core.paths"] = previous_paths
            core_package.paths = previous_attr


def _count(db_path: Path, state: str | None = None) -> int:
    where, params = ("", ()) if state is None else (" WHERE state=?", (state,))
    with closing(sqlite3.connect(db_path)) as db:
        return int(db.execute("SELECT COUNT(*) FROM student_push_outbox" + where, params).fetchone()[0])


def _announcement_checks(root: Path, state: list[int]) -> None:
    ann_root, db_path = root / "announcement", root / "ann.sqlite"
    ann_root.mkdir()
    with _announcement_module(ann_root) as (module, paths):
        _write(paths.STU_PATH, [{"id": "sid-a", "name": "가"}, {"id": "sid-b", "name": "나"}])
        _write(paths.ANNS_PATH, [])
        _write(paths.ANN_STATUS_PATH, {})
        repository = StudentPushRepository(db_path, clock=lambda: 1000.0)
        disabled_repository = StudentPushRepository(root / "disabled-enqueue.sqlite", clock=lambda: 1000.0)
        with patch.dict(os.environ, {"STUDENT_APP_PUBLIC_ENABLED": "0", "STUDENT_APP_CANARY_SIDS": ""}):
            disabled_ids = enqueue_announcement("disabled", ["sid-a", "sid-b"], disabled_repository)
        _check(state, disabled_ids == [] and _count(root / "disabled-enqueue.sqlite") == 0, "feature-off enqueue created Push rows")
        canary_repository = StudentPushRepository(root / "canary-enqueue.sqlite", clock=lambda: 1000.0)
        with patch.dict(os.environ, {"STUDENT_APP_PUBLIC_ENABLED": "1", "STUDENT_APP_CANARY_SIDS": "sid-a"}):
            canary_ids = enqueue_announcement("canary", ["sid-a", "sid-b"], canary_repository)
        _check(state, len(canary_ids) == 1 and _count(root / "canary-enqueue.sqlite") == 1, "enqueue ignored the current canary SID gate")
        app = Flask("announcement-push-check")
        app.register_blueprint(module.bp_api_announcements)
        client = app.test_client()
        body = {"title": "비공개 본문", "content": "학생 개인정보 없음", "targetSids": ["sid-a", "sid-b"], "expiresAt": "2099-01-01T00:00:00Z"}
        with patch("routes.api_student_push.default_push_repository", return_value=repository):
            created = client.post("/api/announcements", json=body)
            announcement_id = created.get_json()["id"]
            _check(state, created.status_code == 201 and _count(db_path) == 2, "successful create did not enqueue target SIDs")
            updated = client.put(f"/api/announcements/{announcement_id}", json={**body, "title": "수정"})
            _check(state, updated.status_code == 200 and _count(db_path) == 2, "update enqueue was not deduplicated")
            before = _count(db_path)
            client.post("/api/announce-ack", json={"sid": "sid-a", "id": announcement_id})
            client.post("/api/announce-submit", json={"sid": "sid-a", "id": announcement_id, "reply": "확인"})
            _check(state, _count(db_path) == before, "ack or reply enqueued Push")
            future = client.post("/api/announcements", json={**body, "createdAt": "2098-01-01T00:00:00Z"})
            _check(state, future.status_code == 201 and _count(db_path) == 2, "future announcement was enqueued")
            expired = client.post("/api/announcements", json={**body, "expiresAt": "2000-01-01T00:00:00Z"})
            survey = {"status": "draft", "questions": [{"id": "q1", "text": "확인", "type": "short"}]}
            draft = client.post("/api/announcements", json={**body, "kind": "survey", "survey": survey})
            _check(state, expired.status_code == 201 and draft.status_code == 201 and _count(db_path) == 2, "expired or draft announcement was enqueued")
            before = _count(db_path)
            client.delete(f"/api/announcements/{announcement_id}")
            _check(state, _count(db_path) == before, "delete enqueued Push")
        with patch("routes.api_student_push.enqueue_announcement", side_effect=RuntimeError("private failure")):
            resilient = client.post("/api/announcements", json=body)
        _check(state, resilient.status_code == 201 and any(row["id"] == resilient.get_json()["id"] for row in json.loads(paths.ANNS_PATH.read_text(encoding="utf-8"))), "enqueue failure rolled back announcement")
        resilient_id = resilient.get_json()["id"]
        with patch("routes.api_student_push.enqueue_announcement", side_effect=RuntimeError("private failure")):
            resilient_update = client.put(f"/api/announcements/{resilient_id}", json={**body, "title": "저장됨"})
        stored_rows = json.loads(paths.ANNS_PATH.read_text(encoding="utf-8"))
        _check(state, resilient_update.status_code == 200 and any(row["id"] == resilient_id and row["title"] == "저장됨" for row in stored_rows), "enqueue failure rolled back announcement update")
        with closing(sqlite3.connect(db_path)) as db:
            payloads = [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM student_push_outbox")]
        _check(state, all(set(item) == {"type", "announcementId", "url"} for item in payloads) and "비공개" not in json.dumps(payloads, ensure_ascii=False), "outbox payload leaked announcement data")


def _worker_checks(root: Path, state: list[int]) -> None:
    now, db_path = [1000.0], root / "worker.sqlite"
    repository = StudentPushRepository(db_path, clock=lambda: now[0])
    for sid, device in (("sid-a", "device-a"), ("sid-a", "device-b"), ("sid-b", "device-c")):
        sub = _subscription(device)
        repository.upsert_subscription("account", sid, device, sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"])
    repository.enqueue("ann-a", "sid-a", {"type": "announcement", "announcementId": "ann-a", "url": "/app?announcement=ann-a"})
    repository.enqueue("ann-a", "sid-b", {"type": "announcement", "announcementId": "ann-a", "url": "/app?announcement=ann-a"})
    sender = _Sender()
    authority = _Authority("account")
    first, second = run_once(repository, sender, authority=authority), run_once(repository, sender, authority=authority)
    _check(state, first["sent"] == 2 and first["deliveries"] == 3 and second["leased"] == 0 and len(sender.calls) == 3, "successful rows were resent or fan-out failed")
    _check(state, not any(value in json.dumps(first) for value in ("sid-a", "ann-a", "fcm.googleapis.com")), "worker summary leaked target data")

    cli_repo = StudentPushRepository(root / "worker-cli.sqlite", clock=lambda: 1000.0)
    cli_subscription = _subscription("worker-cli")
    cli_repo.upsert_subscription("account", "sid-cli", "device-cli", cli_subscription["endpoint"], cli_subscription["keys"]["p256dh"], cli_subscription["keys"]["auth"])
    cli_repo.enqueue("ann-cli", "sid-cli", {"type": "announcement", "announcementId": "ann-cli", "url": "/app?announcement=ann-cli"})
    cli_output = io.StringIO()
    with patch("scripts.deliver_student_push_outbox._runtime_dependencies", return_value=(cli_repo, _Sender(), authority)), redirect_stdout(cli_output):
        cli_code = worker_main(["--once", "--limit", "1"])
    cli_receipt = json.loads(cli_output.getvalue())
    _check(state, cli_code == 0 and cli_receipt["ok"] is True and not any(value in cli_output.getvalue() for value in ("sid-cli", "ann-cli", "fcm.googleapis.com")), "worker stdout exposed delivery authority or endpoint data")

    revoked = 0
    for status in (404, 410):
        gone = _subscription(f"gone-{status}")
        sid = f"sid-gone-{status}"
        gone_id = repository.upsert_subscription("account", sid, f"device-{status}", gone["endpoint"], gone["keys"]["p256dh"], gone["keys"]["auth"])
        repository.enqueue(f"ann-gone-{status}", sid, {"type": "announcement"}, subscription_id=gone_id)
        gone_result = run_once(repository, _Sender(PushSendResult(PushResultStatus.PERMANENT_FAILURE, http_status=status)), authority=authority)
        revoked += gone_result["revoked"]
    _check(state, revoked == 2 and not repository.active_subscriptions("sid-gone-404") and not repository.active_subscriptions("sid-gone-410"), "404/410 did not revoke subscriptions")

    retry = _subscription("retry")
    repository.upsert_subscription("account", "sid-retry", "device-retry", retry["endpoint"], retry["keys"]["p256dh"], retry["keys"]["auth"])
    retry_id = repository.enqueue("ann-retry", "sid-retry", {"type": "announcement"})
    retry_sender = _Sender(PushSendResult(PushResultStatus.TRANSIENT_FAILURE, http_status=429))
    deltas = []
    for expected in repository.RETRY_BACKOFF_SECONDS:
        run_once(repository, retry_sender, authority=authority, limit=1)
        with closing(sqlite3.connect(db_path)) as db:
            row = db.execute("SELECT next_attempt FROM student_push_outbox WHERE id=?", (retry_id,)).fetchone()
        deltas.append(int(float(row[0]) - now[0]))
        now[0] += expected
    final = run_once(repository, retry_sender, authority=authority, limit=1)
    _check(state, tuple(deltas) == repository.RETRY_BACKOFF_SECONDS and final["failed"] == 1 and _count(db_path, "failed") == 1, "429 retry/terminal schedule mismatch")

    transient_ok = True
    transient_cases = (("timeout", PushSendResult(PushResultStatus.TRANSIENT_FAILURE, reason="timeout")), ("server", PushSendResult(PushResultStatus.TRANSIENT_FAILURE, http_status=503)))
    for label, result in transient_cases:
        transient_path = root / f"{label}.sqlite"
        transient_repo = StudentPushRepository(transient_path, clock=lambda: 2000.0)
        sub = _subscription(label)
        transient_repo.upsert_subscription("account", "sid", f"device-{label}", sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"])
        row_id = transient_repo.enqueue(f"ann-{label}", "sid", {"type": "announcement"})
        summary = run_once(transient_repo, _Sender(result), authority=authority, limit=1)
        with closing(sqlite3.connect(transient_path)) as db:
            row = db.execute("SELECT next_attempt FROM student_push_outbox WHERE id=?", (row_id,)).fetchone()
        transient_ok = transient_ok and summary["retried"] == 1 and row is not None and float(row[0]) == 2060.0
    _check(state, transient_ok, "timeout/5xx did not use first backoff")

    concurrent_repo = StudentPushRepository(root / "concurrent.sqlite", clock=lambda: 3000.0)
    concurrent_sub = _subscription("concurrent")
    concurrent_repo.upsert_subscription("account", "sid", "device-concurrent", concurrent_sub["endpoint"], concurrent_sub["keys"]["p256dh"], concurrent_sub["keys"]["auth"])
    concurrent_repo.enqueue("ann-concurrent", "sid", {"type": "announcement"})
    concurrent_sender = _Sender()
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _item: run_once(concurrent_repo, concurrent_sender, authority=authority, limit=1), range(2)))
    _check(state, sum(item["leased"] for item in receipts) == 1 and len(concurrent_sender.calls) == 1, "concurrent workers shared one lease")

    authority_root = root / "authority"
    authority_root.mkdir()
    announcements_path = authority_root / "announcements.json"
    students_path = authority_root / "students.json"
    accounts_path = authority_root / "accounts.json"

    valid_announcement = {
        "id": "ann-authority",
        "kind": "announcement",
        "createdAt": "2020-01-01T00:00:00Z",
        "expiresAt": "2099-01-01T00:00:00Z",
        "targetSids": ["sid-authority"],
    }

    def authority_case(
        label: str,
        announcement_rows: object,
        *,
        public_enabled: str = "1",
        canary_sids: str = "",
        student_rows: object = None,
        account_rows: object = None,
    ) -> tuple[dict[str, object], list[str], tuple[object, ...] | None]:
        selected_students = [{"id": "sid-authority", "name": "가"}] if student_rows is None else student_rows
        selected_accounts = {"account-authority": {"sids": ["sid-authority"], "disabled": False}} if account_rows is None else account_rows
        _write(announcements_path, announcement_rows)
        _write(students_path, selected_students)
        _write(accounts_path, selected_accounts)
        case_path = authority_root / f"{label}.sqlite"
        case_repo = StudentPushRepository(case_path, clock=lambda: 4000.0)
        subscription = _subscription(label)
        case_repo.upsert_subscription("account-authority", "sid-authority", f"device-{label}", subscription["endpoint"], subscription["keys"]["p256dh"], subscription["keys"]["auth"])
        row_id = case_repo.enqueue("ann-authority", "sid-authority", {"type": "announcement", "announcementId": "ann-authority", "url": "/app?announcement=ann-authority"})
        case_sender = _Sender()
        with patch.dict(os.environ, {
            "STUDENT_APP_PUBLIC_ENABLED": public_enabled,
            "STUDENT_APP_CANARY_SIDS": canary_sids,
            "STUDENT_APP_ANNOUNCEMENTS_PATH": str(announcements_path),
            "STUDENT_APP_STUDENTS_PATH": str(students_path),
            "STUDENT_APP_ACCOUNTS_PATH": str(accounts_path),
        }):
            case_summary = run_once(case_repo, case_sender, limit=1)
        with closing(sqlite3.connect(case_path)) as db:
            row_state = db.execute("SELECT state,last_error FROM student_push_outbox WHERE id=?", (row_id,)).fetchone()
        return case_summary, case_sender.calls, row_state

    valid_summary, valid_calls, valid_state = authority_case("valid", [valid_announcement])
    _check(state, len(valid_calls) == 1 and valid_summary["sent"] == 1 and valid_state == ("sent", None), "current authority blocked legitimate Push delivery")
    stale_cases = (
        ("deleted", [], {}),
        ("expired", [{**valid_announcement, "createdAt": "1999-01-01T00:00:00Z", "expiresAt": "2000-01-01T00:00:00Z"}], {}),
        ("retargeted", [{**valid_announcement, "targetSids": ["sid-other"]}], {}),
        ("canary", [valid_announcement], {"canary_sids": "sid-other"}),
        ("disabled-feature", [valid_announcement], {"public_enabled": "0"}),
        ("disabled-account", [valid_announcement], {"account_rows": {"account-authority": {"sids": ["sid-authority"], "disabled": True}}}),
        ("missing-roster", [valid_announcement], {"student_rows": []}),
        ("unlinked-account", [valid_announcement], {"account_rows": {"account-authority": {"sids": ["sid-other"], "disabled": False}}}),
    )
    for label, rows, overrides in stale_cases:
        stale_summary, stale_calls, stale_state = authority_case(label, rows, **overrides)
        _check(state, not stale_calls and stale_summary["failed"] == 1 and stale_state == ("failed", "cancelled"), f"{label} authority reached transport or remained retryable")

    _write(announcements_path, [valid_announcement])
    _write(students_path, [{"id": "sid-authority", "name": "가"}])
    _write(accounts_path, {"account-authority": {"sids": ["sid-authority"], "disabled": False}})
    ownership_path = authority_root / "stale-subscription.sqlite"
    ownership_repo = StudentPushRepository(ownership_path, clock=lambda: 4000.0)
    old_subscription = _subscription("ownership-old")
    old_id = ownership_repo.upsert_subscription("account-authority", "sid-authority", "device-old", old_subscription["endpoint"], old_subscription["keys"]["p256dh"], old_subscription["keys"]["auth"])
    ownership_id = ownership_repo.enqueue("ann-authority", "sid-authority", {"type": "announcement", "announcementId": "ann-authority", "url": "/app?announcement=ann-authority"}, subscription_id=old_id)
    ownership_repo.revoke_subscription(old_id)
    replacement = _subscription("ownership-new")
    ownership_repo.upsert_subscription("account-authority", "sid-authority", "device-new", replacement["endpoint"], replacement["keys"]["p256dh"], replacement["keys"]["auth"])
    ownership_sender = _Sender()
    with patch.dict(os.environ, {
        "STUDENT_APP_PUBLIC_ENABLED": "1",
        "STUDENT_APP_CANARY_SIDS": "",
        "STUDENT_APP_ANNOUNCEMENTS_PATH": str(announcements_path),
        "STUDENT_APP_STUDENTS_PATH": str(students_path),
        "STUDENT_APP_ACCOUNTS_PATH": str(accounts_path),
    }):
        ownership_summary = run_once(ownership_repo, ownership_sender, limit=1)
    with closing(sqlite3.connect(ownership_path)) as db:
        ownership_state = db.execute("SELECT state,last_error FROM student_push_outbox WHERE id=?", (ownership_id,)).fetchone()
    _check(state, not ownership_sender.calls and ownership_summary["failed"] == 1 and ownership_state == ("failed", "cancelled"), "stale subscription ownership reached transport or remained retryable")


def run_checks() -> dict[str, object]:
    state = [0]
    with tempfile.TemporaryDirectory(prefix="student-push-todo10-") as raw, patch.dict(os.environ, {"DATA_MIRROR_DIR": str(Path(raw) / "mirror"), "DATA_MIRROR_SNAPSHOTS": "0", "STUDENT_APP_PUBLIC_ENABLED": "1", "STUDENT_APP_CANARY_SIDS": ""}):
        root = Path(raw)
        _route_checks(root, state)
        _announcement_checks(root, state)
        _worker_checks(root, state)
    return {"name": "push", "assertions": state[0], "passed": True, "runtimeIsolation": "temporary JSON and SQLite only"}


if __name__ == "__main__":
    print(json.dumps(run_checks(), sort_keys=True))
