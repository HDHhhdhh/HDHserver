from __future__ import annotations

from typing import Any


PROGRESS_ALL_STUDENTS_META_KEY = "__allStudentsProgressMids"
WATCH_AUTO_PROGRESS_META_KEY = "__autoWatchProgressMids"
PROGRESS_MANUAL_META_KEY = "__manualProgressMids"
TEST_ASSIGN_CLEAR_META_KEY = "__testsClearedAt"

WATCH_INTERRUPTED_RATIO = 0.05
WATCH_DONE_RATIO = 0.90

VALID_VIDEO_PROGRESS_STATUSES = frozenset({"", "done", "interrupted", "none", "skip"})


def _copy_meta(entry: dict, key: str) -> dict:
    meta = entry.get(key)
    return dict(meta) if isinstance(meta, dict) else {}


def normalize_watch_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}

    try:
        last = max(0, int(float(entry.get("last", 0) or 0)))
    except Exception:
        last = 0
    try:
        dur = max(0, int(float(entry.get("dur", 0) or 0)))
    except Exception:
        dur = 0
    try:
        updated_at = int(entry.get("updatedAt") or 0)
    except Exception:
        updated_at = 0

    completed = bool(entry.get("completed", False))
    if watch_ratio({"last": last, "dur": dur}) >= WATCH_DONE_RATIO:
        completed = True

    return {
        "last": last,
        "dur": dur,
        "completed": completed,
        "updatedAt": updated_at,
    }


def watch_ratio(entry: Any) -> float:
    if not isinstance(entry, dict):
        return 0.0
    try:
        last = max(0, float(entry.get("last", 0) or 0))
        dur = max(0, float(entry.get("dur", 0) or 0))
    except Exception:
        return 0.0
    return last / dur if dur > 0 else 0.0


def watch_auto_status(entry: Any) -> str:
    normalized = normalize_watch_entry(entry)
    pct = watch_ratio(normalized)
    if normalized["completed"] or pct >= WATCH_DONE_RATIO:
        return "done"
    if pct >= WATCH_INTERRUPTED_RATIO or (normalized["dur"] <= 0 and normalized["last"] > 0):
        return "interrupted"
    return ""


def merge_watch_entry(prev: Any, incoming: Any) -> dict[str, Any]:
    current = normalize_watch_entry(prev)
    next_entry = normalize_watch_entry(incoming)

    last = max(current["last"], next_entry["last"])
    dur = max(current["dur"], next_entry["dur"])
    completed = current["completed"] or next_entry["completed"]
    if watch_ratio({"last": last, "dur": dur}) >= WATCH_DONE_RATIO:
        completed = True

    return {
        "last": last,
        "dur": dur,
        "completed": completed,
        "updatedAt": max(current["updatedAt"], next_entry["updatedAt"]),
    }


def watch_rank(entry: Any) -> tuple[int, float, int, int]:
    normalized = normalize_watch_entry(entry)
    pct = (
        normalized["last"] / normalized["dur"]
        if normalized["dur"] > 0
        else (1.0 if normalized["completed"] else 0.0)
    )
    return (
        1 if normalized["completed"] else 0,
        pct,
        normalized["last"],
        normalized["updatedAt"],
    )


