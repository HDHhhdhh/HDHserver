from __future__ import annotations

import time
from typing import Any

from core.progress_notifications import (
    commit_progress_notifications,
    progress_notification_snapshot,
)
from core.progress_rules import (
    VALID_VIDEO_PROGRESS_STATUSES,
    merge_progress_day_sid,
    merge_watch_entry,
    normalize_incoming_watch_updated_at,
    normalize_watch_entry,
)
from core.progress_store import (
    load_progress_strict,
    progress_file_lock,
    save_progress_strict,
)
from core.storage import file_lock, load, save_atomic


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
        data = load(watch_path)
        if not isinstance(data, dict):
            data = {}

        by_date = data.setdefault(date, {})
        if not isinstance(by_date, dict):
            by_date = {}
            data[date] = by_date

        by_sid = None
        sid_key = sid
        for key in sid_keys(sid):
            candidate = by_date.get(key)
            if isinstance(candidate, dict):
                by_sid = candidate
                sid_key = key
                break

        if by_sid is None:
            by_sid = {}
            by_date[sid_key] = by_sid

        previous = by_sid.get(mid, {})
        merged = merge_watch_entry(previous, merged_incoming)
        by_sid[mid] = merged

        save_atomic(watch_path, data)

    return merged


def get_watch_entry(watch_path: Any, date: str, sid: str, mid: str) -> dict:
    """Read and normalize one watch entry through numeric SID aliases."""
    data = load(watch_path)
    if not isinstance(data, dict):
        return {}
    by_date = data.get(str(date or "").strip())
    if not isinstance(by_date, dict):
        return {}
    for key in sid_keys(sid):
        by_sid = by_date.get(key)
        if isinstance(by_sid, dict):
            return normalize_watch_entry(by_sid.get(str(mid or "").strip()))
    return {}


def save_progress_status(
    progress_path: Any,
    students_path: Any,
    videos_path: Any,
    date: str,
    sid: str,
    mid: str,
    status: str,
) -> dict:
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

        merged = merge_progress_day_sid(current_sid, {mid: status}, source="auto")

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
    return merged


__all__ = (
    "get_watch_entry",
    "save_progress_status",
    "save_watch_entry",
    "sid_keys",
)
