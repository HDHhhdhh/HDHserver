from __future__ import annotations

import datetime as dt
import random
import re
import threading
import time
import json
from urllib.parse import parse_qs, urlparse
from typing import List, Optional, Tuple, Dict, Any

from flask import Blueprint, abort, jsonify, request

from core.paths import (
    BASE,
    STU_PATH, VID_PATH, PRG_PATH, UPD_PATH, ASN_PATH, MAT_PATH, CAL_PATH,
    EXTRA_PATH, LOGS_PATH, CLINIC_PATH, TODAY_ORDER_PATH, WEEKEND_SLOTS_PATH,
    WATCH_PATH, TESTS_CFG_PATH,
)
from core.ghost_student import (
    GHOST_STUDENT_ID,
    GHOST_STUDENT_WRITE_ERROR,
    is_ghost_student_sid,
    mapping_contains_ghost_student_sid,
)
from core.log_repository import LogRepository
from core import log_rules as _log_rules
from core.network_access import (
    ACADEMY_ACCESS_MESSAGE,
    academy_network_allowed,
    strip_answer_link_fields,
)
from core.progress_rules import (
    PROGRESS_ALL_STUDENTS_META_KEY,
    PROGRESS_MANUAL_META_KEY,
    TEST_ASSIGN_CLEAR_META_KEY,
    WATCH_AUTO_PROGRESS_META_KEY,
    merge_progress_day_sid as _merge_progress_day_sid,
    merge_watch_entry as _merge_watch_entries_for_mid_migration,
    watch_auto_status as _watch_auto_status,
)
from core.storage import InterProcessFileLock, load, save_atomic, nocache_resp
from core.absent import load_absent, save_absent, DATE_RE

bp_api_basic = Blueprint("api_basic", __name__)

CT = {"Content-Type": "application/json"}
STUDENT_COURSE_BLOCK_MESSAGE = "수업일이 아닌 것 같습니다. 선생님께 문의주세용 ^_^"
GHOST_STUDENT_HOMEWORK_BOOK = "고스트 숙제 교재"
GHOST_STUDENT_VIDEO_MID = "ghost-outside-video"
GHOST_STUDENT_TEST_ID = "ghost-outside-answer-test"
_PROGRESS_CACHE_LOCK = threading.Lock()
_PROGRESS_CACHE_SIGNATURE: tuple[int, int] | None = None
_PROGRESS_CACHE_DATA: dict | None = None

# ─────────────────────────────────────────────
# 공통 CRUD
# ─────────────────────────────────────────────
def crud(path):
    if request.method == "GET":
        return jsonify(load(path))
    obj = request.get_json(force=True)
    save_atomic(path, obj)
    return "", 204


def _progress_file_signature() -> tuple[int, int] | None:
    try:
        stat = PRG_PATH.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _load_progress_strict() -> dict:
    global _PROGRESS_CACHE_DATA, _PROGRESS_CACHE_SIGNATURE

    signature = _progress_file_signature()
    with _PROGRESS_CACHE_LOCK:
        if _PROGRESS_CACHE_SIGNATURE == signature and _PROGRESS_CACHE_DATA is not None:
            return _PROGRESS_CACHE_DATA

    try:
        data = {} if signature is None else json.loads(PRG_PATH.read_text("utf-8-sig"))
    except Exception as e:
        raise RuntimeError(f"progress.json read failed: {e}") from e

    if not isinstance(data, dict):
        raise RuntimeError("progress.json must be an object")

    with _PROGRESS_CACHE_LOCK:
        _PROGRESS_CACHE_SIGNATURE = signature
        _PROGRESS_CACHE_DATA = data
    return data


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


def _student_is_registered_on_date(student: dict, sid: str, date_key: str) -> bool:
    if _student_has_schedule_on_date(student, date_key):
        return True
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


def _progress_status_rank(status: str) -> int:
    s = str(status or "").strip()
    if s == "done":
        return 3
    if s == "interrupted":
        return 2
    if s == "skip":
        return 1
    return 0