def merge_progress_day_sid(
    current: dict,
    incoming: dict,
    source: str = "",
    *,
    test_clear_meta_key: str = TEST_ASSIGN_CLEAR_META_KEY,
) -> dict:
    if not isinstance(current, dict):
        current = {}
    if not isinstance(incoming, dict):
        return dict(current)

    out = dict(current)
    source_s = str(source or "").strip()
    all_page_meta = _copy_meta(out, PROGRESS_ALL_STUDENTS_META_KEY)
    watch_auto_meta = _copy_meta(out, WATCH_AUTO_PROGRESS_META_KEY)
    manual_meta = _copy_meta(out, PROGRESS_MANUAL_META_KEY)

    for mid, status in incoming.items():
        mid_s = str(mid).strip()
        if not mid_s:
            continue

        if mid_s == test_clear_meta_key:
            marker = str(status or "").strip()
            if marker:
                out[test_clear_meta_key] = marker
            else:
                out.pop(test_clear_meta_key, None)
            continue

        if mid_s == "tests":
            if not isinstance(status, dict):
                continue

            cur_tests = out.get("tests")
            cur_tests = dict(cur_tests) if isinstance(cur_tests, dict) else {}

            for test_key, test_status in status.items():
                test_key_s = str(test_key or "").strip()
                if not test_key_s:
                    continue

                if test_status is None or test_status is False:
                    cur_tests.pop(test_key_s, None)
                    continue

                if isinstance(test_status, str):
                    status_s = test_status.strip()
                    if status_s in ("", "none"):
                        cur_tests.pop(test_key_s, None)
                    else:
                        cur_tests[test_key_s] = status_s
                    continue

                if isinstance(test_status, dict):
                    if test_status.get("remove") is True:
                        cur_tests.pop(test_key_s, None)
                    else:
                        cur_tests[test_key_s] = dict(test_status)
                    continue

                cur_tests[test_key_s] = str(test_status).strip()

            if cur_tests:
                out["tests"] = cur_tests
                out.pop(test_clear_meta_key, None)
            else:
                out.pop("tests", None)
            continue

        if mid_s.startswith("__"):
            continue

        status_s = str(status).strip()
        if source_s == "auto":
            prev_s = str(out.get(mid_s) or "").strip()
            prev_auto = (
                prev_s in ("done", "interrupted", "skip")
                and str(watch_auto_meta.get(mid_s) or "").strip() == prev_s
            )
            manual_override = bool(manual_meta.get(mid_s))

            all_page_meta.pop(mid_s, None)
            if status_s in ("", "none"):
                if prev_auto and prev_s != "done":
                    out.pop(mid_s, None)
                    watch_auto_meta.pop(mid_s, None)
                elif prev_s not in ("done", "interrupted", "skip", "none"):
                    out.pop(mid_s, None)
                    watch_auto_meta.pop(mid_s, None)
                continue

            if status_s == "interrupted":
                if prev_s == "" or (prev_auto and prev_s != "done"):
                    out[mid_s] = "interrupted"
                    watch_auto_meta[mid_s] = "interrupted"
                    manual_meta.pop(mid_s, None)
                continue

            if status_s == "done":
                if prev_s == "" or prev_auto or (prev_s == "interrupted" and not manual_override):
                    out[mid_s] = "done"
                    watch_auto_meta[mid_s] = "done"
                    manual_meta.pop(mid_s, None)
                continue

            if status_s == "skip":
                if prev_s == "":
                    out[mid_s] = "skip"
                    watch_auto_meta[mid_s] = "skip"
                    manual_meta.pop(mid_s, None)
                continue

        if status_s == "none":
            out[mid_s] = "none"
        elif status_s == "":
            out.pop(mid_s, None)
        else:
            out[mid_s] = status_s

        if source_s == "allStudents":
            if status_s == "":
                all_page_meta.pop(mid_s, None)
            else:
                all_page_meta[mid_s] = True
        else:
            all_page_meta.pop(mid_s, None)

        watch_auto_meta.pop(mid_s, None)
        if source_s == "auto" or status_s == "":
            manual_meta.pop(mid_s, None)
        else:
            manual_meta[mid_s] = True

    if all_page_meta:
        out[PROGRESS_ALL_STUDENTS_META_KEY] = all_page_meta
    else:
        out.pop(PROGRESS_ALL_STUDENTS_META_KEY, None)
    if watch_auto_meta:
        out[WATCH_AUTO_PROGRESS_META_KEY] = watch_auto_meta
    else:
        out.pop(WATCH_AUTO_PROGRESS_META_KEY, None)
    if manual_meta:
        out[PROGRESS_MANUAL_META_KEY] = manual_meta
    else:
        out.pop(PROGRESS_MANUAL_META_KEY, None)

    return out


def merge_auto_watch_progress_status(current: dict, mid: str, status: str) -> dict:
    return merge_progress_day_sid(current, {mid: status}, source="auto")
