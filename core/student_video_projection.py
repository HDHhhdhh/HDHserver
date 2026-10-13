from __future__ import annotations

import datetime as dt
import re
from copy import deepcopy

from core.progress_rules import (
    PROGRESS_MANUAL_META_KEY,
    latest_video_status_by_sid,
    watch_auto_status,
)
from core.update_assignment_rules import (
    is_manual_video_assignment,
    normalize_video_assign_list,
    sid_keys,
)
from core.video_review_rules import resolve_video_review_states_before_date
from core.video_watch_cycles import VIDEO_WATCH_CYCLES_KEY
from core.video_sources import GICHUL_COURSE, GICHUL_OVERLAY_FIELD


VIDEO_PROGRESS_FINISHED_STATUSES = {"done", "skip"}


def date_indexed_history_through(source: dict, date_key: str) -> dict:
    """Return valid date-indexed history no later than ``date_key``."""
    try:
        cutoff = dt.date.fromisoformat(str(date_key or "").strip())
    except ValueError:
        return {}

    if not isinstance(source, dict):
        return {}

    projected: dict = {}
    for raw_date, value in source.items():
        try:
            event_date = dt.date.fromisoformat(str(raw_date or "").strip())
        except ValueError:
            continue
        if event_date <= cutoff:
            projected[raw_date] = value
    return projected


def history_for_sid(source: dict, sid: str) -> dict:
    """Limit a read-only projection to the requested SID and numeric aliases."""
    if not isinstance(source, dict):
        return {}
    requested_keys = set(sid_keys(sid))
    matching_keys: dict = {}
    projected: dict = {}
    for date_key, day in source.items():
        if not isinstance(day, dict):
            continue
        selected: dict = {}
        for raw_sid, entry in day.items():
            if raw_sid not in matching_keys:
                matching_keys[raw_sid] = bool(requested_keys.intersection(sid_keys(str(raw_sid))))
            if matching_keys[raw_sid]:
                selected[raw_sid] = entry
        if selected:
            projected[date_key] = selected
    return projected


def chapter_number(video: dict) -> float:
    chapter = video.get("chapter", 0)
    try:
        return float(chapter)
    except Exception:
        normalized = re.sub(r"[^0-9.]", "", str(chapter))
        return float(normalized) if normalized else 0.0


def is_finished_video_progress_status(status) -> bool:
    return str(status or "").strip() in VIDEO_PROGRESS_FINISHED_STATUSES


def student_completion_videos(student: dict, videos: list) -> list[dict]:
    if not isinstance(student, dict):
        return []
    if student.get(GICHUL_OVERLAY_FIELD) is True:
        return sorted(student_auto_assignment_videos(student, videos), key=lambda video: (chapter_number(video), str(video.get("mid") or "")))

    curriculum = (student.get("curriculum") or "").strip()
    sub_curriculum = (student.get("subCurriculum") or "").strip()
    exact = [
        video
        for video in (videos or [])
        if isinstance(video, dict)
        and (video.get("curriculum") or "").strip() == curriculum
        and (video.get("subCurriculum") or "").strip() == sub_curriculum
    ]
    if exact:
        exact.sort(
            key=lambda video: (
                chapter_number(video),
                str(video.get("mid") or ""),
            )
        )
        return exact

    fallback = [
        video
        for video in (videos or [])
        if isinstance(video, dict)
        and (video.get("curriculum") or "").strip() == curriculum
    ]
    fallback.sort(
        key=lambda video: (
            chapter_number(video),
            str(video.get("mid") or ""),
        )
    )
    return fallback


def student_review_states_before_date(
    student: dict,
    progress: dict,
    watch: dict,
    date_key: str,
) -> dict:
    sid = (
        str(student.get("id") or "").strip()
        if isinstance(student, dict)
        else ""
    )
    if not sid:
        return {}
    return resolve_video_review_states_before_date(
        progress if isinstance(progress, dict) else {},
        watch if isinstance(watch, dict) else {},
        sid_keys=sid_keys(sid),
        before_date=date_key,
    )


def student_review_states_through_date(
    student: dict,
    progress: dict,
    watch: dict,
    date_key: str,
) -> dict:
    try:
        before_date = (
            dt.date.fromisoformat(str(date_key)) + dt.timedelta(days=1)
        ).isoformat()
    except ValueError:
        return {}
    return student_review_states_before_date(
        student,
        progress,
        watch,
        before_date,
    )


def student_current_curriculum_videos(
    student: dict,
    videos: list,
) -> list[dict]:
    if not isinstance(student, dict):
        return []
    curriculum = str(student.get("curriculum") or "").strip().casefold()
    sub_curriculum = (
        str(student.get("subCurriculum") or "").strip().casefold()
    )
    if not curriculum:
        return []
    return [
        video
        for video in (videos or [])
        if isinstance(video, dict)
        and str(video.get("curriculum") or "").strip().casefold()
        == curriculum
        and (
            not sub_curriculum
            or str(video.get("subCurriculum") or "").strip().casefold()
            == sub_curriculum
        )
    ]


