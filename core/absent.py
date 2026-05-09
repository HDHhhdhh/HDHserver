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
        }

    # 구버전: {sid: date}
    if isinstance(raw, dict):
        return {
            "by_date": {},
            "by_student": _norm_by_student(raw),
        }

    return {"by_date": {}, "by_student": {}}


def save_absent(obj: Dict[str, Any]) -> None:
    """
    어떤 형태가 들어와도 표준 포맷으로 정규화해서 저장.
    """
    if not isinstance(obj, dict):
        obj = {}

    out = {
        "by_date": _norm_by_date(obj.get("by_date")),
        "by_student": _norm_by_student(obj.get("by_student")),
    }

    save_atomic(ABS_PATH, out)
