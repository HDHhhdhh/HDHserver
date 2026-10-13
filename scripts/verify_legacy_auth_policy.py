"""Verify legacy JWT renames and the approved master-password scope in temp stores."""
from __future__ import annotations

import argparse
from contextvars import copy_context
import json
import os
from pathlib import Path
import sys
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.student_account_repository import StudentAccountRepository
from core.student_app_auth_store import change_credentials, create_account
from scripts.verify_legacy_auth_storage import fixture, fingerprint


class Checks:
    def __init__(self):
        self.count = 0

    def check(self, condition, message):
        assert condition, message
        self.count += 1


def auth(token):
    return {"Authorization": "Bearer " + token}


def login(checks, client, identifier="Alice", password="old-password"):
    response = client.post("/api/auth/login", json={"id": identifier, "password": password})
    checks.check(response.status_code == 200, ("login", identifier, response.status_code))
    return response.json["token"]


def old_token_denied(checks, legacy, client, token):
    before = fingerprint(legacy.ACCT_PATH)
    for path, body in (("/me", None), ("/switch", {"sid": "a2"}),
                       ("/change", {"curPw": "1234", "newPw": "attacker"})):
        response = (client.get("/api/auth" + path, headers=auth(token)) if body is None else
                    client.post("/api/auth" + path, json=body, headers=auth(token)))
        checks.check(response.status_code == 401, (path, response.status_code))
        checks.check(fingerprint(legacy.ACCT_PATH) == before, "rejected token changed account bytes/mtime")


def lifecycle(checks, source_root, vulnerable):
    with fixture(source_root) as (legacy, app), app.test_client() as client:
        old = legacy._issue_token("a1", "Alice", ["a1"])
        checks.check(client.get("/api/auth/me", headers=auth(old)).status_code == 200,
                     "unchanged legacy token remains valid")
        changed = client.post("/api/auth/change", json={"curPw": "old-password", "newId": "Custom", "newPw": "changed"},
                              headers=auth(old))
        checks.check(changed.status_code == 200, "rename succeeds")
        if vulnerable:
            response = client.get("/api/auth/me", headers=auth(old))
            accounts = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))
            checks.check(response.status_code == 200 and "Alice" in accounts and "Custom" not in accounts,
                         "negative control did not reproduce old-token recreation/pruning")
            print("negative control: old JWT recreated default account and removed renamed account")
            return
        old_token_denied(checks, legacy, client, old)
        current = changed.json["token"]
        checks.check(client.get("/api/auth/me", headers=auth(current)).status_code == 200, "replacement token is valid")
        accounts = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))
        checks.check(accounts["Custom"]["unknown"] == {"keep": 7} and accounts["_meta"] == {"version": 9},
                     "unknown metadata survives")
        session = accounts["Custom"]["legacy_session_id"]
        switched = client.post("/api/auth/switch", json={"sid": "a2"}, headers=auth(current))
        checks.check(switched.status_code == 200 and legacy._decode_token(switched.json["token"])["account_session"] == session,
                     "switch retains session generation")
        password = client.post("/api/auth/change", json={"curPw": "changed", "newPw": "changed-again"}, headers=auth(current))
        checks.check(password.status_code == 200 and client.get("/api/auth/me", headers=auth(current)).status_code == 200,
                     "password-only preserves existing session policy")
        back = client.post("/api/auth/change", json={"curPw": "changed-again", "newId": "Alice"},
                           headers=auth(password.json["token"]))
        checks.check(back.status_code == 200, "rename back succeeds")
        old_token_denied(checks, legacy, client, old)
        old_token_denied(checks, legacy, client, current)
        back_token = back.json["token"]
        another = client.post("/api/auth/change", json={"curPw": "changed-again", "newId": "CustomAgain"}, headers=auth(back_token))
        checks.check(another.status_code == 200, "second rename succeeds")
        legacy._ensure_account("Alice", base_sid_for_link="b1")
        old_token_denied(checks, legacy, client, old)
        old_token_denied(checks, legacy, client, back_token)
        checks.check(login(checks, client, "Alice", "1234") != old, "reused ID gets a new account session")
        latest = another.json["token"]
        change_credentials(legacy.ACCT_PATH, "CustomAgain", "MobileID", "mobile-hash")
        change_credentials(legacy.ACCT_PATH, "MobileID", "CustomAgain", "mobile-hash")
        old_token_denied(checks, legacy, client, latest)
        create_account(legacy.ACCT_PATH, "MobileCreated", ["b1"])
        checks.check(bool(json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))["MobileCreated"]["legacy_session_id"]),
                     "shared writer initializes session for new IDs")
    print("JWT lifecycle: rename/back/reuse/shared writer/switch/password compatibility passed")


