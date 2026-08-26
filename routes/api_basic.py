from __future__ import annotations

import datetime as dt
import os
import random
import re
import time
import json
from copy import deepcopy
from urllib.parse import parse_qs, unquote, urlparse
from typing import List, Optional, Tuple, Dict, Any

from flask import Blueprint, abort, current_app, g, has_request_context, jsonify, make_response, request

from core.paths import (
    BASE,
    STU_PATH, VID_PATH, PRG_PATH, UPD_PATH, ASN_PATH, MAT_PATH, CAL_PATH, PAGE_FOLDERS_PATH,
    EXTRA_PATH, LOGS_PATH, CLINIC_PATH, WEEKEND_SLOTS_PATH,
    WATCH_PATH, TESTS_CFG_PATH,
)
try:
    from core.paths import PERSONS_PATH, PERSON_IDENTITY_JOURNAL_PATH
except ImportError:  # Compatibility for isolated route fixtures with a minimal paths stub.
    PERSONS_PATH = BASE / "persons.json"
    PERSON_IDENTITY_JOURNAL_PATH = BASE / "instance" / "person_identity_transactions" / "pending.json"
from core.ghost_student import (
    GHOST_STUDENT_ID,
    GHOST_STUDENT_WRITE_ERROR,
    is_ghost_student_sid,
    mapping_contains_ghost_student_sid,
)
from core.log_repository import LogRepository
from core import log_rules as _log_rules
from core.material_state import (
    MaterialStateConflictError,
    MaterialStateRecoveryRequiredError,
    load_material_state,
    load_material_state_last_good,
    material_state_revision,
    replace_material_state_component,
)
from core.network_access import (
    ACADEMY_ACCESS_MESSAGE,
    academy_network_allowed,
    ip_allowed,
    strip_answer_link_fields,
)
from core.progress_rules import (
    PROGRESS_ALL_STUDENTS_META_KEY,
    PROGRESS_MANUAL_META_KEY,
    TEST_ASSIGN_CLEAR_META_KEY,
    WATCH_AUTO_PROGRESS_META_KEY,
    latest_video_status_by_sid,
    merge_progress_day_sid as _merge_progress_day_sid,
    normalize_watch_entry as _normalize_watch_entry,
    watch_rank as _watch_rank,
    watch_auto_status as _watch_auto_status,
)
from core.progress_notifications import commit_progress_notifications, progress_notification_snapshot
from core.progress_store import load_progress_strict, progress_file_lock, save_progress_strict
from core.person_identity import (
    PERSON_PROFILE_FIELDS,
    PersonIdentityConflictError,
    PersonIdentityNotFoundError,
    PersonIdentityValidationError,
    allocate_unique_sid,
    same_person,
    validate_identity_state,
)
from core.person_identity_store import (
    PersonIdentityRecoveryRequiredError,
    PersonIdentityUnavailableError,
    create_student_with_identity,
    identity_is_configured,
    mutate_identity_state,
    retire_student_identity,
    update_person_profile_field,
)
from core.video_review_rules import resolve_video_review_states_before_date
from core.student_curriculum_progress import build_curriculum_progress
from core.student_schedule_projection import project_student_schedule, select_next_schedule
from core.student_notification_hooks import (
    enqueue_current_schedule_changes,
    student_schedule_changed_sids,
)
from core.test_answer_links import resolve_test_assignment_answer_url
from core.storage import InterProcessFileLock, file_lock, load, save_atomic, nocache_resp
from core.absent import load_absent, save_absent, DATE_RE

bp_api_basic = Blueprint("api_basic", __name__)

CT = {"Content-Type": "application/json"}
STUDENT_COURSE_BLOCK_MESSAGE = "수업일이 아닌 것 같습니다. 선생님께 문의주세용 ^_^"
GHOST_STUDENT_HOMEWORK_BOOK = "고스트 숙제 교재"
GHOST_STUDENT_VIDEO_MID = "ghost-outside-video"
GHOST_STUDENT_TEST_ID = "ghost-outside-answer-test"
_PERSON_PROFILE_FIELD_ALIASES = {
    "highSchool": "school",
    "middleSchool": "school",
}


def _person_identity_configured() -> bool:
    return identity_is_configured(
        PERSONS_PATH,
        PERSON_IDENTITY_JOURNAL_PATH,
        STU_PATH,
    )


def _person_identity_writes_degraded() -> bool:
    return bool(current_app.config.get("PERSON_IDENTITY_WRITES_DEGRADED"))


def _person_identity_error(message: str, status: int):
    return jsonify({"ok": False, "error": message, "code": "person_identity_unavailable"}), status


# ─────────────────────────────────────────────
# 공통 CRUD
# ─────────────────────────────────────────────
def crud(path):
    if request.method == "GET":
        return jsonify(load(path))
    obj = request.get_json(force=True)
    save_atomic(path, obj)
    return "", 204


def _load_material_state_for_read() -> tuple[dict, dict, dict, bool]:
    """Load one coherent snapshot; fall back without disabling the whole server."""
    try:
        materials, assignments, page_folders = load_material_state(
            MAT_PATH,
            ASN_PATH,
            PAGE_FOLDERS_PATH,
        )
    except Exception as primary_error:
        try:
            materials, assignments, page_folders = load_material_state_last_good(MAT_PATH)
        except Exception:
            current_app.logger.error(
                "Material state read degraded without a last-good snapshot: %s",
                primary_error,
            )
            return {}, {}, {}, True
        current_app.logger.warning(
            "Material state read is using the last-good snapshot: %s",
            primary_error,
        )
        return materials, assignments, page_folders, True
    return materials, assignments, page_folders, False


def _material_state_json_response(
    value: dict,
    materials: dict,
    assignments: dict,
    page_folders: dict,
    *,
    degraded: bool,
):
    response = make_response(jsonify(value))
    response.headers["X-Material-State-Revision"] = material_state_revision(
        materials,
        assignments,
        page_folders,
    )
    if degraded:
        response.headers["X-Material-State-Degraded"] = "1"
    return response


def _normalize_material_state_revision(value: str | None) -> str:
    revision = str(value or "").strip()
    if revision.startswith("W/"):
        revision = revision[2:].strip()
    return revision.strip('"')


def _load_progress_strict(path=None) -> dict:
    """Compatibility wrapper around the shared progress store."""
    return load_progress_strict(path or PRG_PATH)


def _save_progress_strict(data: dict, path=None) -> None:
    """Compatibility wrapper around the shared progress store."""
    save_progress_strict(path or PRG_PATH, data)


def _student_has_schedule_on_date(student: dict, date_key: str) -> bool:
    try:
        target = dt.date.fromisoformat(date_key)
    except ValueError:
        return False
    wchr = "월화수목금토일"[target.weekday()]
    for key, value in (student or {}).items():
        if re.fullmatch(r"day\d+", str(key)) and str(value or "").startswith(wchr):
            return True
    return False




def _weekday_char_for_date(date_key: str) -> str:
    try:
        target = dt.date.fromisoformat(str(date_key or "").strip())
    except ValueError:
        return ""
    return "월화수목금토일"[target.weekday()]


def _normalize_schedule_slots(raw) -> list[int]:
    values = raw if isinstance(raw, list) else [raw]
    out = []
    seen = set()
    for value in values:
        for token in re.findall(r"(?<!\d)([1-6])(?!\d)", str(value or "")):
            slot = int(token)
            if slot in seen:
                continue
            seen.add(slot)
            out.append(slot)
    return sorted(out)


def _student_slots_for_date(
    student: dict,
    sid: str,
    date_key: str,
    weekend_slots=None,
    absent=None,
) -> list[int]:
    """Return the date-specific class slots after slot absences are removed."""
    weekend = weekend_slots if isinstance(weekend_slots, dict) else {}
    day_override = weekend.get(str(date_key or "")) if isinstance(weekend, dict) else None
    slots: list[int] = []
    if isinstance(day_override, dict):
        override_value = _sid_lookup(day_override, sid)
        override_slots = _normalize_schedule_slots(override_value)
        if override_slots:
            slots = override_slots

    if not slots:
        weekday = _weekday_char_for_date(date_key)
        if not weekday:
            return []
        for key, value in (student or {}).items():
            if not re.fullmatch(r"day\d+", str(key)):
                continue
            text = str(value or "")
            if text.startswith(weekday):
                slots.extend(_normalize_schedule_slots(text))

    absent_map = absent if isinstance(absent, dict) else {}
    by_slot = absent_map.get("by_slot") if isinstance(absent_map, dict) else None
    day_absences = by_slot.get(str(date_key or "")) if isinstance(by_slot, dict) else None
    absent_slots = set(
        _normalize_schedule_slots(_sid_lookup(day_absences, sid))
        if isinstance(day_absences, dict)
        else []
    )
    return [slot for slot in sorted(set(slots)) if slot not in absent_slots]


def _has_consecutive_slots(slots) -> bool:
    ordered = sorted({int(slot) for slot in (slots or []) if str(slot).isdigit()})
    return any(right == left + 1 for left, right in zip(ordered, ordered[1:]))


def _student_is_registered_on_date(student: dict, sid: str, date_key: str, extra=None) -> bool:
    if _student_has_schedule_on_date(student, date_key):
        return True
    if extra is None:
        try:
            extra = load(EXTRA_PATH) or {}
        except Exception:
            extra = {}
    extra_ids = extra.get(date_key, []) if isinstance(extra, dict) else []
    return str(sid) in {str(x) for x in (extra_ids or [])}


def _extract_kollus_mid_from_url(url) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""

    try:
        parsed = urlparse(raw)
    except Exception:
        return ""

    host = (parsed.netloc or "").lower()
    if "kollus.com" not in host:
        return ""

    query = parse_qs(parsed.query or "", keep_blank_values=False)
    for key in ("mid", "m", "media_content_key", "MEDIA_CONTENT_KEY", "content_key"):
        vals = query.get(key)
        if not vals:
            continue
        cand = str(vals[0] or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]+", cand):
            return cand

    parts = [p for p in (parsed.path or "").split("/") if p]
    for cand in reversed(parts):
        cand_s = str(cand or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]+", cand_s):
            return cand_s

    return ""


def _normalize_video_mid_fields(videos):
    if not isinstance(videos, list):
        return videos

    out = []
    for item in videos:
        if not isinstance(item, dict):
            out.append(item)
            continue

        vid = dict(item)
        parsed_mid = _extract_kollus_mid_from_url(vid.get("url"))
        if parsed_mid:
            vid["mid"] = parsed_mid
        elif vid.get("mid") is not None:
            vid["mid"] = str(vid.get("mid") or "").strip()
        out.append(vid)
    return out


VIDEO_CATALOG_IDENTITY_CHANGE_ERROR = "video_catalog_identity_change_blocked"
VIDEO_CATALOG_IDENTITY_CHANGE_MESSAGE = (
    "일반 모드에서는 기존 영상의 MID 변경 또는 삭제를 저장할 수 없습니다. "
    "기존 데이터는 변경되지 않았으며, 필요한 경우 별도 수정 모드에서 처리해야 합니다."
)


def _video_catalog_rows_by_id(rows, label: str) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be an array")

    out: dict[str, dict] = {}
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            raise ValueError(f"{label} row {index + 1} must be an object")
        key = str(item.get("id") or "").strip()
        if not key:
            raise ValueError(f"{label} row {index + 1} is missing id")
        if key in out:
            raise ValueError(f"{label} has duplicate id: {key}")
        out[key] = item
    return out


def _video_catalog_identity_changes(prev_videos, next_videos) -> dict[str, list]:
    previous = _video_catalog_rows_by_id(prev_videos, "current video catalog")
    incoming = _video_catalog_rows_by_id(next_videos, "new video catalog")
    removed_ids = [key for key in previous if key not in incoming]
    mid_changes = []
    for key, old_item in previous.items():
        new_item = incoming.get(key)
        if new_item is None:
            continue
        old_mid = str(old_item.get("mid") or "").strip()
        new_mid = str(new_item.get("mid") or "").strip()
        if old_mid != new_mid:
            mid_changes.append({"id": key, "oldMid": old_mid, "newMid": new_mid})
    return {"removedIds": removed_ids, "midChanges": mid_changes}

# ─────────────────────────────────────────────
# ✅ 프로세스 간 파일 락 (JSON 저장 보호용)
# ─────────────────────────────────────────────
class _InterProcessFileLock(InterProcessFileLock):
    """Backward-compatible alias for modules importing the old route-local lock."""


def _logs_lock():
    lp = str(getattr(LOGS_PATH, "__fspath__", lambda: str(LOGS_PATH))())
    return _InterProcessFileLock(lp + ".lock", timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0)


def _sid_keys(sid: str) -> list[str]:
    """Return canonical and numeric aliases used by date-scoped stores."""
    key = str(sid or "").strip()
    keys = [key]
    if key.isdigit():
        numeric = str(int(key))
        if numeric not in keys:
            keys.append(numeric)
    return [item for item in keys if item]


def _progress_lock():
    return progress_file_lock(PRG_PATH)


def _updates_lock():
    up = str(getattr(UPD_PATH, "__fspath__", lambda: str(UPD_PATH))())
    return _InterProcessFileLock(up + ".lock", timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0)


def _sid_lookup(mapping: dict, sid: str):
    if not isinstance(mapping, dict):
        return None
    keys = [str(sid or "").strip()]
    if keys[0].isdigit():
        alt = str(int(keys[0]))
        if alt not in keys:
            keys.append(alt)
    for key in keys:
        if key and key in mapping:
            return mapping.get(key)
    return None


