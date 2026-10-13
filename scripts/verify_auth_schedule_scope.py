from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes import api_auth


def run_checks() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-auth-schedule-") as temporary:
        root = Path(temporary)
        students = root / "students.json"
        accounts = root / "auth_accounts.json"
        students.write_text(json.dumps([
            {"id": "own-1", "name": "QA 같은이름", "day1": "화1", "visitTime1": "15:00", "phone": "private-fixture", "memo": "private"},
            {"id": "own-2", "name": "QA 같은이름", "days": ["금2"], "book": "private"},
            {"id": "outside", "name": "QA 다른학생", "day1": "화2"},
        ], ensure_ascii=False), "utf-8")
        accounts.write_text(json.dumps({"fixture": {"pw_hash": "unused", "sids": ["own-1", "own-2"], "legacy_session_id": "fixture-session"}}), "utf-8")
        before = {path: path.read_bytes() for path in (students, accounts)}
        with patch.object(api_auth, "STU_PATH", students), patch.object(api_auth, "ACCT_PATH", accounts):
            app = Flask("verify-auth-schedule-scope")
            app.register_blueprint(api_auth.bp_api_auth)
            client = app.test_client()
            assert client.get("/api/auth/schedules").status_code == 401
            token = api_auth._issue_token("own-1", "fixture", ["own-1", "outside"], session_id="fixture-session")
            response = client.get("/api/auth/schedules", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            assert response.get_json() == [
                {"id": "own-1", "day1": "화1"},
                {"id": "own-2", "days": ["금2"]},
            ]
            assert client.get("/api/auth/schedules", headers={"Authorization": "Bearer invalid"}).status_code == 401
            stale = api_auth._issue_token("own-1", "fixture", ["own-1"], session_id="revoked-session")
            assert client.get("/api/auth/schedules", headers={"Authorization": f"Bearer {stale}"}).status_code == 401
        assert all(path.read_bytes() == data for path, data in before.items())
    print("Auth schedules: current account SID scope, no roster/private fields, stale token refusal and byte-identical reads")


if __name__ == "__main__":
    run_checks()
