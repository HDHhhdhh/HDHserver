from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qs, urlparse

from core.progress_rules import (
    PROGRESS_ALL_STUDENTS_META_KEY,
    PROGRESS_MANUAL_META_KEY,
    WATCH_AUTO_PROGRESS_META_KEY,
    merge_watch_entry,
)


DRAFT_KIND = "academy-video-catalog-correction"
DRAFT_SCHEMA_VERSION = 1
_PROGRESS_META_KEYS = (
    PROGRESS_MANUAL_META_KEY,
    WATCH_AUTO_PROGRESS_META_KEY,
    PROGRESS_ALL_STUDENTS_META_KEY,
)
_WATCH_FIELDS = frozenset({"last", "dur", "completed", "updatedAt"})
_MID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class CorrectionValidationError(ValueError):
    pass


class StaleCorrectionDraft(CorrectionValidationError):
    pass


class UnsafeVideoDeletion(CorrectionValidationError):
    def __init__(self, references: dict[str, dict[str, int]]):
        self.references = references
        mids = ", ".join(sorted(references))
        super().__init__(f"referenced video deletion is not allowed: {mids}")


def extract_kollus_mid(url: Any) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    host = str(parsed.hostname or "").lower()
    if host != "kollus.com" and not host.endswith(".kollus.com"):
        return ""
    query = parse_qs(parsed.query or "", keep_blank_values=False)
    for key in ("mid", "m", "media_content_key", "MEDIA_CONTENT_KEY", "content_key"):
        values = query.get(key)
        if not values:
            continue
        candidate = str(values[0] or "").strip()
        if _MID_RE.fullmatch(candidate):
            return candidate
    for part in reversed([part for part in (parsed.path or "").split("/") if part]):
        candidate = str(part or "").strip()
        if _MID_RE.fullmatch(candidate):
            return candidate
    return ""


def _catalog_by_id(rows: Any, label: str) -> tuple[dict[str, dict], dict[str, str]]:
    if not isinstance(rows, list):
        raise CorrectionValidationError(f"{label} must be an array")
    by_id: dict[str, dict] = {}
    mid_owner: dict[str, str] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise CorrectionValidationError(f"{label} row {index + 1} must be an object")
        row_id = str(raw.get("id") or "").strip()
        if not row_id or not row_id.isdigit() or int(row_id) <= 0:
            raise CorrectionValidationError(f"{label} row {index + 1} has an invalid stable id")
        if row_id in by_id:
            raise CorrectionValidationError(f"{label} has duplicate id: {row_id}")
        mid = str(raw.get("mid") or "").strip()
        if not _MID_RE.fullmatch(mid):
            raise CorrectionValidationError(f"{label} id {row_id} has an invalid MID")
        if mid in mid_owner:
            raise CorrectionValidationError(
                f"{label} has duplicate MID {mid} on ids {mid_owner[mid]} and {row_id}"
            )
        url_mid = extract_kollus_mid(raw.get("url"))
        if url_mid != mid:
            raise CorrectionValidationError(f"{label} id {row_id} URL does not resolve to MID {mid}")
        by_id[row_id] = raw
        mid_owner[mid] = row_id
    return by_id, mid_owner


def _identity_summary(base_videos: list, next_videos: list) -> dict[str, Any]:
    base_by_id, base_mid_owner = _catalog_by_id(base_videos, "baseVideos")
    next_by_id, next_mid_owner = _catalog_by_id(next_videos, "nextVideos")
    removed_ids = [row_id for row_id in base_by_id if row_id not in next_by_id]
    new_ids = [row_id for row_id in next_by_id if row_id not in base_by_id]
    mid_changes = []
    replacements: dict[str, str] = {}
    modified_ids = []
    for row_id, base_row in base_by_id.items():
        next_row = next_by_id.get(row_id)
        if next_row is None:
            continue
        if base_row != next_row:
            modified_ids.append(row_id)
        old_mid = str(base_row["mid"])
        new_mid = str(next_row["mid"])
        if old_mid != new_mid:
            replacements[old_mid] = new_mid
            mid_changes.append({"id": row_id, "oldMid": old_mid, "newMid": new_mid})

    for row_id in removed_ids:
        removed_mid = str(base_by_id[row_id]["mid"])
        replacement_owner = next_mid_owner.get(removed_mid)
        if replacement_owner is not None:
            raise CorrectionValidationError(
                f"removed MID {removed_mid} is reused by target id {replacement_owner}"
            )

    return {
        "baseById": base_by_id,
        "nextById": next_by_id,
        "baseMidOwner": base_mid_owner,
        "nextMidOwner": next_mid_owner,
        "removedIds": removed_ids,
        "newIds": new_ids,
        "modifiedIds": modified_ids,
        "midChanges": mid_changes,
        "replacements": replacements,
    }