def _write_sid_mapping(mapping: dict, sid: str, value) -> None:
    key = str(sid or "").strip()
    if not key:
        return
    num_key = str(int(key)) if key.isdigit() else None
    if num_key and num_key != key:
        mapping.pop(num_key, None)
    if value is None:
        mapping.pop(key, None)
    else:
        mapping[key] = value


def _normalize_video_assign_list(value) -> list[str]:
    if isinstance(value, dict):
        value = value.get("videos")
    if not isinstance(value, list):
        return []
    out = []
    seen = set()
    for item in value:
        mid = str(item or "").strip()
        if not mid or mid in seen:
            continue
        out.append(mid)
        seen.add(mid)
    return out


def _is_manual_video_assignment(value) -> bool:
    if not isinstance(value, dict):
        return False
    source = str(value.get("source") or "").strip().lower()
    return (
        source in {"manual", "selfstudy"}
        or value.get("manual") is True
        or value.get("manualVideoAssign") is True
    )


def _normalize_test_assignment_status(value) -> str:
    if isinstance(value, dict):
        value = value.get("status")
    s = str(value or "").strip()
    if not s or s == "none":
        return ""
    if s in ("assigned", "done", "interrupted", "skip"):
        return s
    return "assigned"


def _test_assignment_status_label(status: str) -> str:
    s = _normalize_test_assignment_status(status)
    if s == "done":
        return "완료"
    if s == "interrupted":
        return "배부"
    if s == "skip":
        return "제외"
    return "배정" if s else ""


def _is_active_test_assignment_status(status: str) -> bool:
    return _normalize_test_assignment_status(status) in {"assigned", "interrupted"}


