"""Remove legacy level-mismatch test exclusions from runtime state.

The old admin test popup persisted automatic level exclusions as ``skip`` (the
red/excluded state).  A saved popup could contain a bulk batch of those values,
so this repair treats a date/student entry with three or more legacy-rule
matches as one automatic batch and clears every skip in that batch.  Small
manual skips remain available.  Entries without a known student level/rule
are left untouched unless they are part of such a detected batch.

Run without ``--apply`` for a read-only report.  Use ``--apply`` only after a
runtime backup has been created.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.log_repository import LogRepository
from core.paths import LOGS_PATH, PRG_PATH, STU_PATH, TESTS_CFG_PATH
from core.storage import InterProcessFileLock, load, save_atomic


CATEGORY_LABELS = {
    "복습 테스트": "REVIEW",
    "단원평가": "UNIT",
    "학군지 기출": "SCHOOL_PAST",
    "일산 기출": "ILSAN_PAST",
}
SUBJECT_ALIASES = {
    "공통수학1": "공수1",
    "공통수학2": "공수2",
    "미적1": "미적분1",
    "미적분Ⅰ": "미적분1",
}
AUTO_RED_CATEGORIES = {"REVIEW", "UNIT", "SCHOOL_PAST"}
NOTE_STATUS_MARKERS = ("(빨강)", "(제외)", "(skip)")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", _text(value))


def normalize_subject(value: Any) -> str:
    compact = _compact(value)
    return SUBJECT_ALIASES.get(compact, compact)


def canonical_category(value: Any) -> str:
    raw = _text(value)
    upper = raw.upper()
    if upper in {"REVIEW", "UNIT", "SCHOOL_PAST", "ILSAN_PAST"}:
        return upper
    return CATEGORY_LABELS.get(raw, "")


def _item_parts(item_or_label: Any) -> tuple[str, str, str]:
    if isinstance(item_or_label, dict):
        category = canonical_category(
            item_or_label.get("categoryKey")
            or item_or_label.get("category")
            or item_or_label.get("categoryLabel")
        )
        subject = normalize_subject(
            item_or_label.get("curriculum")
            or item_or_label.get("subject")
        )
        difficulty = _text(item_or_label.get("difficulty") or item_or_label.get("level"))
        if category and subject and difficulty:
            return category, subject, difficulty
        label = _text(item_or_label.get("label"))
    else:
        label = _text(item_or_label)

    parts = [part.strip() for part in label.split(" / ")]
    if len(parts) < 3:
        return "", "", ""
    return (
        canonical_category(parts[0]),
        normalize_subject(parts[1]),
        _text(parts[2]),
    )


def _student_for_sid(students_by_sid: dict[str, dict[str, Any]], sid: Any) -> dict[str, Any] | None:
    key = _text(sid)
    student = students_by_sid.get(key)
    if isinstance(student, dict):
        return student
    if key.isdigit():
        student = students_by_sid.get(str(int(key)))
        if isinstance(student, dict):
            return student
    return None


def is_legacy_auto_red(
    item_or_label: Any,
    student: dict[str, Any] | None,
    tests_config: dict[str, Any],
) -> bool:
    """Return whether a skip state matches the removed automatic rule."""

    category, subject, difficulty = _item_parts(item_or_label)
    if category not in AUTO_RED_CATEGORIES or not subject or not difficulty:
        # ILSAN_PAST is intentionally excluded: its popup rule never created
        # automatic exclusions, and old labels use a different difficulty map.
        return False

    level = _text(student.get("level")) if isinstance(student, dict) else ""
    if not level:
        return False

    rules = tests_config.get("autoAssignRules") if isinstance(tests_config, dict) else None
    levels = (((rules or {}).get(category) or {}).get(subject) or {}).get(difficulty)
    if not isinstance(levels, list):
        return False
    return level not in {_text(value) for value in levels}


def has_legacy_auto_rule(item_or_label: Any, tests_config: dict[str, Any]) -> bool:
    category, subject, difficulty = _item_parts(item_or_label)
    if category not in AUTO_RED_CATEGORIES or not subject or not difficulty:
        return False
    rules = tests_config.get("autoAssignRules") if isinstance(tests_config, dict) else None
    levels = (((rules or {}).get(category) or {}).get(subject) or {}).get(difficulty)
    return isinstance(levels, list)


def _status(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status")
    return _text(value)


def _skip_keys(tests: dict[str, Any]) -> list[str]:
    return [key for key, value in tests.items() if _status(value) == "skip"]


def _is_legacy_auto_batch(
    skip_values: list[Any],
    student: dict[str, Any] | None,
    tests_config: dict[str, Any],
) -> bool:
    if len(skip_values) < 3:
        return False
    return any(has_legacy_auto_rule(value, tests_config) for value in skip_values)


def repair_progress(
    progress: dict[str, Any],
    students_by_sid: dict[str, dict[str, Any]],
    tests_config: dict[str, Any],
) -> dict[str, int]:
    removed = 0
    changed_entries = 0

    for by_sid in progress.values():
        if not isinstance(by_sid, dict):
            continue
        for sid, entry in by_sid.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("tests"), dict):
                continue
            student = _student_for_sid(students_by_sid, sid)
            tests = entry["tests"]
            skip_keys = _skip_keys(tests)
            is_batch = _is_legacy_auto_batch(skip_keys, student, tests_config)
            remove_keys = [
                key
                for key in skip_keys
                if is_batch or is_legacy_auto_red(key, student, tests_config)
            ]
            if not remove_keys:
                continue
            for key in remove_keys:
                tests.pop(key, None)
            if not tests:
                entry.pop("tests", None)
            removed += len(remove_keys)
            changed_entries += 1

    return {"removed": removed, "changedEntries": changed_entries}


def _note_line_matches(line: str, removed_items: list[dict[str, Any]]) -> bool:
    if not any(marker in line for marker in NOTE_STATUS_MARKERS):
        return False
    normalized_line = _text(line)
    for item in removed_items:
        label = _text(item.get("label"))
        if not label:
            continue
        parts = [part.strip() for part in label.split(" / ")]
        if len(parts) >= 2:
            head = " / ".join(parts[:-1])
            name = parts[-1]
            if head in normalized_line and name in normalized_line:
                return True
        if label in normalized_line:
            return True
    return False


def _remove_legacy_red_note_lines(value: Any, removed_items: list[dict[str, Any]]) -> tuple[str, int]:
    text = _text(value)
    if not text or not removed_items:
        return text, 0
    lines = text.splitlines()
    kept = []
    removed = 0
    for line in lines:
        if _note_line_matches(line, removed_items):
            removed += 1
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, removed


def transform_log_entry(
    entry: dict[str, Any],
    sid: str,
    students_by_sid: dict[str, dict[str, Any]],
    tests_config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    out = dict(entry) if isinstance(entry, dict) else {}
    student = _student_for_sid(students_by_sid, sid)
    removed_items: list[dict[str, Any]] = []
    removed = 0
    all_items = [
        item
        for field in ("assignedTests", "testAssignmentDailyTests")
        for item in (out.get(field) if isinstance(out.get(field), list) else [])
        if isinstance(item, dict) and _status(item.get("status")) == "skip"
    ]
    is_batch = _is_legacy_auto_batch(all_items, student, tests_config)

    for field in ("assignedTests", "testAssignmentDailyTests"):
        items = out.get(field)
        if not isinstance(items, list):
            continue
        kept = []
        for item in items:
            if (
                isinstance(item, dict)
                and _status(item.get("status")) == "skip"
                and (is_batch or is_legacy_auto_red(item, student, tests_config))
            ):
                removed_items.append(item)
                removed += 1
            else:
                kept.append(item)
        if len(kept) != len(items):
            if kept:
                out[field] = kept
            else:
                out.pop(field, None)

    note_lines_removed = 0
    if removed_items:
        for field in ("testAssignmentNote", "notes"):
            if field not in out:
                continue
            cleaned, line_count = _remove_legacy_red_note_lines(out.get(field), removed_items)
            note_lines_removed += line_count
            if cleaned:
                out[field] = cleaned
            else:
                out.pop(field, None)

    return out, {"removed": removed, "noteLinesRemoved": note_lines_removed}


def _log_lock() -> InterProcessFileLock:
    return InterProcessFileLock(
        f"{LOGS_PATH}.lock",
        timeout_sec=30.0,
        poll_sec=0.05,
        stale_sec=30.0,
    )


def _entry_has_candidate(
    entry: Any,
    sid: str,
    students_by_sid: dict[str, dict[str, Any]],
    tests_config: dict[str, Any],
) -> bool:
    if not isinstance(entry, dict):
        return False
    student = _student_for_sid(students_by_sid, sid)
    skip_items = [
        item
        for field in ("assignedTests", "testAssignmentDailyTests")
        for item in (entry.get(field) if isinstance(entry.get(field), list) else [])
        if isinstance(item, dict) and _status(item.get("status")) == "skip"
    ]
    return _is_legacy_auto_batch(skip_items, student, tests_config) or any(
        is_legacy_auto_red(item, student, tests_config) for item in skip_items
    )


def collect_log_pairs(
    students_by_sid: dict[str, dict[str, Any]],
    tests_config: dict[str, Any],
) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    json_logs = load(LOGS_PATH) or {}
    if isinstance(json_logs, dict):
        for date, by_sid in json_logs.items():
            if not isinstance(by_sid, dict):
                continue
            for sid, entry in by_sid.items():
                if _entry_has_candidate(entry, str(sid), students_by_sid, tests_config):
                    pairs.add((str(date), str(sid)))

    try:
        con = sqlite3.connect(str(Path(LOGS_PATH).with_name("app.sqlite")))
        rows = con.execute("SELECT date, sid, entry_json FROM logs").fetchall()
        con.close()
    except (OSError, sqlite3.Error):
        rows = []
    for date, sid, raw in rows:
        try:
            entry = json.loads(raw or "{}")
        except (TypeError, ValueError):
            entry = {}
        if _entry_has_candidate(entry, str(sid), students_by_sid, tests_config):
            pairs.add((str(date), str(sid)))
    return pairs


def repair_logs(
    students_by_sid: dict[str, dict[str, Any]],
    tests_config: dict[str, Any],
    *,
    apply: bool,
) -> dict[str, int]:
    pairs = collect_log_pairs(students_by_sid, tests_config)
    summary = {"pairs": len(pairs), "removed": 0, "noteLinesRemoved": 0}

    def transform(entry: dict[str, Any], sid: str) -> tuple[dict[str, Any], bool]:
        next_entry, _counts = transform_log_entry(entry, sid, students_by_sid, tests_config)
        return next_entry, next_entry != entry

    json_logs = load(LOGS_PATH) or {}
    if pairs:
        for date, sid in pairs:
            entry = (json_logs.get(date) or {}).get(sid, {})
            _next_entry, counts = transform_log_entry(entry, sid, students_by_sid, tests_config)
            summary["removed"] += counts["removed"]
            summary["noteLinesRemoved"] += counts["noteLinesRemoved"]

    if apply and pairs:
        repo = LogRepository(logs_path=LOGS_PATH, lock_factory=_log_lock)
        repo.transform_entries(pairs, transform)

    return summary


def run(*, apply: bool) -> dict[str, Any]:
    students = load(STU_PATH) or []
    students_by_sid = {
        _text(student.get("id")): student
        for student in students
        if isinstance(student, dict) and _text(student.get("id"))
    }
    tests_config = load(TESTS_CFG_PATH) or {}

    progress_summary: dict[str, int]
    progress_lock = InterProcessFileLock(
        f"{PRG_PATH}.lock",
        timeout_sec=30.0,
        poll_sec=0.05,
        stale_sec=30.0,
    )
    with progress_lock:
        progress = load(PRG_PATH) or {}
        progress_summary = repair_progress(progress, students_by_sid, tests_config)
        if apply and progress_summary["removed"]:
            save_atomic(PRG_PATH, progress, compact=True)

    logs_summary = repair_logs(students_by_sid, tests_config, apply=apply)
    return {
        "apply": apply,
        "progress": progress_summary,
        "logs": logs_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the repair; without this flag only report candidate changes",
    )
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
