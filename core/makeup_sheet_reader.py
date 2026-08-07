from __future__ import annotations

import csv
import datetime as dt
import io
import re
import urllib.parse
import urllib.request
from typing import Any


DATE_HEADER_RE = re.compile(r"(?P<month>\d{1,2})\s*/\s*(?P<day>\d{1,2})")
SHEET_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)")
COURSE_ALIASES = {
    "미적1": "미적분1",
    "미적분1": "미적분1",
    "미적2": "미적분2",
    "미적분2": "미적분2",
    "공수1": "공수1",
    "공수2": "공수2",
    "대수": "대수",
    "기하": "기하",
    "확통": "확통",
}


def sheet_cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def read_sheet_makeup_rows(
    sheet_url: str,
    target_date: dt.date,
    students: list[dict[str, Any]],
) -> tuple[dict[int, str], list[tuple[int, list[str], dict[str, Any]]]]:
    rows = _download_csv_rows(sheet_url)
    date_columns = _date_columns(rows, target_date.year, target_date.month)
    if not date_columns:
        msg = f"{target_date.year}년 {target_date.month}월 날짜 열을 찾지 못했습니다."
        raise RuntimeError(msg)
    matched_rows = _match_sheet_rows(rows, students)
    if not matched_rows:
        raise RuntimeError("시트에서 현재 학생 명단과 맞는 행을 찾지 못했습니다.")
    return date_columns, matched_rows


def _download_csv_rows(sheet_url: str) -> list[list[str]]:
    export_url = _csv_export_url(sheet_url)
    request = urllib.request.Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    text = raw.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or not any("학생명" in cell for row in rows[:8] for cell in row):
        raise RuntimeError("시트를 CSV로 읽지 못했습니다. 링크 권한 또는 gid를 확인해주세요.")
    return rows


def _csv_export_url(sheet_url: str) -> str:
    raw = str(sheet_url or "").strip()
    match = SHEET_ID_RE.search(raw)
    if not match:
        raise RuntimeError("구글 스프레드시트 링크가 아닙니다.")
    parsed = urllib.parse.urlparse(raw)
    query = urllib.parse.parse_qs(parsed.query)
    fragment_query = urllib.parse.parse_qs(urllib.parse.urlparse("?" + parsed.fragment).query)
    gid = (query.get("gid") or fragment_query.get("gid") or ["0"])[0]
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv&gid={gid}"


def _date_columns(rows: list[list[str]], year: int, month: int) -> dict[int, str]:
    if len(rows) < 4:
        return {}
    out: dict[int, str] = {}
    for index, value in enumerate(rows[3]):
        match = DATE_HEADER_RE.search(str(value or ""))
        if not match or int(match.group("month")) != month:
            continue
        try:
            out[index] = dt.date(year, month, int(match.group("day"))).isoformat()
        except ValueError:
            continue
    return out


def _match_sheet_rows(rows: list[list[str]], students: list[dict[str, Any]]) -> list[tuple[int, list[str], dict[str, Any]]]:
    out: list[tuple[int, list[str], dict[str, Any]]] = []
    used_sids: set[str] = set()
    for row_index, row in enumerate(rows[5:], start=6):
        name = _clean_name(sheet_cell(row, 2))
        course = _course_key(sheet_cell(row, 3))
        school = _clean_text(sheet_cell(row, 5) or sheet_cell(row, 4))
        if not name or not course:
            continue
        for student in _matching_students(students, name, school, course):
            sid = str(student.get("id") or "").strip()
            if sid and sid not in used_sids:
                out.append((row_index, row, student))
                used_sids.add(sid)
    return out


def _matching_students(
    students: list[dict[str, Any]],
    name: str,
    school: str,
    course: str,
) -> list[dict[str, Any]]:
    return [
        student for student in students
        if _clean_name(student.get("name")) == name
        and _course_key(student.get("curriculum")) == course
        and (not school or _clean_text(student.get("school")) == school)
    ]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _clean_name(value: Any) -> str:
    text = re.sub(r"\([^)]*\)", "", str(value or ""))
    return _clean_text(text)


def _course_key(value: Any) -> str:
    text = _clean_text(value)
    for key, normalized in COURSE_ALIASES.items():
        if key in text:
            return normalized
    return text
