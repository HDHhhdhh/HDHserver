from __future__ import annotations

import hmac
import os
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from core.admin_chat import MAX_QUERY_LEN, answer_admin_chat
from core.storage import nocache_resp

bp_api_admin_chat = Blueprint("api_admin_chat", __name__, url_prefix="/api/admin")


def _admin_page_referrer_ok() -> bool:
    raw = (request.headers.get("Referer") or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except Exception:
        return False

    host = (request.host or "").lower()
    if parsed.netloc and parsed.netloc.lower() != host:
        return False
    return parsed.path.rstrip("/") == "/admin"


def _optional_token_ok() -> bool:
    expected = (os.environ.get("ADMIN_CHAT_TOKEN") or "").strip()
    if not expected:
        return True

    auth = (request.headers.get("Authorization") or "").strip()
    provided = ""
    if auth.startswith("Bearer "):
        provided = auth.split(" ", 1)[1].strip()
    if not provided:
        provided = (request.headers.get("X-Admin-Chat-Token") or "").strip()
    return bool(provided) and hmac.compare_digest(provided, expected)


@bp_api_admin_chat.before_request
def require_admin_surface():
    # The app does not have admin login yet. This keeps the endpoint bound to
    # the admin page browser context, and allows an optional env token later.
    if not _admin_page_referrer_ok() or not _optional_token_ok():
        return jsonify({"ok": False, "error": "admin chat is only available from /admin"}), 403


@bp_api_admin_chat.post("/chat")
def api_admin_chat():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    if len(message) > MAX_QUERY_LEN:
        return jsonify({"ok": False, "error": "message too long"}), 400
    return nocache_resp(answer_admin_chat(message))
