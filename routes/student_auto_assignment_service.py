from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core import log_rules
from core.video_sources import GICHUL_OVERLAY_FIELD
from core.student_schedule_projection import scheduled_makeup_slots_by_student
from core.student_schedule_rules import (
    effective_auto_video_assign_count,
    log_entry_for_date,
    student_absent_on_date,
    student_has_started_on_date,
    student_is_self_study_on_date,
)
from core.student_video_assignment_rules import (
    advance_existing_auto_assignment,
    append_auto_assignment_videos,
    self_study_review_video_mids,
)
from core.student_video_projection import (
    blocked_mids_for_sid,
    build_auto_assignment_blocked_by_sid,
    build_latest_status_by_sid,
    chapter_number,
    course_videos_completed,
    date_indexed_history_through,
    student_completion_videos,
    student_current_curriculum_videos,
    student_auto_assignment_videos,
    student_assignment_preservation_videos,
    student_review_curriculum_videos,
    student_eligible_review_video_mids,
)
from core.update_assignment_rules import (
    SELF_STUDY_VIDEO_ASSIGN_SOURCE,
    StudentAssignmentNotFoundError,
    is_manual_video_assignment,
    normalize_video_assign_list,
    remove_future_auto_assignments,
    sid_lookup,
    stable_json,
    write_sid_mapping,
)


@dataclass(frozen=True)
class StudentAutoAssignmentServiceDependencies:
    updates_path: Any
    students_path: Any
    videos_path: Any
    extra_path: Any
    watch_path: Any
    weekend_slots_path: Any
    load: Callable[[Any], Any]
    load_updates: Callable[[Any], dict]
    save_updates: Callable[[Any, dict], None]
    load_progress: Callable[[], dict]
    load_absent: Callable[[], dict]
    get_log_repository: Callable[[], Any]
    absence_barrier: Callable[[], Any]
    updates_lock: Callable[[], Any]
    today_iso: Callable[[], str]
    student_is_registered: Callable[..., bool]
    on_auto_pick: Callable[[str, list[str]], None]
    makeup_path: Any = None


def student_is_today_auto_target(
    dependencies: StudentAutoAssignmentServiceDependencies,
    student: dict,
    sid: str,
    date_key: str,
    *,
    extra=None,
    absent=None,
    logs=None,
    makeup_slots=None,
) -> bool:
    if not student_has_started_on_date(student, date_key):
        return False
    if student_absent_on_date(absent, date_key, sid):
        return False
    entry = log_entry_for_date(logs, date_key, sid)
    if isinstance(entry, dict) and log_rules.truthy(entry.get("done")):
        return False
    if student_is_self_study_on_date(logs, date_key, sid, student, makeup_slots=makeup_slots):
        return True
    return dependencies.student_is_registered(
        student,
        sid,
        date_key,
        extra=extra,
    )