def _merge_progress_status(existing: str, incoming: str) -> str:
    a = str(existing or "").strip()
    b = str(incoming or "").strip()
    return a if _progress_status_rank(a) >= _progress_status_rank(b) else b


def _replace_mid_in_updates(data, old_mid: str, new_mid: str) -> bool:
    changed = False
    for by_day in (data.values() if isinstance(data, dict) else []):
        if not isinstance(by_day, dict):
            continue
        for sid, raw in list(by_day.items()):
            if isinstance(raw, list):
                next_raw = [new_mid if str(x) == old_mid else x for x in raw]
                if next_raw != raw:
                    by_day[sid] = next_raw
                    changed = True
            elif isinstance(raw, dict) and isinstance(raw.get("videos"), list):
                videos = raw.get("videos") or []
                next_videos = [new_mid if str(x) == old_mid else x for x in videos]
                if next_videos != videos:
                    next_raw = dict(raw)
                    next_raw["videos"] = next_videos
                    by_day[sid] = next_raw
                    changed = True
    return changed


def _replace_mid_in_progress(data, old_mid: str, new_mid: str) -> bool:
    changed = False
    for by_day in (data.values() if isinstance(data, dict) else []):
        if not isinstance(by_day, dict):
            continue
        for sid, per_sid in list(by_day.items()):
            if not isinstance(per_sid, dict) or old_mid not in per_sid:
                continue
            old_status = str(per_sid.pop(old_mid) or "").strip()
            new_status = _merge_progress_status(per_sid.get(new_mid), old_status)
            if new_status:
                per_sid[new_mid] = new_status
            changed = True
            if not per_sid:
                by_day.pop(sid, None)
    return changed


def _replace_mid_in_watch(data, old_mid: str, new_mid: str) -> bool:
    changed = False
    for by_day in (data.values() if isinstance(data, dict) else []):
        if not isinstance(by_day, dict):
            continue
        for sid, per_sid in list(by_day.items()):
            if not isinstance(per_sid, dict) or old_mid not in per_sid:
                continue
            old_entry = per_sid.pop(old_mid)
            per_sid[new_mid] = _merge_watch_entries_for_mid_migration(per_sid.get(new_mid), old_entry)
            changed = True
            if not per_sid:
                by_day.pop(sid, None)
    return changed


def _migrate_video_mid_references(prev_videos, next_videos):
    prev_map = {}
    for item in (prev_videos or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or "").strip()
        if key:
            prev_map[key] = item

    replacements = []
    for item in (next_videos or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or "").strip()
        if not key or key not in prev_map:
            continue

        old_mid = str(prev_map[key].get("mid") or "").strip()
        new_mid = str(item.get("mid") or "").strip()
        if old_mid and new_mid and old_mid != new_mid:
            replacements.append((old_mid, new_mid))

    if not replacements:
        return

    updates = load(UPD_PATH) or {}
    progress = _load_progress_strict()
    watch = load(WATCH_PATH) or {}

    updates_changed = False
    progress_changed = False
    watch_changed = False

    for old_mid, new_mid in replacements:
        updates_changed = _replace_mid_in_updates(updates, old_mid, new_mid) or updates_changed
        progress_changed = _replace_mid_in_progress(progress, old_mid, new_mid) or progress_changed
        watch_changed = _replace_mid_in_watch(watch, old_mid, new_mid) or watch_changed

    if updates_changed:
        save_atomic(UPD_PATH, updates)
    if progress_changed:
        save_atomic(PRG_PATH, progress)
    if watch_changed:
        save_atomic(WATCH_PATH, watch)


# ─────────────────────────────────────────────
# ✅ 프로세스 간 파일 락 (JSON 저장 보호용)
# ─────────────────────────────────────────────
class _InterProcessFileLock(InterProcessFileLock):
    """Backward-compatible alias for modules importing the old route-local lock."""