def public_reactivation(checks, source_root):
    for creator in ("activate_unique", "public_login"):
        for delete_current in (False, True):
            with fixture(source_root) as (legacy, app), app.test_client() as client:
                old = legacy._issue_token("a1", "Alice", ["a1"])
                changed = client.post("/api/auth/change", json={"curPw": "old-password", "newId": "Custom"}, headers=auth(old))
                checks.check(changed.status_code == 200, "rename before public reactivation")
                if delete_current:
                    accounts = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))
                    accounts.pop("Custom")
                    legacy.ACCT_PATH.write_text(json.dumps(accounts), encoding="utf-8")
                repository = StudentAccountRepository(legacy.ACCT_PATH, legacy.STU_PATH)
                getattr(repository, creator)("Alice", "1234")
                accounts = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))
                checks.check("Alice" in accounts and ("Custom" in accounts) is not delete_current,
                             "actual repository creator exercised after rename/deletion")
                checks.check(bool(accounts["Alice"].get("legacy_session_id")), "public creator initializes fresh session")
                old_token_denied(checks, legacy, client, old)
                after = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))
                checks.check(after["_meta"] == {"version": 9} if delete_current else after["Custom"]["unknown"] == {"keep": 7},
                             "old JWT cannot prune current account or replace unrelated metadata")
    print("actual public repository activation/login: four rename/deletion cases keep old JWT revoked")


def master_policy(checks, source_root):
    with fixture(source_root) as (legacy, app), app.test_client() as client:
        legacy.MASTER_PW = "qa-only-master"
        initial = login(checks, client, password="qa-only-master")
        renamed = client.post("/api/auth/change", json={"curPw": "qa-only-master", "newId": "Custom", "newPw": "custom-password"},
                              headers=auth(initial))
        checks.check(renamed.status_code == 200, "master permits account credential change")
        by_name = login(checks, client, "Alice", "qa-only-master")
        by_id = login(checks, client, "Custom", "qa-only-master")
        checks.check(legacy._decode_token(by_name)["aid"] == "Custom" and legacy._decode_token(by_id)["aid"] == "Custom",
                     "master name/renamed-ID login resolves current account")
        before = fingerprint(legacy.ACCT_PATH)
        checks.check(client.post("/api/auth/login", json={"id": "Unknown", "password": "qa-only-master"}).status_code == 401,
                     "master still requires a known account/student")
        checks.check(fingerprint(legacy.ACCT_PATH) == before, "unknown master login does not write")
        legacy.MASTER_PW = ""
        checks.check(client.post("/api/auth/login", json={"id": "Custom", "password": "qa-only-master"}).status_code == 401,
                     "unset master does not bypass password")
        checks.check(client.post("/api/auth/change", json={"curPw": "qa-only-master", "newPw": "wrong"}, headers=auth(by_id)).status_code == 401,
                     "unset master cannot change credentials")
        login(checks, client, "Custom", "custom-password")
    print("approved master policy: name/renamed-ID/change accepted, unknown/unset denied")


def concurrent_rename(checks, source_root):
    with fixture(source_root) as (legacy, app):
        token = legacy._issue_token("a1", "Alice", ["a1"])
        barrier = threading.Barrier(3)
        statuses, failures = [], []
        def worker(identifier):
            try:
                barrier.wait(6)
                with app.test_client() as client:
                    response = client.post("/api/auth/change", json={"curPw": "old-password", "newId": identifier}, headers=auth(token))
                    statuses.append(response.status_code)
            except BaseException as exc:
                failures.append(exc)
        workers = [threading.Thread(target=worker, args=(identifier,)) for identifier in ("RenameA", "RenameB")]
        for thread in workers:
            thread.start()
        barrier.wait(6)
        for thread in workers:
            thread.join(8)
        checks.check(not failures and all(not thread.is_alive() for thread in workers), failures)
        checks.check(sorted(statuses) == [200, 401], ("concurrent old-token renames", statuses))
        accounts = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))
        checks.check("Alice" not in accounts and sum(name in accounts for name in ("RenameA", "RenameB")) == 1,
                     "exactly one current account survives")
    print("concurrent rename: one success, one revoked token, no default recreation")


