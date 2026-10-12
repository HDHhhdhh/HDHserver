from __future__ import annotations

import datetime as dt
import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlencode

from flask import Blueprint, abort, g, jsonify, request, make_response

from core.network_access import ACADEMY_ACCESS_MESSAGE, academy_network_allowed, client_ip_from_request, ip_allowed
from core.paths import PRG_PATH, STU_PATH, VID_PATH, WATCH_PATH
from core.progress_rules import WATCH_DONE_RATIO, WATCH_INTERRUPTED_RATIO
from core.storage import load
from core.progress_store import load_progress_strict
from core.video_watch_cycles import cycle_watch_record, latest_watch_cycles
from core.isolated_kollus_qa import isolated_kollus_qa_allowed
from core.video_sources import is_youtube_mid, youtube_embed_url, parse_youtube_url
from core.watch_progress_writer import save_progress_status, save_watch_entry, save_watch_observation_progress
from core.watch_store import WatchStoreReadError

bp_api_kollus = Blueprint("api_kollus", __name__)


@bp_api_kollus.errorhandler(WatchStoreReadError)
def _watch_store_unavailable(_error):
    return jsonify({"ok": False, "error": "watch_store_unavailable"}), 503

KST = dt.timezone(dt.timedelta(hours=9))
MID_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
CALLBACK_TOKEN_MAX_AGE_SEC = 24 * 60 * 60
CALLBACK_TOKEN_FUTURE_SKEW_SEC = 5 * 60


def _callback_secret() -> str:
    return str(os.environ.get("KOLLUS_CALLBACK_SECRET") or "").strip()


def _callback_signature(secret: str, sid: str, mid: str, issued_at: str) -> str:
    message = f"{sid}\n{mid}\n{issued_at}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _encode_callback_token(secret: str, sid: str, mid: str, issued_at: str, cycle_token: str = "") -> str:
    encoded_sid = base64.urlsafe_b64encode(sid.encode("utf-8")).decode("ascii").rstrip("=")
    if cycle_token:
        signature = _callback_signature(secret, sid, mid, f"{issued_at}\n{cycle_token}")
        return f"v2.{encoded_sid}.{issued_at}.{cycle_token}.{signature}"
    signature = _callback_signature(secret, sid, mid, issued_at)
    return f"v1.{encoded_sid}.{issued_at}.{signature}"


def _decode_callback_token(token: str, mid: str, secret: str) -> tuple[str | None, bool]:
    sid, valid, _cycle = _decode_callback_session(token, mid, secret)
    return sid, valid


def _decode_callback_session(token: str, mid: str, secret: str) -> tuple[str | None, bool, str]:
    parts = str(token or "").split(".")
    if not ((len(parts) == 4 and parts[0] == "v1") or (len(parts) == 5 and parts[0] == "v2")):
        return None, False, ""
    try:
        padding = "=" * (-len(parts[1]) % 4)
        sid = base64.b64decode(parts[1] + padding, altchars=b"-_", validate=True).decode("utf-8").strip()
        issued_at_int = int(parts[2])
    except Exception:
        return None, False, ""
    if not sid:
        return None, False, ""
    now = int(time.time())
    within_window = (
        issued_at_int <= now + CALLBACK_TOKEN_FUTURE_SKEW_SEC
        and issued_at_int >= now - CALLBACK_TOKEN_MAX_AGE_SEC
    )
    if not secret or not within_window:
        return sid, False, ""
    cycle = parts[3] if parts[0] == "v2" else ""
    signed_time = f"{parts[2]}\n{cycle}" if cycle else parts[2]
    expected_signature = _callback_signature(secret, sid, mid, signed_time)
    valid = hmac.compare_digest(parts[-1], expected_signature)
    return sid, valid, cycle if valid else ""


def kollus_signed_url(mid: str, client_ip: str, sid: str = "", cycle_token: str = "") -> str:
    query = {}
    if sid:
        secret = _callback_secret()
        if secret:
            issued_at = str(int(time.time()))
            query["uservalue0"] = _encode_callback_token(secret, sid, mid, issued_at, cycle_token)
        else:
            query["uservalue0"] = sid
    query_string = urlencode(query)
    return f"https://v.kr.kollus.com/{mid}?{query_string}" if query_string else f"https://v.kr.kollus.com/{mid}?"


def get_real_client_ip() -> str:
    if getattr(g, "student_app_public_request", False) is True:
        resolved = getattr(g, "student_app_client_ip", None)
        if isinstance(resolved, str):
            return resolved
    return client_ip_from_request()


def _academy_request_allowed() -> bool:
    if getattr(g, "student_app_public_request", False) is True:
        resolved = getattr(g, "student_app_client_ip", None)
        return isinstance(resolved, str) and ip_allowed(resolved)
    return academy_network_allowed()


def _public_sid_matches(sid: str) -> bool:
    if getattr(g, "student_app_public_request", False) is not True:
        return True
    active_sid = getattr(g, "student_app_active_sid", None)
    return isinstance(active_sid, str) and bool(sid) and sid == active_sid