def _logs_lock():
    lp = str(getattr(LOGS_PATH, "__fspath__", lambda: str(LOGS_PATH))())
    return _InterProcessFileLock(lp + ".lock", timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0)


def _progress_lock():
    pp = str(getattr(PRG_PATH, "__fspath__", lambda: str(PRG_PATH))())
    return _InterProcessFileLock(pp + ".lock", timeout_sec=30.0, poll_sec=0.05, stale_sec=30.0)


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
    return source == "manual" or value.get("manual") is True or value.get("manualVideoAssign") is True


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


def _normalize_test_answer_round(round_value) -> str:
    raw = str(round_value or "1").strip()
    match = re.search(r"\d+", raw)
    if match:
        return match.group(0)
    return "1"


def _drive_file_url(file_id: str) -> str:
    fid = str(file_id or "").strip()
    return f"https://drive.google.com/file/d/{fid}/view?usp=drivesdk" if fid else ""


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


def _answer_url_from_link_entry(entry) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        for key in ("answerUrl", "answer_url", "solutionUrl", "solution_url", "url", "link"):
            value = str(entry.get(key) or "").strip()
            if value:
                return value
    return ""


def _assignment_direct_answer_url(item: dict) -> str:
    direct = _answer_url_from_link_entry(item)
    if direct:
        return direct

    source_files = item.get("sourceFiles") or item.get("source_files")
    if isinstance(source_files, dict):
        direct = _answer_url_from_link_entry(source_files)
        if direct:
            return direct

    return ""


def _test_assignment_category_key(item: dict) -> str:
    source = " ".join(str(item.get(key) or "") for key in (
        "category", "categoryKey", "categoryLabel", "label", "type"
    ))
    upper = source.upper()
    compact = re.sub(r"\s+", "", source)
    if re.search(r"\bUNIT\b", upper) or "\ub2e8\uc6d0\ud3c9\uac00" in source or "\ub2e8\uc6d0" in source:
        return "UNIT"
    if "REVIEW" in upper or "\ubcf5\uc2b5" in compact:
        return "REVIEW"
    if "SCHOOL_PAST" in upper or "SCHOOL" in upper or "\ud559\uad70\uc9c0" in compact or "\ud559\uad50\ubcc4" in compact:
        return "SCHOOL_PAST"
    if "ILSAN_PAST" in upper or "ILSAN" in upper or "\uc77c\uc0b0" in compact:
        return "ILSAN_PAST"
    return ""


def _normalize_test_assignment_difficulty(category_key: str, value) -> str:
    text = str(value or "").strip()
    if category_key == "ILSAN_PAST":
        if "\uadf8\ub798\ud504" in text:
            return "\uadf8\ub798\ud504 \ud3ec\ud568"
        if text == "\uc0c1" or "\uc911\uc0c1" in text:
            return "\uc911\uc0c1"
        if "\uc911" in text:
            return "\uc911"
    return text


def _test_assignment_has_answer_link(item: dict) -> bool:
    return _test_assignment_category_key(item) in {"UNIT", "REVIEW", "SCHOOL_PAST", "ILSAN_PAST"}


def _test_config_answer_url(test: dict) -> str:
    if not isinstance(test, dict):
        return ""
    direct = _answer_url_from_link_entry(test)
    if direct:
        return direct
    source_files = test.get("sourceFiles") or test.get("source_files")
    if isinstance(source_files, dict):
        direct = _answer_url_from_link_entry(source_files)
        if direct:
            return direct
        for key in ("solutionFileId", "solution_file_id", "answerFileId", "answer_file_id"):
            url = _drive_file_url(source_files.get(key))
            if url:
                return url
    for key in ("solutionFileId", "solution_file_id", "answerFileId", "answer_file_id"):
        url = _drive_file_url(test.get(key))
        if url:
            return url
    return ""


