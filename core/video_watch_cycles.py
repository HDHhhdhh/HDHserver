"""Pure, date/SID/MID-scoped fresh-watch generations for explicit reassignment."""
from __future__ import annotations

from copy import deepcopy
import re

from core.progress_rules import (
    PROGRESS_ALL_STUDENTS_META_KEY, PROGRESS_MANUAL_META_KEY,
    WATCH_AUTO_PROGRESS_META_KEY, normalize_watch_entry, watch_rank,
)
from core.update_assignment_rules import sid_keys


VIDEO_WATCH_CYCLES_KEY = "__videoWatchCycles"
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class WatchCycleConflict(ValueError):
    pass


def validate_watch_rearms(value, source: str) -> dict:
    if not isinstance(value, dict) or (value and source not in ("", "manual")):
        raise ValueError("bad resumeAutoWatch")
    for mid, command in value.items():
        if (not isinstance(mid, str) or not mid.strip() or mid != mid.strip()
                or mid.startswith("__") or mid == "tests" or not isinstance(command, dict)
                or set(command) != {"token", "baseToken"}
                or not isinstance(command["token"], str) or not _TOKEN.fullmatch(command["token"])
                or not isinstance(command["baseToken"], str)
                or (command["baseToken"] and not _TOKEN.fullmatch(command["baseToken"]))):
            raise ValueError("bad resumeAutoWatch")
    return value


def rearm_watch_cycles(entry: dict, commands: dict, now_ms: int) -> dict:
    out = deepcopy(entry)
    cycles = out.setdefault(VIDEO_WATCH_CYCLES_KEY, {})
    for mid, command in commands.items():
        previous = cycles.get(mid, {})
        token = previous.get("token", "")
        if token == command["token"]:
            continue  # Lost-response retries must not reset already received watch.
        if token != command["baseToken"]:
            raise WatchCycleConflict("영상 재배정 상태가 변경됐습니다. 팝업을 다시 열어 주세요.")
        cycles[mid] = {
            "token": command["token"], "startedAt": now_ms,
            "watch": normalize_watch_entry({"updatedAt": now_ms}),
        }
        out[mid] = "none"
        for key in (PROGRESS_MANUAL_META_KEY, PROGRESS_ALL_STUDENTS_META_KEY):
            meta = out.get(key)
            if isinstance(meta, dict):
                meta.pop(mid, None)
                if not meta:
                    out.pop(key, None)
        out.setdefault(WATCH_AUTO_PROGRESS_META_KEY, {})[mid] = "none"
    return out


def latest_watch_cycles(progress: dict, sid: str, through_date: str) -> dict:
    out = {}
    for date in sorted(progress if isinstance(progress, dict) else {}):
        if date > through_date:
            continue
        day = progress.get(date)
        if not isinstance(day, dict):
            continue
        entry = next((day[key] for key in sid_keys(sid) if isinstance(day.get(key), dict)), {})
        cycles = entry.get(VIDEO_WATCH_CYCLES_KEY)
        if isinstance(cycles, dict):
            for mid, cycle in cycles.items():
                if isinstance(cycle, dict) and cycle.get("token"):
                    out[mid] = cycle
    return out


def cycle_watch_record(cycle: dict) -> dict:
    return {**normalize_watch_entry(cycle.get("watch")), "cycleToken": cycle["token"]}


def latest_watch_projection(watch: dict, progress: dict, sid: str, through_date: str, *, date: str = "") -> dict:
    out = {}
    for day_key, day in (watch.items() if isinstance(watch, dict) else []):
        if (date and day_key != date) or day_key > through_date or not isinstance(day, dict):
            continue
        entries = next((day[key] for key in sid_keys(sid) if isinstance(day.get(key), dict)), {})
        for mid, entry in entries.items():
            mid = str(mid or "").strip()
            if not mid:
                continue
            normalized = normalize_watch_entry(entry)
            if mid not in out or watch_rank(normalized) > watch_rank(out[mid]):
                out[mid] = normalized
    for mid, cycle in latest_watch_cycles(progress, sid, through_date).items():
        out[mid] = cycle_watch_record(cycle)
    return out
