"""Pure dashboard curriculum-progress and schedule-projection checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IMPORT_MODULE_STATE = {name: name in sys.modules for name in ("app", "core.paths")}

from core.student_curriculum_progress import build_curriculum_progress  # noqa: E402
from core.student_schedule_projection import (  # noqa: E402
    project_student_schedule,
    select_next_schedule,
)


CALCULATED_AT = "2026-08-09T09:00:00+09:00"


def _check(state: dict[str, int], condition: bool, label: str) -> None:
    state["assertions"] += 1
    if not condition:
        raise AssertionError(label)


def _progress_checks(state: dict[str, int]) -> None:
    student = {"id": "sid-a", "curriculum": "ALG", "subCurriculum": "BASE"}
    videos = [
        {"mid": "m1", "curriculum": "ALG", "subCurriculum": "BASE"},
        {"mid": "m2", "curriculum": "ALG", "subCurriculum": "BASE"},
        {"mid": "m3", "curriculum": "ALG", "subCurriculum": "BASE"},
        {"mid": "m4", "curriculum": "ALG", "subCurriculum": "BASE"},
    ]
    summary = build_curriculum_progress(
        student,
        videos,
        {"m1": "done", "m2": "skip", "m3": "interrupted", "m4": "none"},
        calculated_at=CALCULATED_AT,
    )
    _check(state, (summary["completed"], summary["interrupted"], summary["total"], summary["percent"]) == (2, 1, 4, 50), "done/skip/interrupted/pending counts drifted")
    _check(state, summary["state"] == "available" and summary["basis"] == "curriculum_videos_v1", "available progress contract drifted")
    _check(state, summary["scope"] == "curriculum_subcurriculum" and summary["calculatedAt"] == CALCULATED_AT, "exact scope or injected timestamp drifted")

    empty = build_curriculum_progress(student, [], {}, calculated_at=CALCULATED_AT)
    _check(state, empty["total"] == 0 and empty["percent"] is None and empty["state"] == "unavailable", "empty catalog did not fail unavailable")
    _check(state, empty["basis"] == "curriculum_videos_v1" and empty["scope"] == "none", "empty catalog basis/scope drifted")

    mixed = [
        {"mid": "base", "curriculum": "ALG", "subCurriculum": "BASE"},
        {"mid": "advanced", "curriculum": "ALG", "subCurriculum": "ADV"},
    ]
    exact = build_curriculum_progress(student, mixed, {"base": "done", "advanced": "done"}, calculated_at=CALCULATED_AT)
    fallback = build_curriculum_progress({**student, "subCurriculum": "UNKNOWN"}, mixed, {"base": "done"}, calculated_at=CALCULATED_AT)
    _check(state, exact["total"] == 1 and exact["scope"] == "curriculum_subcurriculum", "exact catalog selection included another sub-curriculum")
    _check(state, fallback["total"] == 2 and fallback["scope"] == "curriculum_fallback", "curriculum-only fallback did not activate")

    duplicate = build_curriculum_progress(student, videos + [dict(videos[0])], {"m1": "done"}, calculated_at=CALCULATED_AT)
    _check(state, duplicate["total"] == 4 and duplicate["completed"] == 1, "duplicate MID changed the denominator")

    switched = build_curriculum_progress(
        {"id": "sid-b", "curriculum": "GEO", "subCurriculum": "BASE"},
        mixed + [{"mid": "g1", "curriculum": "GEO", "subCurriculum": "BASE"}],
        {"g1": "done", "base": "done"},
        calculated_at=CALCULATED_AT,
    )
    _check(state, switched["curriculum"] == "GEO" and switched["completed"] == switched["total"] == 1, "student switch retained the prior curriculum")
    _check(state, "sid-a" not in json.dumps(switched) and "sid-b" not in json.dumps(switched), "curriculum summary leaked a SID")


def _schedule_checks(state: dict[str, int]) -> None:
    student = {
        "id": "sid-a",
        "name": "must-not-leak",
        "day1": "월1",
        "visitTime1": "13:25",
        "day2": "화2",
        "visitTime2": "18:20",
        "day3": "목3",
    }
    regular = project_student_schedule(
        student,
        sid="sid-a",
        start_date="2026-08-10",
        end_date="2026-08-10",
    )
    _check(state, regular == [{"kind": "regular", "status": "scheduled", "date": "2026-08-10", "startAt": "2026-08-10T13:25:00+09:00", "timeLabel": "13:25", "slots": [1]}], "paired regular day/visit time projection drifted")
    multi_slot = project_student_schedule(
        {"id": "sid-a", "day1": "월1", "day2": "월2", "visitTime2": "18:20"},
        sid="sid-a", start_date="2026-08-10", end_date="2026-08-10",
    )
    _check(state, multi_slot[0]["slots"] == [1, 2] and multi_slot[0]["timeLabel"] == "13:00", "missing slot-1 visit time did not retain its earlier default")

    makeup = {
        "by_absence": {
            "2026-08-01": {
                "sid-a|1": {"scheduledMakeup": {"studentId": "sid-a", "makeupDate": "2026-08-10", "makeupTimes": [1], "status": "scheduled"}},
                "sid-a|2": {"scheduledMakeup": {"studentId": "sid-a", "makeupDate": "2026-08-12", "makeupTimes": [3], "status": "scheduled"}},
                "sid-a|3": {"scheduledMakeup": {"studentId": "sid-a", "makeupDate": "2026-08-13", "makeupTimes": [3], "status": "cancelled"}},
                "sid-b|1": {"scheduledMakeup": {"studentId": "sid-b", "makeupDate": "2026-08-11", "makeupTimes": [1], "status": "scheduled", "name": "foreign"}},
            }
        }
    }
    rows = project_student_schedule(
        student,
        sid="sid-a",
        start_date="2026-08-10",
        end_date="2026-08-13",
        absence={"by_date": {"2026-08-10": ["sid-a"]}, "by_student": {}, "by_slot": {"2026-08-10": {"sid-a": [1]}}},
        extra={"2026-08-11": ["sid-a", "sid-b"], "2026-08-12": ["sid-a"], "2026-08-13": ["sid-a"]},
        weekend={"2026-08-11": {"sid-a": [2], "sid-b": [1]}, "2026-08-12": {"sid-a": [3]}},
        makeup=makeup,
    )
    _check(state, [(row["kind"], row["status"]) for row in rows] == [("absence", "cancelled"), ("extra", "scheduled"), ("makeup", "scheduled"), ("makeup", "cancelled")], "schedule source priority drifted")
    _check(state, rows[1]["timeLabel"] == "18:20" and rows[1]["slots"] == [2], "extra schedule lost weekend slot/paired time")
    _check(state, rows[2]["timeLabel"] == "18:00" and rows[2]["slots"] == [3], "makeup slot 3 default time drifted")
    _check(state, all(str(row["startAt"]).endswith("+09:00") for row in rows), "schedule timestamps are not KST ISO strings")
    _check(state, all(set(row) == {"kind", "status", "date", "startAt", "timeLabel", "slots"} for row in rows), "schedule output is not fixed-whitelist")
    dumped = json.dumps(rows, ensure_ascii=False)
    _check(state, "sid-a" not in dumped and "sid-b" not in dumped and "must-not-leak" not in dumped and "foreign" not in dumped, "schedule projection leaked SID/PII")

    foreign_only = project_student_schedule(
        student,
        sid="sid-a",
        start_date="2026-08-10",
        end_date="2026-08-10",
        absence={"by_date": {"2026-08-10": ["sid-b"]}},
        extra={"2026-08-10": ["sid-b"]},
        weekend={"2026-08-10": {"sid-b": [2]}},
        makeup={"schedules": [{"studentId": "sid-b", "makeupDate": "2026-08-10", "status": "cancelled", "makeupTimes": [2]}]},
    )
    _check(state, foreign_only[0]["kind"] == "regular" and len(foreign_only) == 1, "cross-SID markers changed the target schedule")

    _check(state, project_student_schedule(student, sid="sid-a", start_date="bad", end_date="2026-08-10") == [], "invalid range start did not fail closed")
    _check(state, project_student_schedule(student, sid="sid-a", start_date="2026-08-11", end_date="2026-08-10") == [], "reversed range did not fail closed")
    _check(state, project_student_schedule(student, sid="sid-a", start_date="2026-08-10", end_date="2026-10-10") != [], "exactly 62 inclusive days were rejected")
    _check(state, project_student_schedule(student, sid="sid-a", start_date="2026-08-01", end_date="2026-10-02") == [], "over-62-day range did not fail closed")
    _check(state, project_student_schedule(student, sid="sid-b", start_date="2026-08-10", end_date="2026-08-10") == [], "student/SID mismatch did not fail closed")

    next_row = select_next_schedule(rows, as_of="2026-08-10T14:00:00+09:00")
    _check(state, next_row is not None and next_row["kind"] == "absence" and next_row["status"] == "cancelled", "today's absence was hidden by next-schedule selection")
    after_absence = select_next_schedule(rows, as_of="2026-08-11T19:00:00+09:00")
    _check(state, after_absence is not None and after_absence["kind"] == "makeup" and after_absence["date"] == "2026-08-12", "next scheduled makeup selection drifted")
    completed = [{**rows[1], "status": "completed"}, rows[2]]
    _check(state, select_next_schedule(completed, as_of="2026-08-10")["date"] == "2026-08-12", "completed schedule was not excluded")


def _bootstrap_checks(state: dict[str, int]) -> None:
    from scripts.student_mobile_app_checks import student_data as student_data_checks

    date_key = student_data_checks.DATE
    with tempfile.TemporaryDirectory(prefix="student-dashboard-check-") as raw, patch.dict(
        os.environ,
        {"DATA_MIRROR_DIR": str(Path(raw) / "mirror"), "DATA_MIRROR_SNAPSHOTS": "0"},
    ):
        with student_data_checks._isolated_routes(Path(raw)) as (api_basic, announcements, watch, fs, paths):
            logs = student_data_checks._fixtures(paths)
            student_data_checks._write(paths.VID_PATH, [
                {"mid": "mid-a", "title": "A1", "curriculum": "수학A", "subCurriculum": "기본"},
                {"mid": "mid-a-2", "title": "A2", "curriculum": "수학A", "subCurriculum": "기본"},
                {"mid": "mid-b", "title": "B1", "curriculum": "수학B", "subCurriculum": "기본"},
            ])
            student_data_checks._write(paths.PRG_PATH, {
                date_key: {
                    "sid-a": {"mid-a": "done", "mid-a-2": "skip", "tests": {"A시험": "assigned"}},
                    "sid-b": {"mid-b": "done", "tests": {"B시험": "assigned"}},
                }
            })
            student_data_checks._write(paths.EXTRA_PATH, {date_key: ["sid-b"]})
            student_data_checks._write(paths.WEEKEND_SLOTS_PATH, {date_key: {"sid-b": [2]}})
            student_data_checks._write(paths.ABS_PATH, {
                "by_date": {date_key: ["sid-b"]}, "by_student": {"sid-b": date_key},
                "by_slot": {date_key: {"sid-b": [2]}},
            })
            student_data_checks._write(paths.BASE / "makeup_carryover.json", {
                "by_absence": {"2026-08-01": {"sid-b|2": {"scheduledMakeup": {
                    "studentId": "sid-b", "makeupDate": date_key,
                    "makeupTimes": [2], "status": "cancelled", "name": "foreign-marker",
                }}}}
            })
            app, config, _active = student_data_checks._build_app(api_basic, announcements, watch, fs, logs)
            app.config["STUDENT_APP_DASHBOARD_ENABLED"] = True
            client = app.test_client()
            client.set_cookie(config.session_cookie_name, "session-token", domain="app.5a-math.com", path="/")
            edge = {"CF-Connecting-IP": "203.0.113.10"}

            response = client.get(
                f"/api/student/bootstrap?date={date_key}",
                base_url="https://app.5a-math.com",
                headers=edge,
            )
            body = response.get_json()
            dashboard = body.get("dashboard") if isinstance(body, dict) else None
            _check(state, response.status_code == 200 and isinstance(dashboard, dict) and dashboard.get("enabled") is True, "dashboard flag ON did not expose the real bootstrap projection")
            _check(state, dashboard["curriculumProgress"]["completed"] == 2 and dashboard["curriculumProgress"]["total"] == 2, "real bootstrap lost SID-A curriculum progress")
            _check(state, dashboard["homeworkSummary"] == {"count": 1, "state": "assigned"}, "real bootstrap lost SID-A homework summary")
            _check(state, dashboard["nextSchedule"]["kind"] == "regular" and dashboard["nextSchedule"]["date"] == date_key, "real bootstrap next schedule was changed by SID-B markers")
            dashboard_dump = json.dumps(dashboard, ensure_ascii=False)
            _check(state, "sid-b" not in dashboard_dump and "mid-b" not in dashboard_dump and "foreign-marker" not in dashboard_dump, "real dashboard leaked a SID-B marker")

            mismatch = client.get(
                f"/api/student/bootstrap?sid=sid-b&date={date_key}",
                base_url="https://app.5a-math.com",
                headers=edge,
            )
            _check(state, mismatch.status_code == 403, "dashboard bootstrap accepted a mismatched query SID")

            app.config["STUDENT_APP_DASHBOARD_ENABLED"] = False
            disabled = client.get(
                f"/api/student/bootstrap?date={date_key}",
                base_url="https://app.5a-math.com",
                headers=edge,
            ).get_json()
            _check(state, isinstance(disabled, dict) and "dashboard" not in disabled, "dashboard flag OFF retained the dashboard key")


def run_checks() -> dict[str, object]:
    state = {"assertions": 0}
    _progress_checks(state)
    _schedule_checks(state)
    _bootstrap_checks(state)
    _check(state, IMPORT_MODULE_STATE == {name: name in sys.modules for name in IMPORT_MODULE_STATE}, "dashboard services imported app or core.paths")
    return {
        "name": "dashboard",
        "assertions": state["assertions"],
        "passed": True,
        "runtimeIsolation": "pure fixtures plus temporary isolated routes; no live app/runtime paths",
    }


def main() -> int:
    result = run_checks()
    print(f"dashboard checks passed: {result['assertions']} assertions")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_checks"]
