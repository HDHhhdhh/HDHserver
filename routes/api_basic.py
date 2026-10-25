from __future__ import annotations

import datetime as dt
import os
import json

from flask import Blueprint, current_app, jsonify, request

from core.paths import (
    BASE,
    STU_PATH, VID_PATH, PRG_PATH, UPD_PATH, ABS_PATH, ASN_PATH, MAT_PATH, PAGE_FOLDERS_PATH,
    EXTRA_PATH, CLINIC_PATH, WEEKEND_SLOTS_PATH,
    WATCH_PATH, TESTS_CFG_PATH,
)
from core.absence_transaction import absence_consistency_barrier
from core import log_rules as _log_rules
from core.network_access import strip_answer_link_fields
from core.progress_rules import (
    PROGRESS_ALL_STUDENTS_META_KEY,
    TEST_ASSIGN_CLEAR_META_KEY,
    WATCH_AUTO_PROGRESS_META_KEY,
    merge_progress_day_sid as _merge_progress_day_sid,
)
from core.progress_store import load_progress_strict
from core.person_identity import same_person
from core.update_assignment_rules import (
    SELF_STUDY_VIDEO_ASSIGN_SOURCE,
    StudentAssignmentNotFoundError,
    is_manual_video_assignment as _is_manual_video_assignment,
    merge_update_assignment as _merge_update_assignment,
    normalize_video_assign_list as _normalize_video_assign_list,
    sid_keys as _sid_keys,
    sid_lookup as _sid_lookup,
    stable_json as _json_stable,
    write_sid_mapping as _write_sid_mapping,
)
from core.student_video_assignment_rules import (
    advance_existing_auto_assignment as _advance_existing_auto_assignment,
    append_auto_assignment_videos as _append_auto_assignment_videos,
    self_study_review_video_mids as _self_study_review_video_mids,
)
from core.student_schedule_rules import (
    effective_auto_video_assign_count as _effective_auto_video_assign_count,
    has_consecutive_slots as _has_consecutive_slots,
    log_entry_for_date as _log_entry_for_date,
    normalize_schedule_slots as _normalize_schedule_slots,
    student_absent_on_date as _student_absent_on_date,
    student_has_schedule_on_date as _student_has_schedule_on_date,
    student_has_scheduled_self_study_on_date as _student_has_scheduled_self_study_on_date,
    student_is_self_study_on_date as _student_is_self_study_on_date,
    student_slots_for_date as _student_slots_for_date,
    weekday_char_for_date as _weekday_char_for_date,
)
from core.student_video_projection import (
    academy_restricted_student_videos as _academy_restricted_student_videos,
    blocked_mids_for_sid as _blocked_mids_for_sid,
    build_auto_assignment_blocked_by_sid as _build_auto_assignment_blocked_by_sid,
    build_latest_status_by_sid as _build_latest_status_by_sid,
    chapter_number as _chap_num,
    course_videos_completed as _course_videos_completed,
    filter_auto_assignment_for_current_curriculum as _filter_auto_assignment_for_current_curriculum,
    filter_self_study_assignment_for_response as _filter_self_study_assignment_for_response,
    is_finished_video_progress_status as _is_finished_video_progress_status,
    student_completion_videos as _student_completion_videos,
    student_current_curriculum_videos as _student_current_curriculum_videos,
    student_eligible_review_video_mids as _student_eligible_review_video_mids,
    student_primary_video_mids as _student_primary_video_mids,
    student_review_states_before_date as _student_review_states_before_date,
    student_review_states_through_date as _student_review_states_through_date,
    student_review_video_projection as _student_review_video_projection,
)
from core.update_assignment_store import (
    load_updates_strict,
    save_updates_strict,
    updates_lock as _make_updates_lock,
)
from core.student_curriculum_progress import build_curriculum_progress
from core.student_schedule_projection import project_student_schedule, select_next_schedule
from core.student_notification_hooks import (
    enqueue_current_schedule_changes,
    student_schedule_changed_sids,
)
from core.test_answer_links import resolve_test_assignment_answer_url
from core.student_test_projection import (
    _normalize_test_assignment_status,
    _test_assignment_status_label,
    _is_active_test_assignment_status,
    _round_label_for_assignment,
    _fallback_assigned_test_from_label,
    _normalized_test_curriculum,
    _assigned_test_curriculum,
    _filter_assigned_tests_for_student_curriculum,
    _assigned_test_label,
    _normalized_test_status_map,
    _append_unique_assigned_test_label,
    _collect_assigned_test_metadata,
    _student_assigned_test_labels,
    project_student_assigned_tests,
    resolve_student_assigned_tests,
)
from core.storage import InterProcessFileLock, file_lock, load, save_atomic
from core.absent import load_absent, save_absent
from core.date_rules import is_iso_date_key
from routes.log_repository_provider import (
    get_log_repository,
    student_homework_book_names_from_log as _student_homework_book_names_from_log,
)
from routes.material_state_provider import load_material_state_for_read
from routes.student_bootstrap_projection import (
    StudentBootstrapProjectionDependencies,
)
from routes.student_auto_assignment_service import (
    StudentAutoAssignmentServiceDependencies,
    ensure_today_auto_assign as _service_ensure_today_auto_assign,
    load_updates_with_auto_assign as _service_load_updates_with_auto_assign,
    reconcile_self_study_assignment as _service_reconcile_self_study_assignment,
    student_is_today_auto_target as _service_student_is_today_auto_target,
)

