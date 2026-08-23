from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import makeup_sheet_reader
from core.makeup_sheet_sync import SHEET_SYNC_MAX_ROW, merge_additive_sheet_absences


def test_additive_merge_never_changes_existing_schedule() -> None:
    scheduled_row = {
        "state": "carried",
        "updatedAt": "2026-08-01T00:00:00Z",
        "scheduledMakeup": {
            "originalAbsenceId": "absence|2026-08-10|sid-a|1",
            "studentId": "sid-a",
            "makeupDate": "2026-08-23",
            "makeupTimes": [1],
            "status": "scheduled",
            "ownedExtra": True,
            "ownedSlots": [1],
        },
    }
    carryover = {
        "by_absence": {"2026-08-10": {"sid-a|1": copy.deepcopy(scheduled_row)}},
        "manual": {},
    }
    absent = {"by_date": {}, "by_student": {}, "by_slot": {}}
    candidates = [
        {"date": "2026-08-10", "sid": "sid-a", "slot": 1, "cell": "*"},
        {"date": "2026-08-11", "sid": "sid-b", "slot": 1, "cell": "*"},
        {"date": "2026-08-11", "sid": "sid-b", "slot": 2, "cell": "*"},
    ]
    carryover_before = copy.deepcopy(carryover)
    absent_before = copy.deepcopy(absent)

    result = merge_additive_sheet_absences(
        carryover,
        absent,
        candidates,
        now="2026-08-23T00:00:00.000Z",
    )

    assert carryover == carryover_before
    assert absent == absent_before
    assert result["protectedScheduled"] == 1
    assert result["added"] == 2
    assert result["addedPairs"] == [{"date": "2026-08-11", "sid": "sid-b"}]
    assert result["carryover"]["by_absence"]["2026-08-10"]["sid-a|1"] == scheduled_row
    assert result["carryover"]["by_absence"]["2026-08-11"]["sid-b|1"]["note"] == ""
    assert result["carryover"]["by_absence"]["2026-08-11"]["sid-b|2"]["note"] == ""
    assert result["absent"]["by_slot"]["2026-08-11"]["sid-b"] == [1, 2]
    assert all(change.get("kind") != "cancel" for change in result["changes"])


def test_additive_merge_is_idempotent_and_never_deletes() -> None:
    candidates = [{"date": "2026-08-12", "sid": "sid-c", "slot": 1, "cell": "*"}]
    first = merge_additive_sheet_absences(
        {"by_absence": {}, "manual": {}},
        {"by_date": {}, "by_student": {}, "by_slot": {}},
        candidates,
        now="2026-08-23T00:00:00.000Z",
    )
    second = merge_additive_sheet_absences(
        first["carryover"],
        first["absent"],
        candidates,
        now="2026-08-23T01:00:00.000Z",
    )
    empty = merge_additive_sheet_absences(
        first["carryover"],
        first["absent"],
        [],
        now="2026-08-23T02:00:00.000Z",
    )

    assert second["added"] == 0
    assert second["carryover"] == first["carryover"]
    assert second["absent"] == first["absent"]
    assert empty["carryover"] == first["carryover"]
    assert empty["absent"] == first["absent"]


def test_reader_hard_caps_at_row_127_and_rejects_ambiguous_matches() -> None:
    assert SHEET_SYNC_MAX_ROW == 127
    rows = [[""] * 8 for _ in range(130)]
    rows[0][0] = "학생명"
    rows[3][6] = "8/1"

    def set_student(sheet_row: int, name: str) -> None:
        row = rows[sheet_row - 1]
        row[2] = name
        row[3] = "미적1"
        row[5] = "테스트고"
        row[6] = "*"

    set_student(6, "정상학생")
    set_student(7, "중복학생")
    set_student(127, "경계학생")
    set_student(128, "제외학생")
    students = [
        {"id": "sid-normal", "name": "정상학생", "curriculum": "미적분1", "school": "테스트고"},
        {"id": "sid-ambiguous-1", "name": "중복학생", "curriculum": "미적분1", "school": "테스트고"},
        {"id": "sid-ambiguous-2", "name": "중복학생", "curriculum": "미적분1", "school": "테스트고"},
        {"id": "sid-boundary", "name": "경계학생", "curriculum": "미적분1", "school": "테스트고"},
        {"id": "sid-excluded", "name": "제외학생", "curriculum": "미적분1", "school": "테스트고"},
    ]

    original_download = makeup_sheet_reader._download_csv_rows
    makeup_sheet_reader._download_csv_rows = lambda _url: rows
    try:
        _columns, matches = makeup_sheet_reader.read_sheet_makeup_rows(
            "https://docs.google.com/spreadsheets/d/test/edit?gid=0",
            dt.date(2026, 8, 23),
            students,
            max_sheet_row=127,
        )
    finally:
        makeup_sheet_reader._download_csv_rows = original_download

    matched_sids = {student["id"] for _row_index, _row, student in matches}
    assert matched_sids == {"sid-normal", "sid-boundary"}


def main() -> int:
    test_additive_merge_never_changes_existing_schedule()
    test_additive_merge_is_idempotent_and_never_deletes()
    test_reader_hard_caps_at_row_127_and_rejects_ambiguous_matches()
    print("additive makeup sheet sync safety checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