def ensure_today_auto_assign(
    dependencies: StudentAutoAssignmentServiceDependencies,
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
    makeup=None,
):
    today = date_key or dependencies.today_iso()

    if not isinstance(updates, dict):
        updates = {}
    updates.setdefault(today, {})
    if not isinstance(updates[today], dict):
        updates[today] = {}

    valid_mids = {
        str(video.get("mid") or "").strip()
        for video in (videos or [])
        if isinstance(video, dict)
        and str(video.get("mid") or "").strip()
    }
    progress_through_date = date_indexed_history_through(progress, today)
    watch_through_date = date_indexed_history_through(watch or {}, today)
    latest_status_by_sid = build_latest_status_by_sid(progress_through_date)
    blocked_by_sid = build_auto_assignment_blocked_by_sid(
        progress_through_date,
        watch_through_date,
    )
    logs = logs if isinstance(logs, dict) else {}
    if extra is None:
        try:
            extra = dependencies.load(dependencies.extra_path) or {}
        except Exception:
            extra = {}
    if absent is None:
        try:
            absent = dependencies.load_absent()
        except Exception:
            absent = {}
    if weekend_slots is None:
        try:
            weekend_slots = (
                dependencies.load(dependencies.weekend_slots_path) or {}
            )
        except Exception:
            weekend_slots = {}

    if makeup is None and dependencies.makeup_path is not None:
        makeup = dependencies.load(dependencies.makeup_path)
    makeup_slots_by_sid = scheduled_makeup_slots_by_student(makeup, date_key=today)

    for student in students or []:
        if not isinstance(student, dict):
            continue

        sid = str(student.get("id") or "").strip()
        if not sid:
            continue

        current_videos = student_auto_assignment_videos(student, videos)
        preservation_videos = student_assignment_preservation_videos(student, videos)
        current_videos.sort(
            key=lambda video: (
                chapter_number(video),
                str(video.get("mid") or ""),
            )
        )

        current = sid_lookup(updates[today], sid)
        is_auto_target = student_is_today_auto_target(
            dependencies,
            student,
            sid,
            today,
            extra=extra,
            absent=absent,
            logs=logs,
            makeup_slots=makeup_slots_by_sid.get(sid),
        )
        if not is_auto_target:
            scoped_assignment, scope_changed = append_auto_assignment_videos(
                current,
                preservation_videos,
                set(),
                len(normalize_video_assign_list(current)),
                allow_expand=False,
            )
            if scope_changed:
                write_sid_mapping(
                    updates[today],
                    sid,
                    scoped_assignment,
                )
            continue

        blocked = blocked_mids_for_sid(blocked_by_sid, sid)
        max_assign = effective_auto_video_assign_count(
            student,
            sid,
            today,
            weekend_slots,
            absent,
        )
        self_study = student_is_self_study_on_date(
            logs,
            today,
            sid,
            student,
            makeup_slots=makeup_slots_by_sid.get(sid),
        )
        completion_videos = student_completion_videos(student, videos)
        if self_study:
            if student.get(GICHUL_OVERLAY_FIELD) is True:
                completion_videos = sorted(student_review_curriculum_videos(student, videos), key=lambda video: (chapter_number(video), str(video.get("mid") or "")))
            current_videos = completion_videos

        auto_candidates: list[str] = []
        for video in current_videos:
            mid = str(video.get("mid") or "").strip()
            if not mid or mid not in valid_mids or mid in blocked:
                continue
            auto_candidates.append(mid)
            if len(auto_candidates) >= max_assign:
                break

        if self_study:
            if is_manual_video_assignment(current):
                continue

            completed_review_mids = student_eligible_review_video_mids(
                student,
                videos,
                progress,
                watch or {},
                today,
            )
            review_mids = self_study_review_video_mids(
                completion_videos,
                normalize_video_assign_list(current),
                auto_candidates,
                eligible_mids=completed_review_mids,
            )
            next_assignment = (
                {
                    "videos": review_mids,
                    "source": SELF_STUDY_VIDEO_ASSIGN_SOURCE,
                }
                if review_mids
                else None
            )
            if current != next_assignment:
                write_sid_mapping(updates[today], sid, next_assignment)
            continue

        current_course_mids = {
            str(video.get("mid") or "").strip()
            for video in preservation_videos
            if str(video.get("mid") or "").strip()
        }
        if current is not None and all(
            mid in current_course_mids
            for mid in normalize_video_assign_list(current)
        ):
            continue

        next_assignment, assignment_changed = advance_existing_auto_assignment(
            current,
            current_videos,
            blocked,
            max_assign,
        )
        if assignment_changed:
            write_sid_mapping(updates[today], sid, next_assignment)
            current = next_assignment

        if course_videos_completed(
            current_videos,
            sid,
            latest_status_by_sid,
        ):
            continue
        if current is not None:
            continue
        if auto_candidates:
            dependencies.on_auto_pick(sid, auto_candidates)
            updates[today][sid] = {
                "videos": auto_candidates,
                "source": "auto",
            }

    return updates


def load_updates_with_auto_assign(
    dependencies: StudentAutoAssignmentServiceDependencies,
    *,
    students=None,
    videos=None,
    date_key: str | None = None,
    extra=None,
    absent=None,
    weekend_slots=None,
    logs=None,
):
    """Load assignments and initialize today under the absence coordinator.

    ``absent`` remains accepted for compatibility, but today's authoritative
    absence state is always re-read after entering the coordinator barrier.
    """
    real_today = dependencies.today_iso()
    target_date = str(date_key or real_today).strip()
    if target_date != real_today:
        return dependencies.load_updates(dependencies.updates_path)

    with dependencies.absence_barrier():
        return _load_real_today_updates_with_auto_assign(
            dependencies,
            students=students,
            videos=videos,
            target_date=target_date,
            extra=extra,
            weekend_slots=weekend_slots,
            logs=logs,
        )


def _load_real_today_updates_with_auto_assign(
    dependencies: StudentAutoAssignmentServiceDependencies,
    *,
    students,
    videos,
    target_date: str,
    extra,
    weekend_slots,
    logs,
):

    students = (
        students
        if students is not None
        else dependencies.load(dependencies.students_path)
    )
    videos = (
        videos
        if videos is not None
        else dependencies.load(dependencies.videos_path)
    )
    progress = dependencies.load_progress()
    watch = dependencies.load(dependencies.watch_path)
    logs = (
        logs
        if logs is not None
        else dependencies.get_log_repository().read_logs(target_date)
    )
    extra = (
        extra
        if extra is not None
        else dependencies.load(dependencies.extra_path)
    )
    # Never decide from an absence snapshot loaded before coordinator entry.
    absent = dependencies.load_absent()
    weekend_slots = (
        weekend_slots
        if weekend_slots is not None
        else dependencies.load(dependencies.weekend_slots_path)
    )

    with dependencies.updates_lock():
        updates = dependencies.load_updates(dependencies.updates_path)
        before = stable_json(updates)
        remove_future_auto_assignments(updates, today=target_date)
        fixed = ensure_today_auto_assign(
            dependencies,
            updates,
            students,
            videos,
            progress,
            date_key=target_date,
            watch=watch,
            logs=logs,
            extra=extra,
            absent=absent,
            weekend_slots=weekend_slots,
        )
        if stable_json(fixed) != before:
            dependencies.save_updates(dependencies.updates_path, fixed)
        return fixed


