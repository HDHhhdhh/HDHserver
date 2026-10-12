from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Final, TypedDict, assert_never

from ocr_post_chain_evidence_index_common import display_path, path_mtime
from ocr_provider_free_extended_gate_common import (
    JsonObject,
    assert_common_safety,
    require_bool_value,
    require_int_value,
    require_text_value,
)
import verify_ocr_provider_free_final_handoff_chain as final_chain
import verify_ocr_provider_free_final_handoff_chain_guard as final_guard


@unique
class SourceLabel(StrEnum):
    FINAL_HANDOFF_CHAIN = "final_handoff_chain"
    FINAL_HANDOFF_CHAIN_GUARD = "final_handoff_chain_guard"


class HandoffStatusSourceRow(TypedDict):
    label: str
    report_path: str
    status: str
    metrics: dict[str, int]
    fresh: bool
    failed_metric_count: int


class HandoffStatusCardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    manual_qa_handoff_status: str
    source_report_count: int
    stale_source_count: int
    failed_source_count: int
    source_reports: list[HandoffStatusSourceRow]
    handoff_retention_guard_probe_count: int
    handoff_retention_guard_failed_probe_count: int
    handoff_retention_missing_start_card_freshness_helper_missing_count: int
    training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count: int
    training_pack_partial_evidence_arrival_guard_complete_probe_passed_count: int
    training_pack_partial_evidence_arrival_guard_invalid_probe_blocked_count: int
    training_pack_partial_evidence_arrival_guard_failed_probe_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class HandoffStatusSourceSpec:
    label: SourceLabel
    path: Path
    expected_status: str
    freshness_anchor: Path | None


SOURCE_SPECS: Final[tuple[HandoffStatusSourceSpec, ...]] = (
    HandoffStatusSourceSpec(
        SourceLabel.FINAL_HANDOFF_CHAIN,
        final_chain.REPORT_JSON_OUT,
        "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_VERIFIED",
        None,
    ),
    HandoffStatusSourceSpec(
        SourceLabel.FINAL_HANDOFF_CHAIN_GUARD,
        final_guard.REPORT_JSON_OUT,
        "OCR_PROVIDER_FREE_FINAL_HANDOFF_CHAIN_GUARD_VERIFIED",
        final_chain.REPORT_JSON_OUT,
    ),
)

FINAL_HANDOFF_CHAIN_INT_METRICS: Final[tuple[tuple[str, int], ...]] = (
    ("step_count", 3),
    ("failed_step_count", 0),
    ("provider_free_chain_failed_step_count", 0),
    ("handoff_guard_failed_probe_count", 0),
    ("handoff_runner_common_self_check_source_report_count", 16),
    ("handoff_runner_evidence_index_source_report_count", 18),
    ("handoff_runner_evidence_index_guard_failed_probe_count", 0),
    ("post_chain_evidence_index_source_report_count", 18),
    ("post_chain_qa_start_here_source_count", 4),
    ("handoff_retention_guard_probe_count", 9),
    ("handoff_retention_guard_failed_probe_count", 0),
    ("handoff_retention_missing_start_card_freshness_helper_missing_count", 1),
    ("training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count", 4),
    ("training_pack_partial_evidence_arrival_guard_complete_probe_passed_count", 1),
    ("training_pack_partial_evidence_arrival_guard_invalid_probe_blocked_count", 3),
    ("training_pack_partial_evidence_arrival_guard_failed_probe_count", 0),
    ("manual_qa_handoff_refresh_serial_guard_probe_count", 4),
    ("manual_qa_handoff_refresh_serial_guard_failed_probe_count", 0),
)

FINAL_HANDOFF_CHAIN_GUARD_INT_METRICS: Final[tuple[tuple[str, int], ...]] = (
    ("probe_count", 6),
    ("failed_probe_count", 0),
    ("live_step_count", 3),
    ("live_failed_step_count", 0),
)


def source_row(spec: HandoffStatusSourceSpec, payload: JsonObject) -> HandoffStatusSourceRow:
    assert_common_safety(spec.label, payload)
    require_text_value(payload.get("status"), spec.expected_status, f"{spec.label}.status")
    freshness = source_is_fresh(spec)
    return {
        "label": spec.label.value,
        "report_path": display_path(spec.path),
        "status": spec.expected_status,
        "metrics": metrics_for(spec.label, payload),
        "fresh": freshness,
        "failed_metric_count": 0 if freshness else 1,
    }