def _candidate_test_ids(item: dict) -> list[str]:
    candidates = []
    for key in ("id", "testId", "sourceId", "source_id"):
        raw = str(item.get(key) or "").strip()
        if not raw:
            continue
        candidates.append(raw)
        stripped = re.sub(r"_r[123]$", "", raw)
        if stripped != raw:
            candidates.append(stripped)
    out = []
    seen = set()
    for value in candidates:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _find_test_config_for_assignment(item: dict) -> dict:
    category_key = _test_assignment_category_key(item)
    if category_key not in {"UNIT", "REVIEW", "SCHOOL_PAST", "ILSAN_PAST"}:
        return {}

    config = _load_tests_config_for_answer_links()
    category = (config.get("categories") or {}).get(category_key) if isinstance(config, dict) else {}
    tests = category.get("tests") if isinstance(category, dict) else []
    if not isinstance(tests, list):
        return {}

    ids = set(_candidate_test_ids(item))
    if ids:
        for test in tests:
            if not isinstance(test, dict):
                continue
            test_ids = {
                str(test.get("id") or "").strip(),
                str(test.get("sourceId") or test.get("source_id") or "").strip(),
            }
            if ids.intersection(x for x in test_ids if x):
                return test

    item_name = str(item.get("name") or item.get("testName") or "").strip()
    item_label = str(item.get("label") or "").strip()
    item_round = _normalize_test_answer_round(item.get("round"))
    item_cur = str(item.get("curriculum") or "").strip()
    item_difficulty = _normalize_test_assignment_difficulty(
        category_key,
        item.get("difficulty"),
    )
    item_term = str(item.get("term") or "").strip()

    for test in tests:
        if not isinstance(test, dict):
            continue
        test_name = str(test.get("name") or "").strip()
        name_ok = item_name == test_name if item_name else bool(test_name and test_name in item_label)
        if not name_ok:
            continue
        if item_round and _normalize_test_answer_round(test.get("round")) != item_round:
            continue
        if item_cur and str(test.get("curriculum") or "").strip() != item_cur:
            continue
        test_difficulty = _normalize_test_assignment_difficulty(
            category_key,
            test.get("difficulty"),
        )
        if item_difficulty and test_difficulty != item_difficulty:
            continue
        if item_term and str(test.get("term") or "").strip() != item_term:
            continue
        return test
    return {}


def _test_assignment_answer_url(item: dict) -> str:
    if not isinstance(item, dict) or not _test_assignment_has_answer_link(item):
        return ""

    direct_url = _assignment_direct_answer_url(item)
    if direct_url:
        return direct_url

    configured_test = _find_test_config_for_assignment(item)
    config_url = _test_config_answer_url(configured_test)
    if config_url:
        return config_url

    link_map = _load_test_answer_link_map()
    if not link_map:
        return ""

    round_key = _normalize_test_answer_round(item.get("round"))
    for candidate in (item, configured_test):
        for test_id in _candidate_test_ids(candidate):
            rounds = link_map.get(test_id)
            if isinstance(rounds, dict):
                url = _answer_url_from_link_entry(rounds.get(round_key))
                if url:
                    return url
            url = _answer_url_from_link_entry(rounds)
            if url:
                return url
    return ""


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


def _merge_updates_payload(current, incoming):
    if not isinstance(current, dict):
        current = {}
    if not isinstance(incoming, dict):
        return current

    out = dict(current)
    for date, by_sid in incoming.items():
        date_s = str(date or "").strip()
        if not DATE_RE.match(date_s) or not isinstance(by_sid, dict):
            continue

        day = out.setdefault(date_s, {})
        if not isinstance(day, dict):
            out[date_s] = {}
            day = out[date_s]

        for sid, value in by_sid.items():
            sid_s = str(sid or "").strip()
            if not sid_s:
                continue
            merged = _merge_update_assignment(_sid_lookup(day, sid_s), value)
            _write_sid_mapping(day, sid_s, merged)

        if not day:
            out.pop(date_s, None)
    return out


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


