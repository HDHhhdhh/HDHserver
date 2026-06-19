from __future__ import annotations

import hmac
import json
import os
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from core.admin_chat import MAX_QUERY_LEN, answer_admin_chat
from core.storage import nocache_resp

bp_api_admin_chat = Blueprint("api_admin_chat", __name__, url_prefix="/api/admin")
MAX_CHAT_PAYLOAD_BYTES = 32 * 1024
MAX_CHAT_CONTEXT_CHARS = 8 * 1024


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


def _payload_too_large() -> bool:
    return bool(request.content_length and request.content_length > MAX_CHAT_PAYLOAD_BYTES)


def _conversation_context_too_large(body: dict) -> bool:
    try:
        context_size = len(json.dumps(body.get("context"), ensure_ascii=False, separators=(",", ":")))
        history_size = len(json.dumps(body.get("history"), ensure_ascii=False, separators=(",", ":")))
    except TypeError:
        context_size = len(str(body.get("context") or ""))
        history_size = len(str(body.get("history") or ""))
    return context_size + history_size > MAX_CHAT_CONTEXT_CHARS


@bp_api_admin_chat.before_request
def require_admin_surface():
    # The app does not have admin login yet. This keeps the endpoint bound to
    # the admin page browser context, and allows an optional env token later.
    if not _admin_page_referrer_ok() or not _optional_token_ok():
        return jsonify({"ok": False, "error": "admin chat is only available from /admin"}), 403


@bp_api_admin_chat.post("/chat")
def api_admin_chat():
    if _payload_too_large():
        return jsonify({"ok": False, "error": "payload too large"}), 400
    raw_body = request.get_json(silent=True) or {}
    body = raw_body if isinstance(raw_body, dict) else {}
    if _conversation_context_too_large(body):
        return jsonify({"ok": False, "error": "payload too large"}), 400
    message = str(body.get("message") or "").strip()
    if len(message) > MAX_QUERY_LEN:
        return jsonify({"ok": False, "error": "message too long"}), 400
    return nocache_resp(
        answer_admin_chat(
            message,
            context=body.get("context"),
            history=body.get("history"),
        )
    )
