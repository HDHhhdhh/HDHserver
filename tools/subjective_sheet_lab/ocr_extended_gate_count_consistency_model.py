from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import JsonValue
from ocr_provider_free_extended_gate_count import EXTENDED_GATE_COUNT
from ocr_next_action_queue_state_model import latest_section
from ocr_report_field_access import int_field, nullable_int_field, str_field

COUNT_PATTERN: Final[re.Pattern[str]] = re.compile(r"Extended provider-free gate count:\s*`?(\d+)`?")


class CountConsistencyReport(TypedDict):
    ok: bool
    student_facing: bool
    expected_extended_gate_count: int
    extended_report_count: int | None
    matrix_report_count: int | None
    classifier_report_count: int | None
    freshness_report_count: int | None
    queue_state_report_count: int | None
    operator_summary_report_count: int | None
    queue_state_modified_ns: int
    operator_summary_modified_ns: int
    operator_summary_newer_than_queue_state: bool
    latest_queue_count: int | None
    latest_queue_count_match_count: int
    total_queue_count_occurrence_count: int
    historical_queue_count_occurrence_count: int
    historical_counts_ignored_for_current: bool
    training_pack_recognized_evidence_contract_rejected_probe_count: int
    training_pack_recognized_evidence_contract_sensitive_probe_count: int
    training_pack_recognized_evidence_contract_path_probe_count: int
    training_pack_recognized_evidence_contract_schema_probe_count: int
    training_pack_recognized_evidence_contract_safe_auto_grade_status_probe_count: int
    training_pack_replacement_sandbox_safe_auto_grade_status_rejected_count: int
    issue_count: int
    issues: list[str]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def build_report(
    reports: Mapping[str, Mapping[str, JsonValue]],
    queue_text: str,
    modified_times_ns: Mapping[str, int],
) -> CountConsistencyReport:
    latest_values = count_values(extract_latest_section(queue_text))
    all_values = count_values(queue_text)
    counts = report_counts(reports)
    issues = count_issues(counts, latest_values)
    add_freshness_issues(issues, modified_times_ns)
    production_default = str_field(reports["freshness"], "production_default")
    add_safety_issues(issues, reports["freshness"], production_default)
    return {
        "ok": not issues,
        "student_facing": False,
        "expected_extended_gate_count": EXTENDED_GATE_COUNT,
        **counts,
        "queue_state_modified_ns": modified_times_ns["queue_state"],
        "operator_summary_modified_ns": modified_times_ns["operator_summary"],
        "operator_summary_newer_than_queue_state": operator_summary_is_fresh(modified_times_ns),
        "latest_queue_count": first_int(latest_values),
        "latest_queue_count_match_count": len(latest_values),
        "total_queue_count_occurrence_count": len(all_values),
        "historical_queue_count_occurrence_count": len(all_values) - len(latest_values),
        "historical_counts_ignored_for_current": True,
        "training_pack_recognized_evidence_contract_rejected_probe_count": int_field(
            reports["extended"],
            "training_pack_recognized_evidence_contract_rejected_probe_count",
        ),
        "training_pack_recognized_evidence_contract_sensitive_probe_count": int_field(
            reports["extended"],
            "training_pack_recognized_evidence_contract_sensitive_probe_count",
        ),
        "training_pack_recognized_evidence_contract_path_probe_count": int_field(
            reports["extended"],
            "training_pack_recognized_evidence_contract_path_probe_count",
        ),
        "training_pack_recognized_evidence_contract_schema_probe_count": int_field(
            reports["extended"],
            "training_pack_recognized_evidence_contract_schema_probe_count",
        ),
        "training_pack_recognized_evidence_contract_safe_auto_grade_status_probe_count": int_field(
            reports["extended"],
            "training_pack_recognized_evidence_contract_safe_auto_grade_status_probe_count",
        ),
        "training_pack_replacement_sandbox_safe_auto_grade_status_rejected_count": int_field(
            reports["extended"],
            "training_pack_replacement_sandbox_safe_auto_grade_status_rejected_count",
        ),
        "issue_count": len(issues),
        "issues": issues,
        "provider_call_count": int_field(reports["freshness"], "provider_call_count"),
        "external_ocr_api_call_count": int_field(reports["freshness"], "external_ocr_api_call_count"),
        "submit_test_call_count": int_field(reports["freshness"], "submit_test_call_count"),
        "ts_submit_click_count": int_field(reports["freshness"], "ts_submit_click_count"),
        "answer_key_or_grading_field_leak_count": int_field(
            reports["freshness"],
            "answer_key_or_grading_field_leak_count",
        ),
        "filesystem_path_leak_count": int_field(reports["freshness"], "filesystem_path_leak_count"),
        "production_default": production_default,
        "next_safe_action": next_safe_action(not issues),
    }


def operator_summary_is_fresh(modified_times_ns: Mapping[str, int]) -> bool:
    return modified_times_ns["operator_summary"] >= modified_times_ns["queue_state"]


def report_counts(reports: Mapping[str, Mapping[str, JsonValue]]) -> dict[str, int | None]:
    return {
        "extended_report_count": nullable_int_field(reports["extended"], "extended_gate_count"),
        "matrix_report_count": nullable_int_field(reports["matrix"], "extended_gate_count"),
        "classifier_report_count": nullable_int_field(reports["classifier"], "extended_gate_count"),
        "freshness_report_count": nullable_int_field(reports["freshness"], "extended_gate_count"),
        "queue_state_report_count": nullable_int_field(reports["queue_state"], "extended_gate_count"),
        "operator_summary_report_count": nullable_int_field(reports["operator_summary"], "extended_gate_count"),
    }


def extract_latest_section(queue_text: str) -> str:
    return latest_section(queue_text)


def count_values(text: str) -> tuple[int, ...]:
    return tuple(int(match.group(1)) for match in COUNT_PATTERN.finditer(text))


def count_issues(counts: Mapping[str, int | None], latest_values: tuple[int, ...]) -> list[str]:
    issues: list[str] = []
    for label, value in counts.items():
        if value != EXTENDED_GATE_COUNT:
            issues.append(f"{label} expected {EXTENDED_GATE_COUNT}, got {value}")
    if len(latest_values) != 1:
        issues.append(f"latest queue section should contain one count, found {len(latest_values)}")
    elif latest_values[0] != EXTENDED_GATE_COUNT:
        issues.append(f"latest queue count expected {EXTENDED_GATE_COUNT}, got {latest_values[0]}")
    return issues


def add_freshness_issues(issues: list[str], modified_times_ns: Mapping[str, int]) -> None:
    if not operator_summary_is_fresh(modified_times_ns):
        issues.append("operator summary must be refreshed after queue-state verification")


def add_safety_issues(issues: list[str], freshness: Mapping[str, JsonValue], production_default: str) -> None:
    for field in (
        "provider_call_count",
        "external_ocr_api_call_count",
        "submit_test_call_count",
        "ts_submit_click_count",
        "answer_key_or_grading_field_leak_count",
        "filesystem_path_leak_count",
        "issue_count",
    ):
        value = int_field(freshness, field)
        if value != 0:
            issues.append(f"{field} expected 0, got {value}")
    if production_default != "NO_GO":
        issues.append(f"production_default expected NO_GO, got {production_default}")


def first_int(values: tuple[int, ...]) -> int | None:
    if not values:
        return None
    return values[0]


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep generated count artifacts aligned whenever the extended gate count changes."
    return "Rerun extended gate, matrix, classifier, freshness, queue-state verifier, then this count verifier."
