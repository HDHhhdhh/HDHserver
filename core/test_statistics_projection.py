"""Pure historical test statistics; clocks, query policy and storage stay in routes."""
from __future__ import annotations

import datetime as dt
from statistics import median, pstdev

from core.test_record_projection import (
    canonical_test_name as _canon_test_name,
    normalize_test_term as _normalize_test_term,
    record_meta as _record_meta,
)

TEST_TYPE_ORDER = ("REVIEW", "UNIT", "TRAINING_PACK", "SCHOOL_PAST", "ILSAN_PAST", "FINAL", "HELL")

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


def project_test_statistics(records, catalog: dict, students, *, start: dt.date, end: dt.date, include_wrong: bool) -> dict:
    def level_band(level: str) -> str:
        lv = str(level or "").strip()
        if lv in ("상", "중상", "중", "하"):
            return lv
        return "하"

    sid_band: dict[str, str] = {}
    if isinstance(students, list):
        for s in students:
            sid = str(s.get("id") or "").strip()
            if not sid:
                continue
            sid_band[sid] = level_band(s.get("level", ""))

    agg: dict[str, dict] = {}
    agg_by_id: dict[str, dict] = {}
    agg_by_signature: dict[str, dict] = {}
    unit_agg: dict[tuple[str, str, str], dict] = {}
    series_agg: dict[tuple[str, str, str], dict] = {}
    wrong_freq: dict[str, dict[int, int]] = {}
    type_summary = {key: _make_stats_agg() for key in TEST_TYPE_ORDER}

    for rec in records:
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

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "by_test": out,
        "by_test_id": out_by_id,
        "by_test_signature": out_by_signature,
        "summary": summary,
        "unit_rows": unit_rows,
        "series_rows": series_rows_by_type,
        "final_rows": final_rows,
        "hell_rows": hell_rows,
    }