def student_eligible_review_video_mids(
    student: dict,
    videos: list,
    progress: dict,
    watch: dict,
    date_key: str,
) -> set[str]:
    catalog_mids = {
        str(video.get("mid") or "").strip()
        for video in student_review_curriculum_videos(student, videos)
        if str(video.get("mid") or "").strip()
    }
    states = student_review_states_before_date(
        student,
        progress,
        watch,
        date_key,
    )
    return {
        str(mid or "").strip()
        for mid, state in (
            states.items() if isinstance(states, dict) else []
        )
        if str(mid or "").strip() in catalog_mids
        and isinstance(state, dict)
        and state.get("status") == "done"
    }


def filter_self_study_assignment_for_response(
    assignment,
    eligible_mids: set[str],
):
    eligible = {
        str(mid or "").strip()
        for mid in eligible_mids
        if str(mid or "").strip()
    }
    if isinstance(assignment, list):
        return [
            mid
            for mid in normalize_video_assign_list(assignment)
            if mid in eligible
        ]
    if not isinstance(assignment, dict):
        return assignment

    response_assignment = deepcopy(assignment)
    if "videos" in response_assignment:
        response_assignment["videos"] = [
            mid
            for mid in normalize_video_assign_list(
                response_assignment.get("videos")
            )
            if mid in eligible
        ]
    return response_assignment


def filter_auto_assignment_for_current_curriculum(
    assignment,
    student: dict,
    videos: list,
):
    legacy_auto = isinstance(assignment, list)
    named_auto = (
        isinstance(assignment, dict)
        and str(assignment.get("source") or "").strip().casefold() == "auto"
        and not is_manual_video_assignment(assignment)
    )
    if not legacy_auto and not named_auto:
        return assignment

    allowed_mids = {
        str(video.get("mid") or "").strip()
        for video in student_assignment_preservation_videos(student, videos)
        if str(video.get("mid") or "").strip()
    }
    filtered_mids = [
        mid
        for mid in normalize_video_assign_list(assignment)
        if mid in allowed_mids
    ]
    if legacy_auto:
        return filtered_mids

    response_assignment = deepcopy(assignment)
    response_assignment["videos"] = filtered_mids
    return response_assignment


def academy_restricted_student_videos(
    items: list[dict],
    academy_allowed: bool,
) -> list[dict]:
    if academy_allowed:
        return items

    blocked_keys = {
        "url",
        "link",
        "src",
        "source",
        "playUrl",
        "play_url",
        "streamUrl",
        "stream_url",
        "embedUrl",
        "embed_url",
        "youtubeId",
        "youtubeStart",
    }
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        for key in blocked_keys:
            next_item.pop(key, None)
        next_item["playbackRestricted"] = True
        out.append(next_item)
    return out


def student_review_video_projection(
    student: dict,
    videos_all: list,
    progress: dict,
    watch: dict,
    date_key: str,
    assigned_mids,
    academy_allowed: bool,
) -> list[dict]:
    states = student_review_states_through_date(
        student,
        progress,
        watch,
        date_key,
    )
    primary_mids = student_primary_video_mids(student, videos_all)
    catalog_by_mid: dict[str, dict] = {}
    for video in student_review_curriculum_videos(student, videos_all):
        mid = str(video.get("mid") or "").strip()
        if not mid or mid in catalog_by_mid:
            continue
        item = deepcopy(video)
        for internal_key in ("eventDate", "progress", "watch"):
            item.pop(internal_key, None)
        item["isExtraAssignment"] = mid not in primary_mids
        catalog_by_mid[mid] = item

    assigned = {
        str(mid or "").strip()
        for mid in (assigned_mids or [])
        if str(mid or "").strip()
    }
    candidates: list[tuple[float, str, dict]] = []
    for raw_mid, state in states.items():
        mid = str(raw_mid or "").strip()
        if not mid or mid in assigned or mid not in catalog_by_mid:
            continue
        if not isinstance(state, dict) or state.get("status") != "done":
            continue
        item = deepcopy(catalog_by_mid[mid])
        item["reviewStatus"] = state["status"]
        candidates.append((chapter_number(item), mid, item))

    candidates.sort(key=lambda entry: (entry[0], entry[1]))
    return academy_restricted_student_videos(
        [entry[2] for entry in candidates],
        academy_allowed,
    )


def student_primary_video_mids(student: dict, videos: list) -> set[str]:
    return {
        str(video.get("mid") or "").strip()
        for video in student_completion_videos(student, videos)
        if isinstance(video, dict)
        and str(video.get("mid") or "").strip()
    }


def student_auto_assignment_videos(student: dict, videos: list) -> list[dict]:
    if isinstance(student, dict) and student.get(GICHUL_OVERLAY_FIELD) is True:
        return student_current_curriculum_videos({**student, "subCurriculum": GICHUL_COURSE}, videos)
    return student_current_curriculum_videos(student, videos)