bp_api_basic = Blueprint("api_basic", __name__)

CT = {"Content-Type": "application/json"}
STUDENT_COURSE_BLOCK_MESSAGE = "수업일이 아닌 것 같습니다. 선생님께 문의주세용 ^_^"


# ─────────────────────────────────────────────
# 공통 CRUD
# ─────────────────────────────────────────────
def crud(path):
    if request.method == "GET":
        return jsonify(load(path))
    obj = request.get_json(force=True)
    save_atomic(path, obj)
    return "", 204


def _load_material_state_for_read() -> tuple[dict, dict, dict, bool]:
    return load_material_state_for_read(
        MAT_PATH,
        ASN_PATH,
        PAGE_FOLDERS_PATH,
    )


def _load_progress_strict(path=None) -> dict:
    """Compatibility wrapper around the shared progress store."""
    return load_progress_strict(path or PRG_PATH)


def _student_is_registered_on_date(student: dict, sid: str, date_key: str, extra=None) -> bool:
    if _student_has_schedule_on_date(student, date_key):
        return True
    if extra is None:
        try:
            extra = load(EXTRA_PATH) or {}
        except Exception:
            extra = {}
    extra_ids = extra.get(date_key, []) if isinstance(extra, dict) else []
    return str(sid) in {str(x) for x in (extra_ids or [])}


# ─────────────────────────────────────────────
# ✅ 프로세스 간 파일 락 (JSON 저장 보호용)
# ─────────────────────────────────────────────
class _InterProcessFileLock(InterProcessFileLock):
    """Backward-compatible alias for modules importing the old route-local lock."""


def _updates_lock():
    return _make_updates_lock(UPD_PATH, lock_factory=_InterProcessFileLock)


def _auto_assignment_absence_barrier():
    return absence_consistency_barrier(absent_path=ABS_PATH)


