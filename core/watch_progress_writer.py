from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from core.progress_notifications import (
    commit_progress_notifications,
    progress_notification_snapshot,
)
from core.progress_rules import (
    VALID_VIDEO_PROGRESS_STATUSES,
    WATCH_AUTO_PROGRESS_META_KEY,
    merge_progress_day_sid,
    merge_watch_entry,
    normalize_incoming_watch_updated_at,
    normalize_watch_entry,
    watch_auto_status,
)
from core.video_watch_cycles import VIDEO_WATCH_CYCLES_KEY, cycle_watch_record, latest_watch_cycles
from core.progress_store import (
    load_progress_strict,
    progress_file_lock,
    save_progress_strict,
)
from core.storage import file_lock, save_atomic
from core.watch_store import load_watch_strict, watch_object_member


def sid_keys(sid: str) -> list[str]:
    """Return the canonical SID plus its numeric compatibility alias."""
    keys = [str(sid or "").strip()]
    if keys[0].isdigit():
        alternate = str(int(keys[0]))
        if alternate not in keys:
            keys.append(alternate)
    return [key for key in keys if key]


def save_watch_entry(
    watch_path: Any,
    date: str,
    sid: str,
    mid: str,
    incoming,
    *,
    now_ms: int | None = None,
) -> dict:
    """Monotonically merge one playback observation into a watch store."""
    date = str(date or "").strip()
    sid = str(sid or "").strip()
    mid = str(mid or "").strip()
    if not date or not sid or not mid:
        raise ValueError("missing date/sid/mid")

    merged_incoming = normalize_watch_entry(incoming)
    server_now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    merged_incoming["updatedAt"] = normalize_incoming_watch_updated_at(
        merged_incoming["updatedAt"],
        server_now_ms,
    )

    with file_lock(watch_path, timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0):
        data = load_watch_strict(watch_path)
        by_date = watch_object_member(data, date)
        data[date] = by_date

        by_sid = None
        sid_key = sid
        for key in sid_keys(sid):
            if key in by_date:
                by_sid = watch_object_member(by_date, key)
                sid_key = key
                break

        if by_sid is None:
            by_sid = {}
            by_date[sid_key] = by_sid

        previous = watch_object_member(by_sid, mid)
        merged = merge_watch_entry(previous, merged_incoming)
        by_sid[mid] = {**previous, **merged}

        save_atomic(watch_path, data)

    return merged


def get_watch_entry(watch_path: Any, date: str, sid: str, mid: str) -> dict:
    """Read and normalize one watch entry through numeric SID aliases."""
    data = load_watch_strict(watch_path)
    by_date = watch_object_member(data, str(date or "").strip())
    for key in sid_keys(sid):
        if key in by_date:
            by_sid = watch_object_member(by_date, key)
            return normalize_watch_entry(watch_object_member(by_sid, str(mid or "").strip()))
    return {}


def _save_progress_status(
    progress_path: Any,
    students_path: Any,
    videos_path: Any,
    date: str,
    sid: str,
    mid: str,
    status: str,
    *,
    observation=None,
    cycle_token: str = "",
    observation_status: str = "",
) -> tuple[dict, dict | None, bool]:
    """Merge one automatic watch-derived status without overriding manual ownership."""
    date = str(date or "").strip()
    sid = str(sid or "").strip()
    mid = str(mid or "").strip()
    status = str(status or "").strip()

    if not date or not sid or not mid:
        raise ValueError("missing date/sid/mid")
    if status not in VALID_VIDEO_PROGRESS_STATUSES:
        raise ValueError("bad status")

    with progress_file_lock(progress_path):
        current = dict(load_progress_strict(progress_path))
        notification_before = progress_notification_snapshot(
            current,
            sid,
            students_path=students_path,
            videos_path=videos_path,
        )

        current_day = current.get(date)
        day = dict(current_day) if isinstance(current_day, dict) else {}
        current[date] = day

        sid_key = sid
        current_sid = None
        for key in sid_keys(sid):
            candidate = day.get(key)
            if isinstance(candidate, dict):
                sid_key = key
                current_sid = candidate
                break
        if current_sid is None:
            current_sid = {}

        cycle = latest_watch_cycles(current, sid, date).get(mid)
        cycle_watch = None
        if cycle:
            # Never feed historical high-water marks or an older player session
            # into a fresh generation. Check under the same lock as the write.
            if observation is None or cycle_token != cycle["token"]:
                return current_sid, cycle_watch_record(cycle), True
            cycle = deepcopy(cycle)
            observation = normalize_watch_entry(observation)
            observation["updatedAt"] = normalize_incoming_watch_updated_at(observation["updatedAt"], int(time.time() * 1000))
            cycle["watch"] = merge_watch_entry(cycle.get("watch"), observation)
            cycle_watch = cycle_watch_record(cycle)
            status = watch_auto_status(cycle_watch)
            if not status and observation_status == "interrupted":
                status = "interrupted"
            current_sid = deepcopy(current_sid)
            current_sid.setdefault(VIDEO_WATCH_CYCLES_KEY, {})[mid] = cycle
            if mid not in current_sid:
                current_sid[mid] = "none"
                current_sid.setdefault(WATCH_AUTO_PROGRESS_META_KEY, {})[mid] = "none"
        elif cycle_token:
            return current_sid, normalize_watch_entry({}), True

        if not cycle and observation is not None and not status:
            return {}, None, False
        merged = (
            merge_progress_day_sid(current_sid, {mid: status}, source="auto")
            if status or observation is None else current_sid
        )

        if merged:
            day[sid_key] = merged
        else:
            day.pop(sid_key, None)

        if not day:
            current.pop(date, None)

        save_progress_strict(progress_path, current)

        notification_after = progress_notification_snapshot(
            current,
            sid,
            students_path=students_path,
            videos_path=videos_path,
        )

    commit_progress_notifications(notification_before, notification_after, sid)
    return merged, cycle_watch, False


def save_progress_status(progress_path, students_path, videos_path, date, sid, mid, status) -> dict:
    return _save_progress_status(progress_path, students_path, videos_path, date, sid, mid, status)[0]


def save_watch_observation_progress(
    progress_path, students_path, videos_path, date, sid, mid, status,
    *, observation, cycle_token="", observation_status="",
) -> tuple[dict, dict | None, bool]:
    return _save_progress_status(
        progress_path, students_path, videos_path, date, sid, mid, status,
        observation=observation, cycle_token=cycle_token, observation_status=observation_status,
    )


__all__ = (
    "get_watch_entry",
    "save_progress_status",
    "save_watch_entry",
    "save_watch_observation_progress",
    "sid_keys",
)
