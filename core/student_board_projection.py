"""Pure student-safe projection and pagination for the mobile board."""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import mimetypes
import pathlib
import re
from typing import Any

from .student_notification_events import deterministic_event_id


BOARD_TYPES = frozenset({"all", "notice", "video"})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MID_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})
_HIDDEN_STATES = frozenset({"draft", "deleted", "closed", "inactive"})
_TTL = dt.timedelta(hours=4)


class BoardInputError(ValueError):
    """Typed invalid public-board input."""

    def __init__(self, code: str = "invalid_request") -> None:
        super().__init__(code)
        self.code = code


def _parse_time(value: object) -> dt.datetime | None:
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _safe_image(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    path = _safe_text(raw.get("path"), 512).replace("\\", "/").lstrip("/")
    url = _safe_text(raw.get("url"), 512).replace("\\", "/")
    if url.startswith("/files/"):
        path = url.removeprefix("/files/").lstrip("/")
    pure = pathlib.PurePosixPath(path)
    if not path.startswith("announcements/") or ".." in pure.parts:
        return None
    if pure.suffix.lower() not in _IMAGE_EXTS or not pure.name:
        return None
    mime = mimetypes.guess_type(pure.name)[0] or "application/octet-stream"
    return {"url": f"/files/{path}", "mime": mime}


def _safe_images(announcement: dict[str, Any]) -> list[dict[str, str]]:
    raw = announcement.get("images")
    candidates = raw if isinstance(raw, list) else []
    if not candidates:
        candidates = [announcement.get("image")]
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in candidates[:10]:
        image = _safe_image(value)
        if image is None or image["url"] in seen:
            continue
        seen.add(image["url"])
        result.append(image)
    return result


def student_board_announcement_visible(announcement: dict[str, Any], sid: str, now: dt.datetime) -> bool:
    if announcement.get("deleted") is True or announcement.get("_deleted") is True:
        return False
    if announcement.get("draft") is True or announcement.get("published") is False:
        return False
    if _safe_text(announcement.get("deletedAt"), 80):
        return False
    if _safe_text(announcement.get("status"), 32).lower() in _HIDDEN_STATES:
        return False
    targets = announcement.get("targetSids")
    if not isinstance(targets, list) or sid not in {value for value in targets if isinstance(value, str)}:
        return False
    created = _parse_time(announcement.get("createdAt"))
    if created is None or created > now:
        return False
    expires = _parse_time(announcement.get("expiresAt")) or created + _TTL
    if expires <= now:
        return False
    survey = announcement.get("survey")
    kind = _safe_text(announcement.get("kind"), 32).lower() or ("survey" if survey is not None else "announcement")
    if kind == "survey" or survey is not None:
        return (
            isinstance(survey, dict)
            and _safe_text(survey.get("status"), 32).lower() == "public"
            and isinstance(survey.get("questions"), list)
            and bool(survey.get("questions"))
        )
    return kind in {"announcement", "video"}


def _catalog_mids(videos: object) -> set[str]:
    if not isinstance(videos, list):
        return set()
    return {
        value for row in videos if isinstance(row, dict)
        for value in [_safe_text(row.get("mid"), 128)]
        if _MID_RE.fullmatch(value)
    }


def _encode_cursor(board_type: str, item: dict[str, Any]) -> str:
    payload = {"v": 1, "type": board_type, "createdAt": item["createdAt"], "id": item["id"]}
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: object, board_type: str) -> tuple[str, str] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 1024 or not value:
        raise BoardInputError("invalid_cursor")
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeError, json.JSONDecodeError, binascii.Error):
        raise BoardInputError("invalid_cursor") from None
    if not isinstance(payload, dict) or set(payload) != {"v", "type", "createdAt", "id"}:
        raise BoardInputError("invalid_cursor")
    created = _parse_time(payload.get("createdAt"))
    item_id = _safe_text(payload.get("id"), 128)
    if payload.get("v") != 1 or payload.get("type") != board_type:
        raise BoardInputError("invalid_cursor")
    if created is None or _iso(created) != payload.get("createdAt") or not _ID_RE.fullmatch(item_id):
        raise BoardInputError("invalid_cursor")
    return payload["createdAt"], item_id


def project_student_board(
    announcements: object,
    status: object,
    videos: object,
    *,
    sid: str,
    now: dt.datetime,
    board_type: str = "all",
    cursor: str | None = None,
    page_size: int = 50,
    academy_allowed: bool = False,
) -> dict[str, Any]:
    """Return a strict SID-scoped board page without playback authority."""
    if board_type not in BOARD_TYPES or not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise BoardInputError()
    if not isinstance(sid, str) or not sid or page_size < 1 or page_size > 50:
        raise BoardInputError()
    after = _decode_cursor(cursor, board_type)
    mids = _catalog_mids(videos)
    sid_status = status.get(sid, {}) if isinstance(status, dict) else {}
    if not isinstance(sid_status, dict):
        sid_status = {}
    rows: list[dict[str, Any]] = []
    source = announcements if isinstance(announcements, list) else []
    for announcement in source:
        if not isinstance(announcement, dict) or not student_board_announcement_visible(announcement, sid, now):
            continue
        item_id = _safe_text(announcement.get("id"), 128)
        kind = _safe_text(announcement.get("kind"), 32).lower() or ("survey" if announcement.get("survey") is not None else "announcement")
        if not _ID_RE.fullmatch(item_id):
            continue
        item_type = "video" if kind == "video" else "notice"
        if board_type != "all" and board_type != item_type:
            continue
        created = _parse_time(announcement.get("createdAt"))
        expires = _parse_time(announcement.get("expiresAt")) or created + _TTL
        images = _safe_images(announcement)
        entry = sid_status.get(item_id, {})
        read = isinstance(entry, dict) and bool(entry.get("acked") or entry.get("readAt"))
        common = {
            "id": item_id,
            "type": item_type,
            "kind": kind,
            "title": _safe_text(announcement.get("title"), 400) or ("영상" if item_type == "video" else "공지"),
            "content": _safe_text(announcement.get("content"), 10000),
            "createdAt": _iso(created),
            "expiresAt": _iso(expires),
            "read": read,
            "notificationEventId": deterministic_event_id("announcement_published", item_id),
        }
        if item_type == "video":
            mid = _safe_text(announcement.get("videoMid"), 128)
            if not _MID_RE.fullmatch(mid) or mid not in mids:
                continue
            common.update({"thumbnail": images[0]["url"] if images else None, "videoMid": mid, "locked": not academy_allowed})
        else:
            common.update({"images": images, "requireCompletion": bool(announcement.get("requireCompletion", True))})
        rows.append(common)
    rows.sort(key=lambda item: (item["createdAt"], item["id"]), reverse=True)
    if after is not None:
        try:
            start = next(index for index, item in enumerate(rows) if (item["createdAt"], item["id"]) == after) + 1
        except StopIteration:
            raise BoardInputError("invalid_cursor") from None
        rows = rows[start:]
    page = rows[:page_size]
    next_cursor = _encode_cursor(board_type, page[-1]) if len(rows) > page_size else None
    return {"ok": True, "type": board_type, "items": page, "nextCursor": next_cursor}


__all__ = (
    "BOARD_TYPES",
    "BoardInputError",
    "project_student_board",
    "student_board_announcement_visible",
)
