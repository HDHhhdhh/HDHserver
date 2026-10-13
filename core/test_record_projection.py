"""Pure historical test metadata, normalization, deduplication and detail projection."""
from __future__ import annotations

from copy import deepcopy
import datetime as dt
import re
from typing import Final, TypedDict

INTERNAL_TEST_RECORD_FIELDS: Final[frozenset[str]] = frozenset({"submittedAnswers", "answersText", "wrongDetails"})

class WrongAnswerDetail(TypedDict):
    questionNo: int
    myAnswer: str
    correctAnswer: str

TEST_LEVEL_RE = re.compile(r"""
  (?:\(|\[)?\s*
  (?:lv\.?|LV\.?|레벨)\s*\.?\s*([0-9]{1,2})
  \s*(?:\)|\])?
""", re.VERBOSE)


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

def _parse_date(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s)
    except Exception:
        return None

def _normalized_test_record_candidates(container: dict):
    for date_str, by_sid in (container or {}).items():
        date_key = str(date_str)
        day = _parse_date(date_key)
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
                yield {
                    "_date_key": date_key,
                    "sid": str(sid),
                    "test_id": str(rec.get("testId") or "").strip(),
                    "name": name,
                    "correct": int(correct),
                    "total": int(total),
                    "wrong": wrong,
                    "submitted_answers": _submitted_answers_from_record(rec, total),
                    "created_at": str(created_at),
                    "memo": memo,
                    "day": day,
                    "meta": snap_meta,
                }


def merge_test_record_candidates(sources, start: dt.date | None, end: dt.date | None):
    seen: set[tuple[str, str, str, str]] = set()
    for candidates in sources:
        for candidate in candidates:
            day = candidate.get("day")
            if start and (not day or day < start):
                continue
            if end and (not day or day > end):
                continue
            key = (
                str(candidate.get("_date_key") or ""),
                str(candidate.get("sid") or ""),
                str(candidate.get("name") or ""),
                str(candidate.get("created_at") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            item = deepcopy(candidate)
            item.pop("_date_key", None)
            yield item


def normalize_test_record_filters(query) -> dict:
    return {
        "test_id": str(query.get("test_id") or query.get("testId") or "").strip(),
        "test": str(query.get("test") or "").strip(),
        "type": _normalize_test_type(query.get("type") or ""),
        "curriculum": str(query.get("curriculum") or "").strip(),
        "unit_name": str(query.get("unit_name") or "").strip(),
        "test_level": str(query.get("test_level") or "").strip(),
        "term": _normalize_test_term(query.get("term") or query.get("examTerm") or ""),
        "band": str(query.get("band") or "").strip(),
    }


def project_test_records(records, cfg: dict, catalog: dict, students, *, start: dt.date, end: dt.date, filters: dict) -> dict:
    test_id_q = filters["test_id"]
    test_q = filters["test"]
    type_q = filters["type"]
    curriculum_q = filters["curriculum"]
    unit_name_q = filters["unit_name"]
    test_level_q = filters["test_level"]
    term_q = filters["term"]
    band_q = filters["band"]
    sid_to_name = {}
    sid_to_level = {}
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
    for rec in records:
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

    return {
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
        "answerUrl": "",
        "records": recs,
    }


build_test_catalog = _build_test_catalog
normalize_test_type = _normalize_test_type
normalize_test_term = _normalize_test_term
canonical_test_name = _canon_test_name
record_meta = _record_meta
parse_record_date = _parse_date
normalized_test_record_candidates = _normalized_test_record_candidates
sanitize_tests_payload_for_public_api = _sanitize_tests_payload_for_public_api

find_test_def_by_id = _find_test_def_by_id
get_answer_key_for_round = _get_answer_key_for_round
