from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
import sys
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import makeup_sheet_reader
from core import makeup_sheet_sync
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
    assert result["added"] == 3
    assert result["addedPairs"] == [
        {"date": "2026-08-10", "sid": "sid-a"},
        {"date": "2026-08-11", "sid": "sid-b"},
    ]
    assert result["carryover"]["by_absence"]["2026-08-10"]["sid-a|1"] == scheduled_row
    assert result["absent"]["by_slot"]["2026-08-10"]["sid-a"] == [1]
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


def test_reader_normalizes_school_aliases_and_reports_unmatched_starred_rows() -> None:
    rows = [[""] * 8 for _ in range(10)]
    rows[0][0] = "학생명"
    rows[3][6] = "8/22"

    def set_student(sheet_row: int, name: str, school: str) -> None:
        row = rows[sheet_row - 1]
        row[2] = name
        row[3] = "미적1"
        row[5] = school
        row[6] = "*"

    set_student(6, "배이현", "고양국제고")
    set_student(7, "서지우", "일산대진고")
    set_student(8, "미등록학생", "테스트고")
    students = [
        {"id": "sid-international", "name": "배이현", "curriculum": "미적분1", "school": "고국고"},
        {"id": "sid-daejin", "name": "서지우", "curriculum": "미적분1", "school": "대진고"},
    ]

    original_download = makeup_sheet_reader._download_csv_rows
    makeup_sheet_reader._download_csv_rows = lambda _url: rows
    try:
        snapshot = makeup_sheet_reader.read_sheet_makeup_snapshot(
            "https://docs.google.com/spreadsheets/d/test/edit?gid=0",
            dt.date(2026, 8, 23),
            students,
            max_sheet_row=127,
        )
    finally:
        makeup_sheet_reader._download_csv_rows = original_download

    matched_sids = {student["id"] for _row_index, _row, student in snapshot["studentMatches"]}
    assert matched_sids == {"sid-international", "sid-daejin"}
    assert snapshot["unmatchedStarredRows"] == [
        {"sheetRow": 8, "reason": "no_match", "dates": ["2026-08-22"]},
    ]


def test_reader_uses_unique_name_and_school_when_course_changed() -> None:
    students = [
        {"id": "박슬우160", "name": "박슬우", "curriculum": "확통", "school": "백석고"},
    ]
    matches = makeup_sheet_reader._matching_students(
        students,
        "박슬우",
        "백석고",
        "미적분1",
    )
    assert [student["id"] for student in matches] == ["박슬우160"]
    assert makeup_sheet_reader._matching_students(
        students,
        "박슬우",
        "",
        "미적분1",
    ) == []

    ambiguous = students + [
        {"id": "박슬우999", "name": "박슬우", "curriculum": "대수", "school": "백석고"},
    ]
    assert makeup_sheet_reader._matching_students(
        ambiguous,
        "박슬우",
        "백석고",
        "미적분1",
    ) == []


def test_candidate_window_reads_previous_and_current_month() -> None:
    calls: list[str] = []
    original_read = makeup_sheet_sync.read_additive_sheet_candidates

    def fake_read(_url: str, date_key: str) -> dict:
        month = str(date_key)[:7]
        calls.append(str(date_key))
        return {
            "month": month,
            "matchedRows": 2,
            "sheetStudentCount": 2,
            "maxSheetRow": 127,
            "unmatchedStarredRows": 1 if month == "2026-08" else 0,
            "ambiguousStarredRows": 0,
            "unmatchedStarredDetails": [],
            "candidates": [{"date": f"{month}-20", "sid": month, "slot": 1, "cell": "*"}],
        }

    makeup_sheet_sync.read_additive_sheet_candidates = fake_read
    try:
        result = makeup_sheet_sync.read_additive_sheet_candidate_window(
            "https://docs.google.com/spreadsheets/d/test/edit?gid=0",
            "2026-08-24",
            months_back=1,
        )
    finally:
        makeup_sheet_sync.read_additive_sheet_candidates = original_read

    assert calls == ["2026-07-01", "2026-08-01"]
    assert [item["month"] for item in result["months"]] == ["2026-07", "2026-08"]
    assert [item["date"] for item in result["candidates"]] == ["2026-07-20", "2026-08-20"]
    assert result["unmatchedStarredRows"] == 1

def test_candidate_exclusions_are_exact_date_and_student_pairs() -> None:
    candidates = [
        {"date": "2026-08-19", "sid": "임재윤330", "slot": 2},
        {"date": "2026-08-24", "sid": "임재윤330", "slot": 2},
        {"date": "2026-08-19", "sid": "최승윤694", "slot": 2},
        {"date": "2026-08-22", "sid": "박슬우160", "slot": 2},
    ]
    included, excluded = makeup_sheet_sync.partition_excluded_sheet_candidates(
        candidates,
        [
            {"date": "2026-08-19", "sid": "임재윤330"},
            {"date": "2026-08-24", "sid": "임재윤330"},
            {"date": "2026-08-19", "sid": "최승윤694"},
        ],
    )
    assert included == [{"date": "2026-08-22", "sid": "박슬우160", "slot": 2}]
    assert excluded == candidates[:3]


def test_private_sheet_access_reports_the_required_action() -> None:
    original_open = makeup_sheet_reader.urllib.request.urlopen

    def reject_private_sheet(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://docs.google.com/spreadsheets/d/test/export",
            401,
            "Unauthorized",
            {},
            None,
        )

    makeup_sheet_reader.urllib.request.urlopen = reject_private_sheet
    try:
        try:
            makeup_sheet_reader._download_csv_rows(
                "https://docs.google.com/spreadsheets/d/test/edit?gid=0",
            )
        except RuntimeError as exc:
            message = str(exc)
            assert "제한됨" in message
            assert "링크가 있는 모든 사용자 - 뷰어" in message
            assert "웹에 게시할 필요는 없습니다" in message
        else:
            raise AssertionError("private sheet access must fail with an actionable message")
    finally:
        makeup_sheet_reader.urllib.request.urlopen = original_open


def test_csv_export_url_only_uses_an_explicit_sheet_gid() -> None:
    base = "https://docs.google.com/spreadsheets/d/test-sheet/export?format=csv"
    assert makeup_sheet_reader._csv_export_url(
        "https://docs.google.com/spreadsheets/d/test-sheet/edit?usp=sharing",
    ) == base
    assert makeup_sheet_reader._csv_export_url(
        "https://docs.google.com/spreadsheets/d/test-sheet/edit?gid=12345",
    ) == f"{base}&gid=12345"
    assert makeup_sheet_reader._csv_export_url(
        "https://docs.google.com/spreadsheets/d/test-sheet/edit#gid=67890",
    ) == f"{base}&gid=67890"


def main() -> int:
    test_additive_merge_never_changes_existing_schedule()
    test_additive_merge_is_idempotent_and_never_deletes()
    test_reader_hard_caps_at_row_127_and_rejects_ambiguous_matches()
    test_reader_normalizes_school_aliases_and_reports_unmatched_starred_rows()
    test_reader_uses_unique_name_and_school_when_course_changed()
    test_candidate_window_reads_previous_and_current_month()
    test_candidate_exclusions_are_exact_date_and_student_pairs()
    test_private_sheet_access_reports_the_required_action()
    test_csv_export_url_only_uses_an_explicit_sheet_gid()
    print("additive makeup sheet sync safety checks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
