from __future__ import annotations

import os
import pathlib
import sys
from urllib.parse import parse_qs, urlparse

from flask import Flask


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _callback_body(uservalue0: str) -> dict:
    return {
        "json_data": {
            "uservalues": {"uservalue0": uservalue0},
            "content_info": {
                "media_content_key": "mid-1",
                "start_at": 1_787_390_000,
                "last_play_at": 10,
                "duration": 100,
                "playtime_percent": 10,
            },
        }
    }


def main() -> int:
    import routes.api_kollus as api_kollus

    secret = "k" * 64
    fixed_now = 1_787_390_000
    old_secret = os.environ.get("KOLLUS_CALLBACK_SECRET")
    original = {
        "known_sid": api_kollus._known_sid,
        "known_mid": api_kollus._known_mid,
        "save_watch": api_kollus._save_watch_entry,
        "save_progress": api_kollus._save_progress_status,
        "time": api_kollus.time.time,
    }
    saved: list[dict] = []

    os.environ["KOLLUS_CALLBACK_SECRET"] = secret
    api_kollus.time.time = lambda: fixed_now
    signed_url = api_kollus.kollus_signed_url("mid-1", "110.14.147.14", sid="sid-1")
    query = parse_qs(urlparse(signed_url).query)
    callback_token = (query.get("uservalue0") or [""])[0]
    if not callback_token.startswith("v1.") or callback_token == "sid-1" or secret in signed_url:
        raise AssertionError("existing uservalue0 must carry a non-secret signed callback token")

    api_kollus._known_sid = lambda sid: sid == "sid-1"
    api_kollus._known_mid = lambda mid: mid == "mid-1"
    api_kollus._save_watch_entry = lambda date, sid, mid, incoming: saved.append(incoming) or incoming
    api_kollus._save_progress_status = lambda date, sid, mid, status: {mid: status}
    app = Flask("verify-kollus-callback-auth")
    app.register_blueprint(api_kollus.bp_api_kollus)
    client = app.test_client()

    try:
        missing = client.post(
            "/api/kollus/lms-callback",
            json=_callback_body("sid-1"),
        )
        if missing.status_code != 403 or saved:
            raise AssertionError("unsigned Kollus callback must fail before persistence")

        tampered_token = callback_token[:-1] + ("0" if callback_token[-1] != "0" else "1")
        tampered = client.post(
            "/api/kollus/lms-callback",
            json=_callback_body(tampered_token),
        )
        if tampered.status_code != 403 or saved:
            raise AssertionError("callback signature must be scoped to SID and MID")

        valid = client.post(
            "/api/kollus/lms-callback",
            json=_callback_body(callback_token),
        )
        if valid.status_code != 200 or len(saved) != 1:
            raise AssertionError("valid signed callback must reach watch persistence")

        expired_at = str(fixed_now - api_kollus.CALLBACK_TOKEN_MAX_AGE_SEC - 1)
        expired_token = api_kollus._encode_callback_token(secret, "sid-1", "mid-1", expired_at)
        expired = client.post(
            "/api/kollus/lms-callback",
            json=_callback_body(expired_token),
        )
        if expired.status_code != 403 or len(saved) != 1:
            raise AssertionError("expired callback signature must be rejected")

        static_secret = client.post(
            "/api/kollus/lms-callback",
            headers={"X-Kollus-Secret": secret},
            json=_callback_body("sid-1"),
        )
        if static_secret.status_code != 200 or len(saved) != 2:
            raise AssertionError("explicit provider secret must remain a valid callback authentication path")

        os.environ.pop("KOLLUS_CALLBACK_SECRET", None)
        unconfigured = client.post(
            "/api/kollus/lms-callback",
            json=_callback_body(callback_token),
        )
        if unconfigured.status_code != 403 or len(saved) != 2:
            raise AssertionError("callback endpoint must fail closed without its secret")
    finally:
        api_kollus._known_sid = original["known_sid"]
        api_kollus._known_mid = original["known_mid"]
        api_kollus._save_watch_entry = original["save_watch"]
        api_kollus._save_progress_status = original["save_progress"]
        api_kollus.time.time = original["time"]
        if old_secret is None:
            os.environ.pop("KOLLUS_CALLBACK_SECRET", None)
        else:
            os.environ["KOLLUS_CALLBACK_SECRET"] = old_secret

    print("Kollus callback authentication checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
