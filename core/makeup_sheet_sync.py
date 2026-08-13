from __future__ import annotations

import datetime as dt
import re
from typing import Any

from core.absent import load_absent, save_absent
from core.makeup_sheet_reader import read_sheet_makeup_rows, sheet_cell
from core.paths import ABS_PATH, EXTRA_PATH, STU_PATH, WEEKEND_SLOTS_PATH
from core.storage import file_lock, load, save_atomic


WEEKDAY_CHARS = "월화수목금토일"


def sync_makeups_from_sheet(sheet_url: str, date_key: str, carryover: dict[str, Any]) -> dict[str, Any]:
    target_date = dt.date.fromisoformat(str(date_key).split("T")[0])
    students = _student_rows(load(STU_PATH))
    date_columns, student_matches = read_sheet_makeup_rows(sheet_url, target_date, students)

    absent = load_absent()
    extra = _plain_dict(load(EXTRA_PATH))
    weekend = _plain_dict(load(WEEKEND_SLOTS_PATH))
    next_carryover = _normalize_carryover(carryover)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    sheet_seen_sids: set[str] = set()
    sheet_makeup_dates: dict[str, set[str]] = {}
    sheet_star_keys: set[tuple[str, str, int]] = set()
    changes: list[dict[str, Any]] = []
    month_prefix = f"{target_date.year}-{target_date.month:02d}"

    for row_index, row, student in student_matches:
        sid = str(student.get("id") or "").strip()
        if not sid:
            continue
        sheet_seen_sids.add(sid)
        for col_index, absence_date in date_columns.items():
            cell = sheet_cell(row, col_index)
            if "보" in cell:
                sheet_makeup_dates.setdefault(sid, set()).add(absence_date)
            if "*" not in cell:
                continue
            slots = _slots_for_absence(student, absence_date, cell)
            for slot in slots:
                key = (absence_date, sid, slot)
                sheet_star_keys.add(key)
                _ensure_absent_slot(absent, absence_date, sid, slot, changes)
                _open_carryover(next_carryover, absence_date, sid, slot, cell, now, changes)

    _cancel_stale_sheet_open_rows(next_carryover, sheet_star_keys, month_prefix, now, changes)
    _cancel_stale_scheduled_rows(
        next_carryover,
        extra,
        weekend,
        sheet_seen_sids,
        sheet_makeup_dates,
        month_prefix,
        now,
        changes,
    )

    # Sheet parsing can take long enough for an administrator to recover an
    # unrelated absence. Rebase only this sheet's additive star cells onto the
    # newest absence snapshot while holding the same lock as the API writers.
    with file_lock(ABS_PATH):
        latest_absent = load_absent()
        for absence_date, sid, slot in sorted(sheet_star_keys):
            _ensure_absent_slot(latest_absent, absence_date, sid, slot, [])
        save_absent(latest_absent, locked=True)
        absent = load_absent()
    save_atomic(EXTRA_PATH, extra)
    save_atomic(WEEKEND_SLOTS_PATH, weekend)

    return {
        "ok": True,
        "syncedAt": now,
        "month": f"{target_date.year}-{target_date.month:02d}",
        "matchedRows": len(student_matches),
        "sheetStudentCount": len(sheet_seen_sids),
        "opened": _count_changes(changes, "open"),
        "cancelled": _count_changes(changes, "cancel"),
        "attendanceRemoved": _count_changes(changes, "remove-attendance"),
        "changes": changes[:100],
        "absent": load_absent(),
        "carryover": next_carryover,
        "extra": extra,
        "weekendSlots": weekend,
    }


def _student_rows(raw: Any) -> list[dict[str, Any]]:
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _slots_for_absence(student: dict[str, Any], date_key: str, cell: str) -> list[int]:
    regular = _regular_slots(student, date_key)
    if regular:
        return regular
    if "6시" in cell:
        return [2]
    return [1]


def _regular_slots(student: dict[str, Any], date_key: str) -> list[int]:
    weekday = WEEKDAY_CHARS[dt.date.fromisoformat(date_key).weekday()]
    slots: set[int] = set()
    for index in range(1, 6):
        raw = str(student.get(f"day{index}") or "")
        if not raw or "자습" in raw or weekday not in raw:
            continue
        for slot_raw in re.findall(r"[123]", raw):
            slot = int(slot_raw)
            if slot in {1, 2}:
                slots.add(slot)
    return sorted(slots) or []


def _ensure_absent_slot(absent: dict[str, Any], date_key: str, sid: str, slot: int, changes: list[dict[str, Any]]) -> None:
    by_date = absent.setdefault("by_date", {})
    ids = by_date.setdefault(date_key, [])
    if sid not in ids:
        ids.append(sid)
        changes.append({"kind": "open", "type": "absent.add", "date": date_key, "sid": sid})
    by_slot = absent.setdefault("by_slot", {})
    slots = by_slot.setdefault(date_key, {}).setdefault(sid, [])
    if slot not in slots:
        slots.append(slot)
        slots.sort()
        changes.append({"kind": "open", "type": "absent.slot", "date": date_key, "sid": sid, "slot": slot})
    absent.setdefault("by_student", {})[sid] = date_key


def _normalize_carryover(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "by_absence": _plain_dict(raw.get("by_absence")),
        "manual": _plain_dict(raw.get("manual")),
    }


