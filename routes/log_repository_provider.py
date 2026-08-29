from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List

from flask import g, has_request_context

from core import log_rules
from core.log_repository import LogRepository
from core.paths import LOGS_PATH, STU_PATH
from core.storage import InterProcessFileLock, load


KST = dt.timezone(dt.timedelta(hours=9))


def _is_question_placeholder(value) -> bool:
    text = re.sub(r"\s+", "", str(value or ""))
    return len(text) >= 2 and set(text) == {"?"}


def _looks_corrupted_placeholder_text(value) -> bool:
    text = str(value or "").strip()
    if text.count("?") < 2:
        return False
    # Preserve real text such as "확인??" while hiding placeholder mojibake.
    return re.search(r"[A-Za-z가-힣一-龥]", text) is None


def _clean_placeholder_text(value) -> str:
    text = str(value or "").strip()
    return "" if _is_question_placeholder(text) or _looks_corrupted_placeholder_text(text) else text


def _load_student_homework_books_by_sid() -> Dict[str, List[str]]:
    try:
        students = load(STU_PATH) or []
    except Exception:
        students = []
    if not isinstance(students, list):
        return {}

    out: Dict[str, List[str]] = {}
    for student in students:
        if not isinstance(student, dict):
            continue
        sid = str(student.get("id") or "").strip()
        if not sid:
            continue
        books: List[str] = []
        for key in sorted(
            student.keys(),
            key=lambda item: int(item[7:]) if re.match(r"^subBook\d+$", str(item)) else 999,
        ):
            if not re.match(r"^subBook\d+$", str(key)):
                continue
            value = str(student.get(key) or "").strip()
            if value and value not in books:
                books.append(value)
        if books:
            out[sid] = books
    return out


def _student_homework_books(sid: str) -> List[str]:
    sid_s = str(sid or "").strip()
    if not sid_s:
        return []

    if has_request_context():
        cache = getattr(g, "_student_homework_books_by_sid", None)
        if cache is None:
            cache = _load_student_homework_books_by_sid()
            g._student_homework_books_by_sid = cache
    else:
        cache = _load_student_homework_books_by_sid()
    return list(cache.get(sid_s, []))


def _book_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def _homework_row_summary(row: dict) -> str:
    if not isinstance(row, dict) or row.get("_deleted"):
        return ""

    book = str(row.get("book") or "").strip()
    current_homework = str(row.get("this") or "").strip()
    pct = row.get("pct")
    pct_s = "" if pct in ("", None) else f"{str(pct).strip()}%"
    comment = str(row.get("comment") or "").strip()
    next_homework = str(row.get("next") or "").strip()

    parts: List[str] = []
    if book:
        parts.append(f"[{book}]")
    if current_homework:
        parts.append(current_homework)
    if pct_s:
        parts.append(pct_s)
    if comment:
        parts.append(f"({comment})")
    if next_homework:
        parts.append(f"→ {next_homework}")
    return " ".join(parts).strip()


def _repair_homework_rows(rows, sid: str) -> tuple[list, bool]:
    if not isinstance(rows, list):
        return [], False

    books = _student_homework_books(sid)
    used = {
        _book_key(row.get("book"))
        for row in rows
        if isinstance(row, dict) and not _is_question_placeholder(row.get("book"))
    }
    used.discard("")

    out: List[dict] = []
    changed = False
    for row in rows:
        if not isinstance(row, dict):
            changed = True
            continue

        next_row = dict(row)
        raw_book = str(next_row.get("book") or "").strip()
        if _is_question_placeholder(raw_book):
            replacement = next((book for book in books if _book_key(book) not in used), "")
            next_row["book"] = replacement
            if replacement:
                used.add(_book_key(replacement))
            changed = True
        elif raw_book:
            used.add(_book_key(raw_book))

        for field in ("this", "comment", "next"):
            if field in next_row:
                cleaned = _clean_placeholder_text(next_row.get(field))
                if cleaned != str(next_row.get(field) or "").strip():
                    next_row[field] = cleaned
                    changed = True

        out.append(next_row)

    return out, changed


def repair_log_entry_placeholders(entry: dict, sid: str) -> dict:
    if not isinstance(entry, dict):
        return {}

    out = dict(entry)
    if "notes" in out:
        cleaned_notes = _clean_placeholder_text(out.get("notes"))
        if cleaned_notes:
            out["notes"] = cleaned_notes
        else:
            out.pop("notes", None)

    rows = out.get("homeworkTable")
    repaired_rows, changed = _repair_homework_rows(rows, sid)
    if isinstance(rows, list):
        out["homeworkTable"] = repaired_rows
        if changed:
            summary = " / ".join(
                value for value in (_homework_row_summary(row) for row in repaired_rows) if value
            )
            if summary:
                out["homework"] = summary
            else:
                out.pop("homework", None)
    elif _is_question_placeholder(out.get("homework")):
        out.pop("homework", None)
    return out


def student_homework_book_names_from_log(entry: dict) -> list[str]:
    if not isinstance(entry, dict):
        return []

    rows = entry.get("homeworkTable")
    if not isinstance(rows, list):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("_deleted"):
            continue
        book = _clean_placeholder_text(row.get("book"))
        key = _book_key(book)
        if not book or not key or key in seen:
            continue
        seen.add(key)
        out.append(book)
    return out


def _logs_lock():
    path = str(getattr(LOGS_PATH, "__fspath__", lambda: str(LOGS_PATH))())
    return InterProcessFileLock(path + ".lock", timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0)


def _today_kst_iso() -> str:
    return dt.datetime.now(KST).date().isoformat()


def get_log_repository() -> LogRepository:
    return LogRepository(
        logs_path=LOGS_PATH,
        repair_entry=repair_log_entry_placeholders,
        merge_entry=log_rules.merge_log_entry_safe,
        entry_conflicts=log_rules.log_entry_conflicts_with_base,
        lock_factory=_logs_lock,
        truthy=log_rules.truthy,
        today_key=_today_kst_iso,
    )


__all__ = (
    "get_log_repository",
    "repair_log_entry_placeholders",
    "student_homework_book_names_from_log",
)
