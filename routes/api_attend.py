# /routes/api_attend.py
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Dict, List, Any

from flask import Blueprint, abort, jsonify, request

from core.paths import STU_PATH, EXTRA_PATH, ATTENDANCE_PATH, CONTACT_PATH, PRG_PATH, UPD_PATH, LOGS_PATH, ABS_PATH
from core.progress_rules import advance_test_assignment_change_order
from core.student_notification_hooks import enqueue_current_schedule_changes
from core.storage import load, save_atomic, file_lock
from core.absent import load_absent, save_absent, DATE_RE

bp_api_attend = Blueprint("api_attend", __name__)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _date_key_from_query(default: dt.date | None = None) -> str:
    if default is None:
        default = dt.date.today()
    date_str_full = request.args.get("date", default.isoformat())
    date_str = (date_str_full or default.isoformat()).split("T")[0]
    try:
        dt.date.fromisoformat(date_str)
    except ValueError:
        abort(400, description="Invalid date format")
    return date_str


def _norm_date(date_key: str) -> str:
    s = (str(date_key or "")).split("T")[0].strip()
    try:
        dt.date.fromisoformat(s)
    except Exception:
        abort(400, description="Invalid date format")
    return s


def _absence_revision(payload: dict) -> str:
    normalized = payload if isinstance(payload, dict) else {}
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _absence_response(payload: dict, status: int = 200, *, revision_payload: dict | None = None):
    response = jsonify(payload)
    response.status_code = status
    response.headers["X-Absence-Revision"] = _absence_revision(
        revision_payload if revision_payload is not None else payload
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _load_flag_all(path) -> Dict[str, Dict[str, int]]:
    """
    schema:
      {
        "YYYY-MM-DD": { "sid": 1, ... }
      }
    """
    try:
        data = load(path)
        if isinstance(data, dict):
            out: Dict[str, Dict[str, int]] = {}
            for dk, mp in data.items():
                if isinstance(dk, str) and isinstance(mp, dict):
                    out[dk] = {str(sid): 1 for sid in mp.keys() if str(sid).strip()}
            return out
    except Exception:
        pass
    return {}


def _save_flag_all(path, data: Dict[str, Dict[str, int]]) -> None:
    try:
        save_atomic(path, data)
    except Exception as e:
        abort(500, description=f"Failed to save: {e}")


def _patch_flag(path, date_key: str, sid: str, checked: bool) -> None:
    with file_lock(path):
        all_map = _load_flag_all(path)
        day = all_map.get(date_key)
        if not isinstance(day, dict):
            day = {}
            all_map[date_key] = day

        if checked:
            day[sid] = 1
        else:
            day.pop(sid, None)

        _save_flag_all(path, all_map)





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


def _absence_pairs(payload: Any) -> set[tuple[str, str]]:
    if not isinstance(payload, dict):
        return set()

    pairs: set[tuple[str, str]] = set()
    by_date = payload.get("by_date")
    if isinstance(by_date, dict):
        for date_raw, sids in by_date.items():
            date_key = str(date_raw or "").strip()
            if not DATE_RE.match(date_key) or not isinstance(sids, list):
                continue
            for sid_raw in sids:
                sid = str(sid_raw or "").strip()
                if sid:
                    pairs.add((date_key, sid))

    by_student = payload.get("by_student")
    if isinstance(by_student, dict):
        for sid_raw, date_raw in by_student.items():
            sid = str(sid_raw or "").strip()
            date_key = str(date_raw or "").strip()
            if sid and DATE_RE.match(date_key):
                pairs.add((date_key, sid))

    by_slot = payload.get("by_slot")
    if isinstance(by_slot, dict):
        for date_raw, sid_map in by_slot.items():
            date_key = str(date_raw or "").strip()
            if not DATE_RE.match(date_key) or not isinstance(sid_map, dict):
                continue
            for sid_raw, slots_raw in sid_map.items():
                sid = str(sid_raw or "").strip()
                if not sid:
                    continue
                slots = slots_raw if isinstance(slots_raw, list) else [slots_raw]
                if any(str(slot).strip() in {"1", "2"} for slot in slots):
                    pairs.add((date_key, sid))

    return pairs


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
    return " / ".join(str(x).strip() for x in pieces if str(x or "").strip())


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


def _absence_test_status_value(value: Any) -> Any:
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


def _collect_absence_test_carryovers(pairs: set[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    if not pairs:
        return {}
    from routes.api_basic import _load_progress_strict, _sid_lookup, get_log_repository

    progress = _load_progress_strict(PRG_PATH)
    if not isinstance(progress, dict):
        progress = {}
    repo = get_log_repository()
    out: dict[tuple[str, str], dict] = {}

    for date_key, sid in sorted(pairs):
        log_entry = repo.read_entry(date_key, sid).entry
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
                "createdAt": dt.datetime.now(KST).isoformat(timespec="seconds"),
            }
    return out


def _cleared_assignment_log_entry(entry: dict, sid: str, carryover: dict | None = None) -> tuple[dict, bool]:
    if (not isinstance(entry, dict) or not entry) and not carryover:
        return {}, False

    next_entry = dict(entry) if isinstance(entry, dict) else {}
    changed = False
    notes = str(next_entry.get("notes") or "")

    carryover_items = _merge_assignment_items((carryover or {}).get("assignedTests") if isinstance(carryover, dict) else [])
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
            or dt.datetime.now(KST).isoformat(timespec="seconds"),
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
        next_entry["updatedAt"] = dt.datetime.now(KST).isoformat(timespec="seconds")

    return next_entry, changed


def _clear_absence_update_assignments(pairs: set[tuple[str, str]]) -> None:
    if not pairs:
        return
    from routes.api_basic import _sid_lookup, _write_sid_mapping

    changed = False
    with file_lock(UPD_PATH, timeout_sec=8.0):
        updates = load(UPD_PATH) or {}
        if not isinstance(updates, dict):
            return

        for date_key, sid in sorted(pairs):
            day = updates.get(date_key)
            if not isinstance(day, dict):
                continue
            if _sid_lookup(day, sid) is None:
                continue
            _write_sid_mapping(day, sid, None)
            if not day:
                updates.pop(date_key, None)
            changed = True

        if changed:
            save_atomic(UPD_PATH, updates)


def _clear_absence_progress_tests(pairs: set[tuple[str, str]]) -> None:
    if not pairs:
        return
    from routes.api_basic import _load_progress_strict, _save_progress_strict, _sid_lookup, _write_sid_mapping

    changed = False
    with file_lock(PRG_PATH, timeout_sec=8.0):
        progress = dict(_load_progress_strict(PRG_PATH))
        copied_dates: set[str] = set()

        for date_key, sid in sorted(pairs):
            day = progress.get(date_key)
            if not isinstance(day, dict):
                continue
            entry = _sid_lookup(day, sid)
            if not isinstance(entry, dict) or "tests" not in entry:
                continue
            tests = entry.get("tests")
            if not isinstance(tests, dict):
                continue
            next_tests = {
                str(label): _absence_test_status_value(status)
                for label, status in tests.items()
                if str(label).strip()
            }
            if next_tests == tests:
                continue
            if date_key not in copied_dates:
                day = dict(day)
                progress[date_key] = day
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
                progress.pop(date_key, None)
            changed = True

        if changed:
            _save_progress_strict(progress, PRG_PATH)


def _clear_absence_log_assignments(
    pairs: set[tuple[str, str]],
    carryovers: dict[tuple[str, str], dict] | None = None,
) -> None:
    if not pairs:
        return
    from routes.api_basic import get_log_repository

    repo = get_log_repository()
    carryovers = carryovers or {}
    for pair in sorted(pairs):
        carryover = carryovers.get(pair)
        repo.transform_entries(
            {pair},
            lambda entry, sid, carryover=carryover: _cleared_assignment_log_entry(entry, sid, carryover),
        )


def _clear_assignments_for_new_absences(pairs: set[tuple[str, str]]) -> None:
    # Keep this date/sid-scoped; absence registration should not rewrite old runtime data.
    test_carryovers = _collect_absence_test_carryovers(pairs)
    _clear_absence_update_assignments(pairs)
    _clear_absence_progress_tests(pairs)
    _clear_absence_log_assignments(pairs, test_carryovers)


# ------------------------------------------------------------------
# Today students / date-scoped students
# ------------------------------------------------------------------
@bp_api_attend.get("/api/today")
def api_today():
    today = dt.date.today()
    wchr = "월화수목금토일"[today.weekday()]
    students_arr: List[dict] = load(STU_PATH)

    regular = [
        s for s in students_arr
        if any(((s.get(d, "") or "").startswith(wchr) for d in ("day1", "day2", "day3")))
    ]

    extra_ids = load(EXTRA_PATH).get(today.isoformat(), [])
    extra_students = [
        s for s in students_arr
        if str(s.get("id")) in map(str, extra_ids)
    ]

    all_today = {str(s["id"]): s for s in (regular + extra_students)}

    abs_all = load_absent()
    absent_ids = set(map(str, abs_all.get("by_date", {}).get(today.isoformat(), [])))
    for sid in list(all_today.keys()):
        if sid in absent_ids:
            del all_today[sid]

    return jsonify(list(all_today.values()))


@bp_api_attend.get("/api/attend")
def api_attend():
    date_str = _date_key_from_query()
    target = dt.date.fromisoformat(date_str)
    wchr = "월화수목금토일"[target.weekday()]

    students_arr: List[dict] = load(STU_PATH)

    regular = [
        s for s in students_arr
        if any(((s.get(d, "") or "").startswith(wchr) for d in ("day1", "day2", "day3")))
    ]

    extra_ids = load(EXTRA_PATH).get(target.isoformat(), [])
    extra_students = [
        s for s in students_arr
        if str(s.get("id")) in map(str, extra_ids)
    ]

    all_today = {str(s["id"]): s for s in (regular + extra_students)}

    abs_all = load_absent()
    absent_ids = set(map(str, abs_all.get("by_date", {}).get(target.isoformat(), [])))
    for sid in list(all_today.keys()):
        if sid in absent_ids:
            del all_today[sid]

    return jsonify(list(all_today.values()))


# ------------------------------------------------------------------
# Absent state overwrite
# ------------------------------------------------------------------
@bp_api_attend.get("/api/absent")
def api_absent_get():
    return _absence_response(load_absent())


@bp_api_attend.post("/api/absent")
def api_absent_post():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")
    with file_lock(ABS_PATH):
        before = load_absent()
        expected_revision = str(request.headers.get("If-Match") or "").strip().strip('"')
        if not expected_revision:
            return _absence_response(
                {"ok": False, "error": "absence_revision_required"},
                428,
                revision_payload=before,
            )
        if expected_revision and expected_revision != _absence_revision(before):
            return _absence_response(
                {"ok": False, "error": "absence_revision_conflict"},
                409,
                revision_payload=before,
            )
        before_pairs = _absence_pairs(before)
        after_pairs = _absence_pairs(payload)
        new_pairs = after_pairs - before_pairs
        if new_pairs:
            try:
                _clear_assignments_for_new_absences(new_pairs)
            except TimeoutError as e:
                abort(409, description=f"Failed to clear absence assignments: {e}")
            except Exception as e:
                abort(500, description=f"Failed to clear absence assignments: {e}")
        save_absent(payload, locked=True)
        saved = load_absent()
    enqueue_current_schedule_changes(sid for _date, sid in before_pairs ^ after_pairs)
    return _absence_response(saved)


@bp_api_attend.post("/api/absent/recover")
def api_absent_recover():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    date_key = _norm_date(str(payload.get("date") or ""))
    raw_sids = payload.get("sids")
    if not isinstance(raw_sids, list):
        abort(400, description="sids must be a list")
    selected = tuple(dict.fromkeys(
        str(value or "").strip() for value in raw_sids if str(value or "").strip()
    ))
    if not selected:
        abort(400, description="sids must not be empty")

    selected_set = set(selected)
    with file_lock(ABS_PATH):
        latest = load_absent()
        by_date = dict(latest.get("by_date") or {})
        by_student = dict(latest.get("by_student") or {})
        by_slot = {
            str(date): dict(sid_map) if isinstance(sid_map, dict) else {}
            for date, sid_map in (latest.get("by_slot") or {}).items()
        }

        by_date[date_key] = [
            sid for sid in (by_date.get(date_key) or [])
            if str(sid).strip() not in selected_set
        ]
        for sid in selected:
            if str(by_student.get(sid) or "") == date_key:
                by_student.pop(sid, None)
            by_slot.get(date_key, {}).pop(sid, None)
        if date_key in by_slot and not by_slot[date_key]:
            by_slot.pop(date_key, None)

        save_absent({"by_date": by_date, "by_student": by_student, "by_slot": by_slot}, locked=True)
        saved = load_absent()

    enqueue_current_schedule_changes(selected)
    return _absence_response(saved)


# ------------------------------------------------------------------
# Attendance
# ------------------------------------------------------------------
@bp_api_attend.get("/api/attendance")
def api_attendance_get():
    date_key = _date_key_from_query()
    all_map = _load_flag_all(ATTENDANCE_PATH)
    return jsonify(all_map.get(date_key, {}))





@bp_api_attend.post("/api/attendance/patch")
def api_attendance_patch():
    """
    Single-item patch for concurrent-safe writes.
    body: { "date":"YYYY-MM-DD", "sid":"...", "value": true/false }
    """
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    date_key = _norm_date(str(payload.get("date") or ""))
    sid = str(payload.get("sid") or "").strip()
    if not sid:
        abort(400, description="sid is required")

    checked = bool(payload.get("value", True))
    _patch_flag(ATTENDANCE_PATH, date_key, sid, checked)
    return jsonify({"ok": True, "date": date_key, "sid": sid, "value": 1 if checked else 0})


# ------------------------------------------------------------------
# Contact
# ------------------------------------------------------------------
@bp_api_attend.get("/api/contact")
def api_contact_get():
    date_key = _date_key_from_query()
    all_map = _load_flag_all(CONTACT_PATH)
    return jsonify(all_map.get(date_key, {}))





@bp_api_attend.post("/api/contact/patch")
def api_contact_patch():
    """
    Single-item patch for concurrent-safe writes.
    body: { "date":"YYYY-MM-DD", "sid":"...", "value": true/false }
    """
    payload: Any = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Invalid JSON body")

    date_key = _norm_date(str(payload.get("date") or ""))
    sid = str(payload.get("sid") or "").strip()
    if not sid:
        abort(400, description="sid is required")

    checked = bool(payload.get("value", True))
    _patch_flag(CONTACT_PATH, date_key, sid, checked)
    return jsonify({"ok": True, "date": date_key, "sid": sid, "value": 1 if checked else 0})

