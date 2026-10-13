from __future__ import annotations

import pathlib
import json
import os
from typing import Any

BASE = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", str(BASE / "data")))
FILES_DIR = BASE / "files"

def ensure_json(path: pathlib.Path, default: Any) -> pathlib.Path:
    """없으면 기본값으로 생성."""
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(default, stream, ensure_ascii=False, indent=2)
    except FileExistsError:
        pass
    return path

# 데이터 파일 경로
# Identity recovery must see missing stores instead of an empty replacement.
PERSONS_PATH = BASE / "persons.json"
PERSON_IDENTITY_JOURNAL_PATH = BASE / "instance" / "person_identity_transactions" / "pending.json"
STU_PATH = BASE / "students.json"
VID_PATH = BASE / "videos.json"
PRG_PATH = BASE / "progress.json"
MAT_PATH = BASE / "materials.json"
ASN_PATH = BASE / "mat_assign.json"
UPD_PATH = BASE / "updates.json"

TODAY_ORDER_PATH = DATA_DIR / "today_order.json"
EXTRA_PATH = BASE / "extra_attend.json"
LOGS_PATH = BASE / "logs.json"
TESTS_PATH = BASE / "tests.json"
ABS_PATH = BASE / "absent.json"
CLINIC_PATH = BASE / "clinic.json"
CAL_PATH = BASE / "school_calendar.json"
ANNS_PATH = BASE / "announcements.json"
ANN_STATUS_PATH = BASE / "announce_status.json"
WEEKEND_SLOTS_PATH = BASE / "weekend_slots.json"
WATCH_PATH = BASE / "watch.json"
ATTENDANCE_PATH = BASE / "attendance.json"
CONTACT_PATH = BASE / "contact.json"
ARRIVE_TIME_PATH = BASE / "arrive_time.json"

TESTS_CFG_PATH = BASE / "tests-config.json"

PAGE_FOLDERS_PATH = BASE / "page_folders.json"

AUTH_PATH = BASE / "auth.json"


def initialize_runtime_paths() -> None:
    """Create legacy defaults explicitly at guarded application startup."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    if not (PERSONS_PATH.exists() or PERSON_IDENTITY_JOURNAL_PATH.exists()):
        ensure_json(STU_PATH, [])
    for path, default in (
        (VID_PATH, []), (ANNS_PATH, []), (TESTS_CFG_PATH, {"categories": {}}),
        *((path, {}) for path in (
            PRG_PATH, MAT_PATH, ASN_PATH, UPD_PATH, TODAY_ORDER_PATH, EXTRA_PATH,
            LOGS_PATH, TESTS_PATH, ABS_PATH, CLINIC_PATH, CAL_PATH, ANN_STATUS_PATH,
            WEEKEND_SLOTS_PATH, WATCH_PATH, ATTENDANCE_PATH, CONTACT_PATH,
            ARRIVE_TIME_PATH, PAGE_FOLDERS_PATH, AUTH_PATH,
        )),
    ):
        ensure_json(path, default)
