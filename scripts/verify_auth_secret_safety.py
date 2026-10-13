# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
# --- How to run ---
# python scripts/verify_auth_secret_safety.py
from __future__ import annotations

import os
import json
import subprocess
import sys
import time
import tempfile
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import jwt
from flask import Flask

os.environ.pop("AUTH_SECRET", None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

with patch.dict(os.environ, {"MASTER_PW": ""}):
    import routes.api_auth as api_auth  # noqa: E402


DEFAULT_AUTH_SECRET = "CHANGE_ME_AUTH_SECRET"


def _make_client():
    app = Flask("verify-auth-secret-safety")
    app.register_blueprint(api_auth.bp_api_auth)
    return app.test_client()


def _patch_auth_data() -> Callable[[], None]:
    original_student_exists = api_auth._student_exists
    original_recover_sids = api_auth._recover_sids_from_account_id
    original_refresh_sids = api_auth._refresh_and_persist_account_sids
    original_curris_payload = api_auth._curris_payload_from_sids

    api_auth._student_exists = lambda sid: sid == "victim"
    api_auth._recover_sids_from_account_id = lambda _aid: []
    api_auth._refresh_and_persist_account_sids = (
        lambda _aid, sid: [sid] if sid == "victim" else []
    )
    api_auth._curris_payload_from_sids = (
        lambda sids: [{"cur": "demo", "sid": sid} for sid in sids]
    )

    def restore() -> None:
        api_auth._student_exists = original_student_exists
        api_auth._recover_sids_from_account_id = original_recover_sids
        api_auth._refresh_and_persist_account_sids = original_refresh_sids
        api_auth._curris_payload_from_sids = original_curris_payload

    return restore


def _token_for(secret: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sid": "victim",
            "aid": "victim",
            "sids": ["victim"],
            "iat": now,
            "exp": now + 60,
        },
        secret,
        algorithm="HS256",
    )


def _assert_explicit_default_secret_is_replaced() -> None:
    env = os.environ.copy()
    env["AUTH_SECRET"] = DEFAULT_AUTH_SECRET
    env["PYTHONPATH"] = str(ROOT)
    probe = (
        "import routes.api_auth as api_auth; "
        f"raise SystemExit(1 if api_auth.AUTH_SECRET == {DEFAULT_AUTH_SECRET!r} else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            "explicit public AUTH_SECRET must be replaced before signing tokens"
        )


def run_checks() -> None:
    _assert_explicit_default_secret_is_replaced()
    restore = _patch_auth_data()
    try:
        with tempfile.TemporaryDirectory(prefix="auth-secret-safety-") as raw:
            directory = Path(raw)
            accounts = directory / "auth_accounts.json"
            students = directory / "students.json"
            accounts.write_text(json.dumps({"victim": {"sids": ["victim"]}}), encoding="utf-8")
            students.write_text(json.dumps([{"id": "victim"}]), encoding="utf-8")
            with patch.object(api_auth, "ACCT_PATH", accounts), patch.object(api_auth, "STU_PATH", students):
                client = _make_client()
                before = accounts.read_bytes()
                forged = _token_for(DEFAULT_AUTH_SECRET)
                forged_response = client.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {forged}"},
                )
                if forged_response.status_code != 401:
                    raise AssertionError("default AUTH_SECRET must not validate forged student tokens")

                legitimate = api_auth._issue_token("victim", "victim", ["victim"])
                legitimate_response = client.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {legitimate}"},
                )
                if legitimate_response.status_code != 200:
                    raise AssertionError("process-issued student token must remain valid")
                if accounts.read_bytes() != before:
                    raise AssertionError("signature checks must not change account records")
    finally:
        restore()


if __name__ == "__main__":
    run_checks()
    print("auth secret safety checks passed")