def source_is_fresh(spec: HandoffStatusSourceSpec) -> bool:
    if spec.freshness_anchor is None:
        return True
    return path_mtime(spec.path) >= path_mtime(spec.freshness_anchor)


def metrics_for(label: SourceLabel, payload: JsonObject) -> dict[str, int]:
    match label:
        case SourceLabel.FINAL_HANDOFF_CHAIN:
            require_final_handoff_chain_metrics(label, payload)
            return dict(FINAL_HANDOFF_CHAIN_INT_METRICS)
        case SourceLabel.FINAL_HANDOFF_CHAIN_GUARD:
            require_final_handoff_chain_guard_metrics(label, payload)
            return dict(FINAL_HANDOFF_CHAIN_GUARD_INT_METRICS)
        case unreachable:
            assert_never(unreachable)


def require_final_handoff_chain_metrics(label: SourceLabel, payload: JsonObject) -> None:
    require_int_metrics(label, payload, FINAL_HANDOFF_CHAIN_INT_METRICS)
    require_bool_value(
        payload.get("manual_qa_handoff_refresh_serial_guard_lock_file_removed"),
        True,
        f"{label.value}.manual_qa_handoff_refresh_serial_guard_lock_file_removed",
    )
    require_bool_value(
        payload.get("manual_qa_handoff_refresh_serial_guard_artifacts_preserved"),
        True,
        f"{label.value}.manual_qa_handoff_refresh_serial_guard_artifacts_preserved",
    )


def require_final_handoff_chain_guard_metrics(label: SourceLabel, payload: JsonObject) -> None:
    require_int_metrics(label, payload, FINAL_HANDOFF_CHAIN_GUARD_INT_METRICS)
    require_bool_value(payload.get("live_final_handoff_passed"), True, f"{label.value}.live_final_handoff_passed")
    require_bool_value(
        payload.get("copied_serial_guard_step_blocked"),
        True,
        f"{label.value}.copied_serial_guard_step_blocked",
    )


def require_int_metrics(
    label: SourceLabel,
    payload: JsonObject,
    expected_metrics: tuple[tuple[str, int], ...],
) -> None:
    for key, expected in expected_metrics:
        require_int_value(payload.get(key), expected, f"{label.value}.{key}")


def build_report(rows: list[HandoffStatusSourceRow]) -> HandoffStatusCardReport:
    failed_source_count = sum(row["failed_metric_count"] for row in rows)
    stale_source_count = sum(1 for row in rows if not row["fresh"])
    ok = failed_source_count == 0 and stale_source_count == 0 and len(rows) == len(SOURCE_SPECS)
    final_metrics = next(row["metrics"] for row in rows if row["label"] == SourceLabel.FINAL_HANDOFF_CHAIN.value)
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_READY"
        if ok
        else "OCR_PROVIDER_FREE_HANDOFF_STATUS_CARD_BLOCKED",
        "manual_qa_handoff_status": "READY" if ok else "BLOCKED",
        "source_report_count": len(rows),
        "stale_source_count": stale_source_count,
        "failed_source_count": failed_source_count,
        "source_reports": rows,
        "handoff_retention_guard_probe_count": final_metrics["handoff_retention_guard_probe_count"],
        "handoff_retention_guard_failed_probe_count": final_metrics["handoff_retention_guard_failed_probe_count"],
        "handoff_retention_missing_start_card_freshness_helper_missing_count": final_metrics[
            "handoff_retention_missing_start_card_freshness_helper_missing_count"
        ],
        "training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count": final_metrics[
            "training_pack_partial_evidence_arrival_guard_partial_probe_blocked_count"
        ],
        "training_pack_partial_evidence_arrival_guard_complete_probe_passed_count": final_metrics[
            "training_pack_partial_evidence_arrival_guard_complete_probe_passed_count"
        ],
        "training_pack_partial_evidence_arrival_guard_invalid_probe_blocked_count": final_metrics[
            "training_pack_partial_evidence_arrival_guard_invalid_probe_blocked_count"
        ],
        "training_pack_partial_evidence_arrival_guard_failed_probe_count": final_metrics[
            "training_pack_partial_evidence_arrival_guard_failed_probe_count"
        ],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Use this compact status card before live OCR approval or manual-QA handoff."
    return "Refresh the final handoff wrapper and guard before live OCR approval or manual-QA handoff."
