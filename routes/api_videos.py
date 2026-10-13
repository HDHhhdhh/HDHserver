from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import parse_qs, urlparse

from flask import Blueprint, current_app, jsonify, make_response, request

from core.paths import VID_PATH
from core.storage import file_lock, load, save_atomic
from core.video_sources import is_youtube_mid, parse_youtube_url


bp_api_videos = Blueprint("api_videos", __name__)

VIDEO_CATALOG_IDENTITY_CHANGE_ERROR = "video_catalog_identity_change_blocked"
VIDEO_CATALOG_IDENTITY_CHANGE_MESSAGE = (
    "일반 모드에서는 기존 영상의 MID 변경 또는 삭제를 저장할 수 없습니다. "
    "기존 데이터는 변경되지 않았으며, 필요한 경우 별도 수정 모드에서 처리해야 합니다."
)


class VideoCatalogStoreError(RuntimeError):
    pass


@bp_api_videos.errorhandler(VideoCatalogStoreError)
def _video_catalog_store_error(exc):
    return jsonify({"ok": False, "error": "video_catalog_unavailable"}), 503


def _read_video_catalog():
    try:
        rows = load(VID_PATH)
        _video_catalog_rows_by_id(rows, "current video catalog")
        return rows
    except (OSError, UnicodeError, ValueError) as exc:
        raise VideoCatalogStoreError("video catalog unavailable") from exc


def _video_catalog_revision(rows) -> str:
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _video_revision_response(payload, revision: str, status: int = 200):
    response = make_response("", 204) if status == 204 else make_response(jsonify(payload), status)
    response.headers["X-Store-Revision"] = revision
    response.headers["ETag"] = f'"{revision}"'
    return response


def _video_revision_precondition(current_revision: str):
    raw = request.headers.get("If-Match")
    if raw is None:
        raw = request.headers.get("X-Store-Revision")
    revision = str(raw or "").strip()
    mode = os.environ.get("JSON_STORE_REVISION_MODE", "soft").strip().lower()
    if not revision:
        if mode == "soft":
            current_app.logger.warning("[video-catalog] unrevisioned save accepted in soft mode")
            return None
        return _video_revision_response({"ok": False, "error": "video_catalog_revision_required"}, current_revision, 428)
    if revision.startswith('"') and revision.endswith('"'):
        revision = revision[1:-1]
    if re.fullmatch(r"[0-9a-fA-F]{64}", revision) is None:
        return _video_revision_response({"ok": False, "error": "video_catalog_revision_required"}, current_revision, 428)
    if revision.lower() != current_revision:
        return _video_revision_response({"ok": False, "error": "video_catalog_revision_conflict", "message": "다른 화면에서 영상 목록이 변경됐습니다. 새로고침 후 다시 저장해 주세요."}, current_revision, 409)
    return None


def _extract_kollus_mid_from_url(url) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""

    try:
        parsed = urlparse(raw)
    except Exception:
        return ""

    host = (parsed.netloc or "").lower()
    if "kollus.com" not in host:
        return ""

    query = parse_qs(parsed.query or "", keep_blank_values=False)
    for key in ("mid", "m", "media_content_key", "MEDIA_CONTENT_KEY", "content_key"):
        vals = query.get(key)
        if not vals:
            continue
        candidate = str(vals[0] or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
            return candidate

    parts = [part for part in (parsed.path or "").split("/") if part]
    for candidate in reversed(parts):
        normalized = str(candidate or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
            return normalized

    return ""


def _normalize_video_mid_fields(videos):
    if not isinstance(videos, list):
        return videos

    normalized_videos = []
    for item in videos:
        if not isinstance(item, dict):
            normalized_videos.append(item)
            continue

        video = dict(item)
        youtube = parse_youtube_url(video.get("url"), catalog_id=video.get("id"))
        if youtube:
            video.update(youtube)
            normalized_videos.append(video)
            continue
        if video.get("provider") == "youtube" or is_youtube_mid(video.get("mid")):
            raise ValueError("YouTube 영상에는 유효한 YouTube 링크가 필요합니다.")
        parsed_mid = _extract_kollus_mid_from_url(video.get("url"))
        if parsed_mid:
            video["mid"] = parsed_mid
        elif video.get("mid") is not None:
            video["mid"] = str(video.get("mid") or "").strip()
        normalized_videos.append(video)
    seen_youtube = set()
    for video in normalized_videos:
        if not isinstance(video, dict) or video.get("provider") != "youtube":
            continue
        key = tuple(str(video.get(field) or "").strip().casefold() for field in ("curriculum", "subCurriculum")) + (video["youtubeKind"], video["youtubeId"])
        if key in seen_youtube:
            raise ValueError("같은 커리큘럼에 이미 등록된 YouTube 영상/재생목록입니다.")
        seen_youtube.add(key)
    return normalized_videos


def _video_catalog_rows_by_id(rows, label: str) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be an array")

    by_id: dict[str, dict] = {}
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            raise ValueError(f"{label} row {index + 1} must be an object")
        key = str(item.get("id") or "").strip()
        if not key:
            raise ValueError(f"{label} row {index + 1} is missing id")
        if key in by_id:
            raise ValueError(f"{label} has duplicate id: {key}")
        by_id[key] = item
    return by_id


def _video_catalog_identity_changes(previous_videos, next_videos) -> dict[str, list]:
    previous = _video_catalog_rows_by_id(previous_videos, "current video catalog")
    incoming = _video_catalog_rows_by_id(next_videos, "new video catalog")
    removed_ids = [key for key in previous if key not in incoming]
    mid_changes = []
    for key, old_item in previous.items():
        new_item = incoming.get(key)
        if new_item is None:
            continue
        old_mid = str(old_item.get("mid") or "").strip()
        new_mid = str(new_item.get("mid") or "").strip()
        if old_mid != new_mid:
            mid_changes.append({"id": key, "oldMid": old_mid, "newMid": new_mid})
    return {"removedIds": removed_ids, "midChanges": mid_changes}


@bp_api_videos.route("/api/videos", methods=["GET", "POST"])
def api_videos():
    if request.method == "GET":
        current_videos = _read_video_catalog()
        response = _video_revision_response(current_videos, _video_catalog_revision(current_videos))
        response.headers["X-Video-Providers"] = "kollus,youtube"
        return response

    try:
        next_videos = _normalize_video_mid_fields(request.get_json(force=True))
        with file_lock(VID_PATH, timeout_sec=20.0, poll_sec=0.05):
            previous_videos = _read_video_catalog()
            changes = _video_catalog_identity_changes(previous_videos, next_videos)
            if changes["removedIds"] or changes["midChanges"]:
                return jsonify({
                    "ok": False,
                    "error": VIDEO_CATALOG_IDENTITY_CHANGE_ERROR,
                    "message": VIDEO_CATALOG_IDENTITY_CHANGE_MESSAGE,
                    **changes,
                }), 409
            revision_error = _video_revision_precondition(_video_catalog_revision(previous_videos))
            if revision_error is not None:
                return revision_error
            save_atomic(VID_PATH, next_videos)
    except ValueError as exc:
        return jsonify({"ok": False, "error": "invalid_video_catalog", "message": str(exc)}), 400
    return _video_revision_response(None, _video_catalog_revision(next_videos), 204)


@bp_api_videos.get("/api/video-capabilities")
def video_capabilities():
    response = jsonify({"youtube": True, "gichulOverlay": True, "youtubeRecordCleanup": True})
    response.headers["Cache-Control"] = "no-store"
    return response
