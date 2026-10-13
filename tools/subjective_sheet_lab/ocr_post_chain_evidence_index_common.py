from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    assert_common_safety,
    read_json_object,
    require_int,
    require_object,
    require_text_value,
)


class SourceRow(TypedDict):
    label: str
    report_path: str
    status: str
    metrics: dict[str, int]
    included_statuses: list[str]
    failed_metric_count: int


class ProbeResult(TypedDict):
    name: str
    blocked: bool
    ok: bool
    status: str
    issue: str


class PostChainEvidenceIndexReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    manual_qa_handoff_status: str
    source_report_count: int
    failed_source_count: int
    source_reports: list[SourceRow]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


class PostChainEvidenceIndexGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_probe_passed: bool
    copied_bad_status_probe_blocked: bool
    copied_nonzero_failed_count_probe_blocked: bool
    copied_missing_cleanup_status_probe_blocked: bool
    copied_bad_retention_artifact_count_probe_blocked: bool
    copied_bad_retention_guard_probe_count_probe_blocked: bool
    live_file_write_attempted: bool
    copied_bad_status_issue: str
    copied_nonzero_failed_count_issue: str
    copied_missing_cleanup_status_issue: str
    copied_bad_retention_artifact_count_issue: str
    copied_bad_retention_guard_probe_count_issue: str
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class MetricSpec:
    name: str
    expected: int | None


@dataclass(frozen=True, slots=True)
class SourceSpec:
    label: str
    path: Path
    expected_status: str
    metrics: tuple[MetricSpec, ...]
    included_statuses: tuple[str, ...] = ()
    fresh_after_paths: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceIndexSnapshot:
    source_report_modified_ns: tuple[int, ...]
    evidence_index_modified_ns: int


def source_row(spec: SourceSpec, payload: JsonObject) -> SourceRow:
    assert_common_safety(spec.label, payload)
    require_text_value(payload.get("status"), spec.expected_status, f"{spec.label}.status")
    require_fresh_source(spec)
    return {
        "label": spec.label,
        "report_path": display_path(spec.path),
        "status": spec.expected_status,
        "metrics": metrics_for(spec, payload),
        "included_statuses": included_statuses_for(spec, payload),
        "failed_metric_count": 0,
    }


def metrics_for(spec: SourceSpec, payload: JsonObject) -> dict[str, int]:
    metrics: dict[str, int] = {}
    for metric in spec.metrics:
        value = require_int(payload.get(metric.name), f"{spec.label}.{metric.name}")
        if metric.expected is not None and value != metric.expected:
            raise ExtendedGateError(f"{spec.label}.{metric.name} expected {metric.expected}, got {value}")
        metrics[metric.name] = value
    return metrics


def included_statuses_for(spec: SourceSpec, payload: JsonObject) -> list[str]:
    if not spec.included_statuses:
        return []
    reports = payload.get("reports")
    match reports:
        case list():
            statuses = report_statuses(spec.label, reports)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError(f"{spec.label}.reports must be an array")
        case unreachable:
            assert_never(unreachable)
    missing = [status for status in spec.included_statuses if status not in statuses]
    if missing:
        raise ExtendedGateError(f"{spec.label}.reports missing statuses: {missing}")
    return list(spec.included_statuses)


def source_payloads(specs: tuple[SourceSpec, ...]) -> tuple[JsonObject, ...]:
    return tuple(read_json_object(spec.path) for spec in specs)


def require_fresh_source(spec: SourceSpec) -> None:
    if not spec.fresh_after_paths:
        return
    source_mtime = path_mtime(spec.path)
    stale_paths = tuple(path for path in spec.fresh_after_paths if path_mtime(path) > source_mtime)
    if stale_paths:
        raise ExtendedGateError(f"{spec.label}.report is stale relative to {display_path(stale_paths[0])}")


def snapshot_evidence_files(specs: tuple[SourceSpec, ...], evidence_path: Path) -> EvidenceIndexSnapshot:
    return EvidenceIndexSnapshot(
        source_report_modified_ns=tuple(path_mtime(spec.path) for spec in specs),
        evidence_index_modified_ns=path_mtime(evidence_path),
    )


def path_mtime(path: Path) -> int:
    if path.exists():
        return path.stat().st_mtime_ns
    return -1


def copied_payloads(payloads: tuple[JsonObject, ...]) -> list[JsonObject]:
    return [payload.copy() for payload in payloads]


def report_statuses(label: str, reports: list[JsonValue]) -> set[str]:
    statuses: set[str] = set()
    for index, row in enumerate(reports, start=1):
        row_object = require_object(row, f"{label}.reports[{index}]")
        status = row_object.get("status")
        match status:
            case str():
                statuses.add(status)
            case None | bool() | int() | float() | list() | dict():
                raise ExtendedGateError(f"{label}.reports[{index}].status must be text")
            case unreachable:
                assert_never(unreachable)
    return statuses


def source_index(label: str, specs: tuple[SourceSpec, ...]) -> int:
    for index, spec in enumerate(specs):
        if spec.label == label:
            return index
    raise ExtendedGateError(f"missing source spec: {label}")


def reports_without_status(
    reports: list[JsonValue],
    removed_status: str,
    label: str,
) -> list[JsonValue]:
    filtered: list[JsonValue] = []
    for index, row in enumerate(reports, start=1):
        row_object = require_object(row, f"{label}.reports[{index}]")
        if row_object.get("status") != removed_status:
            filtered.append(row)
    return filtered


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"