def _load_tests_config_for_answer_links() -> dict:
    try:
        mtime = TESTS_CFG_PATH.stat().st_mtime
    except FileNotFoundError:
        _TESTS_CONFIG_CACHE.update({"mtime": None, "data": {}})
        return {}
    except Exception:
        return _TESTS_CONFIG_CACHE.get("data") or {}

    if _TESTS_CONFIG_CACHE.get("mtime") == mtime:
        return _TESTS_CONFIG_CACHE.get("data") or {}

    try:
        data = json.loads(TESTS_CFG_PATH.read_text("utf-8-sig"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    _TESTS_CONFIG_CACHE.update({"mtime": mtime, "data": data})
    return data


def _load_test_answer_link_map() -> dict:
    try:
        mtime = TEST_ANSWER_LINK_MAP_PATH.stat().st_mtime
    except FileNotFoundError:
        _TEST_ANSWER_LINK_MAP_CACHE.update({"mtime": None, "data": {}})
        return {}
    except Exception:
        return _TEST_ANSWER_LINK_MAP_CACHE.get("data") or {}

    if _TEST_ANSWER_LINK_MAP_CACHE.get("mtime") == mtime:
        return _TEST_ANSWER_LINK_MAP_CACHE.get("data") or {}

    try:
        data = json.loads(TEST_ANSWER_LINK_MAP_PATH.read_text("utf-8-sig"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    _TEST_ANSWER_LINK_MAP_CACHE.update({"mtime": mtime, "data": data})
    return data


def _test_assignment_answer_url(item: dict) -> str:
    return resolve_test_assignment_answer_url(
        item,
        tests_config=_load_tests_config_for_answer_links(),
        answer_link_map=_load_test_answer_link_map(),
    )


def _student_assigned_tests_for_date(
    progress_all: dict,
    logs_map: dict,
    date: str,
    sid: str,
    fallback_logs_map=None,
) -> list[dict]:
    items = project_student_assigned_tests(
        progress_all, logs_map, date, sid, fallback_logs_map,
    )
    out = []
    for item in items:
        out.extend(resolve_student_assigned_tests(
            [item],
            tests_config=_load_tests_config_for_answer_links(),
            answer_link_map=_load_test_answer_link_map(),
        ))
    return out


def _assigned_material_list(value) -> list[str]:
    if isinstance(value, dict):
        value = value.get("materials")
    if not isinstance(value, list):
        return []
    out = []
    seen = set()
    for item in value:
        if isinstance(item, dict):
            item = item.get("id") or item.get("url") or item.get("path")
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        out.append(key)
        seen.add(key)
    return out


def _filter_materials_for_assignment(materials, assigned):
    if not isinstance(materials, dict):
        return {}
    wanted = {str(x) for x in (assigned or []) if str(x or "").strip()}
    if not wanted:
        return {}

    out = {}
    for key, value in materials.items():
        item = value if isinstance(value, dict) else {}
        candidates = {
            str(key),
            str(item.get("id") or ""),
            str(item.get("mid") or ""),
            str(item.get("url") or ""),
            str(item.get("path") or ""),
        }
        if candidates & wanted:
            out[key] = value
    return out


def _academy_restricted_assigned_tests(items: list[dict], academy_allowed: bool) -> list[dict]:
    if academy_allowed:
        return items

    out: list[dict] = []
    for item in items or []:
        stripped, had_answer_link = strip_answer_link_fields(item)
        if isinstance(stripped, dict) and had_answer_link:
            stripped["answerRestricted"] = True
        out.append(stripped)
    return out


TEST_ASSIGN_DAILY_ITEMS_KEY = "testAssignmentDailyTests"
TEST_ANSWER_LINK_MAP_PATH = BASE / "static" / "js" / "test_answer_link_map.json"
_TEST_ANSWER_LINK_MAP_CACHE = {"mtime": None, "data": {}}
_TESTS_CONFIG_CACHE = {"mtime": None, "data": {}}


KST = dt.timezone(dt.timedelta(hours=9))


# ─────────────────────────────────────────────
# KST 날짜와 학생 dashboard 조합
# ─────────────────────────────────────────────
def _today_kst_iso() -> str:
    return dt.datetime.now(KST).date().isoformat()


def _student_dashboard_enabled() -> bool:
    return bool(current_app.config.get("STUDENT_APP_DASHBOARD_ENABLED", False))


def _student_homework_enabled() -> bool:
    return bool(current_app.config.get("STUDENT_APP_HOMEWORK_ENABLED", False))


def _dashboard_homework_count(sid: str, fallback: int) -> int:
    if not _student_homework_enabled():
        return fallback
    try:
        from core.student_homework_repository import StudentHomeworkRepository

        database = os.environ.get("STUDENT_APP_DB_PATH", str(BASE / "app.sqlite"))
        return StudentHomeworkRepository(database).count_open(sid)
    except Exception:  # noqa: BROAD_EXCEPT_OK - an uninitialized additive store falls back to legacy data
        return fallback


def _dashboard_mapping(path) -> dict:
    try:
        value = load(path) or {}
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _student_dashboard_projection(
    *,
    student: dict,
    sid: str,
    date_key: str,
    videos: list,
    latest_status_by_sid: dict,
    homework_books: list,
    absences: dict,
) -> dict:
    start = dt.date.fromisoformat(date_key)
    end = start + dt.timedelta(days=45)
    calculated_at = dt.datetime.now(KST).replace(microsecond=0)
    schedule_as_of = (
        calculated_at
        if start == calculated_at.date()
        else dt.datetime.combine(start, dt.time.min, tzinfo=KST)
    )
    events = project_student_schedule(
        student,
        sid=sid,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        absence=absences,
        extra=_dashboard_mapping(EXTRA_PATH),
        weekend=_dashboard_mapping(WEEKEND_SLOTS_PATH),
        makeup=_dashboard_mapping(BASE / "makeup_carryover.json"),
    )
    latest_for_student = latest_status_by_sid.get(str(sid), {})
    if not isinstance(latest_for_student, dict):
        latest_for_student = {}
    curriculum_progress = build_curriculum_progress(
        student,
        videos,
        latest_for_student,
        calculated_at=calculated_at.isoformat(),
    )
    legacy_homework_count = len(homework_books) if isinstance(homework_books, list) else 0
    homework_count = _dashboard_homework_count(sid, legacy_homework_count)
    return {
        "enabled": True,
        "curriculumProgress": curriculum_progress,
        "nextSchedule": select_next_schedule(
            events,
            as_of=schedule_as_of.isoformat(),
        ),
        "homeworkSummary": {
            "count": homework_count,
            "state": "assigned" if homework_count else "empty",
        },
        "unreadBoardCount": None,
    }


def _report_auto_assignment_pick(sid: str, picked: list[str]) -> None:
    print("[AUTOASSIGN] PICK sid =", sid, "picked =", picked, flush=True)


def _student_auto_assignment_service_dependencies(
) -> StudentAutoAssignmentServiceDependencies:
    return StudentAutoAssignmentServiceDependencies(
        updates_path=UPD_PATH,
        students_path=STU_PATH,
        videos_path=VID_PATH,
        extra_path=EXTRA_PATH,
        watch_path=WATCH_PATH,
        weekend_slots_path=WEEKEND_SLOTS_PATH,
        load=load,
        load_updates=load_updates_strict,
        save_updates=save_updates_strict,
        load_progress=_load_progress_strict,
        load_absent=load_absent,
        get_log_repository=get_log_repository,
        absence_barrier=_auto_assignment_absence_barrier,
        updates_lock=_updates_lock,
        today_iso=_today_kst_iso,
        student_is_registered=_student_is_registered_on_date,
        on_auto_pick=_report_auto_assignment_pick,
        makeup_path=BASE / "makeup_carryover.json",
    )


def _student_is_today_auto_target(
    stu: dict,
    sid: str,
    date_key: str,
    extra=None,
    absent=None,
    logs=None,
) -> bool:
    return _service_student_is_today_auto_target(
        _student_auto_assignment_service_dependencies(),
        stu,
        sid,
        date_key,
        extra=extra,
        absent=absent,
        logs=logs,
    )


def _same_student_course_alias(left: dict, right: dict) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    identity_match = same_person(left, right)
    if identity_match is not None:
        return identity_match
    if str(left.get("name") or "").strip() != str(right.get("name") or "").strip():
        return False

    shared_doc = str(left.get("docUrl") or "").strip()
    if shared_doc and shared_doc == str(right.get("docUrl") or "").strip():
        return True

    for key in ("school", "grade", "level", "subCurriculum"):
        if str(left.get(key) or "").strip() != str(right.get(key) or "").strip():
            return False
    return True


def _active_student_alias_sid(students, student: dict, sid: str, date_key: str, absent) -> str:
    candidates = []
    for candidate in students if isinstance(students, list) else []:
        candidate_sid = str(candidate.get("id") or "").strip() if isinstance(candidate, dict) else ""
        if not candidate_sid or candidate_sid == sid:
            continue
        if not _same_student_course_alias(student, candidate):
            continue
        if _student_absent_on_date(absent, date_key, candidate_sid):
            continue
        if _student_is_registered_on_date(candidate, candidate_sid, date_key):
            candidates.append(candidate_sid)

    return candidates[0] if len(candidates) == 1 else ""


def _expand_consecutive_auto_assignment_in_updates(
    updates: dict,
    date_key: str,
    sid: str,
    students: list[dict],
    videos: list[dict],
    progress: dict,
    watch=None,
    weekend_slots=None,
    extra=None,
    absent=None,
    logs=None,
) -> bool:
    """Preserve the date snapshot when class slots change."""
    return False


def _reconcile_consecutive_auto_assignment(
    date_key: str,
    sid: str,
    students=None,
    videos=None,
    progress=None,
    watch=None,
    weekend_slots=None,
    extra=None,
    absent=None,
    logs=None,
) -> bool:
    """Schedule edits cannot resize an already-created daily snapshot."""
    return False


def reconcile_auto_assignment_for_schedule_change(
    date_key: str,
    sid: str,
    *,
    weekend_slots,
) -> bool:
    """Public composition hook for schedule-override HTTP routes."""
    return _reconcile_consecutive_auto_assignment(
        date_key,
        sid,
        weekend_slots=weekend_slots,
    )


def _reconcile_auto_assignment_after_progress(
    date_key: str,
    sid: str,
    progress=None,
    watch=None,
) -> bool:
    """Preserve existing snapshots after progress or watch writes.

    Kept as a compatibility seam for focused tests and older imports. Assignment
    selection is date-bound and must never be derived again from completion state.
    """
    return False


def _ensure_today_auto_assign(
    updates,
    students,
    videos,
    progress,
    date_key: str | None = None,
    watch=None,
    logs=None,
    extra=None,
    absent=None,
    weekend_slots=None,
):
    return _service_ensure_today_auto_assign(
        _student_auto_assignment_service_dependencies(),
        updates,
        students,
        videos,
        progress,
        date_key=date_key,
        watch=watch,
        logs=logs,
        extra=extra,
        absent=absent,
        weekend_slots=weekend_slots,
    )


def _load_updates_with_auto_assign(
    students=None,
    videos=None,
    date_key: str | None = None,
    extra=None,
    absent=None,
    weekend_slots=None,
    logs=None,
):
    return _service_load_updates_with_auto_assign(
        _student_auto_assignment_service_dependencies(),
        students=students,
        videos=videos,
        date_key=date_key,
        extra=extra,
        absent=absent,
        weekend_slots=weekend_slots,
        logs=logs,
    )


def initialize_auto_assignment_for_schedule_change(
    *,
    date_key: str,
    extra=None,
    weekend_slots=None,
):
    """Initialize a missing real-today snapshot after a schedule change."""
    return _load_updates_with_auto_assign(
        date_key=date_key,
        extra=extra,
        weekend_slots=weekend_slots,
    )


def initialize_auto_assignment_for_student_identity_change(*, students):
    """Public composition hook after a persisted student curriculum/schedule edit."""
    return _load_updates_with_auto_assign(students=students)


def reconcile_auto_assignment_for_student_identity_change(
    date_key: str,
    sid: str,
    *,
    students,
) -> bool:
    """Public composition hook for one persisted regular-schedule edit."""
    return _reconcile_consecutive_auto_assignment(
        date_key,
        sid,
        students=students,
    )


def initialize_auto_assignment_for_updates_read():
    """Public composition hook for the legacy real-today updates GET."""
    return _load_updates_with_auto_assign()


def reconcile_self_study_assignment_for_updates(
    *,
    date: str,
    sid: str,
    has_requested_videos: bool,
    requested_videos: list[str],
    append_requested_videos: bool,
) -> tuple[dict, int]:
    """Public, Flask-response-free service for the self-study updates route."""
    return _service_reconcile_self_study_assignment(
        _student_auto_assignment_service_dependencies(),
        date=date,
        sid=sid,
        has_requested_videos=has_requested_videos,
        requested_videos=requested_videos,
        append_requested_videos=append_requested_videos,
    )


# ─────────────────────────────────────────────
# 기본 API
# ─────────────────────────────────────────────
def create_student_bootstrap_projection_dependencies(
) -> StudentBootstrapProjectionDependencies:
    return StudentBootstrapProjectionDependencies(
        students_path=STU_PATH,
        videos_path=VID_PATH,
        updates_path=UPD_PATH,
        watch_path=WATCH_PATH,
        makeup_path=BASE / "makeup_carryover.json",
        load=load,
        load_absent=load_absent,
        load_progress=_load_progress_strict,
        load_material_state=_load_material_state_for_read,
        get_log_repository=get_log_repository,
        homework_books_from_log=_student_homework_book_names_from_log,
        student_is_registered=_student_is_registered_on_date,
        student_is_self_study=_student_is_self_study_on_date,
        student_absent=_student_absent_on_date,
        active_alias_sid=_active_student_alias_sid,
        dashboard_enabled=_student_dashboard_enabled,
        dashboard_projection=_student_dashboard_projection,
        build_latest_status=_build_latest_status_by_sid,
        student_completion_videos=_student_completion_videos,
        course_videos_completed=_course_videos_completed,
        load_updates_with_auto_assign=_load_updates_with_auto_assign,
        build_auto_blocked=_build_auto_assignment_blocked_by_sid,
        blocked_mids=_blocked_mids_for_sid,
        eligible_review_mids=_student_eligible_review_video_mids,
        filter_self_study_assignment=_filter_self_study_assignment_for_response,
        filter_auto_assignment=_filter_auto_assignment_for_current_curriculum,
        review_states_through_date=_student_review_states_through_date,
        student_primary_video_mids=_student_primary_video_mids,
        academy_restricted_videos=_academy_restricted_student_videos,
        review_video_projection=_student_review_video_projection,
        assigned_material_list=_assigned_material_list,
        filter_materials=_filter_materials_for_assignment,
        assigned_tests=_student_assigned_tests_for_date,
        filter_tests_for_curriculum=_filter_assigned_tests_for_student_curriculum,
        academy_restricted_tests=_academy_restricted_assigned_tests,
        today_iso=_today_kst_iso,
        dashboard_course_block_message=STUDENT_COURSE_BLOCK_MESSAGE,
    )


@bp_api_basic.post("/api/feedback")
def api_feedback():
    import json as _json
    from core.paths import BASE
    data = request.get_json(force=True) or {}
    with open(BASE / "feedbacks.json", "a", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False)
        f.write("\n")
    return "", 204


# ─────────────────────────────────────────────
# 기타
# ─────────────────────────────────────────────
@bp_api_basic.get("/api/ping")
def api_ping():
    return "ok"
