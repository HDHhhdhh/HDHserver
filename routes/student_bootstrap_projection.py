from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core import log_rules
from core.ghost_student import GHOST_STUDENT_ID, is_ghost_student_sid
from core.network_access import ACADEMY_ACCESS_MESSAGE
from core.student_video_projection import history_for_sid
from core.student_schedule_projection import scheduled_makeup_slots_by_student
from core.update_assignment_rules import (
    SELF_STUDY_VIDEO_ASSIGN_SOURCE,
    is_manual_video_assignment,
    normalize_video_assign_list,
    sid_lookup,
)


GHOST_STUDENT_HOMEWORK_BOOK = "고스트 숙제 교재"
GHOST_STUDENT_VIDEO_MID = "ghost-outside-video"
GHOST_STUDENT_TEST_ID = "ghost-outside-answer-test"


@dataclass(frozen=True)
class StudentBootstrapProjectionDependencies:
    students_path: Any
    videos_path: Any
    updates_path: Any
    watch_path: Any
    load: Callable[..., Any]
    load_absent: Callable[[], dict]
    load_progress: Callable[[], dict]
    load_material_state: Callable[[], tuple[dict, dict, dict, bool]]
    get_log_repository: Callable[[], Any]
    homework_books_from_log: Callable[[dict | None], list[str]]
    student_is_registered: Callable[..., bool]
    student_is_self_study: Callable[..., bool]
    student_absent: Callable[..., bool]
    active_alias_sid: Callable[..., str]
    dashboard_enabled: Callable[[], bool]
    dashboard_projection: Callable[..., dict]
    build_latest_status: Callable[[dict], dict]
    student_completion_videos: Callable[[dict, list], list[dict]]
    course_videos_completed: Callable[[list, str, dict], bool]
    load_updates_with_auto_assign: Callable[..., dict]
    build_auto_blocked: Callable[[dict, dict], dict]
    blocked_mids: Callable[[dict, str], set[str]]
    eligible_review_mids: Callable[..., set[str]]
    filter_self_study_assignment: Callable[[Any, set[str]], Any]
    filter_auto_assignment: Callable[[Any, dict, list], Any]
    review_states_through_date: Callable[..., dict]
    student_primary_video_mids: Callable[[dict, list], set[str]]
    academy_restricted_videos: Callable[[list[dict], bool], list[dict]]
    review_video_projection: Callable[..., list[dict]]
    assigned_material_list: Callable[[Any], list[str]]
    filter_materials: Callable[[Any, list[str]], dict]
    assigned_tests: Callable[..., list[dict]]
    filter_tests_for_curriculum: Callable[[list[dict], dict], list[dict]]
    academy_restricted_tests: Callable[[list[dict], bool], list[dict]]
    today_iso: Callable[[], str]
    dashboard_course_block_message: str
    makeup_path: Any = None


def build_ghost_student_bootstrap_payload(date: str) -> dict:
    ghost_student = {
        "id": GHOST_STUDENT_ID,
        "name": "외부접속 테스트",
        "curriculum": "고스트",
        "subCurriculum": "외부접속",
        "level": "중",
        "school": "",
        "grade": "",
        "ghostStudent": True,
    }
    ghost_video = {
        "mid": GHOST_STUDENT_VIDEO_MID,
        "id": GHOST_STUDENT_VIDEO_MID,
        "title": "외부접속 테스트 영상",
        "chapter": "TEST",
        "curriculum": ghost_student["curriculum"],
        "subCurriculum": ghost_student["subCurriculum"],
        "isExtraAssignment": False,
        "playbackRestricted": True,
    }
    ghost_log_entry = {
        "homeworkTable": [
            {
                "book": GHOST_STUDENT_HOMEWORK_BOOK,
                "this": "",
                "next": "",
                "comment": "",
            }
        ],
    }
    ghost_test = {
        "id": GHOST_STUDENT_TEST_ID,
        "testId": GHOST_STUDENT_TEST_ID,
        "name": "외부접속 테스트 답지",
        "label": "외부접속 테스트 답지",
        "categoryKey": "UNIT",
        "categoryLabel": "단원평가",
        "curriculum": ghost_student["curriculum"],
        "round": "1",
        "status": "assigned",
        "statusLabel": "배정",
        "answerRestricted": True,
    }
    return {
        "ok": True,
        "date": date,
        "students": [ghost_student],
        "student": ghost_student,
        "videos": [ghost_video],
        "reviewVideos": [],
        "updates": {date: {GHOST_STUDENT_ID: [GHOST_STUDENT_VIDEO_MID]}},
        "materials": {},
        "assigns": {GHOST_STUDENT_ID: []},
        "absent": {"by_date": {date: []}, "by_student": {}},
        "logs": {date: {GHOST_STUDENT_ID: ghost_log_entry}},
        "assignedTests": [ghost_test],
        "homeworkBooks": [GHOST_STUDENT_HOMEWORK_BOOK],
        "courseVideosCompleted": False,
        "academyAccessAllowed": False,
        "outsideAcademyBlocked": True,
        "networkBlocked": True,
        "academyOnlyMessage": ACADEMY_ACCESS_MESSAGE,
        "ghostStudent": True,
    }


