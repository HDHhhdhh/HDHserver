from __future__ import annotations

from core.student_auto_assignment_rules import DEFAULT_AUTO_VIDEO_ASSIGN_COUNT
from core.update_assignment_rules import (
    is_manual_video_assignment,
    normalize_video_assign_list,
)


def self_study_review_video_mids(
    current_videos: list,
    assigned: list[str],
    auto_candidates: list[str],
    eligible_mids: set[str] | None = None,
) -> list[str]:
    """Return the last eligible curriculum videos before the assignment anchor."""
    mids: list[str] = []
    seen: set[str] = set()
    for video in current_videos:
        mid = (
            str(video.get("mid") or "").strip()
            if isinstance(video, dict)
            else ""
        )
        if mid and mid not in seen:
            mids.append(mid)
            seen.add(mid)

    positions = {mid: index for index, mid in enumerate(mids)}
    assigned_positions = [
        positions[mid] for mid in assigned if mid in positions
    ]
    base_positions = assigned_positions or [
        positions[mid] for mid in auto_candidates if mid in positions
    ]
    if not base_positions:
        return []

    eligible = (
        set(mids)
        if eligible_mids is None
        else {
            str(mid or "").strip()
            for mid in eligible_mids
            if str(mid or "").strip()
        }
    )
    start = min(base_positions)
    prior = [mid for mid in mids[:start] if mid in eligible]
    return prior[-DEFAULT_AUTO_VIDEO_ASSIGN_COUNT:]


def append_auto_assignment_videos(
    current,
    current_videos: list[dict],
    blocked,
    target_count: int,
    *,
    allow_expand: bool = True,
):
    """Resize/re-scope an auto assignment while preserving metadata."""
    legacy_list = isinstance(current, list)
    if legacy_list:
        if not current:
            return current, False
    elif not isinstance(current, dict):
        return current, False
    elif str(current.get("source") or "").strip().casefold() != "auto":
        return current, False

    assigned = normalize_video_assign_list(current)
    try:
        target_count = max(0, int(target_count))
    except (TypeError, ValueError):
        target_count = len(assigned)

    blocked_set = {
        str(mid or "").strip()
        for mid in (blocked or set())
        if str(mid or "").strip()
    }
    course_mids: list[str] = []
    course_mid_set: set[str] = set()
    for video in current_videos or []:
        mid = (
            str(video.get("mid") or "").strip()
            if isinstance(video, dict)
            else ""
        )
        if not mid or mid in course_mid_set:
            continue
        course_mid_set.add(mid)
        course_mids.append(mid)

    next_videos: list[str] = []
    seen: set[str] = set()
    for mid in assigned:
        if len(next_videos) >= target_count:
            break
        if mid not in course_mid_set or mid in seen:
            continue
        next_videos.append(mid)
        seen.add(mid)

    if allow_expand:
        for mid in course_mids:
            if len(next_videos) >= target_count:
                break
            if not mid or mid in seen or mid in blocked_set:
                continue
            next_videos.append(mid)
            seen.add(mid)

    if next_videos == assigned:
        return current, False
    if not next_videos:
        return None, True
    if legacy_list:
        return next_videos, True
    updated = dict(current)
    updated["videos"] = next_videos
    return updated, True


def advance_existing_auto_assignment(
    current,
    current_videos: list[dict],
    blocked,
    target_count: int,
    *,
    enforce_current_curriculum: bool = True,
):
    """Replace only stale curriculum slots in an existing daily snapshot."""
    legacy_auto = isinstance(current, list)
    named_auto = (
        isinstance(current, dict)
        and str(current.get("source") or "").strip().casefold() == "auto"
        and not is_manual_video_assignment(current)
    )
    if not legacy_auto and not named_auto:
        return current, False

    assigned = normalize_video_assign_list(current)
    blocked_set = {
        str(mid or "").strip()
        for mid in (blocked or set())
        if str(mid or "").strip()
    }
    course_mids: list[str] = []
    course_mid_set: set[str] = set()
    for video in current_videos or []:
        mid = (
            str(video.get("mid") or "").strip()
            if isinstance(video, dict)
            else ""
        )
        if not mid or mid in course_mid_set:
            continue
        course_mid_set.add(mid)
        course_mids.append(mid)

    outside_current_curriculum = (
        enforce_current_curriculum
        and any(mid not in course_mid_set for mid in assigned)
    )
    if not assigned or not outside_current_curriculum:
        return current, False

    desired_count = len(assigned)
    next_videos: list[str] = []
    seen: set[str] = set()
    for mid in assigned:
        if (
            (enforce_current_curriculum and mid not in course_mid_set)
            or mid in seen
        ):
            continue
        next_videos.append(mid)
        seen.add(mid)

    for mid in course_mids:
        if len(next_videos) >= desired_count:
            break
        if not mid or mid in seen or mid in blocked_set:
            continue
        next_videos.append(mid)
        seen.add(mid)

    if not next_videos:
        return None, True
    if legacy_auto:
        return next_videos, next_videos != current

    next_assignment = dict(current)
    next_assignment["videos"] = next_videos
    return next_assignment, next_assignment != current


__all__ = (
    "advance_existing_auto_assignment",
    "append_auto_assignment_videos",
    "self_study_review_video_mids",
)
