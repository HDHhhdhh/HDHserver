"""Pure student curriculum-video progress projection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final


BASIS: Final = "curriculum_videos_v1"
SCOPE_EXACT: Final = "curriculum_subcurriculum"
SCOPE_FALLBACK: Final = "curriculum_fallback"
SCOPE_NONE: Final = "none"
COMPLETED_STATUSES: Final = frozenset({"done", "skip"})


def _text(value: object) -> str:
    return str(value or "").strip()


def _catalog_mids(
    videos: Iterable[object],
    *,
    curriculum: str,
    sub_curriculum: str | None,
) -> list[str]:
    mids: list[str] = []
    seen: set[str] = set()
    for raw in videos:
        if not isinstance(raw, Mapping):
            continue
        if _text(raw.get("curriculum")) != curriculum:
            continue
        if sub_curriculum is not None and _text(raw.get("subCurriculum")) != sub_curriculum:
            continue
        mid = _text(raw.get("mid"))
        if not mid or mid in seen:
            continue
        seen.add(mid)
        mids.append(mid)
    return mids


def _latest_statuses(source: object) -> dict[str, str]:
    if not isinstance(source, Mapping):
        return {}
    statuses: dict[str, str] = {}
    for raw_mid, raw_status in source.items():
        mid = _text(raw_mid)
        if not mid or mid == "tests" or mid.startswith("__"):
            continue
        if isinstance(raw_status, Mapping):
            raw_status = raw_status.get("status")
        statuses[mid] = _text(raw_status)
    return statuses


def build_curriculum_progress(
    student: object,
    videos: Iterable[object],
    latest_status_by_mid: object,
    *,
    calculated_at: str,
) -> dict[str, object]:
    """Build a deterministic, SID-free curriculum progress summary."""
    student_map = student if isinstance(student, Mapping) else {}
    curriculum = _text(student_map.get("curriculum"))
    sub_curriculum = _text(student_map.get("subCurriculum"))
    catalog = tuple(videos) if isinstance(videos, Iterable) and not isinstance(videos, (str, bytes, Mapping)) else ()

    scope = SCOPE_NONE
    mids: list[str] = []
    if curriculum:
        mids = _catalog_mids(
            catalog,
            curriculum=curriculum,
            sub_curriculum=sub_curriculum,
        )
        if mids:
            scope = SCOPE_EXACT
        else:
            mids = _catalog_mids(catalog, curriculum=curriculum, sub_curriculum=None)
            scope = SCOPE_FALLBACK if mids else SCOPE_NONE

    statuses = _latest_statuses(latest_status_by_mid)
    completed = sum(statuses.get(mid) in COMPLETED_STATUSES for mid in mids)
    interrupted = sum(statuses.get(mid) == "interrupted" for mid in mids)
    total = len(mids)
    percent = (completed * 100 + total // 2) // total if total else None

    return {
        "basis": BASIS,
        "scope": scope,
        "curriculum": curriculum,
        "subCurriculum": sub_curriculum,
        "completed": completed,
        "interrupted": interrupted,
        "total": total,
        "percent": percent,
        "state": "available" if total else "unavailable",
        "calculatedAt": _text(calculated_at),
    }


build_student_curriculum_progress = build_curriculum_progress

__all__ = [
    "BASIS",
    "build_curriculum_progress",
    "build_student_curriculum_progress",
]
