# routes/api_todaymeta.py
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, request, jsonify

from core.paths import TODAY_ORDER_PATH
from core.storage import file_lock, save_atomic

bp_api_todaymeta = Blueprint("bp_api_todaymeta", __name__)

def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _canonical_date(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        parsed = dt.date.fromisoformat(raw)
    except ValueError:
        abort(400, description="Invalid date format")
    if parsed.isoformat() != raw:
        abort(400, description="Invalid date format")
    return raw


def _clean_order(value: Any) -> list[str]:
    if not isinstance(value, list):
        abort(400, description="order must be a list")
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        sid = str(item or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _read_object_for_mutation(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError("today order store is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("today order store must be an object")
    return value


# ─────────────────────────────────────────────
# /api/today_order
# - GET  /api/today_order -> { "YYYY-MM-DD": ["sid",...], ... }
# - PATCH /api/today_order body: {date, order} 날짜 하나만 저장
# - DELETE /api/today_order?date=YYYY-MM-DD 날짜 하나만 초기화
# ─────────────────────────────────────────────
@bp_api_todaymeta.route("/api/today_order", methods=["GET", "PATCH", "DELETE"])
def api_today_order():
    p = TODAY_ORDER_PATH

    if request.method == "GET":
        value = _read_json(p, {})
        return jsonify(value if isinstance(value, dict) else {})

    if request.method == "DELETE":
        date_key = _canonical_date(request.args.get("date"))
        try:
            with file_lock(p):
                latest = _read_object_for_mutation(p)
                cleared = date_key in latest
                latest.pop(date_key, None)
                if cleared:
                    save_atomic(p, latest)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({"ok": True, "date": date_key, "cleared": cleared})

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad body"}), 400

    date_key = _canonical_date(payload.get("date"))
    order = _clean_order(payload.get("order"))
    try:
        with file_lock(p):
            latest = _read_object_for_mutation(p)
            latest[date_key] = order
            save_atomic(p, latest)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    return jsonify({"ok": True, "date": date_key, "order": order})
