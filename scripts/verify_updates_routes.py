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

from core.update_assignment_rules import StudentAssignmentNotFoundError  # noqa: E402
from routes import api_updates  # noqa: E402


DATE = "2026-06-06"
OTHER_DATE = "2026-06-07"
GHOST_SID = "ghost-outside-test"


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _fingerprint(path: Path) -> tuple[bytes, str]:
    content = path.read_bytes()
    return content, hashlib.sha256(content).hexdigest()


def _assert_unchanged(
    path: Path,
    before: tuple[bytes, str],
    label: str,
) -> None:
    after = _fingerprint(path)
    assert after[0] == before[0], f"{label} changed updates bytes"
    assert after[1] == before[1], f"{label} changed updates SHA-256"


def _fixture() -> dict:
    return {
        DATE: {
            "7": {
                "videos": ["legacy-mid"],
                "source": "manual",
                "note": "old",
                "unknown": {"keep": True},
            },
            "alpha": {
                "videos": ["mid-alpha"],
                "source": "auto",
                "keep": 1,
            },
        },
        OTHER_DATE: {
            "omega": {
                "videos": ["mid-other"],
                "source": "selfStudy",
                "extra": 5,
            },
            "future-auto-update": {
                "videos": ["mid-future-original"],
                "source": "auto",
                "unknown": {"keep": True},
            },
            "future-auto-remove": {
                "videos": ["mid-future-remove"],
                "source": "auto",
                "keep": "until-explicit-remove",
            },
        },
    }


