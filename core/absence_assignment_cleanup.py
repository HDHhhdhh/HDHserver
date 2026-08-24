from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable

from core.progress_rules import advance_test_assignment_change_order
from core.progress_store import load_progress_strict, save_progress_strict
from core.storage import file_lock, load, save_atomic


ASSIGNMENT_LOG_CLEAR_FIELDS = (
    "assignedTests",
    "testAssignmentNote",
    "assignedExtraVideos",
    "extraVideoAssignmentNote",
)
ASSIGNMENT_NOTE_FIELDS = ("testAssignmentNote", "extraVideoAssignmentNote")
TEST_ASSIGN_DAILY_ITEMS_KEY = "testAssignmentDailyTests"
TEST_ASSIGN_ABSENCE_CARRYOVER_KEY = "testAssignmentAbsenceCarryover"
KST = dt.timezone(dt.timedelta(hours=9))


def _now_kst_iso() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def _sid_keys(sid: str) -> list[str]:
    key = str(sid or "").strip()
    keys = [key]
    if key.isdigit():
        numeric = str(int(key))
        if numeric not in keys:
            keys.append(numeric)
    return [item for item in keys if item]


def _sid_lookup(mapping: dict, sid: str):
    if not isinstance(mapping, dict):
        return None
    for key in _sid_keys(sid):
        if key in mapping:
            return mapping.get(key)
    return None


def _write_sid_mapping(mapping: dict, sid: str, value) -> None:
    key = str(sid or "").strip()
    if not key:
        return
    numeric = str(int(key)) if key.isdigit() else None
    if numeric and numeric != key:
        mapping.pop(numeric, None)
    if value is None:
        mapping.pop(key, None)
    else:
        mapping[key] = value


def _remove_generated_note_block(notes: str, block: Any) -> tuple[str, bool]:
    notes_s = str(notes or "")
    block_s = str(block or "").strip()
    if not notes_s.strip() or not block_s or block_s not in notes_s:
        return notes_s, False
    next_notes = notes_s.replace(block_s, "")
    next_notes = re.sub(r"\n{3,}", "\n\n", next_notes).strip()
    return next_notes, next_notes != notes_s.strip()


def _test_assignment_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    label = str(raw.get("label") or "").strip()
    if label:
        return label
    pieces = [
        raw.get("categoryLabel") or raw.get("category"),
        raw.get("curriculum"),
        raw.get("difficulty"),
        raw.get("term"),
        raw.get("round"),
        raw.get("name"),
    ]
    return " / ".join(str(value).strip() for value in pieces if str(value or "").strip())


