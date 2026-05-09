from __future__ import annotations

import datetime as dt
import json
import time
from urllib.parse import urlencode

import jwt
from flask import Blueprint, jsonify, request

from routes.api_watch import _save_progress_status, _save_watch_entry

bp_api_kollus = Blueprint("api_kollus", __name__)

KOLLUS_POLICY_KEY = "서비스키"
KOLLUS_SERVICE_KEY = "시크릿키"
TOKEN_EXPIRE_SEC = 36000
KST = dt.timezone(dt.timedelta(hours=9))


def kollus_signed_url(mid: str, client_ip: str, sid: str = "") -> str:
    payload = {
        "service_key": KOLLUS_SERVICE_KEY,
        "expired_at": int(time.time()) + TOKEN_EXPIRE_SEC,
        "allow_ip": client_ip,
    }
    _token = jwt.encode(payload, KOLLUS_POLICY_KEY, algorithm="HS256")
    query = {}
    if sid:
        query["uservalue0"] = sid
    query_string = urlencode(query)
    return f"https://v.kr.kollus.com/{mid}?{query_string}" if query_string else f"https://v.kr.kollus.com/{mid}?"


def get_real_client_ip() -> str:
    return (
        request.headers.get("CF-Connecting-IP")
        or (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        or request.remote_addr
        or ""
    )


def local_only(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs)

    return wrapper


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

    sid = _pick_mapping_value(
        uservalues,
        "uservalue0",
        "USERVALUE0",
    ) or _pick_mapping_value(
        params,
        "sid",
        "SID",
        "uservalue0",
        "USERVALUE0",
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

    sid = str(sid or "").strip()
    mid = str(mid or "").strip()
    last = max(0, _to_int(last_play_at, 0))
    dur = max(0, _to_int(duration, 0))
    pct = max(0, _to_int(playtime_percent, 0))
    play_time = max(0, _to_int(play_time, 0))
    real_playtime = max(0, _to_int(real_playtime, 0))

    completed = pct >= 95
    if dur > 0 and last >= max(dur - 1, int(dur * 0.95)):
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
    }


@bp_api_kollus.get("/api/get-url")
@local_only
def api_get_url():
    mid = str(request.args.get("mid", "") or "").strip()
    sid = str(request.args.get("sid", "") or "").strip()
    if not mid:
        return jsonify({"ok": False, "error": "missing mid"}), 400
    client_ip = get_real_client_ip()
    return kollus_signed_url(mid, client_ip, sid=sid)


@bp_api_kollus.route("/api/kollus/lms-callback", methods=["GET", "POST"])
def api_kollus_lms_callback():
    payload = _extract_callback_fields()
    sid = payload["sid"]
    mid = payload["mid"]
    if not sid or not mid:
        return jsonify({"ok": False, "error": "missing sid/mid"}), 400

    has_progress = (
        payload["completed"]
        or payload["last"] > 0
        or payload["pct"] > 0
        or payload["play_time"] > 0
        or payload["real_playtime"] > 0
    )
    if not has_progress:
        return jsonify({"ok": True, "ignored": True})

    watch = _save_watch_entry(
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
    elif payload["pct"] >= 5:
        status = "interrupted"

    progress = _save_progress_status(payload["date"], sid, mid, status) if status else {}

    return jsonify({
        "ok": True,
        "date": payload["date"],
        "sid": sid,
        "mid": mid,
        "watch": watch,
        "progress": progress,
    })
