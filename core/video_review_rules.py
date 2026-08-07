from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Final, Literal, TypeAlias, TypedDict

from core.progress_rules import watch_auto_status


JsonValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | Mapping[str, "JsonValue"]
    | list["JsonValue"]
)
ReviewStatus: TypeAlias = Literal["done", "interrupted"]
ProgressStatus: TypeAlias = Literal["", "done", "interrupted", "none", "skip"]


class ReviewState(TypedDict):
    status: ReviewStatus
    eventDate: str


ReviewStates: TypeAlias = dict[str, ReviewState]

MANUAL_META_KEY: Final = "__manualProgressMids"
_CLEAR_STATUSES: Final = frozenset({"", "none", "skip"})


def _parse_date(raw: str) -> date | None:
    if len(raw) != 10 or raw[4] != "-" or raw[7] != "-":
        return None
    if not raw[:4].isdigit() or not raw[5:7].isdigit() or not raw[8:].isdigit():
        return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == raw else None


def _valid_dates(source: Mapping[str, JsonValue], cutoff: date) -> set[date]:
    dates: set[date] = set()
    for raw_key in source:
        if not isinstance(raw_key, str) or raw_key.startswith("__"):
            continue
        parsed = _parse_date(raw_key)
        if parsed is not None and parsed < cutoff:
            dates.add(parsed)
    return dates


def _as_mapping(value: JsonValue | None) -> Mapping[str, JsonValue] | None:
    return value if isinstance(value, Mapping) else None


def _sid_map(day: JsonValue | None, sid_keys: tuple[str, ...]) -> Mapping[str, JsonValue] | None:
    day_map = _as_mapping(day)
    if day_map is None:
        return None
    for sid in sid_keys:
        candidate = _as_mapping(day_map.get(sid))
        if candidate is not None:
            return candidate
    return None


def _normalize_progress_status(value: JsonValue) -> ProgressStatus | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized in ("", "done", "interrupted", "none", "skip") else None


def _as_review_status(value: str) -> ReviewStatus | None:
    statuses: Mapping[str, ReviewStatus] = {"done": "done", "interrupted": "interrupted"}
    return statuses.get(value)


def _truthy(value: JsonValue) -> bool:
    return bool(value)


def _review_watch_status(value: JsonValue) -> str:
    if not isinstance(value, Mapping):
        return ""

    safe_entry: dict[str, JsonValue] = {
        key: value[key]
        for key in ("last", "dur", "updatedAt")
        if key in value
    }
    safe_entry["completed"] = value.get("completed") is True
    return watch_auto_status(safe_entry)


def resolve_video_review_states_before_date(
    progress: Mapping[str, JsonValue],
    watch: Mapping[str, JsonValue],
    *,
    sid_keys: Iterable[str],
    before_date: str,
) -> ReviewStates:
    """Resolve latest done/interrupted video states strictly before ``before_date``.

    Progress entries are authoritative for their date. Watch entries are considered
    only when that date has no progress entry for the same MID. Manual metadata
    keeps a white/skip override authoritative across later watch-only dates.
    """
    cutoff = _parse_date(before_date)
    if cutoff is None or not isinstance(progress, Mapping) or not isinstance(watch, Mapping):
        return {}

    aliases = tuple(dict.fromkeys(str(sid).strip() for sid in sid_keys if str(sid).strip()))
    if not aliases:
        return {}

    event_dates = _valid_dates(progress, cutoff) | _valid_dates(watch, cutoff)
    states: ReviewStates = {}
    manual_overrides: set[str] = set()

    for event_date in sorted(event_dates):
        date_key = event_date.isoformat()
        progress_map = _sid_map(progress.get(date_key), aliases)
        watch_map = _sid_map(watch.get(date_key), aliases)
        progress_presence: set[str] = set()
        progress_entries: list[tuple[str, JsonValue]] = []
        manual_mids: set[str] = set()

        if progress_map is not None:
            metadata = _as_mapping(progress_map.get(MANUAL_META_KEY))
            if metadata is not None:
                for raw_mid, marker in metadata.items():
                    mid = str(raw_mid).strip()
                    if mid and _truthy(marker):
                        manual_mids.add(mid)
            for raw_mid, value in progress_map.items():
                mid = str(raw_mid).strip()
                if not mid or mid == "tests" or mid.startswith("__"):
                    continue
                progress_presence.add(mid)
                progress_entries.append((mid, value))

        manual_overrides.update(manual_mids)
        for mid, raw_status in progress_entries:
            status = _normalize_progress_status(raw_status)
            manual_overrides.discard(mid)
            if mid in manual_mids:
                manual_overrides.add(mid)
            review_status = _as_review_status(status) if status is not None else None
            if review_status is not None:
                states[mid] = {"status": review_status, "eventDate": date_key}
            elif status in _CLEAR_STATUSES or status is None:
                states.pop(mid, None)

        if watch_map is not None:
            for raw_mid, entry in watch_map.items():
                mid = str(raw_mid).strip()
                if not mid or mid == "tests" or mid.startswith("__"):
                    continue
                if mid in progress_presence or mid in manual_overrides:
                    continue
                review_status = _as_review_status(_review_watch_status(entry))
                if review_status is not None:
                    states[mid] = {"status": review_status, "eventDate": date_key}

    return states