def _normalize_assignment_status(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("status")
    status = str(value or "").strip()
    if status == "none":
        return ""
    if status in {"assigned", "done", "interrupted", "skip"}:
        return status
    return "assigned" if status else ""


def _assignment_status_label(status: str) -> str:
    normalized = _normalize_assignment_status(status)
    if normalized == "done":
        return "완료"
    if normalized == "interrupted":
        return "배부"
    if normalized == "skip":
        return "제외"
    return "배정" if normalized else ""


def absence_test_status_value(value: Any) -> Any:
    status = _normalize_assignment_status(value)
    if status == "assigned":
        status = "interrupted"
    if not status:
        return value
    if isinstance(value, dict):
        return {**value, "status": status}
    return status


def _absence_test_item(raw: dict) -> tuple[dict, bool]:
    item = dict(raw)
    before = _normalize_assignment_status(item.get("status"))
    after = "interrupted" if before == "assigned" else before
    if not after:
        return item, False
    changed = False
    if item.get("status") != after:
        item["status"] = after
        changed = True
    label = _assignment_status_label(after)
    if label and item.get("statusLabel") != label:
        item["statusLabel"] = label
        changed = True
    return item, changed


def _absence_test_items(items: Any) -> tuple[list[Any] | None, bool]:
    if not isinstance(items, list):
        return None, False
    changed = False
    out: list[Any] = []
    for raw in items:
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        item, item_changed = _absence_test_item(raw)
        out.append(item)
        changed = changed or item_changed
    return out, changed


def _merge_assignment_items(*groups: list[dict]) -> list[dict]:
    by_label: dict[str, dict] = {}
    for group in groups:
        if not isinstance(group, list):
            continue
        for raw in group:
            if not isinstance(raw, dict):
                continue
            label = _test_assignment_label(raw)
            if not label:
                continue
            status = _normalize_assignment_status(raw.get("status"))
            if status in {"", "skip"}:
                continue
            item = dict(raw)
            item["label"] = label
            item["status"] = status
            by_label[label] = {**by_label.get(label, {}), **item}
    return list(by_label.values())


def _progress_test_items(tests: Any) -> list[dict]:
    if not isinstance(tests, dict):
        return []
    out: list[dict] = []
    for label_raw, status_raw in tests.items():
        label = str(label_raw or "").strip()
        status = _normalize_assignment_status(status_raw)
        if label and status and status != "skip":
            out.append({"label": label, "status": status})
    return out


def _collect_absence_test_carryovers(
    pairs: set[tuple[str, str]],
    *,
    progress_path: Any,
    log_repository_factory: Callable[[], Any],
) -> dict[tuple[str, str], dict]:
    if not pairs:
        return {}

    progress = load_progress_strict(progress_path)
    if not isinstance(progress, dict):
        progress = {}
    repository = log_repository_factory()
    log_entries = {
        (date_key, sid): repository.read_entry(date_key, sid).entry
        for date_key, sid in sorted(pairs)
    }
    return collect_absence_test_carryovers_from_state(
        pairs,
        progress=progress,
        log_entries=log_entries,
    )


def collect_absence_test_carryovers_from_state(
    pairs: set[tuple[str, str]],
    *,
    progress: dict,
    log_entries: dict[tuple[str, str], dict],
) -> dict[tuple[str, str], dict]:
    """Project carryover rows from a consistent pre-mutation snapshot."""
    out: dict[tuple[str, str], dict] = {}

    for date_key, sid in sorted(pairs):
        log_entry = log_entries.get((date_key, sid), {})
        if not isinstance(log_entry, dict):
            log_entry = {}
        progress_day = progress.get(date_key) if isinstance(progress, dict) else {}
        progress_entry = _sid_lookup(progress_day if isinstance(progress_day, dict) else {}, sid)
        if not isinstance(progress_entry, dict):
            progress_entry = {}

        daily_items = log_entry.get(TEST_ASSIGN_DAILY_ITEMS_KEY)
        assigned_items = log_entry.get("assignedTests")
        items = _merge_assignment_items(
            daily_items if isinstance(daily_items, list) else [],
            assigned_items if isinstance(assigned_items, list) else [],
            _progress_test_items(progress_entry.get("tests")),
        )
        if items:
            out[(date_key, sid)] = {
                "sourceDate": date_key,
                "assignedTests": items,
                "createdAt": _now_kst_iso(),
            }
    return out


def cleared_assignment_log_entry(
    entry: dict,
    sid: str,
    carryover: dict | None = None,
) -> tuple[dict, bool]:
    if (not isinstance(entry, dict) or not entry) and not carryover:
        return {}, False

    next_entry = dict(entry) if isinstance(entry, dict) else {}
    changed = False
    notes = str(next_entry.get("notes") or "")

    carryover_items = _merge_assignment_items(
        (carryover or {}).get("assignedTests") if isinstance(carryover, dict) else []
    )
    if carryover_items:
        current = next_entry.get(TEST_ASSIGN_ABSENCE_CARRYOVER_KEY)
        current_items = current.get("assignedTests") if isinstance(current, dict) else []
        next_entry[TEST_ASSIGN_ABSENCE_CARRYOVER_KEY] = {
            **(current if isinstance(current, dict) else {}),
            "sourceDate": str((carryover or {}).get("sourceDate") or ""),
            "assignedTests": _merge_assignment_items(
                current_items if isinstance(current_items, list) else [],
                carryover_items,
            ),
            "createdAt": (current if isinstance(current, dict) else {}).get("createdAt")
            or (carryover or {}).get("createdAt")
            or _now_kst_iso(),
        }
        changed = True

    for note_key in ASSIGNMENT_NOTE_FIELDS:
        notes, note_changed = _remove_generated_note_block(notes, next_entry.get(note_key))
        changed = changed or note_changed

    for field in (TEST_ASSIGN_DAILY_ITEMS_KEY, "assignedTests"):
        items, items_changed = _absence_test_items(next_entry.get(field))
        if items_changed and items is not None:
            next_entry[field] = items
            changed = True

    for field in ASSIGNMENT_LOG_CLEAR_FIELDS:
        if field == "assignedTests":
            continue
        if field in next_entry:
            next_entry.pop(field, None)
            changed = True

    if changed:
        if notes.strip():
            next_entry["notes"] = notes.strip()
        else:
            next_entry.pop("notes", None)
        next_entry["updatedAt"] = _now_kst_iso()

    return next_entry, changed


def _clear_absence_update_assignments(
    pairs: set[tuple[str, str]],
    *,
    updates_path: Any,
) -> None:
    if not pairs:
        return

    with file_lock(updates_path, timeout_sec=8.0):
        updates = load(updates_path) or {}
        if not isinstance(updates, dict):
            return
        updates, changed = clear_absence_update_assignments_map(updates, pairs)
        if changed:
            save_atomic(updates_path, updates)


def clear_absence_update_assignments_map(
    updates: dict,
    pairs: set[tuple[str, str]],
) -> tuple[dict, bool]:
    """Return a copy with only the supplied date/SID assignments removed."""
    next_updates = dict(updates) if isinstance(updates, dict) else {}
    copied_dates: set[str] = set()
    changed = False

    for date_key, sid in sorted(pairs):
        day = next_updates.get(date_key)
        if not isinstance(day, dict) or _sid_lookup(day, sid) is None:
            continue
        if date_key not in copied_dates:
            day = dict(day)
            next_updates[date_key] = day
            copied_dates.add(date_key)
        _write_sid_mapping(day, sid, None)
        if not day:
            next_updates.pop(date_key, None)
        changed = True

    return next_updates, changed


def clear_absence_progress_tests(
    pairs: set[tuple[str, str]],
    *,
    progress_path: Any,
) -> None:
    if not pairs:
        return

    with file_lock(progress_path, timeout_sec=8.0):
        progress, changed = transition_absence_progress_tests_map(
            load_progress_strict(progress_path),
            pairs,
        )
        if changed:
            save_progress_strict(progress_path, progress)


def transition_absence_progress_tests_map(
    progress: dict,
    pairs: set[tuple[str, str]],
) -> tuple[dict, bool]:
    """Return a copy whose assigned tests become interrupted for the pairs."""
    next_progress = dict(progress) if isinstance(progress, dict) else {}
    copied_dates: set[str] = set()
    changed = False

    for date_key, sid in sorted(pairs):
        day = next_progress.get(date_key)
        if not isinstance(day, dict):
            continue
        entry = _sid_lookup(day, sid)
        if not isinstance(entry, dict) or "tests" not in entry:
            continue
        tests = entry.get("tests")
        if not isinstance(tests, dict):
            continue
        next_tests = {
            str(label): absence_test_status_value(status)
            for label, status in tests.items()
            if str(label).strip()
        }
        if next_tests == tests:
            continue
        if date_key not in copied_dates:
            day = dict(day)
            next_progress[date_key] = day
            copied_dates.add(date_key)
        next_entry = dict(entry)
        if next_tests:
            next_entry["tests"] = next_tests
        else:
            next_entry.pop("tests", None)
        changed_test_labels = [
            str(label)
            for label, status in tests.items()
            if _normalize_assignment_status(status)
            != _normalize_assignment_status(next_tests.get(str(label)))
        ]
        next_entry = advance_test_assignment_change_order(next_entry, changed_test_labels)
        _write_sid_mapping(day, sid, next_entry if next_entry else None)
        if not day:
            next_progress.pop(date_key, None)
        changed = True

    return next_progress, changed


def _clear_absence_log_assignments(
    pairs: set[tuple[str, str]],
    *,
    carryovers: dict[tuple[str, str], dict] | None,
    log_repository_factory: Callable[[], Any],
) -> None:
    if not pairs:
        return

    repository = log_repository_factory()
    carryovers = carryovers or {}
    for pair in sorted(pairs):
        carryover = carryovers.get(pair)
        repository.transform_entries(
            {pair},
            lambda entry, sid, carryover=carryover: cleared_assignment_log_entry(
                entry,
                sid,
                carryover,
            ),
        )


def clear_assignments_for_new_absences(
    pairs: set[tuple[str, str]],
    *,
    updates_path: Any,
    progress_path: Any,
    log_repository_factory: Callable[[], Any],
) -> None:
    """Clear only the date/SID assignments affected by newly registered absences."""
    test_carryovers = _collect_absence_test_carryovers(
        pairs,
        progress_path=progress_path,
        log_repository_factory=log_repository_factory,
    )
    _clear_absence_update_assignments(pairs, updates_path=updates_path)
    clear_absence_progress_tests(pairs, progress_path=progress_path)
    _clear_absence_log_assignments(
        pairs,
        carryovers=test_carryovers,
        log_repository_factory=log_repository_factory,
    )


__all__ = (
    "absence_test_status_value",
    "clear_absence_update_assignments_map",
    "clear_absence_progress_tests",
    "clear_assignments_for_new_absences",
    "cleared_assignment_log_entry",
    "collect_absence_test_carryovers_from_state",
    "transition_absence_progress_tests_map",
)