def build_correction_draft(base_videos: Any, next_videos: Any, *, created_at: str) -> dict[str, Any]:
    created = str(created_at or "").strip()
    if not created:
        raise CorrectionValidationError("createdAt is required")
    base = deepcopy(base_videos)
    target = deepcopy(next_videos)
    _identity_summary(base, target)
    return {
        "kind": DRAFT_KIND,
        "schemaVersion": DRAFT_SCHEMA_VERSION,
        "createdAt": created,
        "baseVideos": base,
        "nextVideos": target,
    }


def validate_correction_draft(draft: Any) -> dict[str, Any]:
    if not isinstance(draft, dict):
        raise CorrectionValidationError("correction draft must be an object")
    if draft.get("kind") != DRAFT_KIND:
        raise CorrectionValidationError("unexpected correction draft kind")
    if draft.get("schemaVersion") != DRAFT_SCHEMA_VERSION:
        raise CorrectionValidationError("unsupported correction draft schemaVersion")
    if not str(draft.get("createdAt") or "").strip():
        raise CorrectionValidationError("correction draft createdAt is required")
    _identity_summary(draft.get("baseVideos"), draft.get("nextVideos"))
    return deepcopy(draft)


def _empty_reference_counts() -> dict[str, int]:
    return {
        "updates": 0,
        "progressStatuses": 0,
        "progressMetadata": 0,
        "watch": 0,
    }


def _reference_counts(updates: dict, progress: dict, watch: dict, mids: set[str]) -> dict[str, dict[str, int]]:
    counts = {mid: _empty_reference_counts() for mid in mids}
    for by_day in updates.values():
        if not isinstance(by_day, dict):
            continue
        for raw in by_day.values():
            values = raw if isinstance(raw, list) else raw.get("videos") if isinstance(raw, dict) else None
            if not isinstance(values, list):
                continue
            for value in values:
                key = str(value)
                if key in counts:
                    counts[key]["updates"] += 1

    for by_day in progress.values():
        if not isinstance(by_day, dict):
            continue
        for per_sid in by_day.values():
            if not isinstance(per_sid, dict):
                continue
            for key in per_sid:
                key_s = str(key)
                if key_s in counts:
                    counts[key_s]["progressStatuses"] += 1
            for meta_key in _PROGRESS_META_KEYS:
                meta = per_sid.get(meta_key)
                if not isinstance(meta, dict):
                    continue
                for key in meta:
                    key_s = str(key)
                    if key_s in counts:
                        counts[key_s]["progressMetadata"] += 1

    for by_day in watch.values():
        if not isinstance(by_day, dict):
            continue
        for per_sid in by_day.values():
            if not isinstance(per_sid, dict):
                continue
            for key in per_sid:
                key_s = str(key)
                if key_s in counts:
                    counts[key_s]["watch"] += 1
    return counts


def _replace_mid_list(values: list, replacements: dict[str, str]) -> list:
    if not any(str(value) in replacements for value in values):
        return deepcopy(values)
    mapped = [replacements.get(str(value), value) for value in values]
    out = []
    seen: set[str] = set()
    for value in mapped:
        marker = str(value)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(value)
    return out