def _student_homework_books(sid: str) -> List[str]:
    try:
        students = load(STU_PATH) or []
    except Exception:
        students = []
    if not isinstance(students, list):
        return []

    sid_s = str(sid or "").strip()
    stu = next(
        (s for s in students if isinstance(s, dict) and str(s.get("id") or "").strip() == sid_s),
        None,
    )
    if not stu:
        return []

    books: List[str] = []
    for key in sorted(stu.keys(), key=lambda k: int(k[7:]) if re.match(r"^subBook\d+$", str(k)) else 999):
        if not re.match(r"^subBook\d+$", str(key)):
            continue
        val = str(stu.get(key) or "").strip()
        if val and val not in books:
            books.append(val)
    return books


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
        "submissionRestricted": True,
    }

    # Code-only ghost for outside-Wi-Fi UI checks. It must never enter
    # students.json, updates.json, logs, progress, or tests data.
    return nocache_resp({
        "ok": True,
        "date": date,
        "students": [ghost_student],
        "student": ghost_student,
        "videos": [ghost_video],
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
        "testSubmissionBlocked": True,
    })


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
    out = {}
    if not isinstance(progress, dict):
        return out

    for d in sorted(progress.keys()):
        day = progress.get(d) or {}
        if not isinstance(day, dict):
            continue
        for sid, mids in day.items():
            if not isinstance(mids, dict):
                continue
            sm = out.setdefault(str(sid), {})
            for mid, st in mids.items():
                mid_s = str(mid)
                if mid_s.startswith("__") or mid_s == "tests":
                    continue
                sm[mid_s] = st
    return out


def _build_auto_assignment_blocked_by_sid(progress: dict, watch: dict) -> dict:
    blocked: dict[str, set[str]] = {}
    manual_cleared_at: dict[tuple[str, str], str] = {}

    if isinstance(progress, dict):
        for d in sorted(progress.keys()):
            day = progress.get(d) or {}
            if not isinstance(day, dict):
                continue
            for sid, mids in day.items():
                if not isinstance(mids, dict):
                    continue
                sid_s = str(sid)
                manual_meta = mids.get(PROGRESS_MANUAL_META_KEY)
                if not isinstance(manual_meta, dict):
                    manual_meta = {}
                for mid, st in mids.items():
                    mid_s = str(mid)
                    if mid_s.startswith("__") or mid_s == "tests":
                        continue
                    st_s = str(st or "").strip()
                    key = (sid_s, mid_s)
                    if _is_finished_video_progress_status(st_s):
                        blocked.setdefault(sid_s, set()).add(mid_s)
                    elif st_s == "none" and manual_meta.get(mid_s):
                        blocked.setdefault(sid_s, set()).discard(mid_s)
                        manual_cleared_at[key] = str(d)

    if isinstance(watch, dict):
        for d in sorted(watch.keys()):
            by_date = watch.get(d) or {}
            if not isinstance(by_date, dict):
                continue
            for sid, mids in by_date.items():
                if not isinstance(mids, dict):
                    continue
                sid_s = str(sid)
                for mid, entry in mids.items():
                    mid_s = str(mid or "").strip()
                    if not mid_s:
                        continue
                    status = _watch_auto_status(entry)
                    if status != "done":
                        continue
                    cleared_at = manual_cleared_at.get((sid_s, mid_s), "")
                    if cleared_at and str(cleared_at) >= str(d):
                        continue
                    blocked.setdefault(sid_s, set()).add(mid_s)

    return blocked


def _today_kst_iso() -> str:
    return dt.datetime.now(KST).date().isoformat()


