from __future__ import annotations

from typing import Any


PROGRESS_ALL_STUDENTS_META_KEY = "__allStudentsProgressMids"
WATCH_AUTO_PROGRESS_META_KEY = "__autoWatchProgressMids"
PROGRESS_MANUAL_META_KEY = "__manualProgressMids"
TEST_ASSIGN_CLEAR_META_KEY = "__testsClearedAt"
TEST_ASSIGN_CHANGE_ORDER_META_KEY = "__testAssignmentChangeOrder"
TEST_ASSIGN_TOUCHED_KEYS_META_KEY = "__testAssignmentTouchedKeys"

WATCH_INTERRUPTED_RATIO = 0.05
WATCH_DONE_RATIO = 0.90
WATCH_UPDATED_AT_MIN_MS = 1_000_000_000_000

VALID_VIDEO_PROGRESS_STATUSES = frozenset({"", "done", "interrupted", "none", "skip"})
AUTO_OWNED_PROGRESS_STATUSES = frozenset({"done", "interrupted", "skip"})
AUTO_EMPTY_PRESERVED_STATUSES = frozenset({"done", "interrupted", "skip", "none"})


def normalize_incoming_watch_updated_at(value: Any, fallback_ms: Any) -> int:
    """Replace seconds/Int32 timestamps from stale clients with server epoch ms."""
    try:
        updated_at = int(value or 0)
    except Exception:
        updated_at = 0
    try:
        fallback = max(0, int(fallback_ms or 0))
    except Exception:
        fallback = 0
    return updated_at if updated_at >= WATCH_UPDATED_AT_MIN_MS else fallback


def _is_watch_auto_owned_status(mid: str, status: str, watch_auto_meta: dict) -> bool:
    return (
        status in AUTO_OWNED_PROGRESS_STATUSES
        and str(watch_auto_meta.get(mid) or "").strip() == status
    )


def _has_manual_progress_override(mid: str, manual_meta: dict) -> bool:
    return bool(manual_meta.get(mid))


def _auto_empty_update_should_clear(prev_status: str, prev_auto: bool) -> bool:
    return (prev_auto and prev_status != "done") or prev_status not in AUTO_EMPTY_PRESERVED_STATUSES


def _auto_interrupted_should_apply(prev_status: str, prev_auto: bool) -> bool:
    return prev_status == "" or (prev_auto and prev_status != "done")


def _auto_done_should_apply(prev_status: str, prev_auto: bool, manual_override: bool) -> bool:
    return (
        prev_status == ""
        or prev_auto
        or (prev_status == "interrupted" and not manual_override)
    )


def _auto_skip_should_apply(prev_status: str) -> bool:
    return prev_status == ""


def _copy_meta(entry: dict, key: str) -> dict:
    meta = entry.get(key)
    return dict(meta) if isinstance(meta, dict) else {}


