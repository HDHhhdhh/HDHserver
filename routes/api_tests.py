from __future__ import annotations

from statistics import median, pstdev
import datetime as dt
import re
import time
from typing import Tuple

from flask import Blueprint, jsonify, request

from core.paths import (
    LOGS_PATH, TESTS_PATH, STU_PATH,
    TESTS_CFG_PATH
)
from core.storage import load, save_atomic, nocache_resp, utc_now_isoz

bp_api_tests = Blueprint("api_tests", __name__)
TEST_TYPE_ORDER = ("REVIEW", "UNIT", "SCHOOL_PAST", "ILSAN_PAST", "FINAL", "HELL")

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

def _parse_answer_spec(text: str, problems: int) -> list[str]:
    s = str(text or "").strip()
    if not s:
        return [""] * problems

    if re.search(r"[\s,]", s):
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

    cfg = _load_tests_cfg()
    tdef = _find_test_def_by_id(cfg, test_id) if test_id else None

    if tdef and not name:
        name = str(tdef.get("name") or "").strip()

    pct = None
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
        correct, total, wrong_calc, pct = _grade_answers(answers, key)
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
            arr.append(record)
            per_day[sid] = arr
            tests_json[today] = per_day
            save_atomic(TESTS_PATH, tests_json)
            tests_saved = True
    except Exception as e:
        print("[submit-test] tests.json save failed:", e, flush=True)

    if not logs_saved and not tests_saved:
        return jsonify({'ok': False, 'error': 'failed to save test record'}), 500

    return jsonify({'ok': True, 'score': score, 'wrong': record["wrong"], 'pct': pct})

@bp_api_tests.route("/api/tests", methods=["GET", "POST"])
def api_tests():
    if request.method == "GET":
        return nocache_resp(load(TESTS_PATH))
    incoming = request.get_json(force=True) or {}
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
    return nocache_resp(load(TESTS_CFG_PATH))

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
                    wrong = rec.get("wrong") if isinstance(rec.get("wrong"), list) else []
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
    catalog = _build_test_catalog(_load_tests_cfg())

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

        recs.append({
            "sid": sid,
            "studentName": stu_name,
            "level": lv or "",
            "pct": pct,
            "correct": correct,
            "total": total,
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
