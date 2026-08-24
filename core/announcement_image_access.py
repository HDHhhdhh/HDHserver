from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

from core.storage import file_lock, load
from core.student_board_projection import student_board_announcement_visible


ANNOUNCEMENT_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
)


def normalize_announcement_image_path(raw: Any) -> str:
    """Return one canonical stored announcement path or an empty string."""
    if isinstance(raw, dict):
        url = str(raw.get("url") or "").strip().replace("\\", "/")
        path = str(raw.get("path") or "").strip().replace("\\", "/").lstrip("/")
    else:
        url = ""
        path = str(raw or "").strip().replace("\\", "/").lstrip("/")

    if url.startswith("/files/"):
        path = url.split("/files/", 1)[1].lstrip("/")
    if not path.startswith("announcements/"):
        return ""

    pure = pathlib.PurePosixPath(path)
    if ".." in pure.parts or pure.suffix.lower() not in ANNOUNCEMENT_IMAGE_EXTENSIONS:
        return ""
    return path


def _stored_image_path(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    # Preserve the existing announcement payload validation behavior.
    int(raw.get("size") or 0)
    return normalize_announcement_image_path(raw)


def announcement_image_paths(announcement: dict[str, Any]) -> tuple[str, ...]:
    """Project the same first-ten, deduplicated image membership used by notices."""
    if not isinstance(announcement, dict):
        return ()

    raw_images = announcement.get("images")
    candidates = raw_images if isinstance(raw_images, list) else []
    normalized = [
        path
        for value in candidates
        for path in [_stored_image_path(value)]
        if path
    ]
    if not normalized:
        fallback = _stored_image_path(announcement.get("image"))
        if fallback:
            normalized.append(fallback)

    result: list[str] = []
    seen: set[str] = set()
    for path in normalized[:10]:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return tuple(result)


def student_can_access_announcement_image(
    announcements: Any,
    sid: str,
    image_path: str,
    now: dt.datetime,
) -> bool:
    """Authorize only an image on a notice currently visible to this student."""
    requested = normalize_announcement_image_path(image_path)
    if not requested or not isinstance(announcements, list):
        return False

    for announcement in announcements:
        if not isinstance(announcement, dict):
            continue
        if not student_board_announcement_visible(announcement, str(sid), now):
            continue
        if requested in announcement_image_paths(announcement):
            return True
    return False


def student_can_access_announcement_image_from_store(
    announcements_path,
    sid: str,
    image_path: str,
    *,
    now: dt.datetime | None = None,
) -> bool:
    """Read one locked announcement snapshot and apply the pure access rule."""
    checked_at = now or dt.datetime.now(dt.timezone.utc)
    with file_lock(announcements_path):
        announcements = load(announcements_path)
    return student_can_access_announcement_image(
        announcements,
        sid,
        image_path,
        checked_at,
    )


__all__ = (
    "ANNOUNCEMENT_IMAGE_EXTENSIONS",
    "announcement_image_paths",
    "normalize_announcement_image_path",
    "student_can_access_announcement_image",
    "student_can_access_announcement_image_from_store",
)