def _plain_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _open_carryover(
    carryover: dict[str, Any],
    date_key: str,
    sid: str,
    slot: int,
    cell: str,
    now: str,
    changes: list[dict[str, Any]],
) -> None:
    row_key = f"{sid}|{slot}"
    rows = carryover.setdefault("by_absence", {}).setdefault(date_key, {})
    previous = rows.get(row_key) if isinstance(rows.get(row_key), dict) else {}
    schedule = previous.get("scheduledMakeup") if isinstance(previous, dict) else None
    next_row = {
        **previous,
        "state": "open",
        "updatedAt": now,
        "note": f"sheet-sync: {cell[:80]}",
    }
    if isinstance(schedule, dict) and str(schedule.get("status") or "scheduled") == "scheduled":
        next_row["scheduledMakeup"] = {**schedule, "status": "cancelled", "updatedAt": now}
        next_row["missedScheduledMakeup"] = schedule
    rows[row_key] = next_row
    changes.append({"kind": "open", "type": "carryover.open", "date": date_key, "sid": sid, "slot": slot})


def _cancel_stale_sheet_open_rows(
    carryover: dict[str, Any],
    sheet_star_keys: set[tuple[str, str, int]],
    month_prefix: str,
    now: str,
    changes: list[dict[str, Any]],
) -> None:
    for date_key, rows in list(carryover.get("by_absence", {}).items()):
        if not str(date_key).startswith(month_prefix):
            continue
        if not isinstance(rows, dict):
            continue
        for row_key, row in list(rows.items()):
            if not isinstance(row, dict) or row.get("state") != "open":
                continue
            if not str(row.get("note") or "").startswith("sheet-sync:"):
                continue
            sid, slot = _row_sid_slot(row_key)
            if not sid or (date_key, sid, slot) in sheet_star_keys:
                continue
            row["state"] = "carried"
            row["updatedAt"] = now
            changes.append({"kind": "cancel", "type": "carryover.close-stale", "date": date_key, "sid": sid, "slot": slot})


def _cancel_stale_scheduled_rows(
    carryover: dict[str, Any],
    extra: dict[str, Any],
    weekend: dict[str, Any],
    sheet_seen_sids: set[str],
    sheet_makeup_dates: dict[str, set[str]],
    month_prefix: str,
    now: str,
    changes: list[dict[str, Any]],
) -> None:
    for date_key, rows in list(carryover.get("by_absence", {}).items()):
        if not isinstance(rows, dict):
            continue
        for row_key, row in list(rows.items()):
            if not isinstance(row, dict):
                continue
            schedule = row.get("scheduledMakeup")
            if not isinstance(schedule, dict) or str(schedule.get("status") or "scheduled") != "scheduled":
                continue
            sid = str(schedule.get("studentId") or _row_sid_slot(row_key)[0]).strip()
            makeup_date = str(schedule.get("makeupDate") or "").strip()
            if not sid or not makeup_date.startswith(month_prefix):
                continue
            if sid in sheet_seen_sids and makeup_date in sheet_makeup_dates.get(sid, set()):
                continue
            schedule["status"] = "cancelled"
            schedule["updatedAt"] = now
            row["updatedAt"] = now
            _release_attendance(extra, weekend, sid, schedule, changes)
            changes.append({"kind": "cancel", "type": "scheduled.cancel-stale", "date": date_key, "sid": sid, "makeupDate": makeup_date})


def _row_sid_slot(row_key: str) -> tuple[str, int]:
    pieces = str(row_key or "").split("|", 1)
    sid = pieces[0].strip()
    try:
        slot = int(pieces[1]) if len(pieces) > 1 else 1
    except ValueError:
        slot = 1
    return sid, slot if slot in {1, 2} else 1


def _release_attendance(extra: dict[str, Any], weekend: dict[str, Any], sid: str, schedule: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    makeup_date = str(schedule.get("makeupDate") or "").strip()
    if not makeup_date:
        return
    if schedule.get("ownedExtra") is True and isinstance(extra.get(makeup_date), list):
        next_ids = [item for item in extra[makeup_date] if str(item) != sid]
        if len(next_ids) != len(extra[makeup_date]):
            if next_ids:
                extra[makeup_date] = next_ids
            else:
                extra.pop(makeup_date, None)
            changes.append({"kind": "remove-attendance", "type": "extra.remove", "date": makeup_date, "sid": sid})
    slots_to_remove = _slot_list(schedule.get("ownedSlots") or schedule.get("makeupTimes"))
    day_slots = weekend.get(makeup_date)
    if not slots_to_remove or not isinstance(day_slots, dict) or sid not in day_slots:
        return
    next_slots = [slot for slot in _slot_list(day_slots.get(sid)) if slot not in slots_to_remove]
    if next_slots:
        day_slots[sid] = next_slots
    else:
        day_slots.pop(sid, None)
    if not day_slots:
        weekend.pop(makeup_date, None)
    changes.append({"kind": "remove-attendance", "type": "weekend.remove", "date": makeup_date, "sid": sid, "slots": slots_to_remove})


def _slot_list(value: Any) -> list[int]:
    values = value if isinstance(value, list) else [value]
    out: list[int] = []
    for item in values:
        try:
            slot = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if slot in {1, 2} and slot not in out:
            out.append(slot)
    return sorted(out)


def _count_changes(changes: list[dict[str, Any]], kind: str) -> int:
    return sum(1 for change in changes if change.get("kind") == kind)
