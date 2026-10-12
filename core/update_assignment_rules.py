from __future__ import annotations

import datetime as dt
import json


SELF_STUDY_VIDEO_ASSIGN_SOURCE = "selfStudy"


class StudentAssignmentNotFoundError(LookupError):
    pass


def sid_keys(sid: str) -> list[str]:
    key = str(sid or "").strip()
    keys = [key]
    if key.isdigit():
        numeric = str(int(key))
        if numeric not in keys:
            keys.append(numeric)
    return [item for item in keys if item]


def sid_lookup(mapping: dict, sid: str):
    if not isinstance(mapping, dict):
        return None
    for key in sid_keys(sid):
        if key in mapping:
            return mapping.get(key)
    return None


def write_sid_mapping(mapping: dict, sid: str, value) -> None:
    key = str(sid or "").strip()
    if not key:
        return
    numeric_key = str(int(key)) if key.isdigit() else None
    if numeric_key and numeric_key != key:
        mapping.pop(numeric_key, None)
    if value is None:
        mapping.pop(key, None)
    else:
        mapping[key] = value


def normalize_video_assign_list(value) -> list[str]:
    if isinstance(value, dict):
        value = value.get("videos")
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        mid = str(item or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        normalized.append(mid)
    return normalized


def is_manual_video_assignment(value) -> bool:
    if not isinstance(value, dict):
        return False
    source = str(value.get("source") or "").strip().lower()
    return (
        source in {"manual", "selfstudy"}
        or value.get("manual") is True
        or value.get("manualVideoAssign") is True
    )


def merge_update_assignment(current, incoming):
    if incoming is None:
        return current

    videos = normalize_video_assign_list(incoming)
    if isinstance(incoming, list):
        return videos

    if isinstance(incoming, dict):
        if incoming.get("remove") is True:
            return None
        merged = dict(current) if isinstance(current, dict) else {}
        for key, value in incoming.items():
            if key == "remove":
                continue
            if key == "videos":
                merged["videos"] = videos
            elif value is not None:
                merged[str(key)] = value
        return merged if merged else (videos if videos else current)

    return current


def remove_future_auto_assignments(updates: dict, *, today: str) -> dict:
    """Remove only identifiable future ``source:auto`` snapshots in place."""
    cutoff = dt.date.fromisoformat(str(today or "").strip())
    affected_dates: list[str] = []
    removed = 0
    preserved = {
        "manual": 0,
        "selfStudy": 0,
        "legacyArray": 0,
        "other": 0,
    }

    if not isinstance(updates, dict):
        return {
            "today": cutoff.isoformat(),
            "removedAuto": 0,
            "affectedDates": [],
            "preservedFuture": preserved,
        }

    for raw_date in list(updates):
        try:
            date_key = dt.date.fromisoformat(str(raw_date or "").strip())
        except ValueError:
            continue
        if date_key <= cutoff:
            continue

        day = updates.get(raw_date)
        if not isinstance(day, dict):
            preserved["other"] += 1
            continue

        date_removed = 0
        for sid in list(day):
            entry = day.get(sid)
            if isinstance(entry, list):
                preserved["legacyArray"] += 1
                continue
            if not isinstance(entry, dict):
                preserved["other"] += 1
                continue

            source = str(entry.get("source") or "").strip().casefold()
            if source == "auto":
                day.pop(sid, None)
                removed += 1
                date_removed += 1
            elif source == "manual":
                preserved["manual"] += 1
            elif source == "selfstudy":
                preserved["selfStudy"] += 1
            else:
                preserved["other"] += 1

        if date_removed:
            affected_dates.append(date_key.isoformat())
        if not day:
            updates.pop(raw_date, None)

    return {
        "today": cutoff.isoformat(),
        "removedAuto": removed,
        "affectedDates": sorted(set(affected_dates)),
        "preservedFuture": preserved,
    }


def stable_json(value) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except Exception:
        return ""


__all__ = (
    "SELF_STUDY_VIDEO_ASSIGN_SOURCE",
    "StudentAssignmentNotFoundError",
    "is_manual_video_assignment",
    "merge_update_assignment",
    "normalize_video_assign_list",
    "remove_future_auto_assignments",
    "sid_keys",
    "sid_lookup",
    "stable_json",
    "write_sid_mapping",
)