def _test_assignment_status_name(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("remove") is True:
            return ""
        value = value.get("status")
    if value is None or value is False:
        return ""
    status = str(value).strip()
    return "" if status == "none" else status


def _test_assignment_change_order(entry: dict) -> dict[str, int]:
    raw = entry.get(TEST_ASSIGN_CHANGE_ORDER_META_KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for label, value in raw.items():
        label_s = str(label or "").strip()
        if not label_s:
            continue
        try:
            order = int(value)
        except (TypeError, ValueError):
            continue
        if order > 0:
            out[label_s] = order
    return out


def advance_test_assignment_change_order(entry: dict, labels: Any) -> dict:
    """Give one batch of changed tests the next per-entry ordering token."""
    out = dict(entry) if isinstance(entry, dict) else {}
    tests = out.get("tests")
    tests = tests if isinstance(tests, dict) else {}
    order_by_label = _test_assignment_change_order(out)

    for label in list(order_by_label):
        if label not in tests or not _test_assignment_status_name(tests.get(label)):
            order_by_label.pop(label, None)

    changed_labels: list[str] = []
    seen: set[str] = set()
    for label in labels or []:
        label_s = str(label or "").strip()
        if (
            not label_s
            or label_s in seen
            or label_s not in tests
            or not _test_assignment_status_name(tests.get(label_s))
        ):
            continue
        seen.add(label_s)
        changed_labels.append(label_s)

    if changed_labels:
        next_order = max(order_by_label.values(), default=0) + 1
        for label in changed_labels:
            order_by_label[label] = next_order

    if order_by_label:
        out[TEST_ASSIGN_CHANGE_ORDER_META_KEY] = order_by_label
    else:
        out.pop(TEST_ASSIGN_CHANGE_ORDER_META_KEY, None)
    out.pop(TEST_ASSIGN_TOUCHED_KEYS_META_KEY, None)
    return out


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
    raw_touched_test_keys = incoming.get(TEST_ASSIGN_TOUCHED_KEYS_META_KEY)
    touched_test_keys = {
        str(key or "").strip()
        for key in (raw_touched_test_keys if isinstance(raw_touched_test_keys, list) else [])
        if str(key or "").strip()
    }
    patched_test_keys: set[str] = set()
    changed_test_keys: set[str] = set()
    saw_tests_patch = False

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

        if mid_s == TEST_ASSIGN_TOUCHED_KEYS_META_KEY:
            continue

        if mid_s == "tests":
            if not isinstance(status, dict):
                continue
            saw_tests_patch = True

            cur_tests = out.get("tests")
            cur_tests = dict(cur_tests) if isinstance(cur_tests, dict) else {}

            for test_key, test_status in status.items():
                test_key_s = str(test_key or "").strip()
                if not test_key_s:
                    continue
                patched_test_keys.add(test_key_s)
                before_status = _test_assignment_status_name(cur_tests.get(test_key_s))

                if test_status is None or test_status is False:
                    cur_tests.pop(test_key_s, None)
                elif isinstance(test_status, str):
                    status_s = test_status.strip()
                    if status_s in ("", "none"):
                        cur_tests.pop(test_key_s, None)
                    else:
                        cur_tests[test_key_s] = status_s
                elif isinstance(test_status, dict):
                    if test_status.get("remove") is True:
                        cur_tests.pop(test_key_s, None)
                    else:
                        cur_tests[test_key_s] = dict(test_status)
                else:
                    cur_tests[test_key_s] = str(test_status).strip()

                after_status = _test_assignment_status_name(cur_tests.get(test_key_s))
                if before_status != after_status:
                    changed_test_keys.add(test_key_s)

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
            prev_auto = _is_watch_auto_owned_status(mid_s, prev_s, watch_auto_meta)
            manual_override = _has_manual_progress_override(mid_s, manual_meta)

            all_page_meta.pop(mid_s, None)
            if status_s in ("", "none"):
                if _auto_empty_update_should_clear(prev_s, prev_auto):
                    out.pop(mid_s, None)
                    watch_auto_meta.pop(mid_s, None)
                continue

            if status_s == "interrupted":
                if _auto_interrupted_should_apply(prev_s, prev_auto):
                    out[mid_s] = "interrupted"
                    watch_auto_meta[mid_s] = "interrupted"
                    manual_meta.pop(mid_s, None)
                continue

            if status_s == "done":
                if _auto_done_should_apply(prev_s, prev_auto, manual_override):
                    out[mid_s] = "done"
                    watch_auto_meta[mid_s] = "done"
                    manual_meta.pop(mid_s, None)
                continue

            if status_s == "skip":
                if _auto_skip_should_apply(prev_s):
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

    if saw_tests_patch:
        # The popup sends the complete test map plus the rows the user actually
        # touched. Other callers send only changed statuses, so status diffing is
        # their authoritative change signal.
        ordered_test_keys = (
            touched_test_keys & patched_test_keys
            if touched_test_keys
            else changed_test_keys
        )
        out = advance_test_assignment_change_order(out, sorted(ordered_test_keys))

    return out


def merge_auto_watch_progress_status(current: dict, mid: str, status: str) -> dict:
    return merge_progress_day_sid(current, {mid: status}, source="auto")
