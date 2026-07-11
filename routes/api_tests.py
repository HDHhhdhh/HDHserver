from __future__ import annotations

import os
from statistics import median, pstdev
import datetime as dt
import re
import time
from typing import Final, Tuple, TypedDict

from flask import Blueprint, current_app, jsonify, request

from core.ghost_student import (
    GHOST_STUDENT_WRITE_ERROR,
    is_ghost_student_sid,
    mapping_contains_ghost_student_sid,
)
from core.network_access import academy_network_allowed, strip_tests_config_answer_links
from core.paths import (
    LOGS_PATH, TESTS_PATH, STU_PATH, PRG_PATH,
    TESTS_CFG_PATH
)
from core.storage import load, save_atomic, nocache_resp, utc_now_isoz, file_lock

bp_api_tests = Blueprint("api_tests", __name__)
TEST_TYPE_ORDER = ("REVIEW", "UNIT", "TRAINING_PACK", "SCHOOL_PAST", "ILSAN_PAST", "FINAL", "HELL")
TEST_ASSIGNMENT_TYPE_LABELS = {
    "REVIEW": "복습 테스트",
    "UNIT": "단원평가",
    "TRAINING_PACK": "트레이닝팩",
    "SCHOOL_PAST": "학군지 기출",
    "ILSAN_PAST": "일산 기출",
    "FINAL": "파이널",
    "HELL": "HELL",
}
TEST_ASSIGNMENT_ACTIVE_STATUSES = {"assigned", "interrupted"}
OCR_MAX_IMAGE_BYTES = 8 * 1024 * 1024
OCR_PHASE2A_REVIEW_ROUTE_ENABLED_ENV = "OCR_PHASE2_REVIEW_ROUTE_ENABLED"
OCR_PHASE2A_TRUTHY_VALUES = {"1", "true", "yes", "on"}
OCR_PHASE2A_REVIEW_TEST_ID = "t_unit_daesu_01_lv3_r1"
OCR_PHASE2A_REVIEW_ROUND = 1
OCR_PHASE2A_REVIEW_ALLOWED_TESTS: Final[dict[str, int]] = {
    OCR_PHASE2A_REVIEW_TEST_ID: OCR_PHASE2A_REVIEW_ROUND,
    "t_unit_daesu_02_lv3_r1": 1,
}
OCR_PHASE2A_UNIT_REVIEW_ROUNDS: Final[frozenset[int]] = frozenset((1, 2, 3))
OCR_PHASE2B_IMAGE_FIELD = "image"
OCR_PHASE2B_ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
OCR_PHASE2B_ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
OCR_PHASE2A_MOCK_ANSWERS = (
    "1", "-3", "x=n", "0.5", "2",
    "ㄴ,ㄹ", "5", "2x+1", "4", "6",
    "256", "a/2", "5", "1", "-1<x<5",
    "y=n", "2", "139/2", "x±2=4", "26sqrt(21)",
)
OCR_PHASE2A_REVIEW_CANDIDATES = {
    3: ("x=2", "3", "x=n", "x=?"),
    10: ("0", "6", "?"),
    18: ("129/2", "139/2", "?"),
    19: ("x+2=4", "3", "x±2=4", "x-2=4"),
}
OCR_STUDENT_FORBIDDEN_KEYS = {
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "score",
    "wrong",
    "pct",
}
OCR_STUDENT_FORBIDDEN_VALUE_TOKENS = (
    "C:\\",
    "C:/",
    "server-ocr",
    "phase2c_route_uploads",
    "crop_benchmark_inputs",
)
OCR_REVIEW_META_TEXT_FIELDS = (
    "photo_correction",
    "answer_box_extraction",
    "answer_box_source",
    "provider_input",
    "cache_status",
    "cache_source",
    "provider_status",
)
OCR_REVIEW_META_INT_FIELDS = (
    "crop_count",
    "contact_sheet_count",
    "provider_call_count",
)
OCR_REVIEW_META_TEXT_MAX_LENGTH: Final = 80
INTERNAL_TEST_RECORD_FIELDS: Final[frozenset[str]] = frozenset({"submittedAnswers", "answersText", "wrongDetails"})
SUBMIT_OFFSET_GUARD_MIN_PROBLEMS: Final = 10
SUBMIT_OFFSET_GUARD_MIN_SHIFTED_RATIO: Final = 0.6
SUBMIT_OFFSET_GUARD_MIN_DELTA: Final = 5
SUBMIT_PROGRESS_STATUS_SKIP_MODES: Final = {"skip", "none", "disabled"}
SUBMIT_PROGRESS_STATUS_MARK_DONE_MODES: Final = {"mark_done", "submit_complete"}
SUBMIT_PROGRESS_STATUS_AUTHORIZED_VALUES: Final = {"true", "1", "yes", "authorized"}
SUBMIT_PROGRESS_STATUS_OCR_SOURCES: Final = {"ocr_review", "ocr-review", "ocr"}


class WrongAnswerDetail(TypedDict):
    questionNo: int
    myAnswer: str
    correctAnswer: str

TEST_LEVEL_RE = re.compile(r"""
  (?:\(|\[)?\s*
  (?:lv\.?|LV\.?|레벨)\s*\.?\s*([0-9]{1,2})
  \s*(?:\)|\])?
""", re.VERBOSE)


def _tests_lock():
    from routes.api_basic import _InterProcessFileLock

    tp = str(getattr(TESTS_PATH, "__fspath__", lambda: str(TESTS_PATH))())
    return _InterProcessFileLock(tp + ".lock", timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0)


def _tests_config_lock():
    from routes.api_basic import _InterProcessFileLock

    tp = str(getattr(TESTS_CFG_PATH, "__fspath__", lambda: str(TESTS_CFG_PATH))())
    return _InterProcessFileLock(tp + ".lock", timeout_sec=20.0, poll_sec=0.05, stale_sec=30.0)


def _append_test_record(entry: dict, record: dict) -> dict:
    base = dict(entry) if isinstance(entry, dict) else {}
    tests = base.get("tests")
    if not isinstance(tests, list):
        tests = []
    else:
        tests = [x for x in tests if isinstance(x, dict)]
    tests.append(record)
    base["tests"] = tests
    return base

def _strip_prefix_for_display(name: str) -> str:
    s = str(name or "").strip()
    if " / " in s:
        s = s.split(" / ", 1)[1].strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _parse_unit_and_test_level(name: str) -> tuple[str, int | None]:
    s = _strip_prefix_for_display(name)
    if not s:
        return "", None

    m = TEST_LEVEL_RE.search(s)
    lvl = None
    if m:
        try:
            lvl = int(m.group(1))
        except Exception:
            lvl = None
        s = (s[:m.start()] + s[m.end():]).strip()
        s = re.sub(r"\s+", " ", s)

    s = s.strip(" -_/|()[]")
    s = re.sub(r"\s+", " ", s).strip()
    return s, lvl