def _replace_updates(data: dict, replacements: dict[str, str]) -> dict:
    out = deepcopy(data)
    for by_day in out.values():
        if not isinstance(by_day, dict):
            continue
        for sid, raw in list(by_day.items()):
            if isinstance(raw, list):
                by_day[sid] = _replace_mid_list(raw, replacements)
            elif isinstance(raw, dict) and isinstance(raw.get("videos"), list):
                next_raw = dict(raw)
                next_raw["videos"] = _replace_mid_list(raw["videos"], replacements)
                by_day[sid] = next_raw
    return out


def _progress_rank(status: Any) -> int:
    return {"done": 3, "interrupted": 2, "skip": 1}.get(str(status or "").strip(), 0)


def _higher_progress_status(left: Any, right: Any) -> str:
    a = str(left or "").strip()
    b = str(right or "").strip()
    return a if _progress_rank(a) >= _progress_rank(b) else b


def _remap_bool_meta(raw: Any, replacements: dict[str, str], affected: set[str]) -> dict:
    source = dict(raw) if isinstance(raw, dict) else {}
    out = {str(key): deepcopy(value) for key, value in source.items() if str(key) not in affected}
    for key, value in source.items():
        key_s = str(key)
        if key_s in affected and value:
            out[replacements.get(key_s, key_s)] = True
    return out


def _remap_auto_meta(raw: Any, replacements: dict[str, str], affected: set[str]) -> dict:
    source = dict(raw) if isinstance(raw, dict) else {}
    out = {str(key): deepcopy(value) for key, value in source.items() if str(key) not in affected}
    grouped: dict[str, list[str]] = {}
    for key, value in source.items():
        key_s = str(key)
        if key_s in affected:
            grouped.setdefault(replacements.get(key_s, key_s), []).append(str(value or "").strip())
    for target, statuses in grouped.items():
        merged = ""
        for status in statuses:
            merged = _higher_progress_status(merged, status)
        if merged:
            out[target] = merged
    return out


def _choose_progress_status(candidates: list[dict], target: str) -> str:
    manual = [candidate for candidate in candidates if candidate["manual"]]
    if manual:
        if any(candidate["status"] == "none" for candidate in manual):
            return "none"
        existing = next((candidate for candidate in manual if candidate["source"] == target), None)
        if existing is not None:
            return existing["status"]
        candidates = manual
    merged = ""
    for candidate in candidates:
        merged = _higher_progress_status(merged, candidate["status"])
    return merged


def _replace_progress(data: dict, replacements: dict[str, str]) -> dict:
    out = deepcopy(data)
    affected = set(replacements) | set(replacements.values())
    if not affected:
        return out
    for by_day in out.values():
        if not isinstance(by_day, dict):
            continue
        for per_sid in by_day.values():
            if not isinstance(per_sid, dict):
                continue
            before = deepcopy(per_sid)
            manual_raw = before.get(PROGRESS_MANUAL_META_KEY)
            manual_raw = dict(manual_raw) if isinstance(manual_raw, dict) else {}
            auto_raw = before.get(WATCH_AUTO_PROGRESS_META_KEY)
            auto_raw = dict(auto_raw) if isinstance(auto_raw, dict) else {}
            all_raw = before.get(PROGRESS_ALL_STUDENTS_META_KEY)
            all_raw = dict(all_raw) if isinstance(all_raw, dict) else {}
            grouped: dict[str, list[dict]] = {}
            for key, value in before.items():
                key_s = str(key)
                if key_s not in affected or key_s == "tests" or key_s.startswith("__"):
                    continue
                target = replacements.get(key_s, key_s)
                grouped.setdefault(target, []).append({
                    "source": key_s,
                    "status": str(value or "").strip(),
                    "manual": bool(manual_raw.get(key_s) or all_raw.get(key_s)),
                })
                per_sid.pop(key, None)

            manual_meta = _remap_bool_meta(manual_raw, replacements, affected)
            auto_meta = _remap_auto_meta(auto_raw, replacements, affected)
            all_meta = _remap_bool_meta(all_raw, replacements, affected)
            for target, candidates in grouped.items():
                status = _choose_progress_status(candidates, target)
                if status:
                    per_sid[target] = status
                else:
                    per_sid.pop(target, None)
                if any(candidate["manual"] for candidate in candidates):
                    manual_meta[target] = True
                if manual_meta.get(target) or all_meta.get(target):
                    manual_meta[target] = True
                    auto_meta.pop(target, None)
                elif str(auto_meta.get(target) or "").strip() != status:
                    auto_meta.pop(target, None)

            for target in affected:
                if all_meta.get(target):
                    manual_meta[target] = True
                    auto_meta.pop(target, None)
            if manual_meta:
                per_sid[PROGRESS_MANUAL_META_KEY] = manual_meta
            else:
                per_sid.pop(PROGRESS_MANUAL_META_KEY, None)
            if auto_meta:
                per_sid[WATCH_AUTO_PROGRESS_META_KEY] = auto_meta
            else:
                per_sid.pop(WATCH_AUTO_PROGRESS_META_KEY, None)
            if all_meta:
                per_sid[PROGRESS_ALL_STUDENTS_META_KEY] = all_meta
            else:
                per_sid.pop(PROGRESS_ALL_STUDENTS_META_KEY, None)
    return out


