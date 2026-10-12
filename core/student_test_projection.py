"""Pure progress-authoritative assigned-test presentation, without loaders or caches."""
from __future__ import annotations

import re

from core.progress_rules import TEST_ASSIGN_CLEAR_META_KEY
from core.test_answer_links import resolve_test_assignment_answer_url
from core.update_assignment_rules import sid_lookup as _sid_lookup

TEST_ASSIGN_DAILY_ITEMS_KEY = "testAssignmentDailyTests"

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
        out.append(item)

    return out


def project_student_assigned_tests(
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


def resolve_student_assigned_tests(items: list[dict], *, tests_config: dict, answer_link_map: dict) -> list[dict]:
    out = []
    for raw in items:
        item = dict(raw)
        answer_url = resolve_test_assignment_answer_url(
            item, tests_config=tests_config, answer_link_map=answer_link_map,
        )
        if answer_url:
            item["answerUrl"] = answer_url
        out.append(item)
    return out


filter_assigned_tests_for_student_curriculum = _filter_assigned_tests_for_student_curriculum
