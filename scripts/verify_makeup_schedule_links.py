import json
from pathlib import Path
import sys
import tempfile

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import routes.api_makeup_carryover as api_makeup_carryover
from routes.api_makeup_carryover import _normalize_payload


def test_scheduled_makeup_normalization() -> None:
    payload = {
        "by_absence": {
            "2026-07-03": {
                "stu-1|2": {
                    "state": "carried",
                    "updatedAt": "2026-07-10T09:00:00",
                    "scheduledMakeup": {
                        "originalAbsenceId": "absence|2026-07-03|stu-1|2",
                        "studentId": "stu-1",
                        "makeupDate": "2026-07-24",
                        "makeupTimes": [2],
                        "status": "scheduled",
                        "createdAt": "2026-07-10T09:00:00",
                        "updatedAt": "2026-07-10T09:00:00",
                        "createdBy": "makeup-planner",
                        "ownedExtra": True,
                        "ownedSlots": [2],
                    },
                }
            }
        },
        "manual": {
            "2026-07-04": {
                "manual-a": {
                    "sid": "stu-2",
                    "slots": [1],
                    "state": "open",
                    "scheduledMakeup": {
                        "studentId": "stu-2",
                        "makeupDate": "2026-07-25",
                        "status": "scheduled",
                    },
                }
            }
        },
    }

    normalized = _normalize_payload(payload)
    scheduled = normalized["by_absence"]["2026-07-03"]["stu-1|2"]["scheduledMakeup"]
    assert scheduled["originalAbsenceId"] == "absence|2026-07-03|stu-1|2"
    assert scheduled["studentId"] == "stu-1"
    assert scheduled["makeupDate"] == "2026-07-24"
    assert scheduled["makeupTimes"] == [2]
    assert scheduled["status"] == "scheduled"
    assert scheduled["ownedExtra"] is True
    assert scheduled["ownedSlots"] == [2]

    manual = normalized["manual"]["2026-07-04"]["manual-a"]["scheduledMakeup"]
    assert manual["originalAbsenceId"] == "manual|2026-07-04|manual-a"
    assert manual["studentId"] == "stu-2"
    assert manual["makeupDate"] == "2026-07-25"
    assert manual["makeupTimes"] == [1]


def test_makeup_revision_guard() -> None:
    with tempfile.TemporaryDirectory(prefix="verify-makeup-revision-") as tmpdir:
        path = Path(tmpdir) / "makeup_carryover.json"
        path.write_text(json.dumps({"by_absence": {}, "manual": {}}), encoding="utf-8")
        original_path = api_makeup_carryover.MAKEUP_CARRYOVER_PATH
        api_makeup_carryover.MAKEUP_CARRYOVER_PATH = path
        try:
            app = Flask("verify-makeup-revision")
            app.register_blueprint(api_makeup_carryover.bp_api_makeup_carryover)
            client = app.test_client()

            initial = client.get("/api/makeup-carryover")
            revision = initial.headers.get("X-Makeup-Carryover-Revision")
            assert initial.status_code == 200 and revision
            first_payload = {
                "manual": {
                    "2026-07-04": {
                        "manual-a": {
                            "sid": "stu-1",
                            "slots": [1],
                            "state": "open",
                        }
                    }
                }
            }
            assert client.post("/api/makeup-carryover", json=first_payload).status_code == 428

            accepted = client.post(
                "/api/makeup-carryover",
                json=first_payload,
                headers={"If-Match": revision},
            )
            accepted_revision = accepted.headers.get("X-Makeup-Carryover-Revision")
            assert accepted.status_code == 200 and accepted_revision and accepted_revision != revision

            stale_payload = {
                "manual": {
                    "2026-07-05": {
                        "manual-b": {
                            "sid": "stu-2",
                            "slots": [2],
                            "state": "open",
                        }
                    }
                }
            }
            conflict = client.post(
                "/api/makeup-carryover",
                json=stale_payload,
                headers={"If-Match": revision},
            )
            assert conflict.status_code == 409
            current = client.get("/api/makeup-carryover")
            assert current.get_json() == accepted.get_json()
            assert current.headers.get("X-Makeup-Carryover-Revision") == accepted_revision
        finally:
            api_makeup_carryover.MAKEUP_CARRYOVER_PATH = original_path


if __name__ == "__main__":
    test_scheduled_makeup_normalization()
    test_makeup_revision_guard()
    print("makeup schedule link normalization and revision guard ok")