def login_rename_race(checks, source_root):
    with fixture(source_root) as (legacy, app):
        entered, resume, writer_started, writer_done = [threading.Event() for _ in range(4)]
        failures, responses = [], []
        original = legacy.check_password_hash
        def held_password(*values):
            if threading.current_thread().name == "legacy-login":
                entered.set()
                assert resume.wait(6), "login gate timed out"
            return original(*values)
        def login_worker():
            try:
                with app.test_client() as client:
                    responses.append(client.post("/api/auth/login", json={"id": "Alice", "password": "old-password"}))
            except BaseException as exc:
                failures.append(exc)
        def rename_worker():
            try:
                writer_started.set()
                change_credentials(legacy.ACCT_PATH, "Alice", "ConcurrentID", "mobile-new-hash")
            except BaseException as exc:
                failures.append(exc)
            finally:
                writer_done.set()
        first = threading.Thread(target=login_worker, name="legacy-login")
        second = threading.Thread(target=rename_worker, name="mobile-rename")
        with patch.object(legacy, "check_password_hash", held_password):
            first.start()
            assert entered.wait(6)
            try:
                second.start()
                assert writer_started.wait(6)
                try:
                    with legacy.file_lock(legacy.ACCT_PATH, timeout_sec=0.12, poll_sec=0.01):
                        pass
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("login validation did not hold canonical account lock")
                checks.check(not writer_done.is_set(), "rename cannot commit between validation and refresh")
            finally:
                resume.set()
                first.join(8)
                second.join(8)
        checks.check(not failures and not first.is_alive() and not second.is_alive(), failures)
        checks.check(len(responses) == 1 and responses[0].status_code == 200, "login before rename returns normally")
        accounts = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))
        checks.check("Alice" not in accounts and accounts["ConcurrentID"]["pw_hash"] == "mobile-new-hash",
                     "late login never recreates/prunes renamed account")
        with app.test_client() as client:
            old_token_denied(checks, legacy, client, responses[0].json["token"])
    print("login/rename race: validation through token issuance is one canonical lease")


def copied_context_leases(checks, source_root):
    with fixture(source_root) as (legacy, app):
        with legacy._account_lock():
            context = copy_context()
            failures = []
            def observer():
                try:
                    with patch.object(legacy, "file_lock", side_effect=TimeoutError("separate owner")):
                        context.run(lambda: legacy._ensure_account("Blocked", base_sid_for_link="b1"))
                except TimeoutError:
                    return
                except BaseException as exc:
                    failures.append(exc)
                else:
                    failures.append(AssertionError("copied context skipped another thread's lock"))
            thread = threading.Thread(target=observer)
            thread.start()
            thread.join(6)
            checks.check(not thread.is_alive() and not failures, failures)
            with patch.object(legacy, "file_lock", side_effect=TimeoutError("separate PID")), patch.object(legacy.os, "getpid", return_value=-1):
                try:
                    context.run(lambda: legacy._ensure_account("Blocked", base_sid_for_link="b1"))
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("copied context skipped another PID's lock")
            checks.check("Blocked" not in json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8")), "different PID cannot inherit authority")
        before = fingerprint(legacy.ACCT_PATH)
        with patch.object(legacy, "file_lock", side_effect=TimeoutError("expired lease")):
            try:
                context.run(lambda: legacy._ensure_account("Blocked", base_sid_for_link="b1"))
            except TimeoutError:
                pass
            else:
                raise AssertionError("stale copied context skipped expired lock")
        checks.check(fingerprint(legacy.ACCT_PATH) == before, "copied contexts cannot authorize writes")
    print("lease scope: cross-thread/PID and expired contexts reacquire canonical lock")


def malformed_sessions(checks, source_root):
    for value in (None, "", 1, [], {}):
        with fixture(source_root) as (legacy, app), app.test_client() as client:
            token = legacy._issue_token("a1", "Alice", ["a1"])
            accounts = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))
            accounts["Alice"]["legacy_session_id"] = value
            legacy.ACCT_PATH.write_text(json.dumps(accounts), encoding="utf-8")
            before = fingerprint(legacy.ACCT_PATH)
            checks.check(client.get("/api/auth/me", headers=auth(token)).status_code == 503, "malformed stored session fails closed")
            checks.check(fingerprint(legacy.ACCT_PATH) == before, "malformed session stays byte identical")
    with fixture(source_root) as (legacy, app), app.test_client() as client:
        token = legacy._issue_token("a1", "MissingAccount", ["a1"])
        old_token_denied(checks, legacy, client, token)
    print("malformed session and missing account: strict failures and no writes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--expect", choices=("guarded", "vulnerable"), default="guarded")
    args = parser.parse_args()
    checks = Checks()
    with patch.object(os, "environ", {"AUTH_SECRET": "qa-only-policy-secret-" + "x" * 48, "MASTER_PW": ""}):
        lifecycle(checks, args.source_root, args.expect == "vulnerable")
        if args.expect == "guarded":
            public_reactivation(checks, args.source_root)
            master_policy(checks, args.source_root)
            concurrent_rename(checks, args.source_root)
            login_rename_race(checks, args.source_root)
            copied_context_leases(checks, args.source_root)
            malformed_sessions(checks, args.source_root)
    print(f"legacy policy: {checks.count} assertions passed; only injected OS-temp stores were written")


if __name__ == "__main__":
    main()