def student_assignment_preservation_videos(student: dict, videos: list) -> list[dict]:
    # Overlay toggles change only new picks, never an existing dated snapshot.
    base = student_current_curriculum_videos(student, videos)
    overlay = student_current_curriculum_videos({**student, "subCurriculum": GICHUL_COURSE}, videos) if isinstance(student, dict) else []
    return base + [video for video in overlay if video not in base]


def student_review_curriculum_videos(student: dict, videos: list) -> list[dict]:
    if isinstance(student, dict) and student.get(GICHUL_OVERLAY_FIELD) is True:
        return student_assignment_preservation_videos(student, videos)
    return student_current_curriculum_videos(student, videos)


def course_videos_completed(
    course_videos: list,
    sid: str,
    latest_status_by_sid: dict,
) -> bool:
    mids = [
        str(video.get("mid") or "").strip()
        for video in (course_videos or [])
        if isinstance(video, dict)
        and str(video.get("mid") or "").strip()
    ]
    if not mids:
        return False

    latest = latest_status_by_sid.get(str(sid), {})
    if not isinstance(latest, dict):
        return False
    return all(
        is_finished_video_progress_status(latest.get(mid)) for mid in mids
    )


def build_latest_status_by_sid(progress: dict) -> dict:
    return latest_video_status_by_sid(progress)


def build_auto_assignment_blocked_by_sid(
    progress: dict,
    watch: dict,
) -> dict:
    blocked: dict[str, set[str]] = {}
    manual_reopened_at: dict[tuple[str, str], str] = {}
    cycled_mids: set[tuple[str, str]] = set()

    if isinstance(progress, dict):
        for date_key in sorted(progress.keys()):
            day = progress.get(date_key) or {}
            if not isinstance(day, dict):
                continue
            for sid, mids in day.items():
                if not isinstance(mids, dict):
                    continue
                sid_text = str(sid)
                aliases = sid_keys(sid_text)
                canonical_sid = aliases[-1] if aliases else sid_text
                manual_meta = mids.get(PROGRESS_MANUAL_META_KEY)
                if not isinstance(manual_meta, dict):
                    manual_meta = {}
                cycles = mids.get(VIDEO_WATCH_CYCLES_KEY)
                if isinstance(cycles, dict):
                    cycled_mids.update((canonical_sid, mid) for mid in cycles)
                for mid, status in mids.items():
                    mid_text = str(mid)
                    if mid_text.startswith("__") or mid_text == "tests":
                        continue
                    status_text = str(status or "").strip()
                    if is_finished_video_progress_status(status_text):
                        blocked.setdefault(canonical_sid, set()).add(mid_text)
                    elif (
                        status_text in {"none", "interrupted"}
                        and (manual_meta.get(mid_text) or (canonical_sid, mid_text) in cycled_mids)
                    ):
                        blocked.setdefault(canonical_sid, set()).discard(
                            mid_text
                        )
                        manual_reopened_at[(canonical_sid, mid_text)] = str(
                            date_key
                        )

    if isinstance(watch, dict):
        for date_key in sorted(watch.keys()):
            day = watch.get(date_key) or {}
            if not isinstance(day, dict):
                continue
            for sid, mids in day.items():
                if not isinstance(mids, dict):
                    continue
                sid_text = str(sid)
                aliases = sid_keys(sid_text)
                canonical_sid = aliases[-1] if aliases else sid_text
                for mid, entry in mids.items():
                    mid_text = str(mid or "").strip()
                    if not mid_text or watch_auto_status(entry) != "done":
                        continue
                    if (canonical_sid, mid_text) in cycled_mids:
                        continue  # Fresh-cycle progress, not the historical high-water mark.
                    reopened_at = manual_reopened_at.get(
                        (canonical_sid, mid_text),
                        "",
                    )
                    if reopened_at and str(reopened_at) >= str(date_key):
                        continue
                    blocked.setdefault(canonical_sid, set()).add(mid_text)

    return blocked


def blocked_mids_for_sid(blocked_by_sid: dict, sid: str) -> set[str]:
    blocked: set[str] = set()
    for key in sid_keys(sid):
        blocked.update(blocked_by_sid.get(key) or set())
    return blocked


__all__ = (
    "academy_restricted_student_videos",
    "blocked_mids_for_sid",
    "build_auto_assignment_blocked_by_sid",
    "build_latest_status_by_sid",
    "chapter_number",
    "course_videos_completed",
    "date_indexed_history_through",
    "history_for_sid",
    "filter_auto_assignment_for_current_curriculum",
    "filter_self_study_assignment_for_response",
    "student_completion_videos",
    "student_current_curriculum_videos",
    "student_eligible_review_video_mids",
    "student_primary_video_mids",
    "student_review_states_before_date",
    "student_review_states_through_date",
    "student_review_video_projection",
)