def main() -> int:
    previous_path = api_updates.UPD_PATH
    previous_mirror = os.environ.get("DATA_MIRROR_DIR")
    previous_lock = api_updates._updates_lock
    previous_today = api_updates._today_kst_iso
    try:
        with tempfile.TemporaryDirectory(prefix="verify-updates-routes-") as tmp:
            root = Path(tmp)
            updates_path = root / "updates.json"
            os.environ["DATA_MIRROR_DIR"] = str(root / "mirror")
            api_updates.UPD_PATH = updates_path
            api_updates._today_kst_iso = lambda: DATE
            _write_json(updates_path, _fixture())

            initialize_calls: list[bool] = []
            reconcile_calls: list[dict] = []

            def initialize_today():
                initialize_calls.append(True)
                return {
                    "2026-06-08": {
                        "hook-student": {
                            "videos": ["hook-mid"],
                            "source": "auto",
                        },
                    },
                }

            def reconcile_self_study(**kwargs):
                reconcile_calls.append(deepcopy(kwargs))
                return {
                    "ok": True,
                    "assignment": {
                        "videos": ["literal-result"],
                        "source": "selfStudy",
                    },
                }, 202

            app = Flask("verify-updates-routes")
            app.config["TESTING"] = False
            api_updates.configure_updates_assignment_hooks(
                app,
                initialize_today=initialize_today,
                reconcile_self_study=reconcile_self_study,
            )
            app.register_blueprint(api_updates.bp_api_updates)
            client = app.test_client()

            route_rows = sorted(
                (
                    rule.rule,
                    rule.endpoint,
                    sorted(rule.methods - {"HEAD", "OPTIONS"}),
                )
                for rule in app.url_map.iter_rules()
                if rule.rule.startswith("/api/updates")
            )
            assert route_rows == [
                ("/api/updates", "api_updates.api_updates", ["GET"]),
                ("/api/updates/ensure-today", "api_updates.api_updates_ensure_today", ["POST"]),
                (
                    "/api/updates/patch",
                    "api_updates.api_updates_patch",
                    ["POST"],
                ),
                (
                    "/api/updates/self-study",
                    "api_updates.api_updates_self_study",
                    ["POST"],
                ),
            ]

            read_before = _fingerprint(updates_path)
            response = client.get("/api/updates?readOnly=YES")
            assert response.status_code == 200
            assert response.get_json() == _fixture()
            assert "no-store" in str(response.headers.get("Cache-Control") or "")
            assert initialize_calls == []
            _assert_unchanged(updates_path, read_before, "read-only GET")

            response = client.get("/api/updates")
            assert response.status_code == 200
            assert response.get_json() == _fixture()
            assert initialize_calls == []
            _assert_unchanged(updates_path, read_before, "default read-only GET")

            response = client.get("/api/updates?ensure=1")
            assert response.status_code == 200
            assert response.get_json() == {
                "2026-06-08": {
                    "hook-student": {
                        "videos": ["hook-mid"],
                        "source": "auto",
                    },
                },
            }
            assert initialize_calls == [True]
            _assert_unchanged(updates_path, read_before, "injected normal GET")

            response = client.post("/api/updates", json={"unsafe": True})
            assert response.status_code == 405
            _assert_unchanged(updates_path, read_before, "retired base POST")

            response = client.post(
                "/api/updates/patch",
                json={
                    "date": DATE,
                    "sid": "007",
                    "entry": {
                        "videos": [" mid-a ", "mid-a", "", 42],
                        "note": "new",
                        "added": 0,
                        "ignored": None,
                    },
                },
            )
            expected_assignment = {
                "videos": ["mid-a", "42"],
                "source": "manual",
                "note": "new",
                "unknown": {"keep": True},
                "added": 0,
            }
            expected_after_patch = {
                DATE: {
                    "007": expected_assignment,
                    "alpha": {
                        "videos": ["mid-alpha"],
                        "source": "auto",
                        "keep": 1,
                    },
                },
                OTHER_DATE: {
                    "omega": {
                        "videos": ["mid-other"],
                        "source": "selfStudy",
                        "extra": 5,
                    },
                    "future-auto-update": {
                        "videos": ["mid-future-original"],
                        "source": "auto",
                        "unknown": {"keep": True},
                    },
                    "future-auto-remove": {
                        "videos": ["mid-future-remove"],
                        "source": "auto",
                        "keep": "until-explicit-remove",
                    },
                },
            }
            assert response.status_code == 200
            assert response.get_json() == {
                "ok": True,
                "assignment": expected_assignment,
            }
            assert _read_json(updates_path) == expected_after_patch

            response = client.post(
                "/api/updates/patch",
                json={"date": DATE, "sid": "alpha", "remove": True},
            )
            assert response.status_code == 200
            assert response.get_json() == {"ok": True, "assignment": []}
            expected_after_patch[DATE].pop("alpha")
            assert _read_json(updates_path) == expected_after_patch

            failure_before = _fingerprint(updates_path)
            failure_cases = (
                (
                    {"date": "bad", "sid": "007", "videos": ["mid"]},
                    400,
                    {"ok": False, "error": "bad payload"},
                ),
                (
                    {"date": DATE, "sid": GHOST_SID, "videos": ["mid"]},
                    403,
                    {"ok": False, "error": "ghost_student_read_only"},
                ),
                (
                    {
                        "date": OTHER_DATE,
                        "sid": "future-auto",
                        "entry": {
                            "videos": ["mid-future"],
                            "source": "auto",
                        },
                    },
                    409,
                    {
                        "ok": False,
                        "error": "future automatic assignment is not allowed",
                    },
                ),
                (
                    {
                        "date": OTHER_DATE,
                        "sid": "future-auto-update",
                        "entry": {
                            "videos": ["mid-future-bypass"],
                            "note": "source omitted",
                        },
                    },
                    409,
                    {
                        "ok": False,
                        "error": "future automatic assignment is not allowed",
                    },
                ),
            )
            for payload, status, body in failure_cases:
                response = client.post("/api/updates/patch", json=payload)
                assert response.status_code == status
                assert response.get_json() == body
                _assert_unchanged(updates_path, failure_before, f"PATCH HTTP {status}")

            for invalid_body in ([], ["not-an-object"], "not-an-object", 1):
                response = client.post(
                    "/api/updates/patch",
                    json=invalid_body,
                )
                assert response.status_code == 400
                assert response.get_json() == {
                    "ok": False,
                    "error": "bad payload",
                }
                _assert_unchanged(
                    updates_path,
                    failure_before,
                    f"PATCH non-object body {invalid_body!r}",
                )

            for invalid_remove in ("false", "true", 0, 1, None, [], {}):
                response = client.post(
                    "/api/updates/patch",
                    json={
                        "date": DATE,
                        "sid": "007",
                        "remove": invalid_remove,
                    },
                )
                assert response.status_code == 400
                assert response.get_json() == {
                    "ok": False,
                    "error": "bad payload",
                }
                _assert_unchanged(
                    updates_path,
                    failure_before,
                    f"PATCH non-boolean remove {invalid_remove!r}",
                )

            response = client.post(
                "/api/updates/patch",
                json={
                    "date": OTHER_DATE,
                    "sid": "future-auto-update",
                    "remove": False,
                    "entry": {
                        "source": "manual",
                        "note": "explicitly reclassified",
                    },
                },
            )
            reclassified_assignment = {
                "videos": ["mid-future-original"],
                "source": "manual",
                "unknown": {"keep": True},
                "note": "explicitly reclassified",
            }
            assert response.status_code == 200
            assert response.get_json() == {
                "ok": True,
                "assignment": reclassified_assignment,
            }
            expected_after_patch[OTHER_DATE]["future-auto-update"] = (
                reclassified_assignment
            )
            assert _read_json(updates_path) == expected_after_patch

            response = client.post(
                "/api/updates/patch",
                json={
                    "date": OTHER_DATE,
                    "sid": "future-auto-remove",
                    "remove": True,
                },
            )
            assert response.status_code == 200
            assert response.get_json() == {"ok": True, "assignment": []}
            expected_after_patch[OTHER_DATE].pop("future-auto-remove")
            assert _read_json(updates_path) == expected_after_patch
            failure_before = _fingerprint(updates_path)

            api_updates._updates_lock = lambda: (_ for _ in ()).throw(
                TimeoutError("updates lock busy")
            )
            response = client.post(
                "/api/updates/patch",
                json={"date": DATE, "sid": "007", "videos": ["mid-b"]},
            )
            assert response.status_code == 409
            assert response.get_json() == {
                "ok": False,
                "code": "updates_lock_timeout",
                "retryable": True,
                "error": "영상 배정 저장 요청이 잠시 겹쳤습니다. 자동으로 다시 시도합니다.",
            }
            _assert_unchanged(updates_path, failure_before, "PATCH lock timeout")
            api_updates._updates_lock = previous_lock

            self_study_failure_cases = (
                (
                    {"date": "bad", "sid": "007"},
                    400,
                    {"ok": False, "error": "bad payload"},
                ),
                (
                    {"date": "2026-02-30", "sid": "007"},
                    400,
                    {"ok": False, "error": "bad payload"},
                ),
                (
                    {"date": DATE, "sid": GHOST_SID},
                    403,
                    {"ok": False, "error": "ghost_student_read_only"},
                ),
                (
                    {"date": DATE, "sid": "007", "videos": "mid-a"},
                    400,
                    {"ok": False, "error": "videos must be an array"},
                ),
            )
            for payload, status, body in self_study_failure_cases:
                response = client.post("/api/updates/self-study", json=payload)
                assert response.status_code == status
                assert response.get_json() == body
                assert reconcile_calls == []
                _assert_unchanged(
                    updates_path,
                    failure_before,
                    f"self-study HTTP {status}",
                )

            response = client.post(
                "/api/updates/self-study",
                json={
                    "date": DATE,
                    "sid": "007",
                    "videos": [" mid-a ", "mid-a", 2, ""],
                    "append": True,
                },
            )
            assert response.status_code == 202
            assert response.get_json() == {
                "ok": True,
                "assignment": {
                    "videos": ["literal-result"],
                    "source": "selfStudy",
                },
            }
            assert reconcile_calls == [
                {
                    "date": DATE,
                    "sid": "007",
                    "has_requested_videos": True,
                    "requested_videos": ["mid-a", "2"],
                    "append_requested_videos": True,
                },
            ]
            _assert_unchanged(updates_path, failure_before, "injected self-study")

            def missing_student(**_kwargs):
                raise StudentAssignmentNotFoundError("missing")

            api_updates.configure_updates_assignment_hooks(
                app,
                initialize_today=initialize_today,
                reconcile_self_study=missing_student,
            )
            response = client.post(
                "/api/updates/self-study",
                json={"date": DATE, "sid": "missing"},
            )
            assert response.status_code == 404
            _assert_unchanged(updates_path, failure_before, "missing self-study student")

            def busy_self_study(**_kwargs):
                raise TimeoutError("self-study lock busy")

            api_updates.configure_updates_assignment_hooks(
                app,
                initialize_today=initialize_today,
                reconcile_self_study=busy_self_study,
            )
            response = client.post(
                "/api/updates/self-study",
                json={"date": DATE, "sid": "007"},
            )
            assert response.status_code == 409
            assert response.get_json() == {
                "ok": False,
                "code": "updates_lock_timeout",
                "retryable": True,
                "error": "영상 배정 저장 요청이 잠시 겹쳤습니다. 자동으로 다시 시도합니다.",
            }
            _assert_unchanged(updates_path, failure_before, "self-study lock timeout")

            response = client.post(
                "/api/updates/patch",
                json={"date": DATE, "sid": "007", "remove": True},
            )
            assert response.status_code == 200
            assert response.get_json() == {"ok": True, "assignment": []}
            assert DATE not in _read_json(updates_path)
            assert _read_json(updates_path) == {
                OTHER_DATE: {
                    "omega": {
                        "videos": ["mid-other"],
                        "source": "selfStudy",
                        "extra": 5,
                    },
                    "future-auto-update": reclassified_assignment,
                },
            }

            for label, corrupt_bytes in (
                ("invalid UTF-8", b"\xff\xfeBROKEN-UPDATES"),
                ("non-object JSON", b"[]"),
            ):
                updates_path.write_bytes(corrupt_bytes)
                corrupt_before = _fingerprint(updates_path)

                response = client.get("/api/updates?readOnly=1")
                assert response.status_code == 503
                payload = response.get_json()
                assert payload.get("ok") is False
                assert str(payload.get("error") or "").startswith(
                    "updates store"
                )
                _assert_unchanged(
                    updates_path,
                    corrupt_before,
                    f"{label} read-only GET",
                )

                response = client.post(
                    "/api/updates/patch",
                    json={
                        "date": DATE,
                        "sid": "strict-store",
                        "entry": {
                            "videos": ["must-not-write"],
                            "source": "manual",
                        },
                    },
                )
                assert response.status_code == 503
                payload = response.get_json()
                assert payload.get("ok") is False
                assert str(payload.get("error") or "").startswith(
                    "updates store"
                )
                _assert_unchanged(
                    updates_path,
                    corrupt_before,
                    f"{label} PATCH",
                )

            updates_path.unlink()
            response = client.get("/api/updates?readOnly=1")
            assert response.status_code == 200
            assert response.get_json() == {}
            assert not updates_path.exists()

            response = client.post(
                "/api/updates/patch",
                json={
                    "date": DATE,
                    "sid": "missing-store",
                    "entry": {
                        "videos": ["mid-created"],
                        "source": "manual",
                    },
                },
            )
            assert response.status_code == 200
            assert _read_json(updates_path) == {
                DATE: {
                    "missing-store": {
                        "videos": ["mid-created"],
                        "source": "manual",
                    }
                }
            }

            basic_source = (ROOT / "routes" / "api_basic.py").read_text("utf-8")
            updates_source = (ROOT / "routes" / "api_updates.py").read_text("utf-8")
            app_source = (ROOT / "app.py").read_text("utf-8")
            assert '"/api/updates"' not in basic_source
            assert '"/api/updates/patch"' not in basic_source
            assert '"/api/updates/self-study"' not in basic_source
            assert '@bp_api_updates.get("/api/updates")' in updates_source
            assert '@bp_api_updates.post("/api/updates/patch")' in updates_source
            assert '@bp_api_updates.post("/api/updates/self-study")' in updates_source
            assert "from routes.api_updates import (" in app_source
            assert "configure_updates_assignment_hooks(" in app_source
            assert "app.register_blueprint(bp_api_updates)" in app_source
    finally:
        api_updates.UPD_PATH = previous_path
        api_updates._updates_lock = previous_lock
        api_updates._today_kst_iso = previous_today
        if previous_mirror is None:
            os.environ.pop("DATA_MIRROR_DIR", None)
        else:
            os.environ["DATA_MIRROR_DIR"] = previous_mirror

    print(
        "updates route checks passed: dedicated blueprint, read-only and injected GET, "
        "strict PATCH removal and post-merge future-auto validation, self-study hook "
        "boundary with real-date validation, strict missing/corrupt-store behavior, "
        "and byte-identical failures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
