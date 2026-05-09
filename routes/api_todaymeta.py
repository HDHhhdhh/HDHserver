# routes/api_todaymeta.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, request, jsonify

bp_api_todaymeta = Blueprint("bp_api_todaymeta", __name__)

# ✅ JSON 저장 위치
# - 환경변수 DATA_DIR 있으면 거기 사용
# - 없으면 프로젝트 루트의 data/ 폴더 사용 (없으면 생성)
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _get_date_arg() -> str:
    # today.js: ?date=YYYY-MM-DD 로 때림
    return (request.args.get("date") or "").strip()


# ─────────────────────────────────────────────
# /api/attendance
# - GET  /api/attendance?date=YYYY-MM-DD -> { "sid": 1, ... }
# - POST /api/attendance body: { "YYYY-MM-DD": { "sid": 1, ... } }
# ─────────────────────────────────────────────
@bp_api_todaymeta.route("/api/_legacy/attendance", methods=["GET", "POST"])
def api_attendance():
    p = DATA_DIR / "attendance.json"
    all_map: Dict[str, Dict[str, int]] = _read_json(p, {})

    if request.method == "GET":
        d = _get_date_arg()
        if not d:
            # date 없으면 전체 반환 (원하면 {}만 반환하게 바꿔도 됨)
            return jsonify(all_map)
        day = all_map.get(d, {})
        return jsonify(day if isinstance(day, dict) else {})

    payload = request.get_json(silent=True) or {}
    # payload는 { "YYYY-MM-DD": {sid:1} } 형태 기대
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad body"}), 400

    for d, daymap in payload.items():
        if not isinstance(d, str):
            continue
        if isinstance(daymap, dict):
            # 값은 1/true만 유지
            cleaned = {}
            for sid, v in daymap.items():
                if str(v) in ("1", "true", "True") or v is True or v == 1:
                    cleaned[str(sid)] = 1
            all_map[d] = cleaned

    _write_json(p, all_map)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# /api/contact
# - GET  /api/contact?date=YYYY-MM-DD -> { "sid": 1, ... }
# - POST /api/contact body: { "YYYY-MM-DD": { "sid": 1, ... } }
# ─────────────────────────────────────────────
@bp_api_todaymeta.route("/api/_legacy/contact", methods=["GET", "POST"])
def api_contact():
    p = DATA_DIR / "contact.json"
    all_map: Dict[str, Dict[str, int]] = _read_json(p, {})

    if request.method == "GET":
        d = _get_date_arg()
        if not d:
            return jsonify(all_map)
        day = all_map.get(d, {})
        return jsonify(day if isinstance(day, dict) else {})

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad body"}), 400

    for d, daymap in payload.items():
        if not isinstance(d, str):
            continue
        if isinstance(daymap, dict):
            cleaned = {}
            for sid, v in daymap.items():
                if str(v) in ("1", "true", "True") or v is True or v == 1:
                    cleaned[str(sid)] = 1
            all_map[d] = cleaned

    _write_json(p, all_map)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# /api/arrive-time
# - GET  /api/arrive-time?date=YYYY-MM-DD -> { "sid":"HH:MM", ... }
# - GET  /api/arrive-time -> { "YYYY-MM-DD": {sid:"HH:MM"} , ... }
# - POST /api/arrive-time
#     1) 전체맵을 보내면 그대로 저장
#     2) { "YYYY-MM-DD": {sid:"HH:MM"} } 부분맵이면 날짜별 merge
# ─────────────────────────────────────────────
@bp_api_todaymeta.route("/api/_legacy/arrive-time", methods=["GET", "POST"])
def api_arrive_time():
    p = DATA_DIR / "arrive_time.json"
    all_map: Dict[str, Dict[str, str]] = _read_json(p, {})

    if request.method == "GET":
        d = _get_date_arg()
        if d:
            day = all_map.get(d, {})
            return jsonify(day if isinstance(day, dict) else {})
        return jsonify(all_map)

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad body"}), 400

    # payload가 {date:{sid:time}} 형태면 merge
    looks_like_all = any(
        isinstance(k, str) and len(k) == 10 and k[4] == "-" and k[7] == "-" for k in payload.keys()
    )

    if looks_like_all:
        # 날짜키들만 머지/정리
        for d, daymap in payload.items():
            if not isinstance(d, str) or not isinstance(daymap, dict):
                continue
            all_map[d] = {str(sid): str(t).strip() for sid, t in daymap.items() if str(t).strip()}
        _write_json(p, all_map)
        return jsonify({"ok": True})

    # 혹시 sid맵만 직접 보냈다면 date 파라미터로 받는 방식도 지원
    d = _get_date_arg()
    if d and isinstance(payload, dict):
        all_map[d] = {str(sid): str(t).strip() for sid, t in payload.items() if str(t).strip()}
        _write_json(p, all_map)
        return jsonify({"ok": True})

    return jsonify({"ok": False, "error": "unknown body format"}), 400


# ─────────────────────────────────────────────
# /api/today_order
# - GET  /api/today_order -> { "YYYY-MM-DD": ["sid",...], ... }
# - POST /api/today_order body: 위와 동일(전체맵 저장)
# ─────────────────────────────────────────────
@bp_api_todaymeta.route("/api/today_order", methods=["GET", "POST"])
def api_today_order():
    p = DATA_DIR / "today_order.json"
    all_map: Dict[str, list] = _read_json(p, {})

    if request.method == "GET":
        return jsonify(all_map)

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad body"}), 400

    cleaned: Dict[str, list] = {}
    for d, arr in payload.items():
        if not isinstance(d, str):
            continue
        if isinstance(arr, list):
            cleaned[d] = [str(x) for x in arr if str(x).strip()]
    _write_json(p, cleaned)
    return jsonify({"ok": True})
