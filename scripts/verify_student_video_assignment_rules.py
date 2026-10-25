from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import student_auto_assignment_rules as auto_assignment_rules  # noqa: E402
from core import student_schedule_rules as schedule_rules  # noqa: E402
from core.student_schedule_projection import effective_attendance_student_ids, project_student_schedule, scheduled_makeup_slots_by_student  # noqa: E402
from core import student_video_assignment_rules as assignment_rules  # noqa: E402
from core import student_video_projection as video_projection  # noqa: E402


DATE = "2026-06-06"
SID = "007"


def main() -> int:
    pure_rule_paths = (
        ROOT / "core/student_auto_assignment_rules.py",
        ROOT / "core/student_schedule_rules.py",
        ROOT / "core/student_video_assignment_rules.py",
        ROOT / "core/student_video_projection.py",
    )
    for path in pure_rule_paths:
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "from flask",
            "import flask",
            "core.paths",
            "save_atomic",
            "file_lock",
            "current_app",
        ):
            assert forbidden not in source, (
                f"pure rule {path.name} imported runtime boundary: {forbidden}"
            )

    scheduled_student = {
        "id": SID,
        "curriculum": "ALG",
        "subCurriculum": "BASE",
        "autoVideoAssignCount": 2,
        "day1": "토1",
        "day2": "토2",
    }
    schedule_before = deepcopy(scheduled_student)
    upcoming = {**scheduled_student, "registeredOn": DATE, "firstAttendanceDate": "2026-06-13"}
    upcoming_before = deepcopy(upcoming)
    assert not schedule_rules.student_has_schedule_on_date(upcoming, DATE)
    assert schedule_rules.student_has_schedule_on_date(upcoming, "2026-06-13")
    assert schedule_rules.student_slots_for_date(upcoming, SID, DATE, {DATE: {SID: [1, 2]}}) == []
    assert not schedule_rules.student_has_scheduled_self_study_on_date({**upcoming, "selfStudyDays": ["day1"]}, DATE)
    assert effective_attendance_student_ids([upcoming], date_key=DATE, extra={DATE: [SID]},
        makeup={"schedules": [{"studentId": SID, "makeupDate": DATE, "status": "scheduled", "makeupTimes": [1]}]}) == set()
    assert effective_attendance_student_ids([upcoming], date_key="2026-06-13") == {SID}
    assert [row["date"] for row in project_student_schedule(upcoming, sid=SID,
        start_date=DATE, end_date="2026-06-13", extra={DATE: [SID]})] == ["2026-06-13"]
    assert schedule_rules.student_has_started_on_date({"registeredOn": "2026-06-13", "firstAttendanceDate": DATE}, DATE) is False
    for legacy in ({}, {"firstAttendanceDate": "2026-02-30"}, {"registeredOn": "bad-date"}):
        assert schedule_rules.student_has_started_on_date(legacy, DATE)
    assert upcoming == upcoming_before
    assert auto_assignment_rules.MAX_AUTO_VIDEO_ASSIGN_COUNT == 6
    assert auto_assignment_rules.coerce_auto_video_assign_count(10) == 6
    assert auto_assignment_rules.coerce_auto_video_assign_count(0) == 1
    assert schedule_rules.student_slots_for_date(
        scheduled_student,
        SID,
        DATE,
        weekend_slots={},
        absent={},
    ) == [1, 2]
    assert schedule_rules.effective_auto_video_assign_count(
        scheduled_student,
        SID,
        DATE,
        weekend_slots={},
        absent={},
    ) == 4
    assert schedule_rules.student_slots_for_date(
        scheduled_student,
        SID,
        DATE,
        weekend_slots={DATE: {"7": ["토3", "토4"]}},
        absent={"by_slot": {DATE: {SID: ["토4"]}}},
    ) == [3]
    assert schedule_rules.effective_auto_video_assign_count(
        {**scheduled_student, "autoVideoAssignCount": 10},
        SID,
        DATE,
        weekend_slots={},
        absent={},
    ) == 12
    assert scheduled_student == schedule_before

    scheduled_self_study = {
        **scheduled_student,
        "selfStudyDays": ["day1"],
    }
    assert schedule_rules.student_is_self_study_on_date(
        {},
        DATE,
        SID,
        scheduled_self_study,
    ) is True
    assert schedule_rules.student_is_self_study_on_date(
        {DATE: {SID: {"selfStudy": False}}},
        DATE,
        SID,
        scheduled_self_study,
    ) is False
    assert schedule_rules.student_is_self_study_on_date(
        {DATE: {"7": {"selfStudy": "true"}}},
        DATE,
        SID,
        scheduled_student,
    ) is True

    student = {
        "id": SID,
        "curriculum": "ALG",
        "subCurriculum": "BASE",
    }
    makeup = {"by_absence": {"2026-05-30": {
        SID: {"scheduledMakeup": {"studentId": SID, "makeupDate": DATE, "makeupTimes": [1], "status": "scheduled"}},
        f"{SID}|2": {"scheduledMakeup": {"studentId": SID, "makeupDate": DATE, "makeupTimes": [2], "status": "cancelled"}},
        "other": {"scheduledMakeup": {"studentId": "other", "makeupDate": DATE, "makeupTimes": [2], "status": "scheduled"}},
        "deleted": {"scheduledMakeup": None, "scheduled_makeup": {"student_id": SID, "makeup_date": DATE, "makeup_times": [2]}},
    }}, "manual": {"2026-05-29": {"extra": {"sid": SID, "scheduledMakeup": {
        "studentId": SID, "makeupDate": DATE, "makeupTimes": [3], "status": "completed",
    }}}}}
    makeup_before = deepcopy(makeup)
    assert scheduled_makeup_slots_by_student(makeup, date_key=DATE) == {SID: [1], "other": [2]}
    assert scheduled_makeup_slots_by_student(makeup, date_key="2026-06-07") == {}
    assert scheduled_makeup_slots_by_student(makeup, date_key="invalid") == {}
    assert not schedule_rules.student_is_self_study_on_date({}, DATE, SID, scheduled_self_study, makeup_slots=[1])
    assert schedule_rules.student_is_self_study_on_date({}, DATE, SID, scheduled_self_study, makeup_slots=[2])
    assert schedule_rules.student_is_self_study_on_date(
        {DATE: {SID: {"selfStudy": True}}}, DATE, SID, scheduled_self_study, makeup_slots=[1],
    )
    assert not schedule_rules.student_is_self_study_on_date(
        {DATE: {SID: {"selfStudy": False}}}, DATE, SID, scheduled_self_study, makeup_slots=[2],
    )
    assert makeup == makeup_before and scheduled_self_study["selfStudyDays"] == ["day1"]
    videos = [
        {
            "mid": "m2",
            "title": "Two",
            "chapter": "2",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
            "url": "https://video.example/m2",
            "eventDate": "must-not-leak",
            "progress": {"raw": True},
        },
        {
            "mid": "m1",
            "title": "One",
            "chapter": "1",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
            "link": "https://video.example/m1",
        },
        {
            "mid": "m3",
            "title": "Three",
            "chapter": "3",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
        },
        {
            "mid": "other-sub",
            "title": "Other sub",
            "chapter": "4",
            "curriculum": "ALG",
            "subCurriculum": "OTHER",
        },
        {
            "mid": "old-course",
            "title": "Old course",
            "chapter": "5",
            "curriculum": "OLD",
            "subCurriculum": "BASE",
        },
    ]
    progress = {
        "2026-06-04": {
            SID: {
                "m1": "done",
                "m2": "interrupted",
                "other-sub": "done",
                "old-course": "done",
            }
        },
        "2026-06-06": {"7": {"m3": "done"}},
    }
    watch = {
        "2026-06-05": {
            "7": {"m2": {"last": 95, "dur": 100}}
        }
    }
    inputs_before = deepcopy((student, videos, progress, watch))

    assert [
        item["mid"]
        for item in video_projection.student_current_curriculum_videos(student, videos)
    ] == ["m2", "m1", "m3"]
    assert video_projection.student_eligible_review_video_mids(
        student,
        videos,
        progress,
        watch,
        DATE,
    ) == {"m1", "m2"}
    projection = video_projection.student_review_video_projection(
        student,
        videos,
        progress,
        watch,
        DATE,
        assigned_mids={"m1"},
        academy_allowed=False,
    )
    assert projection == [
        {
            "mid": "m2",
            "title": "Two",
            "chapter": "2",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
            "isExtraAssignment": False,
            "reviewStatus": "done",
            "playbackRestricted": True,
        },
        {
            "mid": "m3",
            "title": "Three",
            "chapter": "3",
            "curriculum": "ALG",
            "subCurriculum": "BASE",
            "isExtraAssignment": False,
            "reviewStatus": "done",
            "playbackRestricted": True,
        },
    ]
    assert (student, videos, progress, watch) == inputs_before

    self_study_videos = [
        {
            "mid": f"s{index}",
            "chapter": str(index),
            "curriculum": "ALG",
            "subCurriculum": "BASE",
        }
        for index in range(1, 7)
    ]
    self_study_before = deepcopy(self_study_videos)
    assert assignment_rules.self_study_review_video_mids(
        self_study_videos,
        assigned=["s6"],
        auto_candidates=[],
        eligible_mids={"s1", "s3", "s5"},
    ) == ["s1", "s3", "s5"]
    assert self_study_videos == self_study_before

    assignment = {
        "videos": ["m1", "other-sub", "old-course"],
        "source": "auto",
        "unknown": {"keep": True},
    }
    assignment_before = deepcopy(assignment)
    assert video_projection.filter_auto_assignment_for_current_curriculum(
        assignment,
        student,
        videos,
    ) == {
        "videos": ["m1"],
        "source": "auto",
        "unknown": {"keep": True},
    }
    assert assignment == assignment_before
    manual = {**assignment, "source": "manual"}
    assert video_projection.filter_auto_assignment_for_current_curriculum(
        manual,
        student,
        videos,
    ) is manual
    assert video_projection.filter_self_study_assignment_for_response(
        {
            "videos": ["m1", "m2", "missing"],
            "source": "selfStudy",
            "unknown": 1,
        },
        {"m2"},
    ) == {
        "videos": ["m2"],
        "source": "selfStudy",
        "unknown": 1,
    }

    reopened_progress = {
        "2026-06-01": {SID: {"m1": "done", "m2": "skip"}},
        "2026-06-03": {
            "7": {
                "m1": "none",
                "__manualProgressMids": {"m1": True},
            }
        },
    }
    old_watch = {
        "2026-06-02": {SID: {"m1": {"last": 100, "dur": 100}}}
    }
    blocked = video_projection.build_auto_assignment_blocked_by_sid(
        reopened_progress,
        old_watch,
    )
    assert video_projection.blocked_mids_for_sid(blocked, SID) == {"m2"}
    newer_watch = {
        **old_watch,
        "2026-06-04": {
            "7": {"m1": {"last": 100, "dur": 100}}
        },
    }
    blocked_after_watch = video_projection.build_auto_assignment_blocked_by_sid(
        reopened_progress,
        newer_watch,
    )
    assert video_projection.blocked_mids_for_sid(
        blocked_after_watch,
        SID,
    ) == {"m1", "m2"}

    history_source = {
        "2026-06-05": {SID: {"m1": "done"}},
        DATE: {SID: {"m2": "skip"}},
        "2026-06-07": {SID: {"m3": "done"}},
        "metadata": {"keep": "out of date projection"},
    }
    history_before = deepcopy(history_source)
    assert video_projection.date_indexed_history_through(
        history_source,
        DATE,
    ) == {
        "2026-06-05": {SID: {"m1": "done"}},
        DATE: {SID: {"m2": "skip"}},
    }
    assert history_source == history_before

    current = {
        "videos": ["stale", "m2"],
        "source": "auto",
        "unknown": {"keep": True},
    }
    current_before = deepcopy(current)
    rebased, changed = assignment_rules.advance_existing_auto_assignment(
        current,
        videos[:3],
        blocked={"m1"},
        target_count=2,
    )
    assert changed is True
    assert rebased == {
        "videos": ["m2", "m3"],
        "source": "auto",
        "unknown": {"keep": True},
    }
    assert current == current_before

    mixed_snapshot = {
        "videos": ["m1", "stale", "m2"],
        "source": "auto",
        "unknown": {"keep": True},
    }
    mixed_before = deepcopy(mixed_snapshot)
    mixed_rebased, mixed_changed = (
        assignment_rules.advance_existing_auto_assignment(
            mixed_snapshot,
            videos[:3],
            blocked={"m1"},
            target_count=1,
        )
    )
    assert mixed_changed is True
    assert mixed_rebased == {
        "videos": ["m1", "m2", "m3"],
        "source": "auto",
        "unknown": {"keep": True},
    }
    assert mixed_snapshot == mixed_before
    scoped, scoped_changed = assignment_rules.append_auto_assignment_videos(
        current,
        videos[:3],
        blocked={"m1"},
        target_count=2,
        allow_expand=False,
    )
    assert scoped_changed is True
    assert scoped == {
        "videos": ["m2"],
        "source": "auto",
        "unknown": {"keep": True},
    }
    assert current == current_before

    assert video_projection.course_videos_completed(
        videos[:2],
        SID,
        {SID: {"m1": "done", "m2": "skip"}},
    ) is True
    assert video_projection.course_videos_completed(
        videos[:2],
        SID,
        {SID: {"m1": "done", "m2": "interrupted"}},
    ) is False
    assert schedule_rules.student_absent_on_date(
        {"by_date": {DATE: [SID]}, "by_student": {}},
        DATE,
        SID,
    ) is True

    print(
        "student video assignment rules passed: literal schedule/review/"
        "blocking/rebase oracles and input immutability"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
