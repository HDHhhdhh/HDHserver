from __future__ import annotations

import datetime as dt
from typing import Any, Dict

from flask import Blueprint, abort, jsonify, request

from core.paths import BASE
from core.storage import load, save_atomic, file_lock

bp_api_makeup_carryover = Blueprint("api_makeup_carryover", __name__)

MAKEUP_CARRYOVER_PATH = BASE / "makeup_carryover.json"


def _norm_date(value: Any) -> str:
    text = str(value or "").split("T")[0].strip()
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        return ""
    return text


def _norm_sid(value: Any) -> str:
    return str(value or "").strip()


def _norm_slot_list(value: Any) -> list[int]:
    values = value if isinstance(value, list) else [value]
    out: list[int] = []
    seen = set()
    for item in values:
        try:
            slot = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if slot not in (1, 2) or slot in seen:
            continue
        seen.add(slot)
        out.append(slot)
    out.sort()
    return out


def _normalize_manual(raw: Any) -> Dict[str, Dict[str, Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for date_raw, rows_raw in raw.items():
        date_key = _norm_date(date_raw)
        if not date_key or not isinstance(rows_raw, dict):
            continue
        rows: Dict[str, Dict[str, Any]] = {}
        for key_raw, value in rows_raw.items():
            key = str(key_raw or "").strip()
            if not key or value is False or value is None:
                continue
            row = value if isinstance(value, dict) else {}
            sid = _norm_sid(row.get("sid"))
            if not sid:
                continue
            date_only = bool(row.get("dateOnly") or row.get("date_only") or row.get("slotless"))
            slots = _norm_slot_list(row.get("slots", row.get("slot")))
            if not slots and not date_only:
                slots = [1]
            rows[key] = {
                "sid": sid,
                "slots": [] if date_only else slots,
                "dateOnly": date_only,
                "state": str(row.get("state") or "").strip(),
                "createdAt": str(row.get("createdAt") or "").strip(),
                "updatedAt": str(row.get("updatedAt") or "").strip(),
                "note": str(row.get("note") or "").strip(),
                "course": str(row.get("course") or "").strip(),
            }
        if rows:
            out[date_key] = rows
    return out


def _normalize_payload(raw: Any) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    by_absence = source.get("by_absence")
    if not isinstance(by_absence, dict):
        by_absence = source

    out: Dict[str, Dict[str, Dict[str, str]]] = {}
    for date_raw, sid_map in by_absence.items():
        date_key = _norm_date(date_raw)
        if not date_key or not isinstance(sid_map, dict):
            continue
        rows: Dict[str, Dict[str, str]] = {}
        for sid_raw, value in sid_map.items():
            sid = _norm_sid(sid_raw)
            if not sid:
                continue
            if value is False or value is None:
                continue
            row = value if isinstance(value, dict) else {}
            state = str(row.get("state") or "").strip().lower()
            if state not in {"open", "carried"}:
                state = "carried"
            rows[sid] = {
                "state": state,
                "updatedAt": str(row.get("updatedAt") or "").strip(),
                "note": str(row.get("note") or "").strip(),
            }
        if rows:
            out[date_key] = rows

    return {
        "by_absence": out,
        "manual": _normalize_manual(source.get("manual")),
    }


@bp_api_makeup_carryover.get("/api/makeup-carryover")
def api_makeup_carryover_get():
    return jsonify(_normalize_payload(load(MAKEUP_CARRYOVER_PATH)))


@bp_api_makeup_carryover.post("/api/makeup-carryover")
def api_makeup_carryover_post():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")
    normalized = _normalize_payload(payload)
    with file_lock(MAKEUP_CARRYOVER_PATH):
        save_atomic(MAKEUP_CARRYOVER_PATH, normalized)
    return jsonify(normalized)