def reconcile_self_study_assignment(
    dependencies: StudentAutoAssignmentServiceDependencies,
    *,
    date: str,
    sid: str,
    has_requested_videos: bool,
    requested_videos: list[str],
    append_requested_videos: bool,
) -> tuple[dict, int]:
    with dependencies.absence_barrier():
        return _reconcile_self_study_assignment_under_barrier(
            dependencies,
            date=date,
            sid=sid,
            has_requested_videos=has_requested_videos,
            requested_videos=requested_videos,
            append_requested_videos=append_requested_videos,
        )


def _reconcile_self_study_assignment_under_barrier(
    dependencies: StudentAutoAssignmentServiceDependencies,
    *,
    date: str,
    sid: str,
    has_requested_videos: bool,
    requested_videos: list[str],
    append_requested_videos: bool,
) -> tuple[dict, int]:
    students = dependencies.load(dependencies.students_path) or []
    student = next(
        (
            item
            for item in students
            if isinstance(item, dict) and str(item.get("id") or "") == sid
        ),
        None,
    )
    if not isinstance(student, dict):
        raise StudentAssignmentNotFoundError(sid)

    logs = dependencies.get_log_repository().read_logs(date, sid)
    makeup = dependencies.load(dependencies.makeup_path) if dependencies.makeup_path is not None else {}
    makeup_slots = scheduled_makeup_slots_by_student(makeup, date_key=date).get(sid)
    if not student_is_self_study_on_date(logs, date, sid, student, makeup_slots=makeup_slots):
        return {"ok": False, "error": "student is not self-study"}, 409

    absences = dependencies.load_absent()
    if student_absent_on_date(absences, date, sid):
        return {"ok": False, "error": "student is absent"}, 409
    log_entry = log_entry_for_date(logs, date, sid)
    if isinstance(log_entry, dict) and log_rules.truthy(
        log_entry.get("archived")
    ):
        return {"ok": False, "error": "student is archived"}, 409

    videos = dependencies.load(dependencies.videos_path) or []
    progress = dependencies.load_progress()
    watch = dependencies.load(dependencies.watch_path) or {}
    eligible_review_mids = student_eligible_review_video_mids(
        student,
        videos,
        progress,
        watch,
        date,
    )
    invalid_requested_videos = [
        mid for mid in requested_videos if mid not in eligible_review_mids
    ]
    if invalid_requested_videos:
        return {
            "ok": False,
            "error": "video is not eligible for self-study review",
            "invalidVideos": invalid_requested_videos,
        }, 409

    with dependencies.updates_lock():
        updates = dependencies.load_updates(dependencies.updates_path)
        if has_requested_videos:
            current = sid_lookup(updates.get(date, {}), sid)
            current_source = (
                str(current.get("source") or "").strip().casefold()
                if isinstance(current, dict)
                else ""
            )
            if (
                is_manual_video_assignment(current)
                and current_source
                != SELF_STUDY_VIDEO_ASSIGN_SOURCE.casefold()
            ):
                return {
                    "ok": False,
                    "error": "manual assignment is protected",
                }, 409
        before = stable_json(updates)
        fixed = ensure_today_auto_assign(
            dependencies,
            updates,
            [student],
            videos,
            progress,
            date_key=date,
            watch=watch,
            logs=logs,
            makeup=makeup,
        )
        if has_requested_videos:
            day = fixed.setdefault(date, {})
            current = sid_lookup(day, sid)
            existing = (
                [
                    mid
                    for mid in normalize_video_assign_list(current)
                    if mid in eligible_review_mids
                ]
                if append_requested_videos
                else []
            )
            selected: list[str] = []
            for mid in [*existing, *requested_videos]:
                if mid not in selected:
                    selected.append(mid)
            assignment = (
                {
                    "videos": selected,
                    "source": SELF_STUDY_VIDEO_ASSIGN_SOURCE,
                }
                if selected
                else None
            )
            write_sid_mapping(day, sid, assignment)
        else:
            assignment = sid_lookup(fixed.get(date, {}), sid)
        if stable_json(fixed) != before:
            dependencies.save_updates(dependencies.updates_path, fixed)
    return {"ok": True, "assignment": assignment}, 200


__all__ = (
    "StudentAutoAssignmentServiceDependencies",
    "ensure_today_auto_assign",
    "load_updates_with_auto_assign",
    "reconcile_self_study_assignment",
    "student_is_today_auto_target",
)