def _build_assigned_tests_payload(
    dependencies: StudentBootstrapProjectionDependencies,
    progress_all: dict,
    logs: dict,
    log_repo,
    *,
    date: str,
    sid: str,
    student: dict,
    academy_allowed: bool,
) -> list[dict]:
    json_logs_for_assigned = log_repo.read_json_map()
    items = dependencies.assigned_tests(progress_all, logs, date, sid, json_logs_for_assigned)
    items = dependencies.filter_tests_for_curriculum(items, student)
    return dependencies.academy_restricted_tests(items, academy_allowed)


def build_student_bootstrap_payload(
    dependencies: StudentBootstrapProjectionDependencies,
    *,
    sid: str,
    date: str,
    public_request: bool,
    academy_allowed_resolver: Callable[[], bool],
) -> tuple[dict, int]:
    if is_ghost_student_sid(sid):
        return build_ghost_student_bootstrap_payload(date), 200

    students = dependencies.load(dependencies.students_path) or []
    student = next(
        (
            item
            for item in students
            if isinstance(item, dict) and str(item.get("id")) == sid
        ),
        None,
    )
    if not student:
        return {"ok": False, "error": "student not found"}, 404
    academy_allowed = bool(academy_allowed_resolver())

    log_repo = dependencies.get_log_repository()
    log_entry = log_repo.read_entry(date, sid).entry
    logs = (
        {date: {sid: log_entry}}
        if isinstance(log_entry, dict) and log_entry
        else {date: {}}
    )
    makeup = dependencies.load(dependencies.makeup_path) if dependencies.makeup_path is not None else {}
    makeup_slots = scheduled_makeup_slots_by_student(makeup, date_key=date).get(sid)
    self_study_day = dependencies.student_is_self_study(
        logs,
        date,
        sid,
        student,
        makeup_slots=makeup_slots,
    )
    archived = isinstance(log_entry, dict) and log_rules.truthy(
        log_entry.get("archived")
    )

    absences = dependencies.load_absent()
    absent_for_date = {
        "by_date": {date: (absences.get("by_date") or {}).get(date, [])},
        "by_student": (
            {sid: (absences.get("by_student") or {}).get(sid)}
            if (absences.get("by_student") or {}).get(sid)
            else {}
        ),
    }
    absent_today = dependencies.student_absent(absences, date, sid)
    registered_today = dependencies.student_is_registered(student, sid, date)

    dashboard_enabled = dependencies.dashboard_enabled()
    videos_all = None
    progress_all = None
    latest_status_by_sid = None
    if dashboard_enabled:
        videos_all = dependencies.load(dependencies.videos_path) or []
        progress_all = dependencies.load_progress()
        latest_status_by_sid = dependencies.build_latest_status(history_for_sid(progress_all, sid))

    if (not registered_today and not self_study_day) or absent_today:
        redirect_sid = dependencies.active_alias_sid(
            students,
            student,
            sid,
            date,
            absences,
        )
        payload = {
            "ok": True,
            "date": date,
            "students": [student],
            "student": student,
            "videos": [],
            "reviewVideos": [],
            "updates": {date: {sid: []}},
            "materials": {},
            "assigns": {sid: []},
            "absent": absent_for_date,
            "logs": {date: {}},
            "assignedTests": [],
            "homeworkBooks": [],
            "courseBlocked": True,
            "selfStudy": self_study_day,
            "blockMessage": dependencies.dashboard_course_block_message,
            "academyAccessAllowed": academy_allowed,
            "outsideAcademyBlocked": not academy_allowed,
            "networkBlocked": not academy_allowed,
            "academyOnlyMessage": ACADEMY_ACCESS_MESSAGE,
            "redirectSid": redirect_sid,
            "recoveredSid": redirect_sid,
            "recoveryReason": "active_course_alias" if redirect_sid else "",
        }
        if dashboard_enabled:
            payload["dashboard"] = dependencies.dashboard_projection(
                student=student,
                sid=sid,
                date_key=date,
                videos=videos_all,
                latest_status_by_sid=latest_status_by_sid,
                homework_books=[],
                absences=absences,
            )
        return payload, 200

    if videos_all is None:
        videos_all = dependencies.load(dependencies.videos_path) or []
    if progress_all is None:
        progress_all = dependencies.load_progress()
    if latest_status_by_sid is None:
        latest_status_by_sid = dependencies.build_latest_status(history_for_sid(progress_all, sid))
    course_videos_completed = dependencies.course_videos_completed(
        dependencies.student_completion_videos(student, videos_all),
        sid,
        latest_status_by_sid,
    )
    if date == dependencies.today_iso() and not public_request:
        updates = dependencies.load_updates_with_auto_assign(
            students=students,
            videos=videos_all,
            date_key=date,
            logs=logs,
        )
    else:
        updates = dependencies.load(dependencies.updates_path) or {}
    day_updates = updates.get(date) if isinstance(updates, dict) else {}
    assignment = sid_lookup(day_updates if isinstance(day_updates, dict) else {}, sid)
    watch_all = dependencies.load(dependencies.watch_path) or {}
    progress_until_date = {
        raw_date: value
        for raw_date, value in progress_all.items()
        if str(raw_date) <= str(date)
    }
    watch_until_date = {
        raw_date: value
        for raw_date, value in (
            watch_all.items() if isinstance(watch_all, dict) else []
        )
        if str(raw_date) <= str(date)
    }
    finished_by_sid = dependencies.build_auto_blocked(
        history_for_sid(progress_until_date, sid),
        history_for_sid(watch_until_date, sid),
    )
    finished_mids = dependencies.blocked_mids(finished_by_sid, sid)
    eligible_mids = dependencies.eligible_review_mids(
        student,
        videos_all,
        progress_all,
        watch_all,
        date,
    )
    assignment_source = (
        str(assignment.get("source") or "").strip().casefold()
        if isinstance(assignment, dict)
        else ""
    )
    if (
        self_study_day
        or assignment_source == SELF_STUDY_VIDEO_ASSIGN_SOURCE.casefold()
    ):
        response_assignment = dependencies.filter_self_study_assignment(
            assignment,
            eligible_mids,
        )
    else:
        response_assignment = dependencies.filter_auto_assignment(
            assignment,
            student,
            videos_all,
        )
    assigned_videos = normalize_video_assign_list(response_assignment)
    assigned_set = set(assigned_videos)
    today_auto_completed_mids: set[str] = set()
    if (
        date == dependencies.today_iso()
        and not self_study_day
        and assignment_source == "auto"
        and not is_manual_video_assignment(response_assignment)
    ):
        states_through_date = dependencies.review_states_through_date(
            student,
            progress_all,
            watch_all,
            date,
        )
        today_auto_completed_mids = {
            mid
            for mid in assigned_set
            if isinstance(states_through_date.get(mid), dict)
            and states_through_date[mid].get("status") == "done"
        }

    playlist_assigned_videos = [
        mid
        for mid in assigned_videos
        if mid not in finished_mids or mid in today_auto_completed_mids
    ]
    playlist_assigned_set = set(playlist_assigned_videos)

    primary_video_mids = dependencies.student_primary_video_mids(
        student,
        videos_all,
    )
    videos = []
    for item_value in videos_all:
        if not isinstance(item_value, dict):
            continue
        mid = str(item_value.get("mid") or "").strip()
        if mid not in playlist_assigned_set:
            continue
        item = dict(item_value)
        item["isExtraAssignment"] = mid not in primary_video_mids
        if mid in today_auto_completed_mids:
            item["todayAutoAssignmentStatus"] = "done"
        videos.append(item)
    videos = dependencies.academy_restricted_videos(videos, academy_allowed)

    review_videos = []
    if not absent_today and not archived:
        review_videos = dependencies.review_video_projection(
            student,
            videos_all,
            progress_all,
            watch_all,
            date,
            playlist_assigned_videos,
            academy_allowed,
        )

    material_catalog, assigns, _page_folders, _degraded = (
        dependencies.load_material_state()
    )
    material_assignment = sid_lookup(assigns, sid)
    assigned_materials = dependencies.assigned_material_list(material_assignment)
    materials = dependencies.filter_materials(
        material_catalog,
        assigned_materials,
    )

    assigned_tests = _build_assigned_tests_payload(
        dependencies, progress_all, logs, log_repo,
        date=date, sid=sid, student=student, academy_allowed=academy_allowed,
    )
    homework_books = dependencies.homework_books_from_log(log_entry)

    payload = {
        "ok": True,
        "date": date,
        "students": [student],
        "student": student,
        "videos": videos,
        "reviewVideos": review_videos,
        "updates": {date: {sid: response_assignment or []}},
        "materials": materials,
        "assigns": {sid: material_assignment or []},
        "absent": absent_for_date,
        "logs": logs,
        "assignedTests": assigned_tests,
        "homeworkBooks": homework_books,
        "selfStudy": self_study_day,
        "courseVideosCompleted": course_videos_completed,
        "academyAccessAllowed": academy_allowed,
        "outsideAcademyBlocked": not academy_allowed,
        "networkBlocked": not academy_allowed,
        "academyOnlyMessage": ACADEMY_ACCESS_MESSAGE,
    }
    if dashboard_enabled:
        payload["dashboard"] = dependencies.dashboard_projection(
            student=student,
            sid=sid,
            date_key=date,
            videos=videos_all,
            latest_status_by_sid=latest_status_by_sid,
            homework_books=homework_books,
            absences=absences,
        )
    return payload, 200


__all__ = (
    "StudentBootstrapProjectionDependencies",
    "build_ghost_student_bootstrap_payload",
    "build_student_bootstrap_payload",
)
