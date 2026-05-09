from __future__ import annotations

import pathlib
import json
from typing import Any

BASE = pathlib.Path(__file__).resolve().parents[1]
FILES_DIR = BASE / "files"
FILES_DIR.mkdir(exist_ok=True)

def ensure_json(path: pathlib.Path, default: Any) -> pathlib.Path:
    """없으면 기본값으로 생성."""
    if not path.exists():
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), "utf-8")
    return path

# 데이터 파일 경로
STU_PATH   = ensure_json(BASE / "students.json", [])
VID_PATH   = ensure_json(BASE / "videos.json", [])
PRG_PATH   = ensure_json(BASE / "progress.json", {})
MAT_PATH   = ensure_json(BASE / "materials.json", {})
ASN_PATH   = ensure_json(BASE / "mat_assign.json", {})
UPD_PATH   = ensure_json(BASE / "updates.json", {})

TODAY_ORDER_PATH = ensure_json(BASE / "today_order.json", {})
EXTRA_PATH = ensure_json(BASE / "extra_attend.json", {})
LOGS_PATH  = ensure_json(BASE / "logs.json", {})
TESTS_PATH = ensure_json(BASE / "tests.json", {})
ABS_PATH   = ensure_json(BASE / "absent.json", {})
CLINIC_PATH= ensure_json(BASE / "clinic.json", {})
CAL_PATH   = ensure_json(BASE / "school_calendar.json", {})
ANNS_PATH  = ensure_json(BASE / "announcements.json", [])
ANN_STATUS_PATH = ensure_json(BASE / "announce_status.json", {})
WEEKEND_SLOTS_PATH = ensure_json(BASE / "weekend_slots.json", {})
WATCH_PATH = ensure_json(BASE / "watch.json", {})
ATTENDANCE_PATH = ensure_json(BASE / "attendance.json", {})
CONTACT_PATH = ensure_json(BASE / "contact.json", {})
ARRIVE_TIME_PATH = ensure_json(BASE / "arrive_time.json", {})

TESTS_CFG_PATH = ensure_json(BASE / "tests-config.json", {"categories": {}})

PAGE_FOLDERS_PATH = ensure_json(BASE / "page_folders.json", {})

# ✅ 로그인/비번 저장소(별도 파일)
AUTH_PATH = ensure_json(BASE / "auth.json", {})