def _ensure_today_auto_assign(updates, students, videos, progress, date_key: str | None = None, watch=None):
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

    def _normalize_assigned(val):
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        if isinstance(val, dict):
            vids = val.get("videos")
            if isinstance(vids, list):
                return [str(x).strip() for x in vids if str(x).strip()]
        return []

    changed = False

    for sid, cur in list(updates[today].items()):
        assigned = _normalize_assigned(cur)
        if not assigned:
            continue
        cleaned = [mid for mid in assigned if mid in valid_mids]
        if cleaned != assigned:
            if cleaned:
                updates[today][sid] = cleaned
            else:
                updates[today].pop(sid, None)
            changed = True

    for stu in students or []:
        if not isinstance(stu, dict):
            continue

        sid = str(stu.get("id") or "").strip()
        if not sid:
            continue

        cur_key = (stu.get("curriculum") or "").strip()
        sub_key = (stu.get("subCurriculum") or "").strip()

        cur_vids = [
            v for v in (videos or [])
            if isinstance(v, dict)
            and (v.get("curriculum") or "").strip() == cur_key
            and (v.get("subCurriculum") or "").strip() == sub_key
        ]
        cur_vids.sort(key=lambda v: (_chap_num(v), str(v.get("mid") or "")))

        completion_videos = cur_vids or _student_completion_videos(stu, videos)
        if _course_videos_completed(completion_videos, sid, latest_status_by_sid):
            cur = _sid_lookup(updates[today], sid)
            if _has_assigned(cur) and _is_manual_video_assignment(cur):
                continue
            if cur is not None:
                _write_sid_mapping(updates[today], sid, None)
                changed = True
            continue

        cur = _sid_lookup(updates[today], sid)
        if _has_assigned(cur):
            continue

        blocked = {str(mid) for mid in (blocked_by_sid.get(sid) or set())}

        max_assign = _student_auto_video_assign_count(stu)

        picked = []
        for v in cur_vids:
            mid = str(v.get("mid") or "").strip()
            if not mid:
                continue
            if mid not in valid_mids:
                continue
            if mid in blocked:
                continue
            picked.append(mid)
            if len(picked) >= max_assign:
                break

        if picked:
            print("[AUTOASSIGN] PICK sid =", sid, "picked =", picked, flush=True)
            updates[today][sid] = {"videos": picked, "source": "auto"}
            changed = True

    return updates


