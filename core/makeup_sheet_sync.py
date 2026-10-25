from __future__ import annotations

import copy
import datetime as dt
import re
from typing import Any

from core.absent import load_absent
from core.makeup_sheet_reader import read_sheet_makeup_snapshot, sheet_cell
from core.paths import EXTRA_PATH, STU_PATH, WEEKEND_SLOTS_PATH
from core.storage import load


WEEKDAY_CHARS = "월화수목금토일"
SHEET_SYNC_MAX_ROW = 127


def read_additive_sheet_candidates(sheet_url: str, date_key: str) -> dict[str, Any]:
    target_date = dt.date.fromisoformat(str(date_key).split("T")[0])
    students = _student_rows(load(STU_PATH))
    snapshot = read_sheet_makeup_snapshot(
        sheet_url,
        target_date,
        students,
        max_sheet_row=SHEET_SYNC_MAX_ROW,
    )
    date_columns = snapshot["dateColumns"]
    student_matches = snapshot["studentMatches"]
    unmatched = snapshot.get("unmatchedStarredRows") or []
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()

    for row_index, row, student in student_matches:
        sid = str(student.get("id") or "").strip()
        if not sid:
            continue
        for col_index, absence_date in date_columns.items():
            cell = sheet_cell(row, col_index)
            if "*" not in cell:
                continue
            for slot in _slots_for_absence(student, absence_date, cell):
                key = (absence_date, sid, slot)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    "date": absence_date,
                    "sid": sid,
                    "slot": slot,
                    "cell": cell[:80],
                    "sheetRow": row_index,
                })

    return {
        "month": f"{target_date.year}-{target_date.month:02d}",
        "matchedRows": len(student_matches),
        "sheetStudentCount": len({str(student.get("id") or "").strip() for _, _, student in student_matches}),
        "maxSheetRow": SHEET_SYNC_MAX_ROW,
        "unmatchedStarredRows": len(unmatched),
        "ambiguousStarredRows": sum(1 for row in unmatched if row.get("reason") == "ambiguous"),
        "unmatchedStarredDetails": copy.deepcopy(unmatched[:20]),
        "candidates": candidates,
    }


def read_additive_sheet_candidate_window(
    sheet_url: str,
    date_key: str,
    *,
    months_back: int = 1,
) -> dict[str, Any]:
    target_date = dt.date.fromisoformat(str(date_key).split("T")[0])
    safe_months_back = max(0, min(int(months_back), 3))
    snapshots: list[dict[str, Any]] = []
    month_errors: list[dict[str, str]] = []

    for offset in range(-safe_months_back, 1):
        absolute_month = target_date.year * 12 + target_date.month - 1 + offset
        year, zero_month = divmod(absolute_month, 12)
        anchor = dt.date(year, zero_month + 1, 1)
        try:
            snapshots.append(read_additive_sheet_candidates(sheet_url, anchor.isoformat()))
        except RuntimeError as exc:
            month_errors.append({"month": anchor.strftime("%Y-%m"), "error": str(exc)})

    if not snapshots:
        detail = month_errors[-1]["error"] if month_errors else "시트에서 날짜 열을 찾지 못했습니다."
        raise RuntimeError(detail)

    candidate_map: dict[tuple[str, str, int], dict[str, Any]] = {}
    unmatched_details: list[dict[str, Any]] = []
    months: list[dict[str, Any]] = []
    for snapshot in snapshots:
        months.append({
            "month": snapshot["month"],
            "matchedRows": snapshot["matchedRows"],
            "sheetStudentCount": snapshot["sheetStudentCount"],
            "candidateCount": len(snapshot["candidates"]),
            "unmatchedStarredRows": snapshot.get("unmatchedStarredRows", 0),
        })
        for candidate in snapshot["candidates"]:
            key = (
                str(candidate.get("date") or ""),
                str(candidate.get("sid") or ""),
                int(candidate.get("slot") or 0),
            )
            candidate_map[key] = candidate
        for row in snapshot.get("unmatchedStarredDetails") or []:
            unmatched_details.append({"month": snapshot["month"], **copy.deepcopy(row)})

    return {
        "month": target_date.strftime("%Y-%m"),
        "months": months,
        "monthErrors": month_errors,
        "matchedRows": max(snapshot["matchedRows"] for snapshot in snapshots),
        "sheetStudentCount": max(snapshot["sheetStudentCount"] for snapshot in snapshots),
        "maxSheetRow": SHEET_SYNC_MAX_ROW,
        "unmatchedStarredRows": sum(int(snapshot.get("unmatchedStarredRows") or 0) for snapshot in snapshots),
        "ambiguousStarredRows": sum(int(snapshot.get("ambiguousStarredRows") or 0) for snapshot in snapshots),
        "unmatchedStarredDetails": unmatched_details[:20],
        "candidates": [candidate_map[key] for key in sorted(candidate_map)],
    }