def local_only(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        qa_allowed = isolated_kollus_qa_allowed(
            str(request.args.get("sid") or "").strip(), str(request.args.get("mid") or "").strip()
        )
        if not _academy_request_allowed() and not qa_allowed:
            return jsonify({
                "ok": False,
                "error": "academy_network_required",
                "message": ACADEMY_ACCESS_MESSAGE,
            }), 403
        g.kollus_video_qa_allowed = qa_allowed
        return f(*args, **kwargs)

    return wrapper


def _known_mid(mid: str) -> bool:
    mid = str(mid or "").strip()
    if not MID_RE.fullmatch(mid):
        return False
    videos = load(VID_PATH) or []
    return any(isinstance(v, dict) and str(v.get("mid") or "").strip() == mid for v in videos)


def _known_sid(sid: str) -> bool:
    sid = str(sid or "").strip()
    if not sid:
        return False
    students = load(STU_PATH) or []
    return any(isinstance(s, dict) and str(s.get("id") or "").strip() == sid for s in students)


def _callback_secret_ok(payload: dict | None = None) -> bool:
    expected = _callback_secret()
    if not expected:
        return False
    provided = (
        request.headers.get("X-Kollus-Secret")
        or request.args.get("token")
        or request.form.get("token")
        or ""
    )
    if provided and hmac.compare_digest(str(provided).strip(), expected):
        return True
    return isinstance(payload, dict) and payload.get("callbackTokenValid") is True


def _pick_mapping_value(mapping: dict, *keys: str):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _callback_date(start_at) -> str:
    ts = _to_int(start_at, 0)
    if ts > 0:
        try:
            return dt.datetime.fromtimestamp(ts, tz=KST).date().isoformat()
        except Exception:
            pass
    return dt.datetime.now(KST).date().isoformat()


def _extract_callback_fields() -> dict:
    params = {}
    params.update(request.args.to_dict(flat=True))
    params.update(request.form.to_dict(flat=True))

    body = request.get_json(silent=True)
    if isinstance(body, dict):
        for key, value in body.items():
            params.setdefault(key, value)

    raw_json_data = _pick_mapping_value(params, "json_data", "JSON_DATA")
    json_data = raw_json_data if isinstance(raw_json_data, dict) else {}
    if not json_data and isinstance(raw_json_data, str) and raw_json_data.strip():
        try:
            json_data = json.loads(raw_json_data)
        except Exception:
            json_data = {}

    user_info = json_data.get("user_info") if isinstance(json_data.get("user_info"), dict) else {}
    content_info = json_data.get("content_info") if isinstance(json_data.get("content_info"), dict) else {}
    uservalues = json_data.get("uservalues") if isinstance(json_data.get("uservalues"), dict) else {}

    raw_sid = _pick_mapping_value(
        uservalues,
        "uservalue0",
        "USERVALUE0",
    ) or _pick_mapping_value(
        content_info,
        "uservalue0",
        "USERVALUE0",
    ) or _pick_mapping_value(
        params,
        "uservalue0",
        "USERVALUE0",
        "sid",
        "SID",
    ) or _pick_mapping_value(
        user_info,
        "client_user_id",
        "CLIENT_USER_ID",
    ) or _pick_mapping_value(
        params,
        "client_user_id",
        "CLIENT_USER_ID",
        "id",
        "ID",
    )

    mid = _pick_mapping_value(
        content_info,
        "media_content_key",
        "MEDIA_CONTENT_KEY",
    ) or _pick_mapping_value(
        params,
        "media_content_key",
        "MEDIA_CONTENT_KEY",
    )

    start_at = _pick_mapping_value(content_info, "start_at", "START_AT") or _pick_mapping_value(params, "start_at", "START_AT")
    last_play_at = _pick_mapping_value(content_info, "last_play_at", "LAST_PLAY_AT") or _pick_mapping_value(params, "last_play_at", "LAST_PLAY_AT", "ET")
    duration = _pick_mapping_value(content_info, "duration", "DURATION") or _pick_mapping_value(params, "duration", "DURATION")
    playtime_percent = _pick_mapping_value(content_info, "playtime_percent", "PLAYTIME_PERCENT") or _pick_mapping_value(params, "playtime_percent", "PLAYTIME_PERCENT")
    play_time = _pick_mapping_value(content_info, "playtime", "PLAY_TIME") or _pick_mapping_value(params, "playtime", "PLAY_TIME", "PT")
    real_playtime = _pick_mapping_value(content_info, "real_playtime", "REAL_PLAYTIME") or _pick_mapping_value(params, "real_playtime", "REAL_PLAYTIME")

    mid = str(mid or "").strip()
    raw_sid = str(raw_sid or "").strip()
    token_sid, callback_token_valid, cycle_token = _decode_callback_session(raw_sid, mid, _callback_secret())
    sid = token_sid or raw_sid
    last = max(0, _to_int(last_play_at, 0))
    dur = max(0, _to_int(duration, 0))
    pct = max(0, _to_int(playtime_percent, 0))
    play_time = max(0, _to_int(play_time, 0))
    real_playtime = max(0, _to_int(real_playtime, 0))

    completed = (pct / 100) >= WATCH_DONE_RATIO
    if dur > 0 and (last / dur) >= WATCH_DONE_RATIO:
        completed = True

    return {
        "sid": sid,
        "mid": mid,
        "date": _callback_date(start_at),
        "last": last,
        "dur": dur,
        "pct": pct,
        "play_time": play_time,
        "real_playtime": real_playtime,
        "completed": completed,
        "callbackTokenValid": callback_token_valid,
        "cycleToken": cycle_token,
    }


@bp_api_kollus.get("/api/get-url")
@local_only
def api_get_url():
    mid = str(request.args.get("mid", "") or "").strip()
    sid = str(request.args.get("sid", "") or "").strip()
    if not _public_sid_matches(sid):
        return jsonify({"ok": False, "code": "sid_mismatch", "error": "sid_mismatch"}), 403
    if not mid or not MID_RE.fullmatch(mid):
        return jsonify({"ok": False, "error": "missing mid"}), 400
    if not _known_mid(mid):
        return jsonify({"ok": False, "error": "unknown mid"}), 404
    if sid and not _known_sid(sid):
        return jsonify({"ok": False, "error": "unknown sid"}), 404
    if is_youtube_mid(mid):
        if not sid:
            return jsonify({"ok": False, "error": "missing sid"}), 400
        video = next((row for row in load(VID_PATH) if isinstance(row, dict) and row.get("mid") == mid), {})
        try:
            response = make_response(youtube_embed_url(video))
            response.headers["X-Video-Provider"] = "youtube"
            response.headers["X-Video-Open-Url"] = parse_youtube_url(video.get("url"))["url"]
            response.headers["Cache-Control"] = "no-store"
            return response
        except ValueError:
            return jsonify({"ok": False, "error": "invalid youtube catalog entry"}), 409
    client_ip = get_real_client_ip()
    today = dt.datetime.now(KST).date().isoformat()
    cycle = latest_watch_cycles(load_progress_strict(PRG_PATH), sid, today).get(mid, {}) if sid else {}
    provider_sid = "" if getattr(g, "kollus_video_qa_allowed", False) is True else sid
    if not cycle:
        return kollus_signed_url(mid, client_ip, sid=provider_sid)
    response = make_response(kollus_signed_url(mid, client_ip, sid=provider_sid, cycle_token=cycle.get("token", "")))
    response.headers["X-Video-Watch-State"] = json.dumps(cycle_watch_record(cycle), separators=(",", ":"))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp_api_kollus.route("/api/kollus/lms-callback", methods=["GET", "POST"])
def api_kollus_lms_callback():
    payload = _extract_callback_fields()
    if not _callback_secret_ok(payload):
        abort(403)

    sid = payload["sid"]
    mid = payload["mid"]
    if not sid or not mid:
        return jsonify({"ok": False, "error": "missing sid/mid"}), 400
    if not MID_RE.fullmatch(mid):
        return jsonify({"ok": False, "error": "bad mid"}), 400
    if not _known_sid(sid):
        return jsonify({"ok": False, "error": "unknown sid"}), 404
    if not _known_mid(mid):
        return jsonify({"ok": False, "error": "unknown mid"}), 404

    if is_youtube_mid(mid):
        return jsonify({"ok": False, "error": "youtube watch tracking is disabled"}), 400

    has_progress = (
        payload["completed"]
        or payload["last"] > 0
        or payload["pct"] > 0
        or payload["play_time"] > 0
        or payload["real_playtime"] > 0
    )
    if not has_progress:
        return jsonify({"ok": True, "ignored": True})

    watch = save_watch_entry(
        WATCH_PATH,
        payload["date"],
        sid,
        mid,
        {
            "last": payload["last"],
            "dur": payload["dur"],
            "completed": payload["completed"],
            "updatedAt": int(time.time() * 1000),
        },
    )

    status = ""
    if payload["completed"]:
        status = "done"
    elif payload["dur"] <= 0:
        if payload["last"] > 0 or payload["play_time"] > 0 or payload["real_playtime"] > 0:
            status = "interrupted"
    elif (payload["pct"] / 100) >= WATCH_INTERRUPTED_RATIO:
        status = "interrupted"

    progress, cycle_watch, _stale = save_watch_observation_progress(
        PRG_PATH, STU_PATH, VID_PATH, payload["date"], sid, mid, status,
        observation={"last": payload["last"], "dur": payload["dur"], "completed": payload["completed"], "updatedAt": int(time.time() * 1000)},
        cycle_token=payload["cycleToken"],
        observation_status=status,
    )

    return jsonify({
        "ok": True,
        "date": payload["date"],
        "sid": sid,
        "mid": mid,
        "watch": watch,
        "progress": progress,
    })
