"""Exercise legacy/mobile account races using only injected temporary stores."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType
from unittest.mock import patch

from flask import Flask
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.storage import file_lock
from core.student_app_auth_store import change_credentials, create_account


def fingerprint(path):
    return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def fixture(source_root):
    with tempfile.TemporaryDirectory(prefix="legacy-auth-storage-") as raw:
        directory = Path(raw)
        module = ModuleType("legacy_auth_fixture")
        module.__file__ = str(directory / "routes/api_auth.py")
        source = (source_root / "routes/api_auth.py").read_text(encoding="utf-8")
        with patch.dict("os.environ", {"AUTH_SECRET": "qa-only-test-secret-" + "x" * 48, "MASTER_PW": ""}):
            exec(compile(source, module.__file__, "exec"), module.__dict__)
        assert module.ACCT_PATH == directory / "auth_accounts.json"
        students = [
            {"id": "a1", "name": "Alice", "school": "S", "grade": "1", "curriculum": "Math"},
            {"id": "a2", "name": "Alice", "school": "S", "grade": "1", "curriculum": "Science"},
            {"id": "b1", "name": "Bob", "school": "S", "grade": "2"},
        ]
        module.STU_PATH.write_text(json.dumps(students), encoding="utf-8")
        accounts = {"Alice": {"sids": ["a1"], "pw_hash": generate_password_hash("old-password"),
                                "unknown": {"keep": 7}, "disabled": False}, "_meta": {"version": 9}}
        module.ACCT_PATH.write_text(json.dumps(accounts), encoding="utf-8")
        app = Flask("legacy-auth-fixture")
        app.register_blueprint(module.bp_api_auth)
        app.config["TESTING"] = True
        yield module, app


def account_race(source_root, scenario, guarded):
    with fixture(source_root) as (legacy, app):
        entered, resume, external_done = threading.Event(), threading.Event(), threading.Event()
        failures = []
        actual_load = legacy._load_acct_map

        def held_load():
            value = actual_load()
            if threading.current_thread().name == "legacy-writer":
                entered.set()
                assert resume.wait(6), "legacy read gate timed out"
            return value

        legacy._load_acct_map = held_load
        token = legacy._issue_token(sid="a1", aid="Alice", sids=["a1"])

        def legacy_action():
            try:
                if scenario == "refresh":
                    assert set(legacy._refresh_and_persist_account_sids("Alice", "a1")) == {"a1", "a2"}
                elif scenario == "ensure":
                    legacy._ensure_account("LegacyNew", base_sid_for_link="a1")
                else:
                    with app.test_client() as client:
                        response = client.post("/api/auth/change", json={"curPw": "old-password", "newPw": "legacy-new"},
                                               headers={"Authorization": "Bearer " + token})
                        assert response.status_code == 200
            except BaseException as exc:
                failures.append(exc)

        def external_action():
            try:
                if scenario == "refresh":
                    change_credentials(legacy.ACCT_PATH, "Alice", "Alice", "mobile-new-hash")
                else:
                    create_account(legacy.ACCT_PATH, "MobileNew", ["b1"])
            except BaseException as exc:
                failures.append(exc)
            finally:
                external_done.set()

        first = threading.Thread(target=legacy_action, name="legacy-writer")
        second = threading.Thread(target=external_action, name="mobile-writer")
        first.start()
        assert entered.wait(6), "legacy writer never reached its account read"
        try:
            observed_locked = False
            try:
                with file_lock(legacy.ACCT_PATH, timeout_sec=0.12, poll_sec=0.01):
                    pass
            except TimeoutError:
                observed_locked = True
            assert observed_locked is guarded, "external file-lock observer disagrees with expected RMW protection"
            second.start()
            if not guarded:
                assert external_done.wait(6), "negative control must commit between the stale read and save"
        finally:
            resume.set()
            first.join(8)
            if second.ident is not None:
                second.join(8)
        assert not first.is_alive() and not second.is_alive()
        assert not failures, failures
        result = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))
        if scenario == "refresh":
            assert (result["Alice"]["pw_hash"] == "mobile-new-hash") is guarded
        else:
            assert ("MobileNew" in result) is guarded
        assert result["_meta"] == {"version": 9}
        assert result["Alice"]["unknown"] == {"keep": 7}
        print(f"{scenario}: observed lock={observed_locked}; latest independent mutation preserved={guarded}")


def error_contracts(source_root):
    for broken in (b"{broken", b"[]", b"null", b'{"Alice": []}', b'\xff'):
        with fixture(source_root) as (legacy, app):
            legacy.ACCT_PATH.write_bytes(broken)
            before = fingerprint(legacy.ACCT_PATH)
            token = legacy._issue_token(sid="a1", aid="Alice", sids=["a1"])
            with app.test_client() as client:
                for endpoint, body, headers in (
                    ("/api/auth/login", {"id": "Alice", "password": "old-password"}, {}),
                    ("/api/auth/change", {"curPw": "old-password", "newPw": "changed"}, {"Authorization": "Bearer " + token}),
                ):
                    response = client.post(endpoint, json=body, headers=headers)
                    assert response.status_code == 503, (endpoint, broken, response.status_code)
                    assert response.json == {"ok": False, "error": "account_store_unavailable"}
                    assert fingerprint(legacy.ACCT_PATH) == before
            try:
                legacy._ensure_account("New", base_sid_for_link="a1")
            except legacy.AuthAccountStoreError:
                pass
            else:
                raise AssertionError("ensure must not replace malformed storage")
            assert fingerprint(legacy.ACCT_PATH) == before

    with fixture(source_root) as (legacy, app):
        before = fingerprint(legacy.ACCT_PATH)
        with patch.object(Path, "read_text", side_effect=PermissionError("fixture denied")):
            with app.test_client() as client:
                assert client.post("/api/auth/login", json={"id": "Alice", "password": "old-password"}).status_code == 503
        assert fingerprint(legacy.ACCT_PATH) == before
        token = legacy._issue_token(sid="a1", aid="Alice", sids=["a1"])
        with patch.object(legacy, "save_atomic", side_effect=OSError("fixture save failure")):
            with app.test_client() as client:
                assert client.post("/api/auth/change", json={"curPw": "old-password", "newPw": "changed"},
                                   headers={"Authorization": "Bearer " + token}).status_code == 503
        assert fingerprint(legacy.ACCT_PATH) == before

    with fixture(source_root) as (legacy, app):
        before = fingerprint(legacy.ACCT_PATH)
        token = legacy._issue_token(sid="a1", aid="Alice", sids=["a1"])
        with app.test_client() as client:
            denied = client.post("/api/auth/change", json={"curPw": "wrong", "newPw": "changed"},
                                 headers={"Authorization": "Bearer " + token})
            assert denied.status_code == 401 and fingerprint(legacy.ACCT_PATH) == before
            changed = client.post("/api/auth/change", json={"curPw": "old-password", "newId": "AliceNew", "newPw": "changed"},
                                  headers={"Authorization": "Bearer " + token})
            assert changed.status_code == 200 and changed.json["aid"] == "AliceNew"
            account = json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))["AliceNew"]
            assert check_password_hash(account["pw_hash"], "changed")
            assert account["unknown"] == {"keep": 7}
            assert set(account["sids"]) == {"a1", "a2"}
        legacy.ACCT_PATH.unlink()
        legacy._ensure_account("Alice", base_sid_for_link="a1")
        assert check_password_hash(json.loads(legacy.ACCT_PATH.read_text(encoding="utf-8"))["Alice"]["pw_hash"], "1234")
    print("strict errors/failed save/bad password preserve bytes; normal rename/missing initialization preserve legacy contract")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--expect", choices=("guarded", "vulnerable"), default="guarded")
    args = parser.parse_args()
    for name in ("refresh", "ensure", "change"):
        account_race(args.source_root, name, args.expect == "guarded")
    if args.expect == "guarded":
        error_contracts(args.source_root)
    print("legacy account storage checks passed; all account/roster writes stayed in OS temporary fixtures")
