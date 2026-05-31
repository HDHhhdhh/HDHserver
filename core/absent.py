from __future__ import annotations

import re
from typing import Any, Dict, List

from core.paths import ABS_PATH
from core.storage import load, save_atomic

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _norm_sid_list(xs: Any) -> List[str]:
    """sid 목록을 문자열 리스트로 정규화 + 중복 제거(순서 유지)"""
    if not isinstance(xs, list):
        return []
    out: List[str] = []
    seen = set()
    for x in xs:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _norm_slot_list(xs: Any) -> List[int]:
    values = xs if isinstance(xs, list) else [xs]
    out: List[int] = []
    seen = set()
    for value in values:
        try:
            n = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if n not in (1, 2) or n in seen:
            continue
        seen.add(n)
        out.append(n)
    out.sort()
    return out


def _norm_by_date(by_date: Any) -> Dict[str, List[str]]:
    """{date: [sid,...]} 형태로 정규화"""
    if not isinstance(by_date, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for k, v in by_date.items():
        d = str(k).strip()
        if not DATE_RE.match(d):
            continue
        out[d] = _norm_sid_list(v)
    return out


def _norm_by_slot(by_slot: Any) -> Dict[str, Dict[str, List[int]]]:
    if not isinstance(by_slot, dict):
        return {}
    out: Dict[str, Dict[str, List[int]]] = {}
    for date_raw, sid_map in by_slot.items():
        date_key = str(date_raw).strip()
        if not DATE_RE.match(date_key) or not isinstance(sid_map, dict):
            continue
        rows: Dict[str, List[int]] = {}
        for sid_raw, slots_raw in sid_map.items():
            sid = str(sid_raw).strip()
            slots = _norm_slot_list(slots_raw)
            if sid and slots:
                rows[sid] = slots
        if rows:
            out[date_key] = rows
    return out


def _norm_by_student(by_student: Any) -> Dict[str, str]:
    """{sid: date} 형태로 정규화"""
    if not isinstance(by_student, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in by_student.items():
        sid = str(k).strip()
        if not sid:
            continue
        d = str(v).strip() if v is not None else ""
        if d and DATE_RE.match(d):
            out[sid] = d
    return out


def load_absent() -> Dict[str, Any]:
    """
    저장 포맷 표준:
      {"by_date": {date:[sid,...]}, "by_student": {sid:date}}
    구버전(학생->날짜 단일 dict)도 자동 흡수.
    """
    raw = load(ABS_PATH)

    # 표준 포맷
    if isinstance(raw, dict) and "by_date" in raw and "by_student" in raw:
        return {
            "by_date": _norm_by_date(raw.get("by_date")),
            "by_student": _norm_by_student(raw.get("by_student")),
            "by_slot": _norm_by_slot(raw.get("by_slot")),
        }

    # 구버전: {sid: date}
    if isinstance(raw, dict):
        return {
            "by_date": {},
            "by_student": _norm_by_student(raw),
            "by_slot": {},
        }

    return {"by_date": {}, "by_student": {}, "by_slot": {}}


def save_absent(obj: Dict[str, Any]) -> None:
    """
    어떤 형태가 들어와도 표준 포맷으로 정규화해서 저장.
    """
    if not isinstance(obj, dict):
        obj = {}

    existing = load_absent()
    by_slot_source = obj.get("by_slot") if "by_slot" in obj else existing.get("by_slot")

    out = {
        "by_date": _norm_by_date(obj.get("by_date")),
        "by_student": _norm_by_student(obj.get("by_student")),
        "by_slot": _norm_by_slot(by_slot_source),
    }

    save_atomic(ABS_PATH, out)