def partition_excluded_sheet_candidates(
    candidates: list[dict[str, Any]],
    exclusions: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    excluded_pairs = {
        (str(row.get("date") or "").strip(), str(row.get("sid") or "").strip())
        for row in (exclusions if isinstance(exclusions, list) else [])
        if isinstance(row, dict)
        and str(row.get("date") or "").strip()
        and str(row.get("sid") or "").strip()
    }
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        key = (
            str(candidate.get("date") or "").strip(),
            str(candidate.get("sid") or "").strip(),
        )
        (excluded if key in excluded_pairs else included).append(candidate)
    return included, excluded


def merge_additive_sheet_absences(
    carryover: dict[str, Any],
    absent: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    next_carryover = _normalize_carryover(carryover)
    baseline_absent = _normalize_absent(absent)
    next_absent = copy.deepcopy(baseline_absent)
    timestamp = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    scheduled_ids = _scheduled_original_absence_ids(next_carryover)
    changes: list[dict[str, Any]] = []
    skipped_existing = 0
    protected_scheduled = 0
    added = 0
    added_sids: set[str] = set()
    added_pairs: set[tuple[str, str]] = set()
    seen: set[tuple[str, str, int]] = set()

    for candidate in sorted(candidates, key=_candidate_sort_key):
        date_key = str(candidate.get("date") or "").strip()
        sid = str(candidate.get("sid") or "").strip()
        try:
            slot = int(candidate.get("slot"))
        except (TypeError, ValueError):
            continue
        if not date_key or not sid or slot not in {1, 2}:
            continue
        key = (date_key, sid, slot)
        if key in seen:
            continue
        seen.add(key)

        reason = _existing_candidate_reason(
            next_carryover,
            baseline_absent,
            date_key,
            sid,
            slot,
            scheduled_ids,
        )
        if reason == "absence":
            skipped_existing += 1
            changes.append({
                "kind": "skip",
                "type": reason,
                "date": date_key,
                "sid": sid,
                "slot": slot,
            })
            continue

        if reason == "scheduled":
            protected_scheduled += 1
        if reason in {"scheduled", "carryover"}:
            changes.append({
                "kind": "preserve",
                "type": reason,
                "date": date_key,
                "sid": sid,
                "slot": slot,
            })

        _ensure_absent_slot(next_absent, date_key, sid, slot, changes)
        if not reason:
            _additive_open_carryover(
                next_carryover,
                date_key,
                sid,
                slot,
                timestamp,
                changes,
            )
        added += 1
        added_sids.add(sid)
        added_pairs.add((date_key, sid))

    return {
        "added": added,
        "addedSids": sorted(added_sids),
        "addedPairs": [{"date": date, "sid": sid} for date, sid in sorted(added_pairs)],
        "skippedExisting": skipped_existing,
        "protectedScheduled": protected_scheduled,
        "changes": changes,
        "absent": next_absent,
        "carryover": next_carryover,
    }


def build_additive_sheet_sync_result(
    sheet: dict[str, Any],
    carryover: dict[str, Any],
    absent: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    extra = _plain_dict(load(EXTRA_PATH))
    weekend = _plain_dict(load(WEEKEND_SLOTS_PATH))
    timestamp = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    merged = merge_additive_sheet_absences(
        carryover,
        absent,
        sheet["candidates"],
        now=timestamp,
    )
    return {
        "ok": True,
        "mode": "additive-only",
        "syncedAt": timestamp,
        "month": sheet["month"],
        "months": copy.deepcopy(sheet.get("months") or []),
        "monthErrors": copy.deepcopy(sheet.get("monthErrors") or []),
        "matchedRows": sheet["matchedRows"],
        "sheetStudentCount": sheet["sheetStudentCount"],
        "maxSheetRow": SHEET_SYNC_MAX_ROW,
        "unmatchedStarredRows": int(sheet.get("unmatchedStarredRows") or 0),
        "ambiguousStarredRows": int(sheet.get("ambiguousStarredRows") or 0),
        "unmatchedStarredDetails": copy.deepcopy(sheet.get("unmatchedStarredDetails") or []),
        "opened": merged["added"],
        "added": merged["added"],
        "addedSids": merged["addedSids"],
        "addedPairs": merged["addedPairs"],
        "skippedExisting": merged["skippedExisting"],
        "protectedScheduled": merged["protectedScheduled"],
        "cancelled": 0,
        "attendanceRemoved": 0,
        "changes": merged["changes"][:100],
        "absent": merged["absent"],
        "carryover": merged["carryover"],
        "extra": extra,
        "weekendSlots": weekend,
    }


def sync_makeups_from_sheet(sheet_url: str, date_key: str, carryover: dict[str, Any]) -> dict[str, Any]:
    sheet = read_additive_sheet_candidate_window(sheet_url, date_key)
    return build_additive_sheet_sync_result(sheet, carryover, load_absent())


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


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[str, str, int]:
    try:
        slot = int(candidate.get("slot"))
    except (TypeError, ValueError):
        slot = 0
    return (
        str(candidate.get("date") or ""),
        str(candidate.get("sid") or ""),
        slot,
    )


def _normalize_absent(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "by_date": copy.deepcopy(source.get("by_date")) if isinstance(source.get("by_date"), dict) else {},
        "by_student": copy.deepcopy(source.get("by_student")) if isinstance(source.get("by_student"), dict) else {},
        "by_slot": copy.deepcopy(source.get("by_slot")) if isinstance(source.get("by_slot"), dict) else {},
    }


def _ensure_absent_slot(absent: dict[str, Any], date_key: str, sid: str, slot: int, changes: list[dict[str, Any]]) -> None:
    by_date = absent.setdefault("by_date", {})
    ids = by_date.setdefault(date_key, [])
    if sid not in {str(value) for value in ids}:
        ids.append(sid)
        changes.append({"kind": "add", "type": "absent.add", "date": date_key, "sid": sid})
    by_slot = absent.setdefault("by_slot", {})
    slots = by_slot.setdefault(date_key, {}).setdefault(sid, [])
    if slot not in _slot_list(slots):
        slots.append(slot)
        slots.sort()
        changes.append({"kind": "add", "type": "absent.slot", "date": date_key, "sid": sid, "slot": slot})
    by_student = absent.setdefault("by_student", {})
    previous_date = str(by_student.get(sid) or "").strip()
    if not previous_date or date_key >= previous_date:
        by_student[sid] = date_key


def _normalize_carryover(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "by_absence": copy.deepcopy(source.get("by_absence")) if isinstance(source.get("by_absence"), dict) else {},
        "manual": copy.deepcopy(source.get("manual")) if isinstance(source.get("manual"), dict) else {},
        **({"scheduleHistory": copy.deepcopy(source["scheduleHistory"])}
           if isinstance(source.get("scheduleHistory"), dict) else {}),
    }


def _plain_dict(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _active_schedule(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    schedule = row.get("scheduledMakeup") or row.get("scheduled_makeup")
    if not isinstance(schedule, dict):
        return None
    if str(schedule.get("status") or "scheduled").strip().lower() != "scheduled":
        return None
    return schedule


def _scheduled_original_absence_ids(carryover: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for group_name in ("by_absence", "manual"):
        groups = carryover.get(group_name)
        if not isinstance(groups, dict):
            continue
        for rows in groups.values():
            if not isinstance(rows, dict):
                continue
            for row in rows.values():
                schedule = _active_schedule(row)
                original_id = str(schedule.get("originalAbsenceId") or schedule.get("original_absence_id") or "").strip() if schedule else ""
                if original_id:
                    out.add(original_id)
    return out


def _existing_candidate_reason(
    carryover: dict[str, Any],
    absent: dict[str, Any],
    date_key: str,
    sid: str,
    slot: int,
    scheduled_ids: set[str],
) -> str:
    ids = absent.get("by_date", {}).get(date_key, [])
    if sid in {str(value) for value in ids if str(value).strip()}:
        return "absence"

    original_id = f"absence|{date_key}|{sid}|{slot}"
    if original_id in scheduled_ids:
        return "scheduled"

    date_rows = carryover.get("by_absence", {}).get(date_key, {})
    if isinstance(date_rows, dict):
        for row_key in (f"{sid}|{slot}", sid):
            if row_key not in date_rows:
                continue
            return "scheduled" if _active_schedule(date_rows.get(row_key)) else "carryover"

    manual_rows = carryover.get("manual", {}).get(date_key, {})
    if isinstance(manual_rows, dict):
        for row in manual_rows.values():
            if not isinstance(row, dict) or str(row.get("sid") or "").strip() != sid:
                continue
            row_slots = _slot_list(row.get("slots", row.get("slot")))
            if row.get("dateOnly") is True or row.get("date_only") is True or not row_slots or slot in row_slots:
                return "scheduled" if _active_schedule(row) else "carryover"

    return ""


def _additive_open_carryover(
    carryover: dict[str, Any],
    date_key: str,
    sid: str,
    slot: int,
    now: str,
    changes: list[dict[str, Any]],
) -> None:
    row_key = f"{sid}|{slot}"
    rows = carryover.setdefault("by_absence", {}).setdefault(date_key, {})
    if row_key in rows:
        return
    rows[row_key] = {
        "state": "open",
        "updatedAt": now,
        "note": "",
    }
    changes.append({"kind": "add", "type": "carryover.open", "date": date_key, "sid": sid, "slot": slot})


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