def _canon_test_name(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return ""
    if " / " in s:
        s = s.split(" / ", 1)[1].strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _normalize_test_type(raw: str) -> str:
    s = str(raw or "").strip()
    up = s.upper()
    compact = re.sub(r"\s+", "", s)
    if "REVIEW" in up or "복습" in compact:
        return "REVIEW"
    if "TRAINING" in up or "트레이닝팩" in compact or "트팩" in compact:
        return "TRAINING_PACK"
    if "SCHOOL" in up or "학군지" in compact:
        return "SCHOOL_PAST"
    if "ILSAN" in up or "일산" in compact:
        return "ILSAN_PAST"
    if "HELL" in up:
        return "HELL"
    if "FINAL" in up:
        return "FINAL"
    if "UNIT" in up or "단원" in s:
        return "UNIT"
    return ""

def _normalize_test_term(raw: str) -> str:
    s = str(raw or "").strip()
    compact = re.sub(r"\s+", "", s)
    if "기말" in compact or "FINAL" in s.upper():
        return "기말고사"
    if "중간" in compact or "MID" in s.upper():
        return "중간고사"
    return s

def _build_test_catalog(cfg: dict) -> dict:
    cats = cfg.get("categories") if isinstance(cfg, dict) else None
    if not isinstance(cats, dict):
        return {"by_id": {}, "by_name": {}}

    by_id: dict[str, dict] = {}
    by_name: dict[str, list[dict]] = {}

    for cat_key, cat in cats.items():
        if not isinstance(cat, dict):
            continue
        type_key = _normalize_test_type(cat.get("label") or cat_key)
        tests = cat.get("tests")
        if not isinstance(tests, list):
            continue
        for t in tests:
            if not isinstance(t, dict):
                continue
            test_id = str(t.get("id") or "").strip()
            canon = _canon_test_name(t.get("name"))
            curriculum = str(t.get("curriculum") or "").strip()
            unit_name, test_level = _parse_unit_and_test_level(canon)
            meta = {
                "type": type_key or _normalize_test_type(canon) or "UNIT",
                "curriculum": curriculum,
                "test_name": canon,
                "unit_name": unit_name or canon,
                "test_level": test_level,
                "difficulty": str(t.get("difficulty") or "").strip(),
                "term": _normalize_test_term(t.get("term") or t.get("examTerm") or t.get("examPeriod") or t.get("exam_period") or ""),
                "round": str(t.get("round") or "").strip(),
                "source_id": str(t.get("sourceId") or t.get("source_id") or "").strip(),
            }
            if test_id:
                by_id[test_id] = meta
            if canon:
                by_name.setdefault(canon, []).append(meta)

    return {"by_id": by_id, "by_name": by_name}

def _resolve_test_meta(raw_name: str, test_id: str, catalog: dict) -> dict:
    canon = _canon_test_name(raw_name)
    unit_name, test_level = _parse_unit_and_test_level(canon)

    base = {
        "type": _normalize_test_type(raw_name) or ("UNIT" if canon else ""),
        "curriculum": "",
        "test_name": canon,
        "unit_name": unit_name or canon,
        "test_level": test_level,
        "term": _normalize_test_term(raw_name),
    }

    by_id = catalog.get("by_id") if isinstance(catalog, dict) else {}
    by_name = catalog.get("by_name") if isinstance(catalog, dict) else {}
    if not isinstance(by_id, dict):
        by_id = {}
    if not isinstance(by_name, dict):
        by_name = {}

    test_id_s = str(test_id or "").strip()
    if test_id_s and isinstance(by_id.get(test_id_s), dict):
        return dict(by_id[test_id_s])

    candidates = [x for x in by_name.get(canon, []) if isinstance(x, dict)]
    if len(candidates) == 1:
        return dict(candidates[0])

    if candidates:
        type_set = {str(x.get("type") or "").strip() for x in candidates if str(x.get("type") or "").strip()}
        cur_set = {str(x.get("curriculum") or "").strip() for x in candidates if str(x.get("curriculum") or "").strip()}
        if len(type_set) == 1:
            base["type"] = next(iter(type_set))
        if len(cur_set) == 1:
            base["curriculum"] = next(iter(cur_set))

    if not base["type"] and canon:
        base["type"] = "UNIT"
    return base


def _test_assignment_category_label(raw_type: str) -> str:
    type_key = _normalize_test_type(raw_type)
    return TEST_ASSIGNMENT_TYPE_LABELS.get(type_key, str(raw_type or "").strip())


def _test_assignment_round_label(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw if "회" in raw else f"{raw}회차"


def _test_assignment_status_name(value) -> str:
    raw = value.get("status") if isinstance(value, dict) else value
    status = str(raw or "").strip().lower()
    if status in {"assigned", "done", "interrupted", "skip"}:
        return status
    return "assigned" if status else ""


def _test_assignment_is_active(value) -> bool:
    return _test_assignment_status_name(value) in TEST_ASSIGNMENT_ACTIVE_STATUSES


def _test_assignment_done_value(value):
    if isinstance(value, dict):
        updated = dict(value)
        updated["status"] = "done"
        return updated
    return "done"


def _assignment_label_from_parts(parts) -> str:
    return " / ".join(str(part).strip() for part in parts if str(part or "").strip())


def _submitted_assignment_label_candidates(record: dict, meta_snapshot: dict) -> set[str]:
    candidates: set[str] = set()
    names = [
        record.get("name"),
        record.get("testName"),
        meta_snapshot.get("test_name") if isinstance(meta_snapshot, dict) else "",
        meta_snapshot.get("unit_name") if isinstance(meta_snapshot, dict) else "",
    ]
    clean_names: list[str] = []
    for raw_name in names:
        name = str(raw_name or "").strip()
        canon = _canon_test_name(name)
        for candidate in (name, canon):
            if candidate and candidate not in candidates:
                candidates.add(candidate)
                clean_names.append(candidate)

    primary_name = clean_names[0] if clean_names else ""
    category = _test_assignment_category_label(meta_snapshot.get("type") if isinstance(meta_snapshot, dict) else "")
    curriculum = str(meta_snapshot.get("curriculum") or "").strip() if isinstance(meta_snapshot, dict) else ""
    difficulty = str(meta_snapshot.get("difficulty") or "").strip() if isinstance(meta_snapshot, dict) else ""
    term = _normalize_test_term(meta_snapshot.get("term") or "") if isinstance(meta_snapshot, dict) else ""
    round_label = _test_assignment_round_label(meta_snapshot.get("round") if isinstance(meta_snapshot, dict) else "")

    for parts in (
        (category, curriculum, difficulty, round_label, primary_name),
        (category, curriculum, difficulty, term, round_label, primary_name),
    ):
        label = _assignment_label_from_parts(parts)
        if label:
            candidates.add(label)
    return candidates


def _assignment_status_matches_submitted_id(value, test_id: str, source_id: str) -> bool:
    if not isinstance(value, dict):
        return False
    test_id = str(test_id or "").strip()
    source_id = str(source_id or "").strip()
    explicit_ids = [
        str(value.get(key) or "").strip()
        for key in ("id", "testId", "test_id")
    ]
    explicit_ids = [current for current in explicit_ids if current]
    if test_id and test_id in explicit_ids:
        return True
    if test_id and explicit_ids:
        return False

    for key in ("sourceId", "source_id"):
        current = str(value.get(key) or "").strip()
        if current and source_id and current == source_id:
            return True
    return False


def _last_assignment_label_part(label: str) -> str:
    return str(label or "").split(" / ")[-1].strip()


def _matching_submitted_assignment_labels(tests: dict, record: dict, meta_snapshot: dict) -> list[str]:
    candidates = _submitted_assignment_label_candidates(record, meta_snapshot)
    submitted_names = {_canon_test_name(name) for name in candidates if _canon_test_name(name)}
    test_id = str(record.get("testId") or "").strip()
    source_id = str(record.get("sourceId") or "").strip()
    exact_matches: list[str] = []
    active_name_matches: list[str] = []

    for label, status_value in tests.items():
        if not _test_assignment_is_active(status_value):
            continue
        label_text = str(label or "").strip()
        if label_text in candidates or _assignment_status_matches_submitted_id(status_value, test_id, source_id):
            exact_matches.append(label)
            continue
        last_part = _last_assignment_label_part(label_text)
        if _canon_test_name(last_part) in submitted_names:
            active_name_matches.append(label)

    if exact_matches:
        return exact_matches
    if len(active_name_matches) == 1:
        return active_name_matches
    return []


def _mark_submitted_assignment_done(date: str, sid: str, record: dict, meta_snapshot: dict) -> bool:
    date_key = str(date or "").strip()
    sid_key = str(sid or "").strip()
    if not date_key or not sid_key:
        return False

    with file_lock(PRG_PATH):
        progress = load(PRG_PATH)
        if not isinstance(progress, dict):
            return False
        day = progress.get(date_key)
        if not isinstance(day, dict):
            return False
        entry_key = sid_key if sid_key in day else str(sid_key)
        entry = day.get(entry_key)
        if not isinstance(entry, dict):
            return False
        tests = entry.get("tests")
        if not isinstance(tests, dict) or not tests:
            return False

        matches = _matching_submitted_assignment_labels(tests, record, meta_snapshot)
        if not matches:
            return False

        updated_tests = dict(tests)
        for label in matches:
            updated_tests[label] = _test_assignment_done_value(updated_tests.get(label))
        entry = dict(entry)
        entry["tests"] = updated_tests
        day = dict(day)
        day[entry_key] = entry
        progress[date_key] = day
        save_atomic(PRG_PATH, progress)
        return True


def _mark_submitted_assignment_done_best_effort(date: str, sid: str, record: dict, meta_snapshot: dict) -> bool:
    try:
        return _mark_submitted_assignment_done(date, sid, record, meta_snapshot)
    except Exception as exc:
        print("[submit-test] progress test status update failed:", exc, flush=True)
        return False


def _submit_payload_is_ocr_review(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    answer_source = str(data.get("answerSource") or data.get("answer_source") or "").strip().lower()
    return answer_source in SUBMIT_PROGRESS_STATUS_OCR_SOURCES or data.get("ocrReview") is True


def _submit_progress_status_authorized(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    value = data.get("progressStatusAuthorized")
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in SUBMIT_PROGRESS_STATUS_AUTHORIZED_VALUES
    return False


def _submit_progress_status_policy(data: dict) -> dict:
    requested_mode = str(data.get("progressStatusMode") or "").strip().lower() if isinstance(data, dict) else ""
    is_ocr_review = _submit_payload_is_ocr_review(data)

    if requested_mode in SUBMIT_PROGRESS_STATUS_SKIP_MODES:
        return {
            "attempted": False,
            "completed": False,
            "status": "skipped",
            "reason": "request_skipped_progress_status",
            "source": "ocr_review" if is_ocr_review else "manual",
        }

    if is_ocr_review:
        if requested_mode in SUBMIT_PROGRESS_STATUS_MARK_DONE_MODES and _submit_progress_status_authorized(data):
            return {
                "attempted": True,
                "completed": False,
                "status": "authorized",
                "reason": "ocr_review_progress_status_authorized",
                "source": "ocr_review",
            }
        return {
            "attempted": False,
            "completed": False,
            "status": "skipped",
            "reason": "ocr_review_requires_explicit_progress_status_authorization",
            "source": "ocr_review",
        }

    return {
        "attempted": True,
        "completed": False,
        "status": "authorized",
        "reason": "manual_submit_progress_status",
        "source": "manual",
    }


def _submit_assignment_progress_status_result(
    date: str,
    sid: str,
    record: dict,
    meta_snapshot: dict,
    data: dict,
) -> dict:
    result = _submit_progress_status_policy(data)
    if not result["attempted"]:
        return result
    try:
        completed = _mark_submitted_assignment_done(date, sid, record, meta_snapshot)
    except Exception as exc:
        print("[submit-test] progress test status update failed:", exc, flush=True)
        return {**result, "completed": False, "status": "failed", "reason": "progress_status_update_failed"}
    return {
        **result,
        "completed": bool(completed),
        "status": "done" if completed else "not_matched",
        "reason": "progress_status_marked_done" if completed else "no_matching_active_assignment",
    }


def _record_meta(rec: dict, catalog: dict) -> dict:
    resolved = _resolve_test_meta(rec.get("name"), rec.get("test_id"), catalog)
    snap = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    if not snap:
        return resolved

    out = dict(resolved)
    for key in ("type", "curriculum", "test_name", "unit_name", "test_level", "difficulty", "term", "round", "source_id"):
        value = snap.get(key)
        if value is not None and str(value).strip() != "":
            out[key] = _normalize_test_term(value) if key == "term" else value
    return out


def _admin_test_answer_url(target_meta: dict | None, test_id: str) -> str:
    if not academy_network_allowed() or not isinstance(target_meta, dict):
        return ""
    try:
        from routes.api_basic import _test_assignment_answer_url
    except ImportError:
        return ""

    item = {
        "type": target_meta.get("type") or "UNIT",
        "category": target_meta.get("type") or "UNIT",
        "id": test_id,
        "testId": test_id,
        "sourceId": target_meta.get("source_id") or "",
        "name": target_meta.get("test_name") or target_meta.get("unit_name") or "",
        "round": target_meta.get("round") or "",
        "curriculum": target_meta.get("curriculum") or "",
        "difficulty": target_meta.get("difficulty") or "",
        "term": target_meta.get("term") or "",
    }
    return _test_assignment_answer_url(item)


def _meta_matches_target(meta: dict, target: dict | None) -> bool:
    if not isinstance(meta, dict) or not isinstance(target, dict):
        return False

    meta_name = _canon_test_name(meta.get("test_name") or meta.get("unit_name") or "")
    target_name = _canon_test_name(target.get("test_name") or target.get("unit_name") or "")
    if target_name and meta_name != target_name:
        return False

    for key in ("type", "curriculum", "difficulty", "term", "round"):
        meta_value = str(meta.get(key) or "").strip()
        target_value = str(target.get(key) or "").strip()
        if key == "term":
            meta_value = _normalize_test_term(meta_value)
            target_value = _normalize_test_term(target_value)
        if meta_value and target_value and meta_value != target_value:
            return False

    return True

def _stats_signature(meta: dict, fallback_name: str = "") -> str:
    return "\u241f".join([
        str(meta.get("type") or "").strip(),
        str(meta.get("curriculum") or "").strip(),
        _canon_test_name(meta.get("test_name") or fallback_name),
        _normalize_test_term(meta.get("term") or ""),
        str(meta.get("round") or "").strip(),
    ])

def _score_bucket(pct: float) -> str:
    if pct < 50:
        return "0-49"
    if pct < 60:
        return "50-59"
    if pct < 70:
        return "60-69"
    if pct < 80:
        return "70-79"
    if pct < 90:
        return "80-89"
    return "90-100"

def _make_stats_agg() -> dict:
    return {
        "count": 0,
        "correct_list": [],
        "total_list": [],
        "pct_list": [],
        "pct_hist": {k: 0 for k in ["0-49", "50-59", "60-69", "70-79", "80-89", "90-100"]},
    }

def _push_stats_agg(agg: dict, correct: int, total: int) -> float:
    pct = (correct / total) * 100.0 if total > 0 else 0.0
    agg["count"] += 1
    agg["correct_list"].append(correct)
    agg["total_list"].append(total)
    agg["pct_list"].append(pct)
    agg["pct_hist"][_score_bucket(pct)] += 1
    return pct

def _finalize_stats_agg(agg: dict) -> dict | None:
    pct_list = agg.get("pct_list") if isinstance(agg, dict) else None
    if not isinstance(pct_list, list) or not pct_list:
        return None

    pct_sorted = sorted(pct_list)
    p90_idx = max(0, int(len(pct_sorted) * 0.9) - 1)
    correct_list = agg.get("correct_list") or []
    total_list = agg.get("total_list") or []

    return {
        "count": agg["count"],
        "avg_pct": round(sum(pct_list) / len(pct_list), 2),
        "median_pct": round(median(pct_list), 2),
        "p90_pct": round(pct_sorted[p90_idx], 2),
        "min_pct": round(min(pct_list), 2),
        "max_pct": round(max(pct_list), 2),
        "stddev_pct": round(pstdev(pct_list), 2) if len(pct_list) > 1 else 0.0,
        "avg_correct": round(sum(correct_list) / len(correct_list), 2),
        "avg_total": round(sum(total_list) / len(total_list), 2),
        "pct_hist": dict(agg["pct_hist"]),
    }

def _strip_answer_line_number(line: str) -> tuple[int | None, str]:
    match = re.match(r"^\s*(\d{1,3})\s*[\.\):：\-]\s*(.+?)\s*$", line)
    if not match:
        return None, line.strip()
    return int(match.group(1)), match.group(2).strip()


def _parse_answer_spec(text: str, problems: int) -> list[str]:
    s = str(text or "").strip()
    if not s:
        return [""] * problems

    lines = [line.strip() for line in s.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]
    numbered_rows = [_strip_answer_line_number(line) for line in lines]
    if numbered_rows and any(no is not None for no, _answer in numbered_rows):
        arr = [""] * problems
        for no, answer in numbered_rows:
            if no is None or no < 1 or no > problems:
                continue
            arr[no - 1] = answer
        return arr
    if len(lines) > 1:
        arr = [answer for _no, answer in numbered_rows]
    elif re.search(r"[\s,]", s):
        arr = [v.strip() for v in re.split(r"[\s,]+", s) if v.strip()]
    else:
        arr = [ch.strip() for ch in list(s) if ch.strip()]

    if len(arr) > problems:
        arr = arr[:problems]
    if len(arr) < problems:
        arr += [""] * (problems - len(arr))
    return arr

def _load_tests_cfg() -> dict:
    cfg = load(TESTS_CFG_PATH)
    return cfg if isinstance(cfg, dict) else {"categories": {}}

def _find_test_def_by_id(cfg: dict, test_id: str) -> dict | None:
    if not test_id:
        return None
    cats = cfg.get("categories") if isinstance(cfg, dict) else None
    if not isinstance(cats, dict):
        return None
    for cat in cats.values():
        tests = cat.get("tests") if isinstance(cat, dict) else None
        if not isinstance(tests, list):
            continue
        for t in tests:
            if not isinstance(t, dict):
                continue
            if str(t.get("id") or "").strip() == str(test_id).strip():
                return t
    return None

def _get_answer_key_for_round(test_def: dict, problems: int, round_no: int) -> list[str] | None:
    if not isinstance(test_def, dict):
        return None
    r = str(round_no if round_no in (1,2,3) else 1)

    ak = test_def.get("answerKeys")
    if isinstance(ak, dict):
        key = ak.get(r)
        if isinstance(key, list):
            key2 = [str(x).strip() for x in key]
            if len(key2) > problems: key2 = key2[:problems]
            if len(key2) < problems: key2 += [""] * (problems - len(key2))
            return key2

    legacy = test_def.get("answerKey", None)
    if legacy is None:
        legacy = test_def.get("answers", None)
    if legacy is None:
        return None

    if isinstance(legacy, list):
        key2 = [str(x).strip() for x in legacy]
        if len(key2) > problems: key2 = key2[:problems]
        if len(key2) < problems: key2 += [""] * (problems - len(key2))
        return key2

    return _parse_answer_spec(str(legacy), problems)

def _grade_answers(answers: list[str], key: list[str]) -> tuple[int, int, list[int], float]:
    total = len(key)
    wrong = []
    correct = 0
    for i in range(total):
        a = (answers[i] if i < len(answers) else "").strip()
        k = (key[i] if i < len(key) else "").strip()
        if not k:
            wrong.append(i+1)
            continue
        if a == k:
            correct += 1
        else:
            wrong.append(i+1)
    pct = round((correct / total) * 100.0, 2) if total > 0 else 0.0
    return correct, total, wrong, pct


def _wrong_answer_details(answers: list[str], key: list[str], wrong: list[int]) -> list[WrongAnswerDetail]:
    details: list[WrongAnswerDetail] = []
    for question_no in wrong:
        index = question_no - 1
        details.append(
            {
                "questionNo": question_no,
                "myAnswer": (answers[index] if 0 <= index < len(answers) else "").strip(),
                "correctAnswer": (key[index] if 0 <= index < len(key) else "").strip(),
            },
        )
    return details


def _normalize_wrong_numbers(values) -> list[int]:
    if not isinstance(values, list):
        return []
    out: list[int] = []
    for value in values:
        try:
            question_no = int(str(value).strip())
        except Exception:
            continue
        if question_no > 0:
            out.append(question_no)
    return out


def _submitted_answers_from_record(rec: dict, total: int) -> list[str] | None:
    raw = rec.get("submittedAnswers")
    if isinstance(raw, list):
        answers = [str(value).strip() for value in raw]
        if len(answers) > total:
            answers = answers[:total]
        if len(answers) < total:
            answers += [""] * (total - len(answers))
        return answers

    raw_text = rec.get("answersText")
    if isinstance(raw_text, str) and raw_text.strip():
        return _parse_answer_spec(raw_text, total)

    return None


def _sanitize_tests_payload_for_public_api(value):
    if isinstance(value, list):
        return [_sanitize_tests_payload_for_public_api(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_tests_payload_for_public_api(child)
            for key, child in value.items()
            if key not in INTERNAL_TEST_RECORD_FIELDS
        }
    return value


def _count_shifted_answer_matches(answers: list[str], key: list[str], key_shift: int) -> int:
    total = len(key)
    matches = 0
    for index in range(total):
        key_index = index + key_shift
        if key_index < 0 or key_index >= total:
            continue
        answer = (answers[index] if index < len(answers) else "").strip()
        expected = (key[key_index] if key_index < len(key) else "").strip()
        if answer and expected and answer == expected:
            matches += 1
    return matches


def _detect_shifted_answer_mapping(answers: list[str], key: list[str], correct: int) -> bool:
    total = len(key)
    if total < SUBMIT_OFFSET_GUARD_MIN_PROBLEMS:
        return False
    if correct > total // 2:
        return False
    next_key_matches = _count_shifted_answer_matches(answers, key, 1)
    previous_key_matches = _count_shifted_answer_matches(answers, key, -1)
    shifted_matches = max(next_key_matches, previous_key_matches)
    required_matches = max(
        correct + SUBMIT_OFFSET_GUARD_MIN_DELTA,
        int(total * SUBMIT_OFFSET_GUARD_MIN_SHIFTED_RATIO),
    )
    return shifted_matches >= required_matches


def _ocr_preview_items(raw_items, answers: list[str], problems: int) -> list[dict[str, str | int | float]]:
    source_items = raw_items if isinstance(raw_items, list) else []
    out = []
    for idx in range(problems):
        item = {"no": idx + 1, "answer": answers[idx] if idx < len(answers) else ""}
        if idx < len(source_items) and isinstance(source_items[idx], dict):
            confidence = source_items[idx].get("confidence")
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                item["confidence"] = round(float(confidence), 4)
        out.append(item)
    return out


def _phase2a_review_request_value(raw_json, key: str) -> str:
    value = request.form.get(key)
    if value is None and isinstance(raw_json, dict):
        value = raw_json.get(key)
    return str(value or "").strip()


def _phase2a_review_error(status: int, code: str, message: str):
    return jsonify({"ok": False, "errorCode": code, "message": message, "warnings": []}), status


def _phase2a_review_route_enabled() -> bool:
    return os.environ.get(OCR_PHASE2A_REVIEW_ROUTE_ENABLED_ENV, "").strip().lower() in OCR_PHASE2A_TRUTHY_VALUES


def _phase2a_review_catalog_allowed_round(test_id: str) -> int | None:
    if not test_id:
        return None
    cfg = load(TESTS_CFG_PATH)
    categories = cfg.get("categories") if isinstance(cfg, dict) else None
    if not isinstance(categories, dict):
        return None
    for category_key in ("UNIT", "TRAINING_PACK"):
        category = categories.get(category_key)
        tests = category.get("tests") if isinstance(category, dict) else None
        if not isinstance(tests, list):
            continue
        for item in tests:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip() != test_id:
                continue
            try:
                problems = int(item.get("problems") or 0)
                round_no = int(str(item.get("round") or "").strip())
            except (TypeError, ValueError):
                return None
            allowed_rounds = frozenset((1, 2)) if category_key == "TRAINING_PACK" else OCR_PHASE2A_UNIT_REVIEW_ROUNDS
            if problems != 20 or round_no not in allowed_rounds:
                return None
            return round_no
    return None


def _phase2a_review_allowed_round(test_id: str) -> int | None:
    return OCR_PHASE2A_REVIEW_ALLOWED_TESTS.get(test_id) or _phase2a_review_catalog_allowed_round(test_id)


def _phase2b_image_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].strip().lower()


def _phase2b_validate_uploaded_image():
    image = request.files.get(OCR_PHASE2B_IMAGE_FIELD)
    if image is None or not str(image.filename or "").strip():
        return _phase2a_review_error(400, "missing_image", "answer sheet image required")

    extension = _phase2b_image_extension(str(image.filename or ""))
    mimetype = str(image.mimetype or image.content_type or "").split(";", 1)[0].strip().lower()
    if extension not in OCR_PHASE2B_ALLOWED_IMAGE_EXTENSIONS or mimetype not in OCR_PHASE2B_ALLOWED_IMAGE_MIME_TYPES:
        return _phase2a_review_error(415, "unsupported_image_type", "unsupported answer sheet image type")

    stream = image.stream
    try:
        position = stream.tell()
    except (AttributeError, OSError):
        position = None
    data = stream.read(OCR_MAX_IMAGE_BYTES + 1)
    if position is not None:
        stream.seek(position)
    if not data:
        return _phase2a_review_error(400, "missing_image", "answer sheet image required")
    if len(data) > OCR_MAX_IMAGE_BYTES:
        return _phase2a_review_error(413, "image_too_large", "answer sheet image is too large")
    return None


def _phase2a_review_required_stub_payload(test_id: str, round_no: int) -> dict:
    items = []
    for index, answer in enumerate(OCR_PHASE2A_MOCK_ANSWERS, start=1):
        candidates = OCR_PHASE2A_REVIEW_CANDIDATES.get(index)
        items.append({
            "question_no": index,
            "status": "review_required",
            "recognized": answer,
            "warnings": ["cached_or_provider_result_required"],
            "candidates": list(candidates or ()),
            "final_answer": None,
            "source": None,
        })
    return {
        "source": "phase2a_route_stub_review_required",
        "test_id": test_id,
        "round": str(round_no),
        "problem_count": len(OCR_PHASE2A_MOCK_ANSWERS),
        "items": items,
    }


def _phase2a_forbidden_student_payload_paths(value, path: str = "$") -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            next_path = f"{path}.{key}"
            if key in OCR_STUDENT_FORBIDDEN_KEYS:
                out.append(next_path)
            out.extend(_phase2a_forbidden_student_payload_paths(child, next_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.extend(_phase2a_forbidden_student_payload_paths(child, f"{path}[{index}]"))
    return out


def _phase2a_text_has_forbidden_value(value: str) -> bool:
    text = str(value or "")
    normalized = text.replace("\\", "/").lower()
    if re.search(r"\b[a-zA-Z]:[\\/]", text):
        return True
    return any(token.replace("\\", "/").lower() in normalized for token in OCR_STUDENT_FORBIDDEN_VALUE_TOKENS)


def _phase2a_forbidden_student_payload_value_paths(value, path: str = "$") -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            out.extend(_phase2a_forbidden_student_payload_value_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.extend(_phase2a_forbidden_student_payload_value_paths(child, f"{path}[{index}]"))
    elif isinstance(value, str) and _phase2a_text_has_forbidden_value(value):
        out.append(path)
    return out


def _phase2a_review_meta_text(value) -> str:
    text = str(value or "").strip()
    if _phase2a_text_has_forbidden_value(text):
        return "redacted_path"
    return text[:OCR_REVIEW_META_TEXT_MAX_LENGTH]


def _phase2a_review_meta_int(value) -> int:
    try:
        count = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(count, 0)


def _phase2a_harden_review_meta(meta: dict) -> dict:
    source = meta if isinstance(meta, dict) else {}
    out: dict[str, str | int] = {}
    for key in OCR_REVIEW_META_TEXT_FIELDS:
        out[key] = _phase2a_review_meta_text(source.get(key))
    for key in OCR_REVIEW_META_INT_FIELDS:
        out[key] = _phase2a_review_meta_int(source.get(key))
    return out


@bp_api_tests.post("/api/ocr-test-sheet-review")
def ocr_test_sheet_review():
    if not _phase2a_review_route_enabled():
        return _phase2a_review_error(503, "feature_disabled", "OCR review route is disabled.")

    raw_json = request.get_json(silent=True) if request.is_json else {}
    if not isinstance(raw_json, dict):
        raw_json = {}

    sid = _phase2a_review_request_value(raw_json, "sid")
    test_id = _phase2a_review_request_value(raw_json, "testId")
    round_raw = _phase2a_review_request_value(raw_json, "round") or "1"

    if not sid:
        return _phase2a_review_error(400, "invalid_request", "sid required")
    if is_ghost_student_sid(sid):
        return _phase2a_review_error(403, "forbidden_student", GHOST_STUDENT_WRITE_ERROR)
    if not test_id:
        return _phase2a_review_error(400, "invalid_request", "testId required")
    allowed_round = _phase2a_review_allowed_round(test_id)
    if allowed_round is None:
        return _phase2a_review_error(403, "test_not_allowlisted", "OCR review is not enabled for this test.")

    try:
        round_no = int(round_raw)
    except ValueError:
        return _phase2a_review_error(400, "invalid_request", "round must be 1")
    if round_no != allowed_round:
        return _phase2a_review_error(403, "round_not_allowlisted", "OCR review is not enabled for this round.")

    image_error = _phase2b_validate_uploaded_image()
    if image_error is not None:
        return image_error

    image = request.files.get(OCR_PHASE2B_IMAGE_FIELD)
    if image is None:
        return _phase2a_review_error(400, "missing_image", "answer sheet image required")

    try:
        from tools.subjective_sheet_lab.phase2c_crop_pipeline_adapter import (
            Phase2CPipelineError,
            Phase2CRequest,
            run_phase2c_crop_pipeline,
        )
    except ImportError:
        current_app.logger.exception("ocr-test-sheet-review phase2c adapter import failed")
        return _phase2a_review_error(500, "pipeline_unavailable", "Answer sheet processing is unavailable.")

    try:
        pipeline_result = run_phase2c_crop_pipeline(
            Phase2CRequest(
                sid=sid,
                test_id=test_id,
                round_no=round_no,
                image_stream=image.stream,
                original_filename=str(image.filename or ""),
                content_type=str(image.mimetype or image.content_type or ""),
            )
        )
    except Phase2CPipelineError as exc:
        current_app.logger.warning("ocr-test-sheet-review phase2c pipeline failed: %s", exc)
        return _phase2a_review_error(exc.http_status, exc.error_code, exc.student_message)

    current_app.logger.info(
        "ocr-test-sheet-review phase2c prepared case=%s crops=%s contacts=%s",
        pipeline_result.case_id,
        pipeline_result.crop_count,
        pipeline_result.contact_sheet_count,
    )

    review_payload = _phase2a_review_required_stub_payload(test_id, round_no)
    review_meta = {
        "photo_correction": "completed",
        "answer_box_extraction": "completed",
        "answer_box_source": str(getattr(pipeline_result, "answer_box_source", "")),
        "provider_input": "crop_contact_sheet",
        "crop_count": int(getattr(pipeline_result, "crop_count", 0) or 0),
        "contact_sheet_count": int(getattr(pipeline_result, "contact_sheet_count", 0) or 0),
        "cache_status": "not_checked",
        "cache_source": "",
        "provider_status": "not_called",
        "provider_call_count": 0,
    }
    try:
        from tools.subjective_sheet_lab.phase2d_cached_review_payload_adapter import (
            Phase2DCacheUnavailable,
            Phase2DRequest,
            load_phase2d_cached_review_payload,
        )

        cached_review = load_phase2d_cached_review_payload(
            Phase2DRequest(
                sid=sid,
                test_id=test_id,
                round_no=round_no,
                pipeline_result=pipeline_result,
            )
        )
        review_payload = cached_review.review_payload
        review_meta["cache_status"] = str(cached_review.cache_status)
        review_meta["cache_source"] = str(cached_review.source_kind)
        current_app.logger.info(
            "ocr-test-sheet-review phase2d cache hit kind=%s status=%s path=%s",
            cached_review.source_kind,
            cached_review.cache_status,
            cached_review.cache_path,
        )
    except ImportError:
        review_meta["cache_status"] = "adapter_unavailable"
        current_app.logger.exception("ocr-test-sheet-review phase2d adapter import failed")
    except Phase2DCacheUnavailable as exc:
        review_meta["cache_status"] = str(exc.reason)
        current_app.logger.info("ocr-test-sheet-review phase2d cache fallback: %s", exc)
        try:
            from tools.subjective_sheet_lab.phase2e_gemini_live_ocr_adapter import (
                Phase2ERequest,
                prepare_phase2e_live_ocr,
            )

            phase2e_result = prepare_phase2e_live_ocr(
                Phase2ERequest(
                    sid=sid,
                    test_id=test_id,
                    round_no=round_no,
                    pipeline_result=pipeline_result,
                    cache_miss_reason=exc.reason,
                    request_metadata={"route": "/api/ocr-test-sheet-review"},
                )
            )
            review_meta["provider_status"] = str(phase2e_result.status.value)
            review_meta["provider_call_count"] = int(phase2e_result.provider_call_count or 0)
            current_app.logger.info(
                "ocr-test-sheet-review phase2e status=%s reason=%s provider_calls=%s",
                phase2e_result.status.value,
                phase2e_result.reason,
                phase2e_result.provider_call_count,
            )
            if phase2e_result.review_payload is not None:
                review_payload = phase2e_result.review_payload
        except ImportError:
            review_meta["provider_status"] = "adapter_unavailable"
            current_app.logger.exception("ocr-test-sheet-review phase2e adapter import failed")

    review_meta = _phase2a_harden_review_meta(review_meta)
    payload = {
        "ok": True,
        "review_payload": review_payload,
        "review_meta": review_meta,
        "warnings": [],
    }
    leaks = _phase2a_forbidden_student_payload_paths(payload)
    value_leaks = _phase2a_forbidden_student_payload_value_paths(payload)
    if leaks or value_leaks:
        current_app.logger.error(
            "ocr-test-sheet-review student payload leak: keys=%s values=%s",
            ", ".join(leaks),
            ", ".join(value_leaks),
        )
        return _phase2a_review_error(500, "contract_violation", "OCR review payload failed safety checks.")
    return jsonify(payload)


@bp_api_tests.post("/api/ocr-test-sheet")
def ocr_test_sheet():
    try:
        from core.ocr_test_sheet import (
            OcrConfigError,
            OcrInputError,
            OcrRemoteError,
            extract_test_sheet_answers,
        )
    except ImportError:
        return jsonify({"ok": False, "error": "OCR 모듈을 불러오지 못했습니다.", "warnings": []}), 503

    sid = str(request.form.get("sid") or "").strip()
    test_id = str(request.form.get("testId") or "").strip()
    round_raw = str(request.form.get("round") or "1").strip()
    image_file = request.files.get("image")

    if not sid:
        return jsonify({"ok": False, "error": "sid required", "warnings": []}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR, "warnings": []}), 403
    if not test_id:
        return jsonify({"ok": False, "error": "testId required", "warnings": []}), 400
    try:
        round_no = int(round_raw or "1")
    except ValueError:
        return jsonify({"ok": False, "error": "round must be 1, 2, or 3", "warnings": []}), 400
    if round_no not in (1, 2, 3):
        return jsonify({"ok": False, "error": "round must be 1, 2, or 3", "warnings": []}), 400
    if image_file is None:
        return jsonify({"ok": False, "error": "image required", "warnings": []}), 400

    filename = str(image_file.filename or "")
    image_bytes = image_file.read(OCR_MAX_IMAGE_BYTES + 1)
    try:
        result = extract_test_sheet_answers(
            image_bytes=image_bytes,
            filename=filename,
            mime_type=str(image_file.mimetype or ""),
        )
    except OcrInputError as exc:
        return jsonify({"ok": False, "error": str(exc), "warnings": list(getattr(exc, "warnings", []))}), 400
    except OcrConfigError as exc:
        return jsonify({"ok": False, "error": str(exc), "warnings": list(getattr(exc, "warnings", []))}), 503
    except OcrRemoteError as exc:
        return jsonify({"ok": False, "error": str(exc), "warnings": list(getattr(exc, "warnings", []))}), 500
    except Exception as exc:
        current_app.logger.exception("ocr-test-sheet failed")
        return jsonify({"ok": False, "error": "OCR 처리 중 오류가 발생했습니다.", "warnings": []}), 500

    answers_text = str(result.answers_text or "").strip()
    if not answers_text:
        return jsonify({"ok": False, "error": "OCR 결과에서 답안을 찾지 못했습니다.", "warnings": result.warnings}), 422

    return jsonify({
        "ok": True,
        "answersText": answers_text,
        "items": list(result.items),
        "warnings": list(result.warnings),
    })


@bp_api_tests.post('/api/submit-test')
def submit_test():
    data = request.get_json(force=True, silent=True) or {}
    sid   = str(data.get('sid', '')).strip()

    test_id = str(data.get('testId', '')).strip()
    name  = str(data.get('name', '')).strip()

    try:
        round_no = int(data.get("round", 1) or 1)
    except Exception:
        round_no = 1
    if round_no not in (1,2,3):
        round_no = 1

    score = str(data.get('score', '')).strip()
    wrong = data.get('wrong', [])
    memo  = str(data.get('memo', '')).strip()

    answers_text = data.get("answersText", None)

    if not sid or (not name and not test_id):
        return jsonify({'ok': False, 'error': 'sid and (name or testId) required'}), 400
    if is_ghost_student_sid(sid):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403

    cfg = _load_tests_cfg()
    tdef = _find_test_def_by_id(cfg, test_id) if test_id else None

    if tdef and not name:
        name = str(tdef.get("name") or "").strip()

    pct = None
    wrong_details: list[WrongAnswerDetail] = []
    submitted_answers: list[str] | None = None
    if answers_text is not None:

        problems = None
        if isinstance(tdef, dict):
            try:
                problems = int(tdef.get("problems") or 0)
            except Exception:
                problems = None
        if not problems:
            return jsonify({"ok": False, "error": "cannot grade: missing test definition (testId)"}), 400

        key = _get_answer_key_for_round(tdef, problems, round_no)
        if not key:
            return jsonify({"ok": False, "error": "cannot grade: missing answer key"}), 400

        answers = _parse_answer_spec(str(answers_text), problems)
        submitted_answers = answers
        correct, total, wrong_calc, pct = _grade_answers(answers, key)
        wrong_details = _wrong_answer_details(answers, key, wrong_calc)
        if _detect_shifted_answer_mapping(answers, key, correct):
            return jsonify({
                "ok": False,
                "error": "possible_answer_offset",
                "errorCode": "possible_answer_offset",
                "message": "답안이 한 문항 밀린 패턴으로 보입니다. 시험/회차 선택과 답안지 문항 번호를 확인한 뒤 다시 제출해주세요.",
                "fallbackAllowed": False,
            }), 409
        score = f"{correct}/{total}"
        wrong = wrong_calc

    if not name:
        return jsonify({'ok': False, 'error': 'name required'}), 400

    today = dt.date.today().isoformat()
    now_iso = utc_now_isoz()
    meta = _resolve_test_meta(name, test_id, _build_test_catalog(cfg))
    meta_snapshot = {
        "type": meta.get("type") or "",
        "curriculum": meta.get("curriculum") or "",
        "test_name": meta.get("test_name") or _canon_test_name(name),
        "unit_name": meta.get("unit_name") or "",
        "test_level": meta.get("test_level"),
        "difficulty": meta.get("difficulty") or "",
        "term": _normalize_test_term(meta.get("term") or ""),
        "round": meta.get("round") or str(round_no),
        "source_id": meta.get("source_id") or "",
    }

    record = {
        'testId': test_id,
        'round': round_no,
        'name': name,
        'score': score,
        'wrong': wrong if isinstance(wrong, list) else [],
        'memo': memo,
        'pct': pct,
        'createdAt': now_iso,
        'type': meta_snapshot["type"],
        'curriculum': meta_snapshot["curriculum"],
        'testName': meta_snapshot["test_name"],
        'unitName': meta_snapshot["unit_name"],
        'testLevel': meta_snapshot["test_level"],
        'difficulty': meta_snapshot["difficulty"],
        'term': meta_snapshot["term"],
        'sourceId': meta_snapshot["source_id"],
        'testMeta': meta_snapshot,
    }

    logs_saved = False
    try:
        from routes.api_basic import get_log_repository

        logs_saved = get_log_repository().append_record(today, sid, record, _append_test_record)
    except Exception as e:
        print("[submit-test] json logs save failed:", e, flush=True)

    tests_saved = False
    try:
        with _tests_lock():
            tests_json = load(TESTS_PATH)
            if not isinstance(tests_json, dict):
                tests_json = {}
            per_day = tests_json.setdefault(today, {})
            if not isinstance(per_day, dict):
                tests_json[today] = {}
                per_day = tests_json[today]
            arr = per_day.get(sid)
            if not isinstance(arr, list):
                arr = []
            arr = [x for x in arr if isinstance(x, dict)]
            tests_record = dict(record)
            if submitted_answers is not None:
                tests_record["submittedAnswers"] = submitted_answers
            arr.append(tests_record)
            per_day[sid] = arr
            tests_json[today] = per_day
            save_atomic(TESTS_PATH, tests_json)
            tests_saved = True
    except Exception as e:
        print("[submit-test] tests.json save failed:", e, flush=True)

    if not logs_saved and not tests_saved:
        return jsonify({'ok': False, 'error': 'failed to save test record'}), 500

    assignment_progress = _submit_assignment_progress_status_result(today, sid, record, meta_snapshot, data)
    assignment_completed = bool(assignment_progress.get("completed"))

    return jsonify({
        'ok': True,
        'score': score,
        'wrong': record["wrong"],
        'wrongDetails': wrong_details,
        'pct': pct,
        'assignmentCompleted': assignment_completed,
        'assignmentProgress': assignment_progress,
    })

@bp_api_tests.route("/api/tests", methods=["GET", "POST"])
def api_tests():
    if request.method == "GET":
        return nocache_resp(_sanitize_tests_payload_for_public_api(load(TESTS_PATH)))
    incoming = request.get_json(force=True) or {}
    if mapping_contains_ghost_student_sid(incoming):
        return jsonify({"ok": False, "error": GHOST_STUDENT_WRITE_ERROR}), 403
    with _tests_lock():
        current = load(TESTS_PATH)
        if not isinstance(current, dict): current = {}
        for d, m in (incoming.items() if isinstance(incoming, dict) else []):
            cur_m = current.setdefault(d, {})
            if not isinstance(cur_m, dict):
                current[d] = {}
                cur_m = current[d]
            for sid, arr in (m.items() if isinstance(m, dict) else []):
                old = cur_m.get(sid, [])
                if not isinstance(old, list): old = []
                if isinstance(arr, list):
                    old += [x for x in arr if isinstance(x, dict)]
                cur_m[sid] = old
            current[d] = cur_m
        save_atomic(TESTS_PATH, current)
    return "", 204

@bp_api_tests.get("/api/tests-config")
def get_tests_config():
    config = load(TESTS_CFG_PATH)
    if not academy_network_allowed():
        config = strip_tests_config_answer_links(config)
    return nocache_resp(config)

@bp_api_tests.post("/api/tests-config")
def post_tests_config():
    payload = request.get_json(force=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "invalid payload"}), 400
    with _tests_config_lock():
        save_atomic(TESTS_CFG_PATH, payload)
    return jsonify({"ok": True})

def _parse_date(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s)
    except Exception:
        return None

def _iter_test_records(start: dt.date | None, end: dt.date | None):
    seen: set[Tuple[str, str, str]] = set()

    def _walk(container: dict):
        for date_str, by_sid in (container or {}).items():
            day = _parse_date(date_str)
            if start and (not day or day < start):
                continue
            if end and (not day or day > end):
                continue
            if not isinstance(by_sid, dict):
                continue

            for sid, val in by_sid.items():
                if isinstance(val, list):
                    arr = val
                elif isinstance(val, dict):
                    arr = val.get("tests", [])
                    if not isinstance(arr, list):
                        continue
                else:
                    continue

                for rec in arr:
                    if not isinstance(rec, dict):
                        continue
                    name = str(rec.get("name", "")).strip()
                    score = str(rec.get("score", "")).strip()
                    created_at = rec.get("createdAt") or ""
                    wrong = _normalize_wrong_numbers(rec.get("wrong"))
                    memo = str(rec.get("memo") or "").strip()
                    raw_meta = rec.get("testMeta") if isinstance(rec.get("testMeta"), dict) else {}
                    snap_meta = {
                        "type": str(rec.get("type") or raw_meta.get("type") or "").strip(),
                        "curriculum": str(rec.get("curriculum") or raw_meta.get("curriculum") or "").strip(),
                        "test_name": str(rec.get("testName") or raw_meta.get("test_name") or raw_meta.get("testName") or "").strip(),
                        "unit_name": str(rec.get("unitName") or raw_meta.get("unit_name") or raw_meta.get("unitName") or "").strip(),
                        "test_level": rec.get("testLevel") if rec.get("testLevel") is not None else raw_meta.get("test_level") or raw_meta.get("testLevel"),
                        "difficulty": str(rec.get("difficulty") or raw_meta.get("difficulty") or "").strip(),
                        "term": _normalize_test_term(rec.get("term") or raw_meta.get("term") or raw_meta.get("examTerm") or raw_meta.get("examPeriod") or raw_meta.get("exam_period") or ""),
                        "round": str(raw_meta.get("round") or rec.get("round") or "").strip(),
                        "source_id": str(rec.get("sourceId") or raw_meta.get("source_id") or raw_meta.get("sourceId") or "").strip(),
                    }
                    if not name or "/" not in score:
                        continue
                    try:
                        correct_s, total_s = score.split("/", 1)
                        correct = int(str(correct_s).strip())
                        total = int(str(total_s).strip())
                        if total <= 0:
                            continue
                    except Exception:
                        continue
                    submitted_answers = _submitted_answers_from_record(rec, total)

                    key = (str(sid), name, str(created_at))
                    if key in seen:
                        continue
                    seen.add(key)
                    yield {
                        "sid": str(sid),
                        "test_id": str(rec.get("testId") or "").strip(),
                        "name": name,
                        "correct": int(correct),
                        "total": int(total),
                        "wrong": wrong,
                        "submitted_answers": submitted_answers,
                        "created_at": str(created_at),
                        "memo": memo,
                        "day": day,
                        "meta": snap_meta,
                    }

    # tests.json is the durable student-test store. logs.json is kept as a
    # legacy fallback so old 상담/수업 기록 embedded tests still appear.
    for item in _walk(load(TESTS_PATH)):
        yield item
    try:
        from routes.api_basic import get_log_repository

        legacy_logs = get_log_repository().read_json_map()
    except Exception:
        legacy_logs = load(LOGS_PATH)
    for item in _walk(legacy_logs):
        yield item

@bp_api_tests.get("/api/tests-records")
def api_tests_records():
    test_id_q = str(request.args.get("test_id") or request.args.get("testId") or "").strip()
    test_q = str(request.args.get("test") or "").strip()
    type_q = _normalize_test_type(request.args.get("type") or "")
    curriculum_q = str(request.args.get("curriculum") or "").strip()
    unit_name_q = str(request.args.get("unit_name") or "").strip()
    test_level_q = str(request.args.get("test_level") or "").strip()
    term_q = _normalize_test_term(request.args.get("term") or request.args.get("examTerm") or "")
    if not any([test_id_q, test_q, type_q, curriculum_q, unit_name_q, test_level_q, term_q]):
        return jsonify({"ok": False, "error": "missing filter"}), 400

    recent = request.args.get("recent_days")
    band_q = str(request.args.get("band") or "").strip()

    end = dt.date.today()
    try:
        days = int(recent) if recent else 30
    except Exception:
        days = 30
    days = max(1, min(3650, days))
    start = end - dt.timedelta(days=days - 1)
    cfg = _load_tests_cfg()
    catalog = _build_test_catalog(cfg)

    sid_to_name = {}
    sid_to_level = {}
    students = load(STU_PATH)
    if isinstance(students, list):
        for s in students:
            sid = str(s.get("id") or "").strip()
            if not sid:
                continue
            sid_to_name[sid] = str(s.get("name") or sid).strip()
            sid_to_level[sid] = str(s.get("level") or "").strip()

    def norm_band(lv: str) -> str:
        lv = str(lv or "").strip()
        if lv in ("상", "중상", "중", "하"):
            return lv
        return ""

    target = _canon_test_name(test_q)
    by_id = catalog.get("by_id") if isinstance(catalog, dict) else {}
    target_meta = by_id.get(test_id_q) if isinstance(by_id, dict) and test_id_q else None

    recs = []
    for rec in _iter_test_records(start, end):
        sid = rec["sid"]
        rec_test_id = str(rec.get("test_id") or "").strip()
        meta = _record_meta(rec, catalog)
        if test_id_q:
            if rec_test_id:
                target_source_id = str(target_meta.get("source_id") or "").strip() if isinstance(target_meta, dict) else ""
                if rec_test_id == test_id_q:
                    pass
                elif target_source_id and rec_test_id == target_source_id and _meta_matches_target(meta, target_meta):
                    pass
                else:
                    continue
            elif not _meta_matches_target(meta, target_meta):
                continue
        nm = meta.get("test_name") or _canon_test_name(rec.get("name"))
        if target and nm != target:
            continue
        if type_q and meta.get("type") != type_q:
            continue
        if curriculum_q and str(meta.get("curriculum") or "").strip() != curriculum_q:
            continue
        if unit_name_q and str(meta.get("unit_name") or "").strip() != unit_name_q:
            continue
        if test_level_q and str(meta.get("test_level") or "").strip() != test_level_q:
            continue
        if term_q and _normalize_test_term(meta.get("term") or "") != term_q:
            continue

        correct = int(rec["correct"])
        total = int(rec["total"])
        pct = round((correct / total) * 100.0, 2)
        stu_name = sid_to_name.get(sid, sid)
        lv = norm_band(sid_to_level.get(sid, ""))

        if band_q and lv != band_q:
            continue

        wrong_details: list[WrongAnswerDetail] = []
        submitted_answers = rec.get("submitted_answers")
        if isinstance(submitted_answers, list) and submitted_answers:
            try:
                round_no = int(meta.get("round") or 1)
            except Exception:
                round_no = 1
            if round_no not in (1, 2, 3):
                round_no = 1
            test_def = (
                _find_test_def_by_id(cfg, rec_test_id)
                or _find_test_def_by_id(cfg, str(meta.get("source_id") or ""))
                or _find_test_def_by_id(cfg, test_id_q)
            )
            key = _get_answer_key_for_round(test_def, total, round_no) if test_def else None
            if key:
                wrong_details = _wrong_answer_details(submitted_answers, key, rec["wrong"])

        recs.append({
            "sid": sid,
            "studentName": stu_name,
            "level": lv or "",
            "pct": pct,
            "correct": correct,
            "total": total,
            "wrong": rec["wrong"],
            "wrongDetails": wrong_details,
            "createdAt": rec["created_at"],
            "memo": rec["memo"],
            "testId": rec_test_id,
            "type": meta.get("type") or "",
            "curriculum": meta.get("curriculum") or "",
            "testName": nm,
            "unitName": meta.get("unit_name") or "",
            "testLevel": meta.get("test_level"),
            "term": _normalize_test_term(meta.get("term") or ""),
        })

    recs.sort(key=lambda r: (-float(r.get("pct") or 0), str(r.get("studentName") or ""), str(r.get("createdAt") or "")))
    answer_url = _admin_test_answer_url(target_meta, test_id_q)

    return nocache_resp({
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "filters": {
            "test": target,
            "type": type_q,
            "curriculum": curriculum_q,
            "unit_name": unit_name_q,
            "test_level": test_level_q,
            "term": term_q,
            "band": band_q,
        },
        "total": len(recs),
        "answerUrl": answer_url,
        "records": recs,
    })

@bp_api_tests.get("/api/tests-stats")
def api_tests_stats():
    start_q = request.args.get("start")
    end_q   = request.args.get("end")
    recent  = request.args.get("recent_days")
    include_wrong = request.args.get("include_wrong", "0") in ("1", "true", "True")

    end = _parse_date(end_q) or dt.date.today()
    if recent:
        try:
            days = int(recent)
            start = end - dt.timedelta(days=days - 1)
        except Exception:
            start = _parse_date(start_q)
    else:
        start = _parse_date(start_q)

    if not start:
        start = end - dt.timedelta(days=29)
    catalog = _build_test_catalog(_load_tests_cfg())

    def level_band(level: str) -> str:
        lv = str(level or "").strip()
        if lv in ("상", "중상", "중", "하"):
            return lv
        return "하"

    sid_band: dict[str, str] = {}
    students = load(STU_PATH)
    if isinstance(students, list):
        for s in students:
            sid = str(s.get("id") or "").strip()
            if not sid:
                continue
            sid_band[sid] = level_band(s.get("level", ""))

    def bucket(pct: float) -> str:
        if pct < 50: return "0-49"
        if pct < 60: return "50-59"
        if pct < 70: return "60-69"
        if pct < 80: return "70-79"
        if pct < 90: return "80-89"
        return "90-100"

    def make_agg() -> dict:
        return {
            "count": 0,
            "correct_list": [],
            "total_list": [],
            "pct_list": [],
            "pct_hist": {k: 0 for k in ["0-49","50-59","60-69","70-79","80-89","90-100"]},
        }

    agg: dict[str, dict] = {}
    agg_by_id: dict[str, dict] = {}
    agg_by_signature: dict[str, dict] = {}
    unit_agg: dict[tuple[str, str, str], dict] = {}
    series_agg: dict[tuple[str, str, str], dict] = {}
    wrong_freq: dict[str, dict[int, int]] = {}
    type_summary = {key: _make_stats_agg() for key in TEST_TYPE_ORDER}

    for rec in _iter_test_records(start, end):
        sid = rec["sid"]
        correct = int(rec["correct"])
        total = int(rec["total"])
        wrong = rec["wrong"]
        meta = _record_meta(rec, catalog)
        key_name = meta.get("test_name") or _canon_test_name(rec.get("name"))
        if not key_name:
            continue

        a = agg.setdefault(key_name, _make_stats_agg())
        _push_stats_agg(a, correct, total)
        sig = _stats_signature(meta, key_name)
        if sig:
            sa = agg_by_signature.setdefault(sig, _make_stats_agg())
            _push_stats_agg(sa, correct, total)
        test_id = str(rec.get("test_id") or "").strip()
        if test_id:
            ia = agg_by_id.setdefault(test_id, _make_stats_agg())
            _push_stats_agg(ia, correct, total)

        band = sid_band.get(str(sid))
        if band:
            bands_raw = a.setdefault("_bands_raw", {})
            ba = bands_raw.setdefault(band, _make_stats_agg())
            _push_stats_agg(ba, correct, total)

        type_key = str(meta.get("type") or "").strip() or "UNIT"
        if type_key not in type_summary:
            type_summary[type_key] = _make_stats_agg()
        _push_stats_agg(type_summary[type_key], correct, total)

        curriculum = str(meta.get("curriculum") or "").strip()
        if type_key == "UNIT":
            group_key = (
                curriculum,
                str(meta.get("unit_name") or key_name).strip(),
                str(meta.get("test_level") or "").strip(),
            )
            ga = unit_agg.setdefault(group_key, _make_stats_agg())
            _push_stats_agg(ga, correct, total)
        elif type_key:
            group_key = (
                type_key,
                curriculum,
                _normalize_test_term(meta.get("term") or ""),
                key_name,
            )
            ga = series_agg.setdefault(group_key, _make_stats_agg())
            _push_stats_agg(ga, correct, total)

        if include_wrong and isinstance(wrong, list):
            wf = wrong_freq.setdefault(key_name, {})
            for n in wrong:
                try:
                    k = int(n)
                except Exception:
                    continue
                wf[k] = wf.get(k, 0) + 1

    out: dict[str, dict] = {}
    for test_name, a in agg.items():
        base = _finalize_stats_agg(a)
        if not base:
            continue

        bands_out: dict[str, dict] = {}
        bands_raw = a.get("_bands_raw", {})
        for band_name in ("상", "중상", "중", "하", "기타"):
            ba = bands_raw.get(band_name)
            band_base = _finalize_stats_agg(ba)
            if not band_base:
                continue
            bands_out[band_name] = band_base

        if bands_out:
            base["bands"] = bands_out

        if include_wrong:
            wf = wrong_freq.get(test_name, {})
            base["wrong_freq"] = {str(k): wf[k] for k in sorted(wf.keys())}

        out[test_name] = base

    out_by_id: dict[str, dict] = {}
    for test_id, a in agg_by_id.items():
        base = _finalize_stats_agg(a)
        if not base:
            continue
        out_by_id[test_id] = base

    out_by_signature: dict[str, dict] = {}
    for sig, a in agg_by_signature.items():
        base = _finalize_stats_agg(a)
        if not base:
            continue
        out_by_signature[sig] = base

    unit_rows = []
    for (curriculum, unit_name, test_level), ga in unit_agg.items():
        base = _finalize_stats_agg(ga)
        if not base:
            continue
        base.update({
            "type": "UNIT",
            "curriculum": curriculum,
            "unit_name": unit_name,
            "test_level": (int(test_level) if str(test_level).isdigit() else None),
        })
        unit_rows.append(base)
    unit_rows.sort(key=lambda x: (
        str(x.get("curriculum") or ""),
        str(x.get("unit_name") or ""),
        10**9 if x.get("test_level") is None else int(x.get("test_level")),
    ))

    series_rows_by_type: dict[str, list[dict]] = {}
    final_rows = []
    hell_rows = []
    for (type_key, curriculum, term, test_name), ga in series_agg.items():
        base = _finalize_stats_agg(ga)
        if not base:
            continue
        base.update({
            "type": type_key,
            "curriculum": curriculum,
            "term": term,
            "test_name": test_name,
        })
        series_rows_by_type.setdefault(type_key, []).append(base)
        if type_key == "FINAL":
            final_rows.append(base)
        elif type_key == "HELL":
            hell_rows.append(base)
    for rows in series_rows_by_type.values():
        rows.sort(key=lambda x: (str(x.get("curriculum") or ""), str(x.get("test_name") or "")))
    final_rows.sort(key=lambda x: (str(x.get("curriculum") or ""), str(x.get("test_name") or "")))
    hell_rows.sort(key=lambda x: (str(x.get("curriculum") or ""), str(x.get("test_name") or "")))

    summary = {}
    for type_key in TEST_TYPE_ORDER:
        base = _finalize_stats_agg(type_summary.setdefault(type_key, _make_stats_agg()))
        if base:
            summary[type_key] = base

    return nocache_resp({
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "updatedAt": utc_now_isoz(),
        "by_test": out,
        "by_test_id": out_by_id,
        "by_test_signature": out_by_signature,
        "summary": summary,
        "unit_rows": unit_rows,
        "series_rows": series_rows_by_type,
        "final_rows": final_rows,
        "hell_rows": hell_rows,
    })
