from __future__ import annotations

from typing import Any


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    if isinstance(value, dict) and len(value) == 0:
        return True
    return False


def truthy(value: Any) -> bool:
    return value is True or value == 1 or value == "1" or value == "true"


def merge_log_entry_safe(current: dict, incoming: dict) -> dict:
    if not isinstance(current, dict):
        current = {}
    if not isinstance(incoming, dict):
        return current

    out = dict(current)

    clear = incoming.get("__clear")
    if isinstance(clear, list):
        for key in clear:
            key_s = str(key).strip()
            if key_s:
                out.pop(key_s, None)

    current_done = truthy(current.get("done"))

    for key, value in incoming.items():
        if key == "__clear":
            continue

        if value is None:
            continue

        if is_empty_value(value) and not is_empty_value(out.get(key)):
            continue

        out[key] = value

    if current_done and "done" not in incoming:
        out["done"] = True

    marks_done_now = truthy(incoming.get("done"))
    marks_leave_now = any(
        (key in incoming) and (not is_empty_value(incoming.get(key)))
        for key in ("leaveTime", "leaveAt", "doneTime")
    )
    done_after_merge = truthy(out.get("done"))
    if (
        marks_done_now or (marks_leave_now and (current_done or done_after_merge))
    ) and "archived" not in incoming:
        out.pop("archived", None)

    return out


def normalize_homework_rows_for_compare(rows: Any) -> list:
    if not isinstance(rows, list):
        return []

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        if "book" in row or "this" in row or "comment" in row or "next" in row:
            book = str(row.get("book") or "").strip()
            this_hw = str(row.get("this") or "").strip()
            pct = row.get("pct")
            pct_s = "" if pct in ("", None) else str(pct).strip()
            comment = str(row.get("comment") or "").strip()
            next_hw = str(row.get("next") or "").strip()
            deleted = bool(row.get("_deleted") or row.get("_del") or row.get("deleted"))
        else:
            book = str(row.get("name") or "").strip()
            this_hw = str(row.get("unit") or "").strip()
            pct = row.get("pct")
            pct_s = "" if pct in ("", None) else str(pct).strip()
            comment = str(row.get("rem") or "").strip()
            next_hw = ""
            deleted = False

        out.append({
            "book": book,
            "this": this_hw,
            "pct": pct_s,
            "comment": comment,
            "next": next_hw,
            "_deleted": deleted,
        })

    return out


def extract_homework_rows_for_compare(entry: dict) -> list:
    if not isinstance(entry, dict):
        return []

    rows = entry.get("homeworkTable")
    if isinstance(rows, list) and rows:
        return normalize_homework_rows_for_compare(rows)

    homework = str(entry.get("homework") or "").strip()
    if homework:
        return normalize_homework_rows_for_compare([{
            "book": "",
            "this": "",
            "pct": "",
            "comment": homework,
            "next": "",
            "_deleted": False,
        }])

    return []


def log_entry_conflicts_with_base(current: dict, base: dict) -> bool:
    if not isinstance(base, dict) or not base:
        return False

    current_entry = current if isinstance(current, dict) else {}

    if "notes" in base:
        current_notes = str(current_entry.get("notes") or "").strip()
        base_notes = str(base.get("notes") or "").strip()
        if current_notes != base_notes:
            return True

    if "homeworkTable" in base:
        current_rows = extract_homework_rows_for_compare(current_entry)
        base_rows = normalize_homework_rows_for_compare(base.get("homeworkTable"))
        if current_rows != base_rows:
            return True

    return False
