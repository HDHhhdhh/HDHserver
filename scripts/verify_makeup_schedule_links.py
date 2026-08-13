from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


if __name__ == "__main__":
    test_scheduled_makeup_normalization()
    print("makeup schedule link normalization ok")