def _json_stable(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return ""


def _load_updates_with_auto_assign(students=None, videos=None, date_key: str | None = None):
    students = students if students is not None else load(STU_PATH)
    videos = videos if videos is not None else load(VID_PATH)
    progress = load(PRG_PATH)
    watch = load(WATCH_PATH)

    with _updates_lock():
        updates = load(UPD_PATH) or {}
        before = _json_stable(updates)
        fixed = _ensure_today_auto_assign(updates, students, videos, progress, date_key=date_key, watch=watch)
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
@bp_api_basic.route("/api/students", methods=["GET", "POST"])
def api_students():
    return crud(STU_PATH)


@bp_api_basic.route("/api/videos", methods=["GET", "POST"])
def api_videos():
    if request.method == "GET":
        return jsonify(load(VID_PATH))

    prev_videos = load(VID_PATH)
    next_videos = _normalize_video_mid_fields(request.get_json(force=True))
    save_atomic(VID_PATH, next_videos)
    _migrate_video_mid_references(prev_videos, next_videos)
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
            current = _load_progress_strict()

            day = current.setdefault(date, {})
            if not isinstance(day, dict):
                current[date] = {}
                day = current[date]

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

            save_atomic(PRG_PATH, current)

        return jsonify({"ok": True, "progress": merged})
    except TimeoutError as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp_api_basic.route("/api/updates", methods=["GET", "POST"])
def api_updates():
    if request.method == "GET":
        return nocache_resp(_load_updates_with_auto_assign())

    incoming = request.get_json(force=True) or {}
    if mapping_contains_ghost_student_sid(incoming):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403
    with _updates_lock():
        current = load(UPD_PATH) or {}
        merged = _merge_updates_payload(current, incoming)
        save_atomic(UPD_PATH, merged)
    return "", 204


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


@bp_api_basic.get("/api/student/bootstrap")
def api_student_bootstrap():
    sid = str(request.args.get("sid") or "").strip()
    date = str(request.args.get("date") or _today_kst_iso()).strip()
    if not sid:
        return jsonify({"ok": False, "error": "missing sid"}), 400
    if not DATE_RE.match(date):
        return jsonify({"ok": False, "error": "bad date"}), 400

    if _is_ghost_student_sid(sid):
        return _ghost_student_bootstrap(date)

    students = load(STU_PATH) or []
    student = next((s for s in students if isinstance(s, dict) and str(s.get("id")) == sid), None)
    if not student:
        return jsonify({"ok": False, "error": "student not found"}), 404
    academy_allowed = academy_network_allowed()

    absences = load_absent()
    absent_for_date = {
        "by_date": {date: (absences.get("by_date") or {}).get(date, [])},
        "by_student": {sid: (absences.get("by_student") or {}).get(sid)}
            if (absences.get("by_student") or {}).get(sid) else {},
    }

    if not _student_is_registered_on_date(student, sid, date):
        return nocache_resp({
            "ok": True,
            "date": date,
            "students": [student],
            "student": student,
            "videos": [],
            "updates": {date: {sid: []}},
            "materials": {},
            "assigns": {sid: []},
            "absent": absent_for_date,
            "logs": {date: {}},
            "assignedTests": [],
            "homeworkBooks": [],
            "courseBlocked": True,
            "blockMessage": STUDENT_COURSE_BLOCK_MESSAGE,
            "academyAccessAllowed": academy_allowed,
            "outsideAcademyBlocked": not academy_allowed,
            "networkBlocked": not academy_allowed,
            "academyOnlyMessage": ACADEMY_ACCESS_MESSAGE,
        })

    videos_all = load(VID_PATH) or []
    progress_all = load(PRG_PATH) or {}
    latest_status_by_sid = _build_latest_status_by_sid(progress_all)
    course_videos_completed = _course_videos_completed(
        _student_completion_videos(student, videos_all),
        sid,
        latest_status_by_sid,
    )
    if date == _today_kst_iso():
        updates = _load_updates_with_auto_assign(students=students, videos=videos_all, date_key=date)
    else:
        updates = load(UPD_PATH) or {}
    day_updates = updates.get(date) if isinstance(updates, dict) else {}
    assignment = _sid_lookup(day_updates if isinstance(day_updates, dict) else {}, sid)
    assigned_videos = _normalize_video_assign_list(assignment)
    assigned_set = set(assigned_videos)

    primary_video_mids = _student_primary_video_mids(student, videos_all)
    videos = []
    for v in videos_all:
        if not isinstance(v, dict):
            continue
        mid = str(v.get("mid") or "").strip()
        if mid not in assigned_set:
            continue
        item = dict(v)
        item["isExtraAssignment"] = mid not in primary_video_mids
        videos.append(item)
    videos = _academy_restricted_student_videos(videos, academy_allowed)

    assigns = load(ASN_PATH) or {}
    material_assignment = _sid_lookup(assigns if isinstance(assigns, dict) else {}, sid)
    assigned_materials = _assigned_material_list(material_assignment)
    materials = _filter_materials_for_assignment(load(MAT_PATH) or {}, assigned_materials)

    log_repo = get_log_repository()
    log_entry = log_repo.read_entry(date, sid).entry
    logs = {date: {sid: log_entry}} if isinstance(log_entry, dict) and log_entry else {date: {}}
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

    return nocache_resp({
        "ok": True,
        "date": date,
        "students": [student],
        "student": student,
        "videos": videos,
        "updates": {date: {sid: assignment or []}},
        "materials": materials,
        "assigns": {sid: material_assignment or []},
        "absent": absent_for_date,
        "logs": logs,
        "assignedTests": assigned_tests,
        "homeworkBooks": homework_books,
        "courseVideosCompleted": course_videos_completed,
        "academyAccessAllowed": academy_allowed,
        "outsideAcademyBlocked": not academy_allowed,
        "networkBlocked": not academy_allowed,
        "academyOnlyMessage": ACADEMY_ACCESS_MESSAGE,
    })


@bp_api_basic.route("/api/mat-assign", methods=["GET", "POST"])
def api_mat_assign():
    return crud(ASN_PATH)


@bp_api_basic.route("/api/materials", methods=["GET", "POST"])
def api_materials():
    if request.method == "GET":
        return jsonify(load(MAT_PATH))
    save_atomic(MAT_PATH, request.get_json(force=True))
    return "", 204


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
    students: List[dict] = load(STU_PATH)
    data = request.get_json(force=True) or {}
    raw_name = str(data.get("name", "user"))
    name_slug = re.sub(r"[^0-9A-Za-z가-힣]", "", raw_name)
    data["id"] = f"{name_slug}{random.randint(0, 999):03d}"
    _apply_able_auto_video_assign_default(data)
    students.append(data)
    save_atomic(STU_PATH, students)
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


@bp_api_basic.route("/api/extra-attend", methods=["GET", "POST"])
def api_extra_attend():
    return crud(EXTRA_PATH)


@bp_api_basic.route("/api/weekend-slots", methods=["GET", "POST"])
def api_weekend_slots():
    if request.method == "GET":
        return jsonify(load(WEEKEND_SLOTS_PATH))
    body = request.get_json(force=True) or {}
    cur = load(WEEKEND_SLOTS_PATH)
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
    exclude_date = str(
        request.args.get("exclude_date")
        or request.args.get("excludeDate")
        or ""
    ).strip()
    if exclude_date and not DATE_RE.match(exclude_date):
        return jsonify({"ok": False, "error": "bad date"}), 400
    return jsonify(_summarize_unarchived_done_logs(exclude_date))


# ─────────────────────────────────────────────
# ✅ LOGS (dual-write)
# GET: SQLite 우선 + JSON 보강
# POST /api/logs/patch: SQLite 저장 + JSON 저장(둘 다)
# POST /api/logs: 레거시 전체 업로드도 둘 다 반영
# ─────────────────────────────────────────────
@bp_api_basic.route("/api/logs", methods=["GET", "POST"])
def api_logs():
    if request.method == "GET":
        date_filter = str(request.args.get("date") or "").strip()
        sid_filter = str(request.args.get("sid") or "").strip()
        if date_filter and not DATE_RE.match(date_filter):
            return jsonify({"ok": False, "error": "bad date"}), 400
        return nocache_resp(get_log_repository().read_logs(date_filter, sid_filter))

    incoming = request.get_json(force=True) or {}
    if not isinstance(incoming, dict):
        incoming = {}

    result = get_log_repository().legacy_post(incoming)

    if not result.sqlite_ok:
        return jsonify({"ok": False, "sqlite": False, "error": str(result.sqlite_error) if result.sqlite_error else "sqlite failed"}), 409

    return "", 204


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


# ─────────────────────────────────────────────
# 기타
# ─────────────────────────────────────────────
@bp_api_basic.delete("/api/students/<string:sid>")
def api_delete_student(sid: str):
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

    students: List[dict] = load(STU_PATH)
    for s in students:
        if str(s.get("id")) == str(sid):
            was_able = _student_uses_able_curriculum(s)
            if field == AUTO_VIDEO_ASSIGN_FIELD:
                value = _coerce_auto_video_assign_count(value)
            s[field] = value
            if (
                field in {"curriculum", "subCurriculum"}
                and _student_uses_able_curriculum(s)
                and (not was_able or _is_able_curriculum_value(value))
            ):
                _apply_able_auto_video_assign_default(s)
            save_atomic(STU_PATH, students)
            return "OK"
    abort(404)


@bp_api_basic.get("/api/ping")
def api_ping():
    return "ok"
