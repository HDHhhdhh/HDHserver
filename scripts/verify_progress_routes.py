from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.progress_store import reset_progress_cache
from routes import api_basic, api_progress


DATE = "2026-06-01"
OTHER_DATE = "2026-06-02"
GHOST_SID = "ghost-outside-test"


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture() -> dict:
    return {
        DATE: {
            "7": {
                "m-white": "none",
                "legacy": {"keep": True},
                "__manualProgressMids": {"m-white": True},
            },
            "s2": {"m2": "interrupted"},
        },
        OTHER_DATE: {
            "s2": {"m3": "done"},
            "s3": {"m4": "skip"},
        },
    }


def _assert_unchanged(path: Path, before_bytes: bytes, before_hash: str, label: str) -> None:
    assert path.read_bytes() == before_bytes, f"{label} changed progress bytes"
    assert _sha256(path) == before_hash, f"{label} changed progress hash"


def main() -> int:
    previous_path = api_progress.PRG_PATH
    previous_mirror = os.environ.get("DATA_MIRROR_DIR")
    previous_snapshot = api_progress._notification_progress_snapshot
    previous_commit = api_progress._notification_progress_commit
    try:
        with tempfile.TemporaryDirectory(prefix="verify-progress-routes-") as tmp:
            temp_root = Path(tmp)
            progress_path = temp_root / "progress.json"
            os.environ["DATA_MIRROR_DIR"] = str(temp_root / "mirror")
            api_progress.PRG_PATH = progress_path
            _write_json(progress_path, _fixture())
            reset_progress_cache()

            notification_calls: list[tuple[dict, dict, str]] = []
            api_progress._notification_progress_snapshot = (
                lambda progress, _sid: deepcopy(progress)
            )
            api_progress._notification_progress_commit = (
                lambda before, after, sid: notification_calls.append((before, after, sid)) or 1
            )

            app = Flask("verify-progress-routes")
            app.register_blueprint(api_basic.bp_api_basic)
            app.register_blueprint(api_progress.bp_api_progress)
            client = app.test_client()

            get_rules = [rule for rule in app.url_map.iter_rules() if rule.rule == "/api/progress"]
            patch_rules = [rule for rule in app.url_map.iter_rules() if rule.rule == "/api/progress/patch"]
            assert len(get_rules) == 1 and get_rules[0].endpoint == "api_progress.api_progress"
            assert get_rules[0].methods == {"GET", "HEAD", "OPTIONS"}
            assert len(patch_rules) == 1 and patch_rules[0].endpoint == "api_progress.api_progress_patch"
            assert patch_rules[0].methods == {"OPTIONS", "POST"}

            before_get_bytes = progress_path.read_bytes()
            before_get_hash = _sha256(progress_path)

            response = client.get("/api/progress")
            assert response.status_code == 200
            assert response.get_json() == _fixture()

            response = client.get(f"/api/progress?date={DATE}&sid=007")
            assert response.status_code == 200
            assert response.get_json() == {
                DATE: {
                    "007": {
                        "m-white": "none",
                        "legacy": {"keep": True},
                        "__manualProgressMids": {"m-white": True},
                    }
                }
            }

            response = client.get("/api/progress?sids=007,s2&sids=s2")
            assert response.status_code == 200
            assert response.get_json() == {
                DATE: {
                    "007": {
                        "m-white": "none",
                        "legacy": {"keep": True},
                        "__manualProgressMids": {"m-white": True},
                    },
                    "s2": {"m2": "interrupted"},
                },
                OTHER_DATE: {"s2": {"m3": "done"}},
            }

            response = client.get("/api/progress?date=2026-06-03&sids=s2")
            assert response.status_code == 200
            assert response.get_json() == {"2026-06-03": {}}

            response = client.get("/api/progress?date=bad&sids=s2")
            assert response.status_code == 400
            assert response.get_json() == {"ok": False, "error": "bad date"}

            response = client.get("/api/progress?date=2026-02-30&sids=s2")
            assert response.status_code == 400
            assert response.get_json() == {"ok": False, "error": "bad date"}
            _assert_unchanged(progress_path, before_get_bytes, before_get_hash, "GET matrix")

            response = client.post(
                "/api/progress/patch",
                json={"date": DATE, "sid": "7", "progress": {"m-new": "done"}},
            )
            assert response.status_code == 200
            assert response.get_json() == {
                "ok": True,
                "progress": {
                    "m-white": "none",
                    "m-new": "done",
                    "legacy": {"keep": True},
                    "__manualProgressMids": {"m-new": True, "m-white": True},
                },
            }
            assert _read_json(progress_path)[DATE]["7"] == response.get_json()["progress"]
            assert len(notification_calls) == 1 and notification_calls[0][2] == "7"
            assert "m-new" not in notification_calls[0][0][DATE]["7"]
            assert notification_calls[0][1][DATE]["7"]["m-new"] == "done"

            response = client.post(
                "/api/progress/patch",
                json={
                    "date": DATE,
                    "sid": "7",
                    "source": "auto",
                    "progress": {"m-white": "done", "m-auto": "interrupted"},
                },
            )
            assert response.status_code == 200
            merged = response.get_json()["progress"]
            assert merged == {
                "m-white": "none",
                "m-new": "done",
                "m-auto": "interrupted",
                "legacy": {"keep": True},
                "__autoWatchProgressMids": {"m-auto": "interrupted"},
                "__manualProgressMids": {"m-new": True, "m-white": True},
            }
            assert _read_json(progress_path)[DATE]["7"] == merged
            assert len(notification_calls) == 2

            before_failure_bytes = progress_path.read_bytes()
            before_failure_hash = _sha256(progress_path)
            notification_count_before_failure = len(notification_calls)
            failure_cases = (
                (
                    {"date": DATE, "sid": "7", "progress": "invalid"},
                    400,
                    {"ok": False, "error": "bad payload"},
                ),
                (
                    {"date": "bad", "sid": "7", "progress": {"m": "done"}},
                    400,
                    {"ok": False, "error": "bad date"},
                ),
                (
                    {
                        "date": "2026-02-30",
                        "sid": "7",
                        "progress": {"m": "done"},
                    },
                    400,
                    {"ok": False, "error": "bad date"},
                ),
                (
                    {"date": DATE, "sid": GHOST_SID, "progress": {"m": "done"}},
                    403,
                    {"ok": False, "error": "ghost_student_read_only"},
                ),
            )
            for payload, expected_status, expected_body in failure_cases:
                response = client.post("/api/progress/patch", json=payload)
                assert response.status_code == expected_status
                assert response.get_json() == expected_body
                _assert_unchanged(
                    progress_path,
                    before_failure_bytes,
                    before_failure_hash,
                    f"HTTP {expected_status}",
                )
            assert len(notification_calls) == notification_count_before_failure

            previous_lock = api_progress._progress_lock
            api_progress._progress_lock = lambda: (_ for _ in ()).throw(TimeoutError("lock busy"))
            try:
                response = client.post(
                    "/api/progress/patch",
                    json={"date": DATE, "sid": "7", "progress": {"m": "done"}},
                )
            finally:
                api_progress._progress_lock = previous_lock
            assert response.status_code == 409
            assert response.get_json() == {
                "ok": False,
                "code": "progress_lock_timeout",
                "retryable": True,
                "error": "진도 저장 요청이 잠시 겹쳤습니다. 자동으로 다시 시도합니다.",
            }
            _assert_unchanged(progress_path, before_failure_bytes, before_failure_hash, "lock timeout")

            basic_source = (ROOT / "routes" / "api_basic.py").read_text(encoding="utf-8")
            progress_source = (ROOT / "routes" / "api_progress.py").read_text(encoding="utf-8")
            app_source = (ROOT / "app.py").read_text(encoding="utf-8")
            assert '"/api/progress"' not in basic_source
            assert '"/api/progress/patch"' not in basic_source
            assert '@bp_api_progress.route("/api/progress", methods=["GET"])' in progress_source
            assert '@bp_api_progress.post("/api/progress/patch")' in progress_source
            assert "from routes.api_progress import bp_api_progress" in app_source
            assert "app.register_blueprint(bp_api_progress)" in app_source
    finally:
        api_progress.PRG_PATH = previous_path
        api_progress._notification_progress_snapshot = previous_snapshot
        api_progress._notification_progress_commit = previous_commit
        reset_progress_cache()
        if previous_mirror is None:
            os.environ.pop("DATA_MIRROR_DIR", None)
        else:
            os.environ["DATA_MIRROR_DIR"] = previous_mirror

    print(
        "progress route checks passed: dedicated blueprint, GET filters, PATCH merge, "
        "real-date validation, notification boundary, and byte-identical failures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