def _merge_watch_entries(entries: list[Any]) -> Any:
    if len(entries) == 1:
        return deepcopy(entries[0])
    extras: dict[str, Any] = {}
    merged: dict[str, Any] = {}
    for entry in entries:
        if isinstance(entry, dict):
            for key, value in entry.items():
                if key not in _WATCH_FIELDS:
                    extras[key] = deepcopy(value)
        merged = merge_watch_entry(merged, entry)
    return {**extras, **merged}


def _replace_watch(data: dict, replacements: dict[str, str]) -> dict:
    out = deepcopy(data)
    affected = set(replacements) | set(replacements.values())
    if not affected:
        return out
    for by_day in out.values():
        if not isinstance(by_day, dict):
            continue
        for per_sid in by_day.values():
            if not isinstance(per_sid, dict):
                continue
            before = deepcopy(per_sid)
            grouped: dict[str, list[Any]] = {}
            for key, value in before.items():
                key_s = str(key)
                if key_s not in affected:
                    continue
                grouped.setdefault(replacements.get(key_s, key_s), []).append(value)
                per_sid.pop(key, None)
            for target, entries in grouped.items():
                per_sid[target] = _merge_watch_entries(entries)
    return out


def apply_video_catalog_correction(
    *,
    current_videos: Any,
    draft: Any,
    updates: Any,
    progress: Any,
    watch: Any,
) -> dict[str, Any]:
    validated = validate_correction_draft(draft)
    base_videos = validated["baseVideos"]
    next_videos = validated["nextVideos"]
    if current_videos != base_videos:
        raise StaleCorrectionDraft("live videos.json changed after the correction draft was created")
    for label, value in (("updates", updates), ("progress", progress), ("watch", watch)):
        if not isinstance(value, dict):
            raise CorrectionValidationError(f"{label}.json must be an object")

    summary = _identity_summary(base_videos, next_videos)
    replacements = summary["replacements"]
    removed_mids = {
        str(summary["baseById"][row_id]["mid"])
        for row_id in summary["removedIds"]
    }
    affected_old_mids = set(replacements) | removed_mids
    references = _reference_counts(updates, progress, watch, affected_old_mids)
    unsafe_deletions = {
        mid: counts
        for mid, counts in references.items()
        if mid in removed_mids and any(counts.values())
    }
    if unsafe_deletions:
        raise UnsafeVideoDeletion(unsafe_deletions)

    totals = _empty_reference_counts()
    for counts in references.values():
        for key, value in counts.items():
            totals[key] += value
    report = {
        "replacements": deepcopy(replacements),
        "midChanges": deepcopy(summary["midChanges"]),
        "removedIds": list(summary["removedIds"]),
        "newIds": list(summary["newIds"]),
        "modifiedIds": list(summary["modifiedIds"]),
        "referencesByMid": references,
        "referenceTotals": totals,
    }
    return {
        "videos": deepcopy(next_videos),
        "updates": _replace_updates(updates, replacements),
        "progress": _replace_progress(progress, replacements),
        "watch": _replace_watch(watch, replacements),
        "report": report,
    }