from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final, TypedDict

from ocr_next_action_queue_state_snippets import (
    LATEST_HEADING,
    LATEST_REQUIRED_QUEUE_SNIPPETS,
    REQUIRED_QUEUE_SNIPPETS,
)
from ocr_preflight_environment_matrix_model import LAB, JsonValue
from ocr_provider_free_extended_gate_count import EXTENDED_GATE_COUNT
from ocr_report_field_access import bool_field, int_field, nullable_int_field, str_field

QUEUE_PATH: Final[Path] = LAB / "ocr_next_action_queue.md"

class QueueStateReport(TypedDict):
    ok: bool
    student_facing: bool
    queue_path: str
    latest_heading: str
    latest_heading_present: bool
    latest_heading_at_tail: bool
    required_snippet_count: int
    missing_snippet_count: int
    missing_snippets: list[str]
    latest_required_snippet_count: int
    latest_missing_snippet_count: int
    latest_missing_snippets: list[str]
    expected_extended_gate_count: int
    matrix_ok: bool
    classifier_status: str
    freshness_status: str
    extended_gate_count: int | None
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    issue_count: int
    next_safe_action: str


def build_report(
    queue_text: str,
    matrix: Mapping[str, JsonValue],
    classifier: Mapping[str, JsonValue],
    freshness: Mapping[str, JsonValue],
) -> QueueStateReport:
    missing_snippets = [snippet for snippet in REQUIRED_QUEUE_SNIPPETS if snippet not in queue_text]
    actual_latest_heading = latest_heading(queue_text)
    latest_text = latest_section(queue_text)
    latest_missing_snippets = [snippet for snippet in LATEST_REQUIRED_QUEUE_SNIPPETS if snippet not in latest_text]
    latest_heading_at_tail = actual_latest_heading == LATEST_HEADING
    gate_ok = (
        str_field(classifier, "status") == "environment_split_verified"
        and str_field(freshness, "status") == "fresh_and_consistent"
        and int_field(freshness, "issue_count") == 0
        and int_field(freshness, "provider_call_count") == 0
        and int_field(freshness, "external_ocr_api_call_count") == 0
        and int_field(freshness, "submit_test_call_count") == 0
        and int_field(freshness, "ts_submit_click_count") == 0
        and int_field(freshness, "answer_key_or_grading_field_leak_count") == 0
        and int_field(freshness, "filesystem_path_leak_count") == 0
        and str_field(freshness, "production_default") == "NO_GO"
    )
    ok = latest_heading_at_tail and not missing_snippets and not latest_missing_snippets and gate_ok
    return {
        "ok": ok,
        "student_facing": False,
        "queue_path": str(QUEUE_PATH.relative_to(LAB.parents[1])),
        "latest_heading": actual_latest_heading,
        "latest_heading_present": LATEST_HEADING in queue_text,
        "latest_heading_at_tail": latest_heading_at_tail,
        "required_snippet_count": len(REQUIRED_QUEUE_SNIPPETS),
        "missing_snippet_count": len(missing_snippets),
        "missing_snippets": missing_snippets,
        "latest_required_snippet_count": len(LATEST_REQUIRED_QUEUE_SNIPPETS),
        "latest_missing_snippet_count": len(latest_missing_snippets),
        "latest_missing_snippets": latest_missing_snippets,
        "expected_extended_gate_count": EXTENDED_GATE_COUNT,
        "matrix_ok": bool_field(matrix, "ok"),
        "classifier_status": str_field(classifier, "status"),
        "freshness_status": str_field(freshness, "status"),
        "extended_gate_count": nullable_int_field(freshness, "extended_gate_count"),
        "provider_call_count": int_field(freshness, "provider_call_count"),
        "external_ocr_api_call_count": int_field(freshness, "external_ocr_api_call_count"),
        "submit_test_call_count": int_field(freshness, "submit_test_call_count"),
        "ts_submit_click_count": int_field(freshness, "ts_submit_click_count"),
        "answer_key_or_grading_field_leak_count": int_field(
            freshness,
            "answer_key_or_grading_field_leak_count",
        ),
        "filesystem_path_leak_count": int_field(freshness, "filesystem_path_leak_count"),
        "production_default": str_field(freshness, "production_default"),
        "issue_count": int_field(freshness, "issue_count"),
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep queue verifier pinned to the actual file-tail handoff section."
    return "Refresh the queue tail section and rerun the provider-free gate chain."


def latest_section(queue_text: str) -> str:
    lines = queue_text.splitlines()
    start = latest_heading_index(lines)
    if start is None:
        return ""
    return "\n".join(lines[start:])


def latest_heading(queue_text: str) -> str:
    lines = queue_text.splitlines()
    start = latest_heading_index(lines)
    if start is None:
        return ""
    return lines[start]


def latest_heading_index(lines: list[str]) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].startswith("## "):
            return index
    return None
