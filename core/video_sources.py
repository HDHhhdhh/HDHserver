"""Pure YouTube catalog identity and playback URL rules; no provider I/O."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlsplit

YOUTUBE_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
})
GICHUL_OVERLAY_FIELD = "gichulSelectionEnabled"
GICHUL_COURSE = "기출엄선"


def is_youtube_mid(mid) -> bool:
    return bool(re.fullmatch(r"(?:ytv_[A-Za-z0-9_-]{11}|ytp_[A-Za-z0-9_-]{10,100})(?:_r[0-9]{1,12})?", str(mid or "")))


def _start_seconds(raw) -> int:
    text = str(raw or "").strip().lower()
    if not text:
        return 0
    if text.isdigit():
        seconds = int(text)
    else:
        match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
        if not match:
            raise ValueError("YouTube 시작 시간 형식이 올바르지 않습니다.")
        hours, minutes, seconds = (int(value or 0) for value in match.groups())
        seconds += hours * 3600 + minutes * 60
    if seconds > 604800:
        raise ValueError("YouTube 시작 시간이 너무 큽니다.")
    return seconds


def parse_youtube_url(raw, *, catalog_id=None) -> dict | None:
    """Return None for other hosts; reject malformed URLs on a YouTube host."""
    text = str(raw or "").strip()
    try:
        parsed = urlsplit(text)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if host not in YOUTUBE_HOSTS:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise ValueError("유효한 YouTube https 링크를 입력하세요.")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(len(query.get(key, [])) > 1 for key in ("v", "list", "start", "t")):
        raise ValueError("YouTube 링크에 중복 식별자가 있습니다.")
    value = lambda key: (query.get(key) or [""])[0]
    path = parsed.path.rstrip("/")
    parts = path.strip("/").split("/")
    kind = "video"
    identifier = ""
    if host in {"youtu.be", "www.youtu.be"} and len(parts) == 1:
        identifier = parts[0]
    elif path == "/watch":
        identifier = value("v")  # A video with a list parameter is still one video.
    elif len(parts) == 2 and parts[0] in {"embed", "shorts", "v"}:
        identifier = parts[1]
        if identifier == "videoseries" and parts[0] == "embed":
            kind, identifier = "playlist", value("list")
    elif path in {"/playlist", "/embed"}:
        kind, identifier = "playlist", value("list")
    else:
        raise ValueError("영상 또는 재생목록 링크만 지원합니다. 실시간 방송 링크는 제외됩니다.")
    pattern = r"[A-Za-z0-9_-]{11}" if kind == "video" else r"[A-Za-z0-9_-]{10,100}"
    if not re.fullmatch(pattern, identifier):
        raise ValueError("YouTube 영상/재생목록 식별자가 올바르지 않습니다.")
    start = _start_seconds(value("start") or value("t") or (parsed.fragment[2:] if parsed.fragment.startswith("t=") else ""))
    query_out = {"v" if kind == "video" else "list": identifier}
    if start:
        query_out["t"] = str(start)
    suffix = ""
    if catalog_id is not None:
        row_id = str(catalog_id).strip()
        if not re.fullmatch(r"[1-9][0-9]{0,11}", row_id):
            raise ValueError("YouTube 영상에는 유효한 카탈로그 ID가 필요합니다.")
        suffix = "_r" + row_id
    return {
        "provider": "youtube", "youtubeKind": kind, "youtubeId": identifier,
        "mid": ("ytv_" if kind == "video" else "ytp_") + identifier + suffix,
        "url": "https://www.youtube.com/" + ("watch" if kind == "video" else "playlist") + "?" + urlencode(query_out),
        "youtubeStart": start,
    }


def youtube_embed_url(video: dict) -> str:
    source = parse_youtube_url(video.get("url"), catalog_id=video.get("id"))
    if not source or source["mid"] != video.get("mid"):
        raise ValueError("YouTube catalog identity mismatch")
    query = {"autoplay": "0", "playsinline": "1", "rel": "0"}
    if source["youtubeKind"] == "playlist":
        path = "videoseries"
        query["listType"] = "playlist"
        query["list"] = source["youtubeId"]
    else:
        path = source["youtubeId"]
    if source["youtubeStart"]:
        query["start"] = str(source["youtubeStart"])
    return "https://www.youtube-nocookie.com/embed/" + path + "?" + urlencode(query)


def youtube_record_cleanup_patch(assignment, progress_entry: dict, videos: list) -> dict:
    from core.update_assignment_rules import normalize_video_assign_list

    youtube_mids = {str(video.get("mid") or "") for video in videos
                    if isinstance(video, dict) and video.get("provider") == "youtube" and is_youtube_mid(video.get("mid"))}
    return {mid: "done" for mid in normalize_video_assign_list(assignment)
            if mid in youtube_mids and progress_entry.get(mid) in {None, "", "none", "assigned"}}