def _round_label_for_assignment(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw if "회" in raw else f"{raw}회차"


def _fallback_assigned_test_from_label(label: str, status: str) -> dict:
    parts = [p.strip() for p in str(label or "").split(" / ") if p.strip()]
    item = {
        "label": str(label or "").strip(),
        "name": parts[-1] if parts else str(label or "").strip(),
        "status": status,
        "statusLabel": _test_assignment_status_label(status),
    }
    if len(parts) >= 5:
        item.update({
            "categoryLabel": parts[0],
            "curriculum": parts[1],
            "difficulty": parts[2],
            "round": parts[3].replace("회차", "").replace("회", "").strip(),
        })
    return item


def _normalized_test_curriculum(value) -> str:
    compact = re.sub(r"\s+", "", str(value or ""))
    aliases = {
        "공통수학1": "공수1",
        "공통수학2": "공수2",
        "미적1": "미적분1",
        "미적분Ⅰ": "미적분1",
        "미적분I": "미적분1",
        "미적2": "미적분2",
        "미적분Ⅱ": "미적분2",
        "미적분II": "미적분2",
        "확률과통계": "확통",
    }
    return aliases.get(compact, "미적분1" if compact == "미적분" else compact)


def _assigned_test_curriculum(item: dict) -> str:
    direct = item.get("curriculum") or item.get("subject") or item.get("course")
    if str(direct or "").strip():
        return _normalized_test_curriculum(direct)
    parts = [part.strip() for part in str(item.get("label") or "").split("/") if part.strip()]
    return _normalized_test_curriculum(parts[1] if len(parts) > 1 else "")


def _filter_assigned_tests_for_student_curriculum(items: list[dict], student: dict) -> list[dict]:
    current = _normalized_test_curriculum(student.get("curriculum") or student.get("subject"))
    if not current:
        return items
    return [item for item in items if _assigned_test_curriculum(item) == current]


def _assigned_test_label(raw: dict) -> str:
    label = str(raw.get("label") or "").strip()
    if label:
        return label
    pieces = [
        raw.get("categoryLabel"),
        raw.get("curriculum"),
        raw.get("difficulty"),
        _round_label_for_assignment(raw.get("round")),
        raw.get("name"),
    ]
    return " / ".join(str(x).strip() for x in pieces if str(x or "").strip())


def _normalized_test_status_map(tests) -> dict:
    if not isinstance(tests, dict):
        return {}
    statuses = {
        str(label).strip(): _normalize_test_assignment_status(status)
        for label, status in tests.items()
    }
    return {label: status for label, status in statuses.items() if label and status}


def _latest_previous_test_statuses(progress_all: dict, date: str, sid: str) -> dict:
    return _latest_previous_test_statuses_from_sources(progress_all, None, date, sid)


def _log_test_statuses_for_sid(logs_map: dict | None, date: str, sid: str) -> dict:
    if not isinstance(logs_map, dict):
        return {}
    day_logs = logs_map.get(date)
    log_entry = _sid_lookup(day_logs if isinstance(day_logs, dict) else {}, sid)
    if not isinstance(log_entry, dict):
        return {}

    out = {}
    for field in (TEST_ASSIGN_DAILY_ITEMS_KEY, "assignedTests"):
        items = log_entry.get(field)
        if not isinstance(items, list):
            continue
        for raw in items:
            if not isinstance(raw, dict):
                continue
            label = _assigned_test_label(raw)
            status = _normalize_test_assignment_status(raw.get("status") or "assigned")
            if label and _is_active_test_assignment_status(status):
                out[label] = status
    return out


def _latest_previous_test_statuses_from_sources(
    progress_all: dict,
    logs_map: dict | None,
    date: str,
    sid: str,
) -> dict:
    previous_date_keys = set()
    for source in (progress_all, logs_map):
        if not isinstance(source, dict):
            continue
        for raw_date in source.keys():
            raw_date_s = str(raw_date or "")
            if DATE_RE.match(raw_date_s) and raw_date_s < str(date):
                previous_date_keys.add(raw_date_s)

    for prev_date in sorted(previous_date_keys, reverse=True):
        prev_day = progress_all.get(prev_date) if isinstance(progress_all, dict) else {}
        prev_entry = _sid_lookup(prev_day if isinstance(prev_day, dict) else {}, sid)
        if isinstance(prev_entry, dict):
            if prev_entry.get(TEST_ASSIGN_CLEAR_META_KEY):
                break
            prev_tests = prev_entry.get("tests")
            if isinstance(prev_tests, dict) and prev_tests:
                prev_statuses = _normalized_test_status_map(prev_tests)
                # Previous skip means inactive/excluded, so it must not hide a
                # test that became newly assigned on the current date.
                return {
                    label: status
                    for label, status in prev_statuses.items()
                    if _is_active_test_assignment_status(status)
                }
        log_statuses = _log_test_statuses_for_sid(logs_map, prev_date, sid)
        if log_statuses:
            return log_statuses
    return {}


def _load_tests_config_for_answer_links() -> dict:
    try:
        mtime = TESTS_CFG_PATH.stat().st_mtime
    except FileNotFoundError:
        _TESTS_CONFIG_CACHE.update({"mtime": None, "data": {}})
        return {}
    except Exception:
        return _TESTS_CONFIG_CACHE.get("data") or {}

    if _TESTS_CONFIG_CACHE.get("mtime") == mtime:
        return _TESTS_CONFIG_CACHE.get("data") or {}

    try:
        data = json.loads(TESTS_CFG_PATH.read_text("utf-8-sig"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    _TESTS_CONFIG_CACHE.update({"mtime": mtime, "data": data})
    return data


def _load_test_answer_link_map() -> dict:
    try:
        mtime = TEST_ANSWER_LINK_MAP_PATH.stat().st_mtime
    except FileNotFoundError:
        _TEST_ANSWER_LINK_MAP_CACHE.update({"mtime": None, "data": {}})
        return {}
    except Exception:
        return _TEST_ANSWER_LINK_MAP_CACHE.get("data") or {}

    if _TEST_ANSWER_LINK_MAP_CACHE.get("mtime") == mtime:
        return _TEST_ANSWER_LINK_MAP_CACHE.get("data") or {}

    try:
        data = json.loads(TEST_ANSWER_LINK_MAP_PATH.read_text("utf-8-sig"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    _TEST_ANSWER_LINK_MAP_CACHE.update({"mtime": mtime, "data": data})
    return data


def _test_assignment_answer_url(item: dict) -> str:
    return resolve_test_assignment_answer_url(
        item,
        tests_config=_load_tests_config_for_answer_links(),
        answer_link_map=_load_test_answer_link_map(),
    )

def _append_unique_assigned_test_label(labels: list[str], label: str) -> None:
    if label not in labels:
        labels.append(label)


def _collect_assigned_test_metadata(
    source_map,
    date: str,
    sid: str,
    by_label: dict,
    log_labels: list[str],
    daily_labels: list[str],
) -> None:
    day_logs = source_map.get(date) if isinstance(source_map, dict) else {}
    log_entry = _sid_lookup(day_logs if isinstance(day_logs, dict) else {}, sid)

    daily_items = log_entry.get(TEST_ASSIGN_DAILY_ITEMS_KEY) if isinstance(log_entry, dict) else []
    if isinstance(daily_items, list):
        for raw in daily_items:
            if not isinstance(raw, dict):
                continue
            label = _assigned_test_label(raw)
            if not label:
                continue
            _append_unique_assigned_test_label(daily_labels, label)
            by_label[label] = {**by_label.get(label, {}), **raw, "label": label}

    log_items = log_entry.get("assignedTests") if isinstance(log_entry, dict) else []
    if not isinstance(log_items, list):
        return

    for raw in log_items:
        if not isinstance(raw, dict):
            continue
        label = _assigned_test_label(raw)
        if not label:
            continue
        _append_unique_assigned_test_label(log_labels, label)
        item = dict(raw)
        if label in by_label:
            merged = dict(item)
            merged.update(by_label[label])
            by_label[label] = merged
        else:
            by_label[label] = item


def _student_assigned_test_labels(
    status_by_label: dict,
    log_labels: list[str],
    daily_labels: list[str],
) -> list[str]:
    if daily_labels:
        if status_by_label:
            labels = [
                label
                for label in daily_labels
                if (
                    label in status_by_label
                    and _is_active_test_assignment_status(status_by_label.get(label))
                )
            ]
            for label, status in status_by_label.items():
                if not _is_active_test_assignment_status(status) or label in labels:
                    continue
                labels.append(label)
            return labels
        return [
            label
            for label in daily_labels
        ]

    active_labels = [
        label
        for label, status in status_by_label.items()
        if _is_active_test_assignment_status(status)
    ] if status_by_label else list(log_labels)
    return active_labels


def _build_student_assigned_test_items(
    labels: list[str],
    by_label: dict,
    status_by_label: dict,
) -> list[dict]:
    out = []
    for label in labels:
        item = dict(by_label.get(label) or {})
        status = (
            status_by_label.get(label)
            or _normalize_test_assignment_status(item.get("status"))
            or "assigned"
        )
        if not _is_active_test_assignment_status(status):
            continue
        if not item:
            item = _fallback_assigned_test_from_label(label, status)
        item["label"] = item.get("label") or label
        item["status"] = status
        item["statusLabel"] = _test_assignment_status_label(status)
        answer_url = _test_assignment_answer_url(item)
        if answer_url:
            item["answerUrl"] = answer_url
        out.append(item)

    return out


def _student_assigned_tests_for_date(
    progress_all: dict,
    logs_map: dict,
    date: str,
    sid: str,
    fallback_logs_map=None,
) -> list[dict]:
    day_progress = progress_all.get(date) if isinstance(progress_all, dict) else {}
    progress_entry = _sid_lookup(day_progress if isinstance(day_progress, dict) else {}, sid)
    current_cleared = isinstance(progress_entry, dict) and bool(progress_entry.get(TEST_ASSIGN_CLEAR_META_KEY))
    progress_tests = progress_entry.get("tests") if isinstance(progress_entry, dict) else {}
    if not isinstance(progress_tests, dict):
        progress_tests = {}

    status_by_label = _normalized_test_status_map(progress_tests)

    by_label = {}
    log_labels = []
    daily_labels = []

    if current_cleared and not status_by_label:
        return []

    _collect_assigned_test_metadata(logs_map, date, sid, by_label, log_labels, daily_labels)
    if not log_labels:
        _collect_assigned_test_metadata(fallback_logs_map, date, sid, by_label, log_labels, daily_labels)

    labels = _student_assigned_test_labels(
        status_by_label,
        log_labels,
        daily_labels,
    )
    return _build_student_assigned_test_items(labels, by_label, status_by_label)


def _merge_update_assignment(current, incoming):
    if incoming is None:
        return current

    videos = _normalize_video_assign_list(incoming)
    if isinstance(incoming, list):
        return videos

    if isinstance(incoming, dict):
        if incoming.get("remove") is True:
            return None
        out = dict(current) if isinstance(current, dict) else {}
        for key, value in incoming.items():
            if key in ("remove",):
                continue
            if key == "videos":
                out["videos"] = videos
            elif value is not None:
                out[str(key)] = value
        if "videos" not in incoming and videos:
            out["videos"] = videos
        return out if out else (videos if videos else current)

    return current





def _assigned_material_list(value) -> list[str]:
    if isinstance(value, dict):
        value = value.get("materials")
    if not isinstance(value, list):
        return []
    out = []
    seen = set()
    for item in value:
        if isinstance(item, dict):
            item = item.get("id") or item.get("url") or item.get("path")
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        out.append(key)
        seen.add(key)
    return out


def _filter_materials_for_assignment(materials, assigned):
    if not isinstance(materials, dict):
        return {}
    wanted = {str(x) for x in (assigned or []) if str(x or "").strip()}
    if not wanted:
        return {}

    out = {}
    for key, value in materials.items():
        item = value if isinstance(value, dict) else {}
        candidates = {
            str(key),
            str(item.get("id") or ""),
            str(item.get("mid") or ""),
            str(item.get("url") or ""),
            str(item.get("path") or ""),
        }
        if candidates & wanted:
            out[key] = value
    return out


# ─────────────────────────────────────────────
# ✅ logs 안전 merge (날아감 방지)
# - PATCH가 기본
# - "빈 값"으로 기존 "유효 값" 덮는 거 금지
# - "__clear": ["notes", ...] 로 명시 삭제
# - done=true 는 저장/수정으로 false로 풀리지 않게(명시 해제 기능 없으면 고정)
# ─────────────────────────────────────────────
def _is_question_placeholder(value) -> bool:
    text = re.sub(r"\s+", "", str(value or ""))
    return len(text) >= 2 and set(text) == {"?"}


def _looks_corrupted_placeholder_text(value) -> bool:
    text = str(value or "").strip()
    if text.count("?") < 2:
        return False
    # If any real Korean/CJK/Latin text remains, keep it. This avoids
    # stripping legitimate notes such as "확인??" while hiding mojibake.
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
    for stu in students:
        if not isinstance(stu, dict):
            continue
        sid = str(stu.get("id") or "").strip()
        if not sid:
            continue
        books: List[str] = []
        for key in sorted(stu.keys(), key=lambda k: int(k[7:]) if re.match(r"^subBook\d+$", str(k)) else 999):
            if not re.match(r"^subBook\d+$", str(key)):
                continue
            val = str(stu.get(key) or "").strip()
            if val and val not in books:
                books.append(val)
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


def _hw_row_summary(row: dict) -> str:
    if not isinstance(row, dict) or row.get("_deleted"):
        return ""

    book = str(row.get("book") or "").strip()
    this_hw = str(row.get("this") or "").strip()
    pct = row.get("pct")
    pct_s = "" if pct in ("", None) else f"{str(pct).strip()}%"
    comment = str(row.get("comment") or "").strip()
    next_hw = str(row.get("next") or "").strip()

    parts: List[str] = []
    if book:
        parts.append(f"[{book}]")
    if this_hw:
        parts.append(this_hw)
    if pct_s:
        parts.append(pct_s)
    if comment:
        parts.append(f"({comment})")
    if next_hw:
        parts.append(f"→ {next_hw}")
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
            replacement = next((b for b in books if _book_key(b) not in used), "")
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


def _repair_log_entry_placeholders(entry: dict, sid: str) -> dict:
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
                s for s in (_hw_row_summary(row) for row in repaired_rows) if s
            )
            if summary:
                out["homework"] = summary
            else:
                out.pop("homework", None)
    elif _is_question_placeholder(out.get("homework")):
        out.pop("homework", None)

    return out


def _student_homework_book_names_from_log(entry: dict) -> list[str]:
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


def _academy_restricted_assigned_tests(items: list[dict], academy_allowed: bool) -> list[dict]:
    if academy_allowed:
        return items

    out: list[dict] = []
    for item in items or []:
        stripped, had_answer_link = strip_answer_link_fields(item)
        if isinstance(stripped, dict) and had_answer_link:
            stripped["answerRestricted"] = True
        out.append(stripped)
    return out


def _academy_restricted_student_videos(items: list[dict], academy_allowed: bool) -> list[dict]:
    if academy_allowed:
        return items

    blocked_keys = {
        "url",
        "link",
        "src",
        "source",
        "playUrl",
        "play_url",
        "streamUrl",
        "stream_url",
        "embedUrl",
        "embed_url",
    }
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        for key in blocked_keys:
            next_item.pop(key, None)
        next_item["playbackRestricted"] = True
        out.append(next_item)
    return out


def _is_ghost_student_sid(sid: str) -> bool:
    return is_ghost_student_sid(sid)


def _ghost_student_bootstrap(date: str):
    ghost_student = {
        "id": GHOST_STUDENT_ID,
        "name": "외부접속 테스트",
        "curriculum": "고스트",
        "subCurriculum": "외부접속",
        "level": "중",
        "school": "",
        "grade": "",
        "ghostStudent": True,
    }
    ghost_video = {
        "mid": GHOST_STUDENT_VIDEO_MID,
        "id": GHOST_STUDENT_VIDEO_MID,
        "title": "외부접속 테스트 영상",
        "chapter": "TEST",
        "curriculum": ghost_student["curriculum"],
        "subCurriculum": ghost_student["subCurriculum"],
        "isExtraAssignment": False,
        "playbackRestricted": True,
    }
    ghost_log_entry = {
        "homeworkTable": [
            {
                "book": GHOST_STUDENT_HOMEWORK_BOOK,
                "this": "",
                "next": "",
                "comment": "",
            }
        ],
    }
    ghost_test = {
        "id": GHOST_STUDENT_TEST_ID,
        "testId": GHOST_STUDENT_TEST_ID,
        "name": "외부접속 테스트 답지",
        "label": "외부접속 테스트 답지",
        "categoryKey": "UNIT",
        "categoryLabel": "단원평가",
        "curriculum": ghost_student["curriculum"],
        "round": "1",
        "status": "assigned",
        "statusLabel": "배정",
        "answerRestricted": True,

    }

    # Code-only ghost for outside-Wi-Fi UI checks. It must never enter
    # students.json, updates.json, logs, progress, or tests data.
    payload = {
        "ok": True,
        "date": date,
        "students": [ghost_student],
        "student": ghost_student,
        "videos": [ghost_video],
        "reviewVideos": [],
        "updates": {date: {GHOST_STUDENT_ID: [GHOST_STUDENT_VIDEO_MID]}},
        "materials": {},
        "assigns": {GHOST_STUDENT_ID: []},
        "absent": {"by_date": {date: []}, "by_student": {}},
        "logs": {date: {GHOST_STUDENT_ID: ghost_log_entry}},
        "assignedTests": [ghost_test],
        "homeworkBooks": [GHOST_STUDENT_HOMEWORK_BOOK],
        "courseVideosCompleted": False,
        "academyAccessAllowed": False,
        "outsideAcademyBlocked": True,
        "networkBlocked": True,
        "academyOnlyMessage": ACADEMY_ACCESS_MESSAGE,
        "ghostStudent": True,

    }
    return nocache_resp(_finalize_public_bootstrap(payload, GHOST_STUDENT_ID, False))


# ─────────────────────────────────────────────
# ✅ progress 1건(date/sid) 안전 merge
# - inc[mid] = "done" | "interrupted" | "skip" | "none"
# - "none" is an explicit manual clear marker. It must override older
#   historical progress and automatic watch-status updates.
# ─────────────────────────────────────────────
def get_log_repository() -> LogRepository:
    return LogRepository(
        logs_path=LOGS_PATH,
        repair_entry=_repair_log_entry_placeholders,
        merge_entry=_log_rules.merge_log_entry_safe,
        entry_conflicts=_log_rules.log_entry_conflicts_with_base,
        lock_factory=_logs_lock,
        truthy=_log_rules.truthy,
        today_key=_today_kst_iso,
    )


TEST_ASSIGN_DAILY_ITEMS_KEY = "testAssignmentDailyTests"
TEST_ANSWER_LINK_MAP_PATH = BASE / "static" / "js" / "test_answer_link_map.json"
_TEST_ANSWER_LINK_MAP_CACHE = {"mtime": None, "data": {}}
_TESTS_CONFIG_CACHE = {"mtime": None, "data": {}}


KST = dt.timezone(dt.timedelta(hours=9))


# ─────────────────────────────────────────────
# updates 자동배정 보정 (원본 유지)
# ─────────────────────────────────────────────
def _chap_num(v: dict) -> float:
    c = v.get("chapter", 0)
    try:
        return float(c)
    except Exception:
        s = re.sub(r"[^0-9.]", "", str(c))
        return float(s) if s else 0.0


def _has_assigned(val) -> bool:
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, dict):
        vids = val.get("videos")
        return isinstance(vids, list) and len(vids) > 0
    return False


AUTO_VIDEO_ASSIGN_FIELD = "autoVideoAssignCount"
DEFAULT_AUTO_VIDEO_ASSIGN_COUNT = 3
ABLE_AUTO_VIDEO_ASSIGN_COUNT = 1
ABLE_CURRICULUM_KEY = "a:ble"
MIN_AUTO_VIDEO_ASSIGN_COUNT = 1
MAX_AUTO_VIDEO_ASSIGN_COUNT = 10
VIDEO_PROGRESS_FINISHED_STATUSES = {"done", "skip"}
SELF_STUDY_VIDEO_ASSIGN_SOURCE = "selfStudy"
SELF_STUDY_DAY_FIELDS = ("day1", "day2", "day3", "day4", "day5")


def _coerce_auto_video_assign_count(value, default: int = DEFAULT_AUTO_VIDEO_ASSIGN_COUNT) -> int:
    try:
        n = int(round(float(value)))
    except Exception:
        n = default
    return max(MIN_AUTO_VIDEO_ASSIGN_COUNT, min(MAX_AUTO_VIDEO_ASSIGN_COUNT, n))


def _is_able_curriculum_value(value) -> bool:
    return str(value or "").strip().casefold() == ABLE_CURRICULUM_KEY


def _student_uses_able_curriculum(stu: dict) -> bool:
    if not isinstance(stu, dict):
        return False
    return _is_able_curriculum_value(stu.get("curriculum")) or _is_able_curriculum_value(stu.get("subCurriculum"))


def _apply_able_auto_video_assign_default(stu: dict) -> None:
    if _student_uses_able_curriculum(stu):
        stu[AUTO_VIDEO_ASSIGN_FIELD] = ABLE_AUTO_VIDEO_ASSIGN_COUNT


def _student_auto_video_assign_count(stu: dict) -> int:
    if not isinstance(stu, dict):
        return DEFAULT_AUTO_VIDEO_ASSIGN_COUNT
    default = ABLE_AUTO_VIDEO_ASSIGN_COUNT if _student_uses_able_curriculum(stu) else DEFAULT_AUTO_VIDEO_ASSIGN_COUNT
    return _coerce_auto_video_assign_count(stu.get(AUTO_VIDEO_ASSIGN_FIELD), default=default)


def _effective_auto_video_assign_count(
    stu: dict,
    sid: str,
    date_key: str,
    weekend_slots=None,
    absent=None,
) -> int:
    configured = _student_auto_video_assign_count(stu)
    slots = _student_slots_for_date(stu, sid, date_key, weekend_slots, absent)
    return configured * 2 if _has_consecutive_slots(slots) else configured


def _student_has_scheduled_self_study_on_date(stu: dict, date_key: str) -> bool:
    try:
        target = dt.date.fromisoformat(date_key)
    except ValueError:
        return False

    raw = stu.get("selfStudyDays") if isinstance(stu, dict) else None
    scheduled_fields: set[str] = set()
    if isinstance(raw, list):
        scheduled_fields = {str(field or "").strip() for field in raw}
    elif isinstance(raw, dict):
        scheduled_fields = {
            str(field or "").strip()
            for field, enabled in raw.items()
            if _log_rules.truthy(enabled)
        }
    else:
        scheduled_fields = {
            field for field in SELF_STUDY_DAY_FIELDS
            if _log_rules.truthy(stu.get(f"{field}SelfStudy"))
        }

    weekday = "월화수목금토일"[target.weekday()]
    return any(
        field in scheduled_fields and str(stu.get(field) or "").strip().startswith(weekday)
        for field in SELF_STUDY_DAY_FIELDS
    )


def _student_is_self_study_on_date(logs: dict, date_key: str, sid: str, stu: dict) -> bool:
    day_logs = logs.get(date_key) if isinstance(logs, dict) else None
    entry = _sid_lookup(day_logs if isinstance(day_logs, dict) else {}, sid)
    if isinstance(entry, dict) and "selfStudy" in entry:
        return _log_rules.truthy(entry.get("selfStudy"))
    return _student_has_scheduled_self_study_on_date(stu, date_key)


def _self_study_review_video_mids(
    cur_vids: list,
    assigned: list[str],
    auto_candidates: list[str],
    eligible_mids: set[str] | None = None,
) -> list[str]:
    """Return the last eligible curriculum videos before the assignment anchor."""
    mids: list[str] = []
    seen: set[str] = set()
    for video in cur_vids:
        mid = str(video.get("mid") or "").strip() if isinstance(video, dict) else ""
        if mid and mid not in seen:
            mids.append(mid)
            seen.add(mid)

    positions = {mid: index for index, mid in enumerate(mids)}
    assigned_positions = [
        positions[mid]
        for mid in assigned
        if mid in positions
    ]
    base_positions = assigned_positions or [
        positions[mid]
        for mid in auto_candidates
        if mid in positions
    ]
    if not base_positions:
        return []

    eligible = set(mids) if eligible_mids is None else {
        str(mid or "").strip() for mid in eligible_mids if str(mid or "").strip()
    }
    start = min(base_positions)
    prior = [mid for mid in mids[:start] if mid in eligible]
    return prior[-DEFAULT_AUTO_VIDEO_ASSIGN_COUNT:]


def _is_finished_video_progress_status(status) -> bool:
    return str(status or "").strip() in VIDEO_PROGRESS_FINISHED_STATUSES


def _student_completion_videos(stu: dict, videos: list) -> list[dict]:
    if not isinstance(stu, dict):
        return []

    cur_key = (stu.get("curriculum") or "").strip()
    sub_key = (stu.get("subCurriculum") or "").strip()

    exact = [
        v for v in (videos or [])
        if isinstance(v, dict)
        and (v.get("curriculum") or "").strip() == cur_key
        and (v.get("subCurriculum") or "").strip() == sub_key
    ]
    if exact:
        exact.sort(key=lambda v: (_chap_num(v), str(v.get("mid") or "")))
        return exact

    fallback = [
        v for v in (videos or [])
        if isinstance(v, dict)
        and (v.get("curriculum") or "").strip() == cur_key
    ]
    fallback.sort(key=lambda v: (_chap_num(v), str(v.get("mid") or "")))
    return fallback


def _student_review_states_before_date(stu: dict, progress: dict, watch: dict, date_key: str) -> dict:
    """Resolve current-student review states without exposing source maps."""
    sid = str(stu.get("id") or "").strip() if isinstance(stu, dict) else ""
    if not sid:
        return {}
    return resolve_video_review_states_before_date(
        progress if isinstance(progress, dict) else {},
        watch if isinstance(watch, dict) else {},
        sid_keys=_sid_keys(sid),
        before_date=date_key,
    )


def _student_review_states_through_date(stu: dict, progress: dict, watch: dict, date_key: str) -> dict:
    """Resolve review states through ``date_key`` using the strict-cutoff helper."""
    try:
        before_date = (
            dt.date.fromisoformat(str(date_key)) + dt.timedelta(days=1)
        ).isoformat()
    except ValueError:
        return {}
    return _student_review_states_before_date(stu, progress, watch, before_date)


def _student_current_curriculum_videos(stu: dict, videos: list) -> list[dict]:
    """Return the exact current curriculum/sub-curriculum review catalog."""
    if not isinstance(stu, dict):
        return []
    curriculum_key = str(stu.get("curriculum") or "").strip().casefold()
    sub_curriculum_key = str(stu.get("subCurriculum") or "").strip().casefold()
    if not curriculum_key:
        return []
    return [
        video
        for video in (videos or [])
        if isinstance(video, dict)
        and str(video.get("curriculum") or "").strip().casefold() == curriculum_key
        and (
            not sub_curriculum_key
            or str(video.get("subCurriculum") or "").strip().casefold() == sub_curriculum_key
        )
    ]


def _student_eligible_review_video_mids(stu: dict, videos: list, progress: dict, watch: dict, date_key: str) -> set[str]:
    """Return only current-curriculum videos with a completed pre-date state."""
    catalog_mids = {
        str(video.get("mid") or "").strip()
        for video in _student_current_curriculum_videos(stu, videos)
        if str(video.get("mid") or "").strip()
    }
    states = _student_review_states_before_date(stu, progress, watch, date_key)
    return {
        str(mid or "").strip()
        for mid, state in (states.items() if isinstance(states, dict) else [])
        if str(mid or "").strip() in catalog_mids
        and isinstance(state, dict)
        and state.get("status") == "done"
    }


def _filter_self_study_assignment_for_response(assignment, eligible_mids: set[str]):
    """Deep-copy and filter a self-study assignment without touching storage data."""
    eligible = {
        str(mid or "").strip() for mid in eligible_mids if str(mid or "").strip()
    }
    if isinstance(assignment, list):
        return [
            mid for mid in _normalize_video_assign_list(assignment)
            if mid in eligible
        ]
    if not isinstance(assignment, dict):
        return assignment

    response_assignment = deepcopy(assignment)
    if "videos" in response_assignment:
        response_assignment["videos"] = [
            mid for mid in _normalize_video_assign_list(response_assignment.get("videos"))
            if mid in eligible
        ]
    return response_assignment


def _filter_auto_assignment_for_current_curriculum(assignment, stu: dict, videos: list):
    """Hide stale automatic MIDs while leaving manual/self-study additions intact."""
    legacy_auto = isinstance(assignment, list)
    named_auto = (
        isinstance(assignment, dict)
        and str(assignment.get("source") or "").strip().casefold() == "auto"
        and not _is_manual_video_assignment(assignment)
    )
    if not legacy_auto and not named_auto:
        return assignment

    allowed_mids = {
        str(video.get("mid") or "").strip()
        for video in _student_current_curriculum_videos(stu, videos)
        if str(video.get("mid") or "").strip()
    }
    filtered_mids = [
        mid for mid in _normalize_video_assign_list(assignment)
        if mid in allowed_mids
    ]
    if legacy_auto:
        return filtered_mids

    response_assignment = deepcopy(assignment)
    response_assignment["videos"] = filtered_mids
    return response_assignment


def _student_review_video_projection(
    student: dict,
    videos_all: list,
    progress: dict,
    watch: dict,
    date_key: str,
    assigned_mids,
    academy_allowed: bool,
) -> list[dict]:
    """Build a sanitized current-curriculum review list through ``date_key``."""
    states = _student_review_states_through_date(
        student,
        progress,
        watch,
        date_key,
    )
    primary_mids = _student_primary_video_mids(student, videos_all)
    catalog_by_mid: dict[str, dict] = {}
    for video in _student_current_curriculum_videos(student, videos_all):
        mid = str(video.get("mid") or "").strip()
        if not mid or mid in catalog_by_mid:
            continue
        item = deepcopy(video)
        for internal_key in ("eventDate", "progress", "watch"):
            item.pop(internal_key, None)
        item["isExtraAssignment"] = mid not in primary_mids
        catalog_by_mid[mid] = item

    assigned = {
        str(mid or "").strip() for mid in (assigned_mids or []) if str(mid or "").strip()
    }
    candidates: list[tuple[float, str, dict]] = []
    for raw_mid, state in states.items():
        mid = str(raw_mid or "").strip()
        if not mid or mid in assigned or mid not in catalog_by_mid:
            continue
        if not isinstance(state, dict) or state.get("status") != "done":
            continue
        item = deepcopy(catalog_by_mid[mid])
        item["reviewStatus"] = state["status"]
        candidates.append((_chap_num(item), mid, item))

    candidates.sort(key=lambda entry: (entry[0], entry[1]))
    return _academy_restricted_student_videos(
        [entry[2] for entry in candidates],
        academy_allowed,
    )


def _student_primary_video_mids(stu: dict, videos: list) -> set[str]:
    return {
        str(v.get("mid") or "").strip()
        for v in _student_completion_videos(stu, videos)
        if isinstance(v, dict) and str(v.get("mid") or "").strip()
    }


def _course_videos_completed(course_videos: list, sid: str, latest_status_by_sid: dict) -> bool:
    mids = [
        str(v.get("mid") or "").strip()
        for v in (course_videos or [])
        if isinstance(v, dict) and str(v.get("mid") or "").strip()
    ]
    if not mids:
        return False

    latest = latest_status_by_sid.get(str(sid), {})
    if not isinstance(latest, dict):
        return False
    return all(_is_finished_video_progress_status(latest.get(mid)) for mid in mids)


def _build_latest_status_by_sid(progress: dict) -> dict:
    """Compatibility wrapper for existing route and fixture consumers."""
    return latest_video_status_by_sid(progress)


def _build_auto_assignment_blocked_by_sid(progress: dict, watch: dict) -> dict:
    blocked: dict[str, set[str]] = {}
    manual_reopened_at: dict[tuple[str, str], str] = {}

    if isinstance(progress, dict):
        for d in sorted(progress.keys()):
            day = progress.get(d) or {}
            if not isinstance(day, dict):
                continue
            for sid, mids in day.items():
                if not isinstance(mids, dict):
                    continue
                sid_s = str(sid)
                sid_keys = _sid_keys(sid_s)
                sid_key = sid_keys[-1] if sid_keys else sid_s
                manual_meta = mids.get(PROGRESS_MANUAL_META_KEY)
                if not isinstance(manual_meta, dict):
                    manual_meta = {}
                for mid, st in mids.items():
                    mid_s = str(mid)
                    if mid_s.startswith("__") or mid_s == "tests":
                        continue
                    st_s = str(st or "").strip()
                    if _is_finished_video_progress_status(st_s):
                        blocked.setdefault(sid_key, set()).add(mid_s)
                    elif st_s in {"none", "interrupted"} and manual_meta.get(mid_s):
                        blocked.setdefault(sid_key, set()).discard(mid_s)
                        manual_reopened_at[(sid_key, mid_s)] = str(d)

    if isinstance(watch, dict):
        for d in sorted(watch.keys()):
            by_date = watch.get(d) or {}
            if not isinstance(by_date, dict):
                continue
            for sid, mids in by_date.items():
                if not isinstance(mids, dict):
                    continue
                sid_s = str(sid)
                sid_keys = _sid_keys(sid_s)
                sid_key = sid_keys[-1] if sid_keys else sid_s
                for mid, entry in mids.items():
                    mid_s = str(mid or "").strip()
                    if not mid_s:
                        continue
                    status = _watch_auto_status(entry)
                    if status != "done":
                        continue
                    reopened_at = manual_reopened_at.get((sid_key, mid_s), "")
                    if reopened_at and str(reopened_at) >= str(d):
                        continue
                    blocked.setdefault(sid_key, set()).add(mid_s)

    return blocked


def _blocked_mids_for_sid(blocked_by_sid: dict, sid: str) -> set[str]:
    blocked: set[str] = set()
    for key in _sid_keys(sid):
        blocked.update(blocked_by_sid.get(key) or set())
    return blocked


def _today_kst_iso() -> str:
    return dt.datetime.now(KST).date().isoformat()


def _student_dashboard_enabled() -> bool:
    return bool(current_app.config.get("STUDENT_APP_DASHBOARD_ENABLED", False))


def _student_homework_enabled() -> bool:
    return bool(current_app.config.get("STUDENT_APP_HOMEWORK_ENABLED", False))


def _dashboard_homework_count(sid: str, fallback: int) -> int:
    if not _student_homework_enabled():
        return fallback
    try:
        from core.student_homework_repository import StudentHomeworkRepository

        database = os.environ.get("STUDENT_APP_DB_PATH", str(BASE / "app.sqlite"))
        return StudentHomeworkRepository(database).count_open(sid)
    except Exception:  # noqa: BROAD_EXCEPT_OK - an uninitialized additive store falls back to legacy data
        return fallback


def _dashboard_mapping(path) -> dict:
    try:
        value = load(path) or {}
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _student_dashboard_projection(
    *,
    student: dict,
    sid: str,
    date_key: str,
    videos: list,
    latest_status_by_sid: dict,
    homework_books: list,
    absences: dict,
) -> dict:
    start = dt.date.fromisoformat(date_key)
    end = start + dt.timedelta(days=45)
    calculated_at = dt.datetime.now(KST).replace(microsecond=0)
    schedule_as_of = (
        calculated_at
        if start == calculated_at.date()
        else dt.datetime.combine(start, dt.time.min, tzinfo=KST)
    )
    events = project_student_schedule(
        student,
        sid=sid,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        absence=absences,
        extra=_dashboard_mapping(EXTRA_PATH),
        weekend=_dashboard_mapping(WEEKEND_SLOTS_PATH),
        makeup=_dashboard_mapping(BASE / "makeup_carryover.json"),
    )
    latest_for_student = latest_status_by_sid.get(str(sid), {})
    if not isinstance(latest_for_student, dict):
        latest_for_student = {}
    curriculum_progress = build_curriculum_progress(
        student,
        videos,
        latest_for_student,
        calculated_at=calculated_at.isoformat(),
    )
    legacy_homework_count = len(homework_books) if isinstance(homework_books, list) else 0
    homework_count = _dashboard_homework_count(sid, legacy_homework_count)
    return {
        "enabled": True,
        "curriculumProgress": curriculum_progress,
        "nextSchedule": select_next_schedule(
            events,
            as_of=schedule_as_of.isoformat(),
        ),
        "homeworkSummary": {
            "count": homework_count,
            "state": "assigned" if homework_count else "empty",
        },
        "unreadBoardCount": None,
    }


def _log_entry_for_date(logs, date_key: str, sid: str):
    if not isinstance(logs, dict):
        return None
    day_logs = logs.get(date_key)
    if not isinstance(day_logs, dict):
        day_logs = logs
    return _sid_lookup(day_logs, sid)


def _student_absent_on_date(absent, date_key: str, sid: str) -> bool:
    if not isinstance(absent, dict):
        return False
    by_date = absent.get("by_date") or {}
    ids = by_date.get(date_key, []) if isinstance(by_date, dict) else []
    if str(sid) in {str(value) for value in (ids or [])}:
        return True
    by_student = absent.get("by_student") or {}
    return isinstance(by_student, dict) and str(_sid_lookup(by_student, sid) or "") == str(date_key)


def _student_is_today_auto_target(stu: dict, sid: str, date_key: str, extra=None, absent=None, logs=None) -> bool:
    if _student_absent_on_date(absent, date_key, sid):
        return False
    entry = _log_entry_for_date(logs, date_key, sid)
    if isinstance(entry, dict) and _log_rules.truthy(entry.get("done")):
        return False
    # Self-study is an explicit daily mode. It must still reconcile an
    # existing automatic snapshot even when the student has no regular class
    # or makeup registration for this date.
    if _student_is_self_study_on_date(logs, date_key, sid, stu):
        return True
    return _student_is_registered_on_date(stu, sid, date_key, extra=extra)


def _same_student_course_alias(left: dict, right: dict) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    identity_match = same_person(left, right)
    if identity_match is not None:
        return identity_match
    if str(left.get("name") or "").strip() != str(right.get("name") or "").strip():
        return False

    shared_doc = str(left.get("docUrl") or "").strip()
    if shared_doc and shared_doc == str(right.get("docUrl") or "").strip():
        return True

    for key in ("school", "grade", "level", "subCurriculum"):
        if str(left.get(key) or "").strip() != str(right.get(key) or "").strip():
            return False
    return True


def _active_student_alias_sid(students, student: dict, sid: str, date_key: str, absent) -> str:
    candidates = []
    for candidate in students if isinstance(students, list) else []:
        candidate_sid = str(candidate.get("id") or "").strip() if isinstance(candidate, dict) else ""
        if not candidate_sid or candidate_sid == sid:
            continue
        if not _same_student_course_alias(student, candidate):
            continue
        if _student_absent_on_date(absent, date_key, candidate_sid):
            continue
        if _student_is_registered_on_date(candidate, candidate_sid, date_key):
            candidates.append(candidate_sid)

    return candidates[0] if len(candidates) == 1 else ""


def _append_auto_assignment_videos(
    current,
    cur_vids: list[dict],
    blocked,
    target_count: int,
    *,
    allow_expand: bool = True,
):
    """Resize/re-scope an automatic assignment while preserving surviving metadata."""
    legacy_list = isinstance(current, list)
    if legacy_list:
        if not current:
            return current, False
    elif not isinstance(current, dict):
        return current, False
    elif str(current.get("source") or "").strip().casefold() != "auto":
        return current, False

    assigned = _normalize_video_assign_list(current)
    try:
        target_count = max(0, int(target_count))
    except (TypeError, ValueError):
        target_count = len(assigned)

    blocked_set = {str(mid or "").strip() for mid in (blocked or set()) if str(mid or "").strip()}
    course_mids = []
    course_mid_set = set()
    for video in cur_vids or []:
        mid = str(video.get("mid") or "").strip() if isinstance(video, dict) else ""
        if not mid or mid in course_mid_set:
            continue
        course_mid_set.add(mid)
        course_mids.append(mid)

    next_videos = []
    seen = set()
    for mid in assigned:
        if len(next_videos) >= target_count:
            break
        if mid not in course_mid_set or mid in seen:
            continue
        next_videos.append(mid)
        seen.add(mid)

    if allow_expand:
        for mid in course_mids:
            if len(next_videos) >= target_count:
                break
            if not mid or mid in seen or mid in blocked_set:
                continue
            next_videos.append(mid)
            seen.add(mid)

    if next_videos == assigned:
        return current, False
    if not next_videos:
        return None, True
    if legacy_list:
        return next_videos, True
    updated = dict(current)
    updated["videos"] = next_videos
    return updated, True


def _expand_consecutive_auto_assignment_in_updates(
    updates: dict,
    date_key: str,
    sid: str,
    students: list[dict],
    videos: list[dict],
    progress: dict,
    watch=None,
    weekend_slots=None,
    extra=None,
    absent=None,
    logs=None,
) -> bool:
    """Preserve the date snapshot when class slots change."""
    return False


def _reconcile_consecutive_auto_assignment(
    date_key: str,
    sid: str,
    students=None,
    videos=None,
    progress=None,
    watch=None,
    weekend_slots=None,
    extra=None,
    absent=None,
    logs=None,
) -> bool:
    """Schedule edits cannot resize an already-created daily snapshot."""
    return False


def _advance_existing_auto_assignment(
    current,
    cur_vids: list[dict],
    blocked,
    target_count: int,
    *,
    enforce_current_curriculum: bool = True,
):
    """Rebase only snapshots that contain out-of-current-course videos."""
    is_legacy_auto = isinstance(current, list)
    is_named_auto = (
        isinstance(current, dict)
        and str(current.get("source") or "").strip().casefold() == "auto"
        and not _is_manual_video_assignment(current)
    )
    if not is_legacy_auto and not is_named_auto:
        return current, False

    assigned = _normalize_video_assign_list(current)
    blocked_set = {
        str(mid or "").strip()
        for mid in (blocked or set())
        if str(mid or "").strip()
    }
    course_mids = []
    course_mid_set = set()
    for video in cur_vids or []:
        mid = str(video.get("mid") or "").strip() if isinstance(video, dict) else ""
        if not mid or mid in course_mid_set:
            continue
        course_mid_set.add(mid)
        course_mids.append(mid)

    outside_current_curriculum = (
        enforce_current_curriculum
        and any(mid not in course_mid_set for mid in assigned)
    )
    if not assigned or not outside_current_curriculum:
        return current, False

    next_videos = []
    seen = set()
    for mid in assigned:
        if len(next_videos) >= target_count:
            break
        if (
            (enforce_current_curriculum and mid not in course_mid_set)
            or mid in blocked_set
            or mid in seen
        ):
            continue
        next_videos.append(mid)
        seen.add(mid)

    for mid in course_mids:
        if len(next_videos) >= target_count:
            break
        if not mid or mid in seen or mid in blocked_set:
            continue
        next_videos.append(mid)
        seen.add(mid)
        if len(next_videos) >= target_count:
            break

    if not next_videos:
        return None, True
    if is_legacy_auto:
        return next_videos, next_videos != current

    next_assignment = dict(current)
    next_assignment["videos"] = next_videos
    return next_assignment, next_assignment != current




def _reconcile_auto_assignment_after_progress(
    date_key: str,
    sid: str,
    progress=None,
    watch=None,
) -> bool:
    """Preserve existing snapshots after progress or watch writes.

    Kept as a compatibility seam for focused tests and older imports. Assignment
    selection is date-bound and must never be derived again from completion state.
    """
    return False


def _ensure_today_auto_assign(
    updates,
    students,
    videos,
    progress,
    date_key: str | None = None,
    watch=None,
    logs=None,
    extra=None,
    absent=None,
    weekend_slots=None,
):
    today = date_key or _today_kst_iso()

    if not isinstance(updates, dict):
        updates = {}
    updates.setdefault(today, {})
    if not isinstance(updates[today], dict):
        updates[today] = {}

    valid_mids = set()
    for v in (videos or []):
        if isinstance(v, dict):
            mid = str(v.get("mid") or "").strip()
            if mid:
                valid_mids.add(mid)

    latest_status_by_sid = _build_latest_status_by_sid(progress)
    blocked_by_sid = _build_auto_assignment_blocked_by_sid(progress, watch or {})
    logs = logs if isinstance(logs, dict) else {}
    if extra is None:
        try:
            extra = load(EXTRA_PATH) or {}
        except Exception:
            extra = {}
    if absent is None:
        try:
            absent = load_absent()
        except Exception:
            absent = {}
    if weekend_slots is None:
        try:
            weekend_slots = load(WEEKEND_SLOTS_PATH) or {}
        except Exception:
            weekend_slots = {}

    # A regular automatic snapshot is immutable after its first creation.
    # Future dates are never passed here by the automatic-assignment authority.
    changed = False

    for stu in students or []:
        if not isinstance(stu, dict):
            continue

        sid = str(stu.get("id") or "").strip()
        if not sid:
            continue

        cur_vids = _student_current_curriculum_videos(stu, videos)
        cur_vids.sort(key=lambda v: (_chap_num(v), str(v.get("mid") or "")))

        cur = _sid_lookup(updates[today], sid)
        is_auto_target = _student_is_today_auto_target(
            stu,
            sid,
            today,
            extra=extra,
            absent=absent,
            logs=logs,
        )
        if not is_auto_target:
            scoped_assignment, scope_changed = _append_auto_assignment_videos(
                cur,
                cur_vids,
                set(),
                len(_normalize_video_assign_list(cur)),
                allow_expand=False,
            )
            if scope_changed:
                _write_sid_mapping(updates[today], sid, scoped_assignment)
                changed = True
            continue

        blocked = _blocked_mids_for_sid(blocked_by_sid, sid)
        max_assign = _effective_auto_video_assign_count(stu, sid, today, weekend_slots, absent)

        self_study = _student_is_self_study_on_date(logs, today, sid, stu)
        completion_videos = _student_completion_videos(stu, videos)
        if self_study:
            cur_vids = completion_videos

        auto_candidates = []
        for v in cur_vids:
            mid = str(v.get("mid") or "").strip()
            if not mid or mid not in valid_mids or mid in blocked:
                continue
            auto_candidates.append(mid)
            if len(auto_candidates) >= max_assign:
                break

        if self_study:
            if _is_manual_video_assignment(cur):
                continue

            completed_review_mids = _student_eligible_review_video_mids(
                stu,
                videos,
                progress,
                watch or {},
                today,
            )
            review_mids = _self_study_review_video_mids(
                completion_videos,
                _normalize_video_assign_list(cur),
                auto_candidates,
                eligible_mids=completed_review_mids,
            )
            next_assignment = (
                {"videos": review_mids, "source": SELF_STUDY_VIDEO_ASSIGN_SOURCE}
                if review_mids
                else None
            )
            if cur != next_assignment:
                _write_sid_mapping(updates[today], sid, next_assignment)
                changed = True
            continue
        current_course_mids = {
            str(video.get("mid") or "").strip()
            for video in cur_vids
            if str(video.get("mid") or "").strip()
        }
        if cur is not None and all(mid in current_course_mids for mid in _normalize_video_assign_list(cur)):
            continue

        next_assignment, assignment_changed = _advance_existing_auto_assignment(
            cur,
            cur_vids,
            blocked,
            max_assign,
        )
        if assignment_changed:
            _write_sid_mapping(updates[today], sid, next_assignment)
            cur = next_assignment
            changed = True

        resized_assignment, resized = _append_auto_assignment_videos(
            cur,
            cur_vids,
            blocked,
            max_assign,
            allow_expand=False,
        )
        if resized:
            _write_sid_mapping(updates[today], sid, resized_assignment)
            cur = resized_assignment
            changed = True

        completion_videos = cur_vids
        if _course_videos_completed(completion_videos, sid, latest_status_by_sid):
            # Completion blocks new work after stale automatic videos are removed.
            continue

        if cur is not None:
            continue

        if auto_candidates:
            print("[AUTOASSIGN] PICK sid =", sid, "picked =", auto_candidates, flush=True)
            updates[today][sid] = {"videos": auto_candidates, "source": "auto"}
            changed = True

    return updates


def _json_stable(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return ""


def _load_updates_with_auto_assign(
    students=None,
    videos=None,
    date_key: str | None = None,
    extra=None,
    absent=None,
    weekend_slots=None,
    logs=None,
):
    real_today = _today_kst_iso()
    target_date = str(date_key or real_today).strip()
    if target_date != real_today:
        # Future and historical reads are storage-only. Automatic snapshots are
        # created at the real KST date boundary, never pre-generated.
        return load(UPD_PATH) or {}

    students = students if students is not None else load(STU_PATH)
    videos = videos if videos is not None else load(VID_PATH)
    progress = _load_progress_strict()
    watch = load(WATCH_PATH)
    logs = logs if logs is not None else get_log_repository().read_logs(target_date)
    extra = extra if extra is not None else load(EXTRA_PATH)
    absent = absent if absent is not None else load_absent()
    weekend_slots = weekend_slots if weekend_slots is not None else load(WEEKEND_SLOTS_PATH)

    with _updates_lock():
        updates = load(UPD_PATH) or {}
        before = _json_stable(updates)
        fixed = _ensure_today_auto_assign(
            updates,
            students,
            videos,
            progress,
            date_key=target_date,
            watch=watch,
            logs=logs,
            extra=extra,
            absent=absent,
            weekend_slots=weekend_slots,
        )
        if _json_stable(fixed) != before:
            save_atomic(UPD_PATH, fixed)
        return fixed


def _progress_sids_from_query() -> list[str]:
    sid_values = request.args.getlist("sid")
    raw_values = list(request.args.getlist("sids"))
    if raw_values:
        raw_values.extend(sid_values)
    elif len(sid_values) > 1:
        raw_values.extend(sid_values)

    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        for part in str(raw or "").split(","):
            sid = part.strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            out.append(sid)
    return out


def _notification_progress_snapshot(progress: dict, sid: str):
    """Compatibility wrapper for progress milestone projection."""
    return progress_notification_snapshot(
        progress,
        sid,
        students_path=STU_PATH,
        videos_path=VID_PATH,
    )


def _notification_progress_commit(before, after, sid: str) -> int:
    """Compatibility wrapper for progress milestone delivery."""
    return commit_progress_notifications(before, after, sid)


def _is_public_student_request() -> bool:
    return getattr(g, "student_app_public_request", False) is True


def _public_session_sid() -> str | None:
    if not _is_public_student_request():
        return None
    sid = getattr(g, "student_app_active_sid", None)
    return sid if isinstance(sid, str) and sid else None


def _student_request_academy_allowed() -> bool:
    if not _is_public_student_request():
        return academy_network_allowed()
    client_ip = getattr(g, "student_app_client_ip", None)
    return ip_allowed(client_ip) if isinstance(client_ip, str) else False


def _latest_student_watch_payload(watch_all, sid: str) -> dict:
    """Project the existing /api/watch/latest shape for one session SID."""
    out: dict[str, dict] = {}
    for by_date in (watch_all.values() if isinstance(watch_all, dict) else []):
        if not isinstance(by_date, dict):
            continue
        watched = next(
            (by_date.get(key) for key in _sid_keys(sid) if isinstance(by_date.get(key), dict)),
            None,
        )
        if not isinstance(watched, dict):
            continue
        for raw_mid, raw_entry in watched.items():
            mid = str(raw_mid or "").strip()
            if not mid:
                continue
            normalized = _normalize_watch_entry(raw_entry)
            if mid not in out or _watch_rank(normalized) > _watch_rank(out[mid]):
                out[mid] = normalized
    return {"ok": True, "sid": sid, "date": "", "watch": out}


def _strip_public_bootstrap_links(value, restricted_scope: bool = False):
    """Recursively remove off-site answer and homework/material file authority."""
    if isinstance(value, list):
        return [_strip_public_bootstrap_links(item, restricted_scope) for item in value]
    if not isinstance(value, dict):
        return value

    stripped, _ = strip_answer_link_fields(value)
    out = {}
    for raw_key, raw_value in stripped.items():
        key = str(raw_key)
        normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
        if "answer" in normalized or "solution" in normalized:
            continue
        child_scope = restricted_scope or any(
            marker in normalized
            for marker in ("material", "homework", "attachment", "sourcefile", "video")
        )
        if child_scope and (
            normalized in {"url", "link", "path", "src", "source", "fileid"}
            or normalized.endswith(("url", "link", "path", "fileid"))
        ):
            continue
        out[raw_key] = _strip_public_bootstrap_links(raw_value, child_scope)
    return out


def _finalize_public_bootstrap(payload: dict, sid: str, academy_allowed: bool) -> dict:
    if not _is_public_student_request():
        return payload
    result = deepcopy(payload)
    result["academyAccessAllowed"] = academy_allowed
    result["outsideAcademyBlocked"] = not academy_allowed
    result["networkBlocked"] = not academy_allowed

    result["watch"] = _latest_student_watch_payload(load(WATCH_PATH) or {}, sid)
    return result if academy_allowed else _strip_public_bootstrap_links(result)


def _progress_for_sids(data: dict, sids: list[str], date: str = "") -> dict:
    out = {}
    days = [(date, data.get(date) if isinstance(data, dict) else {})] if date else (data.items() if isinstance(data, dict) else [])
    for day_key, day in days:
        if not isinstance(day, dict):
            continue
        filtered = {}
        for sid in sids:
            entry = _sid_lookup(day, sid)
            if isinstance(entry, dict) and entry:
                filtered[str(sid)] = entry
        if filtered:
            out[str(day_key)] = filtered
    if date and date not in out:
        out[date] = {}
    return out


# ─────────────────────────────────────────────
# 기본 API
# ─────────────────────────────────────────────
@bp_api_basic.get("/api/students")
def api_students():
    return jsonify(load(STU_PATH))


@bp_api_basic.route("/api/videos", methods=["GET", "POST"])
def api_videos():
    if request.method == "GET":
        return jsonify(load(VID_PATH))

    next_videos = _normalize_video_mid_fields(request.get_json(force=True))
    try:
        with file_lock(VID_PATH, timeout_sec=20.0, poll_sec=0.05):
            prev_videos = load(VID_PATH)
            changes = _video_catalog_identity_changes(prev_videos, next_videos)
            if changes["removedIds"] or changes["midChanges"]:
                return jsonify({
                    "ok": False,
                    "error": VIDEO_CATALOG_IDENTITY_CHANGE_ERROR,
                    "message": VIDEO_CATALOG_IDENTITY_CHANGE_MESSAGE,
                    **changes,
                }), 409
            save_atomic(VID_PATH, next_videos)
    except ValueError as exc:
        return jsonify({"ok": False, "error": "invalid_video_catalog", "message": str(exc)}), 400
    return "", 204


@bp_api_basic.route("/api/progress", methods=["GET"])
def api_progress():
    data = _load_progress_strict()
    date = str(request.args.get("date") or "").strip()
    sid = str(request.args.get("sid") or "").strip()
    sids = _progress_sids_from_query()

    if date:
        if not DATE_RE.match(date):
            return jsonify({"ok": False, "error": "bad date"}), 400
        day = data.get(date) if isinstance(data, dict) else {}
        if sids:
            return jsonify(_progress_for_sids(data, sids, date=date))
        if sid:
            entry = _sid_lookup(day if isinstance(day, dict) else {}, sid) or {}
            return jsonify({date: {str(sid): entry}})
        return jsonify({date: day if isinstance(day, dict) else {}})

    if sids:
        return jsonify(_progress_for_sids(data, sids))

    if sid:
        out = {}
        for d, day in (data.items() if isinstance(data, dict) else []):
            if not isinstance(day, dict):
                continue
            entry = _sid_lookup(day, sid)
            if isinstance(entry, dict) and entry:
                out[d] = {str(sid): entry}
        return jsonify(out)

    return jsonify(data)


@bp_api_basic.post("/api/progress/patch")
def api_progress_patch():
    """
    body:
      {
        "date": "YYYY-MM-DD",
        "sid": "전강우334",
        "progress": {
          "mid1": "done",
          "mid2": "interrupted",
          "mid3": "none"
        }
      }
    """
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    prog = body.get("progress") or {}
    source = str(body.get("source") or "").strip()

    if not date or not sid or not isinstance(prog, dict):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    if _is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

    try:
        with _progress_lock():
            current = dict(_load_progress_strict())
            notification_before = _notification_progress_snapshot(current, sid)

            current_day = current.get(date)
            day = dict(current_day) if isinstance(current_day, dict) else {}
            current[date] = day

            cur_sid = day.get(sid, {})
            if not isinstance(cur_sid, dict):
                cur_sid = {}

            merged = _merge_progress_day_sid(cur_sid, prog, source=source)

            if merged:
                day[sid] = merged
            else:
                day.pop(sid, None)

            if not day:
                current.pop(date, None)

            _save_progress_strict(current)

            notification_after = _notification_progress_snapshot(current, sid)

        _notification_progress_commit(notification_before, notification_after, sid)



        return jsonify({"ok": True, "progress": merged})
    except TimeoutError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp_api_basic.get("/api/updates")
def api_updates():
    if str(request.args.get("readOnly") or "").strip().lower() in {"1", "true", "yes"}:
        return nocache_resp(load(UPD_PATH) or {})
    return nocache_resp(_load_updates_with_auto_assign())


@bp_api_basic.post("/api/updates/patch")
def api_updates_patch():
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    remove = bool(body.get("remove"))

    if not date or not sid or not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if _is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

    if remove:
        incoming = {"remove": True}
    else:
        incoming = dict(body.get("entry") or {}) if isinstance(body.get("entry"), dict) else {}
        if "videos" in body:
            incoming["videos"] = body.get("videos")
        if not incoming:
            incoming["videos"] = []

    try:
        with _updates_lock():
            current = load(UPD_PATH) or {}
            day = current.setdefault(date, {})
            if not isinstance(day, dict):
                current[date] = {}
                day = current[date]

            if remove:
                _write_sid_mapping(day, sid, None)
                assignment = []
            else:
                assignment = _merge_update_assignment(_sid_lookup(day, sid), incoming)
                _write_sid_mapping(day, sid, assignment)

            if not day:
                current.pop(date, None)

            save_atomic(UPD_PATH, current)
        return jsonify({"ok": True, "assignment": assignment})
    except TimeoutError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@bp_api_basic.post("/api/updates/self-study")
def api_updates_self_study():
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    has_requested_videos = "videos" in body
    append_requested_videos = body.get("append") is True

    if not date or not sid or not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if _is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403
    if has_requested_videos and not isinstance(body.get("videos"), list):
        return jsonify({"ok": False, "error": "videos must be an array"}), 400

    students = load(STU_PATH) or []
    student = next(
        (stu for stu in students if isinstance(stu, dict) and str(stu.get("id") or "") == sid),
        None,
    )
    if not isinstance(student, dict):
        abort(404, description="학생을 찾을 수 없습니다.")

    logs = get_log_repository().read_logs(date, sid)
    if not _student_is_self_study_on_date(logs, date, sid, student):
        return jsonify({"ok": False, "error": "student is not self-study"}), 409

    absences = load_absent()
    if _student_absent_on_date(absences, date, sid):
        return jsonify({"ok": False, "error": "student is absent"}), 409
    log_entry = _log_entry_for_date(logs, date, sid)
    if isinstance(log_entry, dict) and _log_rules.truthy(log_entry.get("archived")):
        return jsonify({"ok": False, "error": "student is archived"}), 409

    videos = load(VID_PATH) or []
    progress = _load_progress_strict()
    watch = load(WATCH_PATH) or {}
    requested_videos = _normalize_video_assign_list(body.get("videos")) if has_requested_videos else []
    eligible_review_mids = _student_eligible_review_video_mids(
        student,
        videos,
        progress,
        watch,
        date,
    )
    invalid_requested_videos = [
        mid for mid in requested_videos
        if mid not in eligible_review_mids
    ]
    if invalid_requested_videos:
        return jsonify({
            "ok": False,
            "error": "video is not eligible for self-study review",
            "invalidVideos": invalid_requested_videos,
        }), 409

    try:
        with _updates_lock():
            updates = load(UPD_PATH) or {}
            if has_requested_videos:
                current = _sid_lookup(updates.get(date, {}), sid)
                current_source = (
                    str(current.get("source") or "").strip().casefold()
                    if isinstance(current, dict)
                    else ""
                )
                if _is_manual_video_assignment(current) and current_source != SELF_STUDY_VIDEO_ASSIGN_SOURCE.casefold():
                    return jsonify({"ok": False, "error": "manual assignment is protected"}), 409
            before = _json_stable(updates)
            fixed = _ensure_today_auto_assign(
                updates,
                [student],
                videos,
                progress,
                date_key=date,
                watch=watch,
                logs=logs,
            )
            if has_requested_videos:
                day = fixed.setdefault(date, {})
                current = _sid_lookup(day, sid)
                existing = (
                    [mid for mid in _normalize_video_assign_list(current) if mid in eligible_review_mids]
                    if append_requested_videos
                    else []
                )
                selected = []
                for mid in [*existing, *requested_videos]:
                    if mid not in selected:
                        selected.append(mid)
                assignment = (
                    {"videos": selected, "source": SELF_STUDY_VIDEO_ASSIGN_SOURCE}
                    if selected
                    else None
                )
                _write_sid_mapping(day, sid, assignment)
            else:
                assignment = _sid_lookup(fixed.get(date, {}), sid)
            if _json_stable(fixed) != before:
                save_atomic(UPD_PATH, fixed)
        return jsonify({"ok": True, "assignment": assignment})
    except TimeoutError as e:
        return jsonify({"ok": False, "error": str(e)}), 409


@bp_api_basic.get("/api/student/bootstrap")
def api_student_bootstrap():
    caller_sid = str(request.args.get("sid") or "").strip()
    session_sid = _public_session_sid()
    if _is_public_student_request() and session_sid is None:
        return jsonify({"ok": False, "code": "unauthenticated"}), 401
    sid = session_sid if session_sid is not None else caller_sid
    date = str(request.args.get("date") or _today_kst_iso()).strip()
    if not sid:
        return jsonify({"ok": False, "error": "missing sid"}), 400
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        return jsonify({"ok": False, "error": "bad date"}), 400

    if _is_ghost_student_sid(sid):
        return _ghost_student_bootstrap(date)

    students = load(STU_PATH) or []
    student = next((s for s in students if isinstance(s, dict) and str(s.get("id")) == sid), None)
    if not student:
        return jsonify({"ok": False, "error": "student not found"}), 404
    academy_allowed = _student_request_academy_allowed()

    log_repo = get_log_repository()
    log_entry = log_repo.read_entry(date, sid).entry
    logs = {date: {sid: log_entry}} if isinstance(log_entry, dict) and log_entry else {date: {}}
    self_study_day = _student_is_self_study_on_date(logs, date, sid, student)
    archived = isinstance(log_entry, dict) and _log_rules.truthy(log_entry.get("archived"))

    absences = load_absent()
    absent_for_date = {
        "by_date": {date: (absences.get("by_date") or {}).get(date, [])},
        "by_student": {sid: (absences.get("by_student") or {}).get(sid)}
            if (absences.get("by_student") or {}).get(sid) else {},
    }
    absent_today = _student_absent_on_date(absences, date, sid)
    registered_today = _student_is_registered_on_date(student, sid, date)

    dashboard_enabled = _student_dashboard_enabled()
    videos_all = None
    progress_all = None
    latest_status_by_sid = None
    if dashboard_enabled:
        videos_all = load(VID_PATH) or []
        progress_all = _load_progress_strict()
        latest_status_by_sid = _build_latest_status_by_sid(progress_all)

    if (not registered_today and not self_study_day) or absent_today:
        redirect_sid = _active_student_alias_sid(students, student, sid, date, absences)
        payload = {
            "ok": True,
            "date": date,
            "students": [student],
            "student": student,
            "videos": [],
            "reviewVideos": [],
            "updates": {date: {sid: []}},
            "materials": {},
            "assigns": {sid: []},
            "absent": absent_for_date,
            "logs": {date: {}},
            "assignedTests": [],
            "homeworkBooks": [],
            "courseBlocked": True,
            "selfStudy": self_study_day,
            "blockMessage": STUDENT_COURSE_BLOCK_MESSAGE,
            "academyAccessAllowed": academy_allowed,
            "outsideAcademyBlocked": not academy_allowed,
            "networkBlocked": not academy_allowed,
            "academyOnlyMessage": ACADEMY_ACCESS_MESSAGE,
            "redirectSid": redirect_sid,
            "recoveredSid": redirect_sid,
            "recoveryReason": "active_course_alias" if redirect_sid else "",
        }
        if dashboard_enabled:
            payload["dashboard"] = _student_dashboard_projection(
                student=student,
                sid=sid,
                date_key=date,
                videos=videos_all,
                latest_status_by_sid=latest_status_by_sid,
                homework_books=[],
                absences=absences,
            )
        return nocache_resp(_finalize_public_bootstrap(payload, sid, academy_allowed))

    if videos_all is None:
        videos_all = load(VID_PATH) or []
    if progress_all is None:
        progress_all = _load_progress_strict()
    if latest_status_by_sid is None:
        latest_status_by_sid = _build_latest_status_by_sid(progress_all)
    course_videos_completed = _course_videos_completed(
        _student_completion_videos(student, videos_all),
        sid,
        latest_status_by_sid,
    )
    if date == _today_kst_iso() and not _is_public_student_request():
        updates = _load_updates_with_auto_assign(
            students=students,
            videos=videos_all,
            date_key=date,
            logs=logs,
        )
    else:
        updates = load(UPD_PATH) or {}
    day_updates = updates.get(date) if isinstance(updates, dict) else {}
    assignment = _sid_lookup(day_updates if isinstance(day_updates, dict) else {}, sid)
    response_assignment = assignment
    watch_all = load(WATCH_PATH) or {}
    # Build the finished set before the self-study response projection below.
    assigned_videos = _normalize_video_assign_list(response_assignment)
    assigned_set = set(assigned_videos)
    progress_until_date = {
        raw_date: value
        for raw_date, value in progress_all.items()
        if str(raw_date) <= str(date)
    }
    watch_until_date = {
        raw_date: value
        for raw_date, value in (watch_all.items() if isinstance(watch_all, dict) else [])
        if str(raw_date) <= str(date)
    }
    finished_by_sid = _build_auto_assignment_blocked_by_sid(progress_until_date, watch_until_date)
    finished_mids = _blocked_mids_for_sid(finished_by_sid, sid)
    playlist_assigned_videos = [
        mid for mid in assigned_videos if mid not in finished_mids
    ]
    eligible_mids = _student_eligible_review_video_mids(
        student,
        videos_all,
        progress_all,
        watch_all,
        date,
    )
    assignment_source = (
        str(assignment.get("source") or "").strip().casefold()
        if isinstance(assignment, dict)
        else ""
    )
    if self_study_day or assignment_source == SELF_STUDY_VIDEO_ASSIGN_SOURCE.casefold():
        response_assignment = _filter_self_study_assignment_for_response(
            assignment,
            eligible_mids,
        )
    else:
        response_assignment = _filter_auto_assignment_for_current_curriculum(
            assignment,
            student,
            videos_all,
        )
    assigned_videos = _normalize_video_assign_list(response_assignment)
    assigned_set = set(assigned_videos)
    today_auto_completed_mids: set[str] = set()
    if (
        date == _today_kst_iso()
        and not self_study_day
        and assignment_source == "auto"
        and not _is_manual_video_assignment(response_assignment)
    ):
        states_through_date = _student_review_states_through_date(
            student,
            progress_all,
            watch_all,
            date,
        )
        today_auto_completed_mids = {
            mid
            for mid in assigned_set
            if isinstance(states_through_date.get(mid), dict)
            and states_through_date[mid].get("status") == "done"
        }

    # Self-study filtering and today's completed-auto retention both affect the visible slice.
    playlist_assigned_videos = [
        mid
        for mid in assigned_videos
        if mid not in finished_mids or mid in today_auto_completed_mids
    ]
    playlist_assigned_set = set(playlist_assigned_videos)

    primary_video_mids = _student_primary_video_mids(student, videos_all)
    videos = []
    for v in videos_all:
        if not isinstance(v, dict):
            continue
        mid = str(v.get("mid") or "").strip()
        if mid not in playlist_assigned_set:
            continue
        item = dict(v)
        item["isExtraAssignment"] = mid not in primary_video_mids
        if mid in today_auto_completed_mids:
            item["todayAutoAssignmentStatus"] = "done"
        videos.append(item)
    videos = _academy_restricted_student_videos(videos, academy_allowed)

    review_videos = []
    if not absent_today and not archived:
        review_videos = _student_review_video_projection(
            student,
            videos_all,
            progress_all,
            watch_all,
            date,
            playlist_assigned_videos,
            academy_allowed,
        )

    material_catalog, assigns, _page_folders, _material_state_degraded = _load_material_state_for_read()
    material_assignment = _sid_lookup(assigns, sid)
    assigned_materials = _assigned_material_list(material_assignment)
    materials = _filter_materials_for_assignment(material_catalog, assigned_materials)

    json_logs_for_assigned = log_repo.read_json_map()

    assigned_tests = _student_assigned_tests_for_date(
        progress_all,
        logs,
        date,
        sid,
        json_logs_for_assigned,
    )
    assigned_tests = _filter_assigned_tests_for_student_curriculum(assigned_tests, student)
    assigned_tests = _academy_restricted_assigned_tests(assigned_tests, academy_allowed)
    homework_books = _student_homework_book_names_from_log(log_entry)

    payload = {
        "ok": True,
        "date": date,
        "students": [student],
        "student": student,
        "videos": videos,
        "reviewVideos": review_videos,
        "updates": {date: {sid: response_assignment or []}},
        "materials": materials,
        "assigns": {sid: material_assignment or []},
        "absent": absent_for_date,
        "logs": logs,
        "assignedTests": assigned_tests,
        "homeworkBooks": homework_books,
        "selfStudy": self_study_day,
        "courseVideosCompleted": course_videos_completed,
        "academyAccessAllowed": academy_allowed,
        "outsideAcademyBlocked": not academy_allowed,
        "networkBlocked": not academy_allowed,
        "academyOnlyMessage": ACADEMY_ACCESS_MESSAGE,
    }
    if dashboard_enabled:
        payload["dashboard"] = _student_dashboard_projection(
            student=student,
            sid=sid,
            date_key=date,
            videos=videos_all,
            latest_status_by_sid=latest_status_by_sid,
            homework_books=homework_books,
            absences=absences,
        )
    return nocache_resp(_finalize_public_bootstrap(payload, sid, academy_allowed))


@bp_api_basic.route("/api/mat-assign", methods=["GET", "POST"])
def api_mat_assign():
    materials, assignments, page_folders, degraded = _load_material_state_for_read()
    if request.method == "GET":
        return _material_state_json_response(
            assignments,
            materials,
            assignments,
            page_folders,
            degraded=degraded,
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "code": "invalid_material_assignments"}), 400
    expected_revision = _normalize_material_state_revision(request.headers.get("If-Match"))
    if not expected_revision:
        return jsonify({"ok": False, "code": "material_state_revision_required"}), 428

    try:
        new_revision = replace_material_state_component(
            MAT_PATH,
            ASN_PATH,
            PAGE_FOLDERS_PATH,
            "assignments",
            body,
            expected_revision=expected_revision,
        )
    except MaterialStateConflictError as exc:
        response = make_response(
            jsonify({"ok": False, "code": "material_state_conflict"}),
            409,
        )
        response.headers["X-Material-State-Revision"] = exc.current_revision
        return response
    except (MaterialStateRecoveryRequiredError, TimeoutError) as exc:
        current_app.logger.error("Material assignment write is unavailable: %s", exc)
        return jsonify({"ok": False, "code": "material_state_unavailable"}), 503
    except ValueError:
        return jsonify({"ok": False, "code": "invalid_material_assignments"}), 400
    except Exception:
        current_app.logger.exception("Material assignment write failed")
        return jsonify({"ok": False, "code": "material_state_unavailable"}), 503

    response = make_response("", 204)
    response.headers["X-Material-State-Revision"] = new_revision
    return response


@bp_api_basic.get("/api/materials")
def api_materials():
    materials, assignments, page_folders, degraded = _load_material_state_for_read()
    return _material_state_json_response(
        materials,
        materials,
        assignments,
        page_folders,
        degraded=degraded,
    )


@bp_api_basic.route("/api/school-calendar", methods=["GET", "POST"])
def api_school_calendar():
    if request.method == "GET":
        return nocache_resp(load(CAL_PATH))
    data = request.get_json(force=True) or {}
    with _InterProcessFileLock(str(CAL_PATH) + ".lock", timeout_sec=4.0, poll_sec=0.05):
        save_atomic(CAL_PATH, data)
    return jsonify(data)


@bp_api_basic.post("/api/add-student")
def api_add_student():
    data = dict(request.get_json(force=True) or {})
    data.pop("id", None)
    data.pop("personId", None)
    data.pop("cloneFromSid", None)
    raw_name = str(data.get("name", "user"))
    name_slug = re.sub(r"[^0-9A-Za-z가-힣]", "", raw_name)
    _apply_able_auto_video_assign_default(data)

    if _person_identity_configured():
        if _person_identity_writes_degraded():
            return _person_identity_error("person identity recovery is required", 503)
        query_clone_sid = str(request.args.get("cloneFromSid") or "").strip()
        header_clone_sid = unquote(str(request.headers.get("X-Clone-From-Sid") or "").strip())
        if query_clone_sid and header_clone_sid and query_clone_sid != header_clone_sid:
            return jsonify({"ok": False, "error": "conflicting clone source SID"}), 400
        clone_from_sid = query_clone_sid or header_clone_sid
        if len(clone_from_sid) > 256:
            return jsonify({"ok": False, "error": "clone source SID is too long"}), 400
        try:
            created = create_student_with_identity(
                PERSONS_PATH,
                STU_PATH,
                PERSON_IDENTITY_JOURNAL_PATH,
                data,
                sid_prefix=name_slug,
                clone_from_sid=clone_from_sid,
                suffix_factory=lambda: random.randint(0, 999),
            )
        except PersonIdentityNotFoundError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 404
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except (
            PersonIdentityRecoveryRequiredError,
            PersonIdentityUnavailableError,
            PersonIdentityValidationError,
        ) as exc:
            return _person_identity_error(str(exc), 503)
        except TimeoutError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        enqueue_current_schedule_changes([created["id"]])
        return jsonify({"id": created["id"], "personId": created["personId"]})

    with file_lock(STU_PATH):
        students: List[dict] = load(STU_PATH)
        try:
            data["id"] = allocate_unique_sid(
                name_slug,
                [str(row.get("id") or "") for row in students if isinstance(row, dict)],
                suffix_factory=lambda: random.randint(0, 999),
            )
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        students.append(data)
        save_atomic(STU_PATH, students)
    enqueue_current_schedule_changes([data["id"]])
    return jsonify({"id": data["id"]})


@bp_api_basic.post("/api/feedback")
def api_feedback():
    import json as _json
    from core.paths import BASE
    data = request.get_json(force=True) or {}
    with open(BASE / "feedbacks.json", "a", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False)
        f.write("\n")
    return "", 204


def _normalize_extra_attend_patch(payload) -> dict[str, list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSON body")

    if "dates" in payload:
        raw_dates = payload.get("dates")
        if not isinstance(raw_dates, dict):
            raise ValueError("dates must be an object")
    else:
        raw_dates = {payload.get("date"): payload.get("sids")}

    normalized: dict[str, list[str]] = {}
    for raw_date, raw_sids in raw_dates.items():
        date_key = str(raw_date or "").strip()
        try:
            valid_date = bool(DATE_RE.fullmatch(date_key)) and dt.date.fromisoformat(date_key).isoformat() == date_key
        except ValueError:
            valid_date = False
        if not valid_date:
            raise ValueError("invalid date")
        if not isinstance(raw_sids, list):
            raise ValueError("sids must be a list")

        sids: list[str] = []
        seen: set[str] = set()
        for raw_sid in raw_sids:
            if isinstance(raw_sid, (dict, list)):
                raise ValueError("invalid sid")
            sid = str(raw_sid or "").strip()
            if not sid or sid in seen:
                continue
            if _is_ghost_student_sid(sid):
                raise PermissionError(GHOST_STUDENT_WRITE_ERROR)
            seen.add(sid)
            sids.append(sid)
        normalized[date_key] = sids

    if not normalized:
        raise ValueError("date patch is required")
    return normalized


def _extra_attend_sids(value) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(sid).strip() for sid in value if str(sid).strip()}


@bp_api_basic.route("/api/extra-attend", methods=["GET", "PATCH"])
def api_extra_attend():
    if request.method == "GET":
        return jsonify(load(EXTRA_PATH))

    try:
        date_patch = _normalize_extra_attend_patch(request.get_json(silent=True))
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    affected_sids: set[str] = set()
    changed_dates: set[str] = set()
    with file_lock(EXTRA_PATH):
        previous = load(EXTRA_PATH) or {}
        previous_map = previous if isinstance(previous, dict) else {}
        next_map = dict(previous_map)
        for date_key, sids in date_patch.items():
            previous_sids = previous_map.get(date_key)
            if _json_stable(previous_sids or []) == _json_stable(sids):
                continue
            changed_dates.add(date_key)
            affected_sids.update(_extra_attend_sids(previous_sids))
            affected_sids.update(sids)
            if sids:
                next_map[date_key] = sids
            else:
                next_map.pop(date_key, None)
        if changed_dates:
            save_atomic(EXTRA_PATH, next_map)

    real_today = _today_kst_iso()
    if real_today in changed_dates:
        # Only a real-today makeup change may initialize today's snapshot.
        _load_updates_with_auto_assign(date_key=real_today, extra=next_map)
    enqueue_current_schedule_changes(affected_sids)
    return jsonify({
        "ok": True,
        "dates": {date_key: date_patch[date_key] for date_key in date_patch},
        "changedDates": sorted(changed_dates),
    })


@bp_api_basic.route("/api/weekend-slots", methods=["GET", "POST"])
def api_weekend_slots():
    if request.method == "GET":
        return jsonify(load(WEEKEND_SLOTS_PATH))
    body = request.get_json(force=True) or {}
    with file_lock(WEEKEND_SLOTS_PATH):
        cur = load(WEEKEND_SLOTS_PATH)
        if not isinstance(cur, dict):
            cur = {}
        for date, mapping in (body.items() if isinstance(body, dict) else []):
            if not isinstance(mapping, dict):
                continue

            def norm(v):
                if isinstance(v, list):
                    return [int(x) for x in v if str(x).isdigit()]
                if str(v).isdigit():
                    return int(v)
                return v

            day = cur.setdefault(date, {})
            for k, v in mapping.items():
                sid = str(k)
                if v is None or v is False or v == []:
                    day.pop(sid, None)
                    continue
                day[sid] = norm(v)
            if not day:
                cur.pop(date, None)
        save_atomic(WEEKEND_SLOTS_PATH, cur)
    enqueue_current_schedule_changes(
        str(sid)
        for mapping in (body.values() if isinstance(body, dict) else [])
        for sid in (mapping.keys() if isinstance(mapping, dict) else [])
    )
    for date, mapping in (body.items() if isinstance(body, dict) else []):
        if not isinstance(mapping, dict) or not DATE_RE.match(str(date)):
            continue
        for sid in mapping:
            _reconcile_consecutive_auto_assignment(
                str(date),
                str(sid),
                weekend_slots=cur,
            )
    return "", 204


@bp_api_basic.get("/api/logs/entry")
def api_logs_entry():
    """
    GET /api/logs/entry?date=YYYY-MM-DD&sid=...
    - SQLite 우선 조회
    - 없거나 실패하면 logs.json fallback
    """
    date = str(request.args.get("date") or "").strip()
    sid = str(request.args.get("sid") or "").strip()

    if not date or not sid or not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad query"}), 400

    result = get_log_repository().read_entry(date, sid)
    return jsonify({"ok": True, "source": result.source, "entry": result.entry})


def _summarize_unarchived_done_logs(exclude_date: str = "") -> dict:
    return get_log_repository().summarize_unarchived_done(exclude_date)


@bp_api_basic.get("/api/logs/unarchived-summary")
def api_logs_unarchived_summary():
    """Return stale-record counts and each student's latest unarchived done log."""
    exclude_date = str(
        request.args.get("exclude_date")
        or request.args.get("excludeDate")
        or ""
    ).strip()
    if exclude_date and not DATE_RE.match(exclude_date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    return nocache_resp(_summarize_unarchived_done_logs(exclude_date))


@bp_api_basic.get("/api/homework-books")
def api_homework_books():
    logs = get_log_repository().read_logs()
    return nocache_resp(_log_rules.latest_homework_books_by_student(logs))


def _log_export_targets_from_query() -> dict[str, str] | None:
    raw = request.args.get("exportTargets")
    if raw is None:
        return None
    if len(raw) > 65536:
        raise ValueError("too many export targets")
    try:
        rows = json.loads(raw)
    except Exception as exc:
        raise ValueError("invalid export targets") from exc
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("invalid export targets")

    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("invalid export target")
        sid = str(row[0] or "").strip()
        date = str(row[1] or "").strip()
        if not sid or not DATE_RE.match(date):
            raise ValueError("invalid export target")
        try:
            dt.date.fromisoformat(date)
        except ValueError as exc:
            raise ValueError("invalid export target") from exc
        previous = out.get(sid, "")
        if date > previous:
            out[sid] = date
    return out


# ─────────────────────────────────────────────
# ✅ LOGS (dual-write)
# GET: SQLite 우선 + JSON 보강
# POST /api/logs/patch: SQLite 저장 + JSON 저장(둘 다)
# ─────────────────────────────────────────────
@bp_api_basic.get("/api/logs")
def api_logs():
    date_filter = str(request.args.get("date") or "").strip()
    sid_filter = str(request.args.get("sid") or "").strip()
    sid_filters = _progress_sids_from_query()
    if date_filter and not DATE_RE.match(date_filter):
        return jsonify({"ok": False, "error": "bad date"}), 400
    try:
        export_targets = _log_export_targets_from_query()
    except ValueError:
        return jsonify({"ok": False, "error": "bad exportTargets"}), 400
    repository = get_log_repository()
    if export_targets is not None:
        return nocache_resp(repository.read_export_history(export_targets))
    return nocache_resp(
        repository.read_logs(
            date_filter,
            sid_filter,
            sid_filters=sid_filters,
        )
    )


@bp_api_basic.post("/api/logs/patch")
def api_logs_patch():
    """
    dual-write PATCH
    body:
      {
        "date": "YYYY-MM-DD",
        "sid": "334",
        "entry": { ...변경 내용... },
        "__clear": ["notes", ...]
      }
    """
    body = request.get_json(force=True) or {}
    date = str(body.get("date") or "").strip()
    sid = str(body.get("sid") or "").strip()
    entry = body.get("entry") or {}
    base = body.get("base") if isinstance(body.get("base"), dict) else {}

    top_clear = body.get("__clear")
    if isinstance(top_clear, list) and isinstance(entry, dict):
        entry = dict(entry)
        entry["__clear"] = top_clear

    if not date or not sid or not isinstance(entry, dict):
        return jsonify({"ok": False, "error": "bad payload"}), 400
    if not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    if _is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

    entry = _repair_log_entry_placeholders(entry, sid)
    base = _repair_log_entry_placeholders(base, sid)

    result = get_log_repository().patch_entry(date, sid, entry, base)

    if result.json_conflict_entry is not None:
        return jsonify({
            "ok": False,
            "retryable": False,
            "error": "다른 화면에서 특이사항/숙제가 먼저 변경되었습니다. 새로고침 후 다시 저장해 주세요.",
            "entry": result.json_conflict_entry,
        }), 409

    if not result.sqlite_ok:
        # SQLite 기준 충돌이어도 legacy JSON 저장이 확인된 경우에만 호환 성공으로 응답한다.
        if result.sqlite_base_conflict:
            if not result.json_ok:
                return jsonify({
                    "ok": False,
                    "sqlite": False,
                    "json": False,
                    "error": "sqlite out-of-sync and legacy logs.json save failed",
                }), 409
            return jsonify({
                "ok": True,
                "sqlite": False,
                "json": result.json_ok,
                "entry": result.merged,
                "warning": "sqlite out-of-sync",
            })
        return jsonify({"ok": False, "sqlite": False, "error": str(result.sqlite_error) if result.sqlite_error else "sqlite failed"}), 409

    if not result.json_ok:
        return jsonify({
            "ok": True,
            "sqlite": True,
            "json": False,
            "entry": result.merged,
            "warning": "SQLite save succeeded, but legacy JSON log storage is out of sync.",
        })

    return jsonify({"ok": True, "sqlite": True, "json": True, "entry": result.merged})


@bp_api_basic.post("/api/logs/patch-batch")
def api_logs_patch_batch():
    """Apply up to 100 independent operational log patches with one dual-store save."""
    body = request.get_json(force=True) or {}
    patches = body.get("patches")
    if not isinstance(patches, list) or not 1 <= len(patches) <= 100:
        return jsonify({"ok": False, "error": "patches must contain 1 to 100 items"}), 400

    incoming = {}
    seen = set()
    for raw in patches:
        if not isinstance(raw, dict):
            return jsonify({"ok": False, "error": "bad patch item"}), 400

        date = str(raw.get("date") or "").strip()
        sid = str(raw.get("sid") or "").strip()
        entry = raw.get("entry") or {}
        clear = raw.get("__clear")

        if not date or not sid or not DATE_RE.match(date) or not isinstance(entry, dict):
            return jsonify({"ok": False, "error": "bad patch item"}), 400
        if clear is not None and not isinstance(clear, list):
            return jsonify({"ok": False, "error": "bad clear list"}), 400
        if _is_ghost_student_sid(sid):
            return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

        target_key = (date, sid)
        if target_key in seen:
            return jsonify({"ok": False, "error": "duplicate patch target"}), 400
        seen.add(target_key)

        safe_entry = dict(entry)
        if isinstance(clear, list) and clear:
            safe_entry["__clear"] = clear
        incoming.setdefault(date, {})[sid] = _repair_log_entry_placeholders(safe_entry, sid)

    result = get_log_repository().legacy_post(incoming)
    if not result.sqlite_ok:
        return jsonify({
            "ok": False,
            "sqlite": False,
            "error": "batch sqlite save failed",
        }), 409

    return jsonify({"ok": True, "sqlite": True, "json": True, "count": len(seen)})


# ─────────────────────────────────────────────
# 기타
# ─────────────────────────────────────────────
@bp_api_basic.delete("/api/students/<string:sid>")
def api_delete_student(sid: str):
    if _person_identity_configured():
        if _person_identity_writes_degraded():
            return _person_identity_error("person identity recovery is required", 503)
        try:
            retire_student_identity(
                PERSONS_PATH,
                STU_PATH,
                PERSON_IDENTITY_JOURNAL_PATH,
                sid,
            )
        except PersonIdentityNotFoundError:
            abort(404, description="학생을 찾을 수 없습니다.")
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except (
            PersonIdentityRecoveryRequiredError,
            PersonIdentityUnavailableError,
            PersonIdentityValidationError,
        ) as exc:
            return _person_identity_error(str(exc), 503)
        except TimeoutError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return "", 204

    with file_lock(STU_PATH):
        students: List[dict] = load(STU_PATH)
        for i, s in enumerate(students):
            if str(s.get("id")) == str(sid):
                del students[i]
                save_atomic(STU_PATH, students)
                return "", 204
    abort(404, description="학생을 찾을 수 없습니다.")


@bp_api_basic.post("/api/update")
def api_update_student_field():
    body = request.get_json(force=True) or {}
    sid = body.get("id")
    field = body.get("field")
    value = body.get("value")

    if not sid or not field:
        abort(400)

    field = str(field)
    if field in {"id", "personId"}:
        return jsonify({"ok": False, "error": f"field is immutable: {field}"}), 400

    identity_configured = _person_identity_configured()
    if identity_configured and _person_identity_writes_degraded():
        return _person_identity_error("person identity recovery is required", 503)

    canonical_profile_field = _PERSON_PROFILE_FIELD_ALIASES.get(field, field)
    if identity_configured and canonical_profile_field in PERSON_PROFILE_FIELDS:
        try:
            update_person_profile_field(
                PERSONS_PATH,
                STU_PATH,
                PERSON_IDENTITY_JOURNAL_PATH,
                str(sid),
                canonical_profile_field,
                value,
            )
        except PersonIdentityNotFoundError:
            abort(404)
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except (
            PersonIdentityRecoveryRequiredError,
            PersonIdentityUnavailableError,
            PersonIdentityValidationError,
        ) as exc:
            return _person_identity_error(str(exc), 503)
        except TimeoutError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return "OK"

    def updated_student_rows(current_students: List[dict]) -> List[dict] | None:
        next_students = deepcopy(current_students)
        next_value = value
        for s in next_students:
            if str(s.get("id")) != str(sid):
                continue
            was_able = _student_uses_able_curriculum(s)
            if field == AUTO_VIDEO_ASSIGN_FIELD:
                next_value = _coerce_auto_video_assign_count(next_value)
            s[field] = next_value
            if (
                field in {"curriculum", "subCurriculum"}
                and _student_uses_able_curriculum(s)
                and (not was_able or _is_able_curriculum_value(next_value))
            ):
                _apply_able_auto_video_assign_default(s)
            return next_students
        return None

    students: List[dict] | None = None
    if identity_configured:
        def mutation(directory: dict, current_students: list):
            next_students = updated_student_rows(current_students)
            if next_students is None:
                raise PersonIdentityNotFoundError("student SID was not found")
            validate_identity_state(directory, next_students)
            return directory, next_students, next_students

        try:
            students = mutate_identity_state(
                PERSONS_PATH,
                STU_PATH,
                PERSON_IDENTITY_JOURNAL_PATH,
                mutation,
            )
        except PersonIdentityNotFoundError:
            abort(404)
        except PersonIdentityConflictError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except (
            PersonIdentityRecoveryRequiredError,
            PersonIdentityUnavailableError,
            PersonIdentityValidationError,
        ) as exc:
            return _person_identity_error(str(exc), 503)
        except TimeoutError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
    else:
        with file_lock(STU_PATH):
            current_students: List[dict] = load(STU_PATH)
            students = updated_student_rows(current_students)
            if students is not None:
                save_atomic(STU_PATH, students)

    if students is None:
        abort(404)

    if field in {"curriculum", "subCurriculum", "selfStudyDays"}:
        _load_updates_with_auto_assign(students=students)
    elif re.fullmatch(r"day\d+", str(field)):
        # Schedule projection runs after releasing the student-store lock so
        # downstream update locks cannot invert the lock order.
        _reconcile_consecutive_auto_assignment(
            _today_kst_iso(),
            str(sid),
            students=students,
        )
        _load_updates_with_auto_assign(students=students)
    if re.fullmatch(r"(?:day|visitTime)\d+", str(field)):
        enqueue_current_schedule_changes([str(sid)])
    return "OK"


@bp_api_basic.get("/api/ping")
def api_ping():
    return "ok"
