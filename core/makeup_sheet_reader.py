from __future__ import annotations

import csv
import datetime as dt
import io
import re
import urllib.error
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
SCHOOL_ALIASES = {
    "고국고": "고양국제고",
    "고양국제고": "고양국제고",
    "대진고": "일산대진고",
    "일산대진고": "일산대진고",
}


def sheet_cell(row: list[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def read_sheet_makeup_rows(
    sheet_url: str,
    target_date: dt.date,
    students: list[dict[str, Any]],
    *,
    max_sheet_row: int = 127,
) -> tuple[dict[int, str], list[tuple[int, list[str], dict[str, Any]]]]:
    snapshot = read_sheet_makeup_snapshot(
        sheet_url,
        target_date,
        students,
        max_sheet_row=max_sheet_row,
    )
    return snapshot["dateColumns"], snapshot["studentMatches"]


def read_sheet_makeup_snapshot(
    sheet_url: str,
    target_date: dt.date,
    students: list[dict[str, Any]],
    *,
    max_sheet_row: int = 127,
) -> dict[str, Any]:
    rows = _download_csv_rows(sheet_url)
    date_columns = _date_columns(rows, target_date.year, target_date.month)
    if not date_columns:
        msg = f"{target_date.year}년 {target_date.month}월 날짜 열을 찾지 못했습니다."
        raise RuntimeError(msg)
    matched_rows, unmatched_starred_rows = _match_sheet_rows_detailed(
        rows,
        students,
        date_columns=date_columns,
        max_sheet_row=max_sheet_row,
    )
    if not matched_rows:
        raise RuntimeError("시트에서 현재 학생 명단과 맞는 행을 찾지 못했습니다.")
    return {
        "dateColumns": date_columns,
        "studentMatches": matched_rows,
        "unmatchedStarredRows": unmatched_starred_rows,
    }


def _download_csv_rows(sheet_url: str) -> list[list[str]]:
    export_url = _csv_export_url(sheet_url)
    request = urllib.request.Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise RuntimeError(
                "현재 시트는 서버에서 읽을 수 없는 '제한됨' 상태입니다. "
                "Google Sheets 공유의 일반 액세스를 '링크가 있는 모든 사용자 - 뷰어'로 "
                "바꾼 뒤 다시 시도해주세요. 웹에 게시할 필요는 없습니다."
            ) from exc
        if exc.code == 404:
            raise RuntimeError("시트 또는 선택한 탭(gid)을 찾지 못했습니다.") from exc
        raise RuntimeError(f"Google Sheets 응답 오류({exc.code})로 시트를 읽지 못했습니다.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("시트를 불러오지 못했습니다. 링크 권한 또는 네트워크 상태를 확인해주세요.") from exc
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
    gid_values = query.get("gid") or fragment_query.get("gid")
    export_url = f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"
    if not gid_values:
        return export_url
    gid = str(gid_values[0] or "").strip()
    if not gid:
        return export_url
    return f"{export_url}&gid={urllib.parse.quote(gid, safe='')}"


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


def _match_sheet_rows(
    rows: list[list[str]],
    students: list[dict[str, Any]],
    *,
    max_sheet_row: int = 127,
) -> list[tuple[int, list[str], dict[str, Any]]]:
    matched, _unmatched = _match_sheet_rows_detailed(
        rows,
        students,
        date_columns={},
        max_sheet_row=max_sheet_row,
    )
    return matched


def _match_sheet_rows_detailed(
    rows: list[list[str]],
    students: list[dict[str, Any]],
    *,
    date_columns: dict[int, str],
    max_sheet_row: int = 127,
) -> tuple[list[tuple[int, list[str], dict[str, Any]]], list[dict[str, Any]]]:
    out: list[tuple[int, list[str], dict[str, Any]]] = []
    unmatched: list[dict[str, Any]] = []
    used_sids: set[str] = set()
    safe_last_row = min(max(6, int(max_sheet_row)), 127)
    for row_index, row in enumerate(rows[5:safe_last_row], start=6):
        name = _clean_name(sheet_cell(row, 2))
        course = _course_key(sheet_cell(row, 3))
        school = _clean_text(sheet_cell(row, 5) or sheet_cell(row, 4))
        if not name or not course:
            continue
        matches = _matching_students(students, name, school, course)
        student = matches[0] if len(matches) == 1 else None
        sid = str(student.get("id") or "").strip() if student else ""
        duplicate = bool(sid and sid in used_sids)
        if student is None or duplicate:
            starred_dates = sorted({
                date_key
                for column, date_key in date_columns.items()
                if "*" in sheet_cell(row, column)
            })
            if starred_dates:
                unmatched.append({
                    "sheetRow": row_index,
                    "reason": "duplicate_student" if duplicate else ("ambiguous" if len(matches) > 1 else "no_match"),
                    "dates": starred_dates,
                })
            continue
        out.append((row_index, row, student))
        if sid:
            used_sids.add(sid)
    return out, unmatched


def _matching_students(
    students: list[dict[str, Any]],
    name: str,
    school: str,
    course: str,
) -> list[dict[str, Any]]:
    identity_matches = [
        student for student in students
        if _clean_name(student.get("name")) == name
        and (not school or _school_key(student.get("school")) == _school_key(school))
    ]
    course_matches = [
        student for student in identity_matches
        if _course_key(student.get("curriculum")) == course
    ]
    if course_matches:
        return course_matches
    if school and len(identity_matches) == 1:
        return identity_matches
    return []


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


def _school_key(value: Any) -> str:
    text = _clean_text(value)
    return SCHOOL_ALIASES.get(text, text)
