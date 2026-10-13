# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_root_cause_dashboard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import JsonObject, read_json_object, require_int as int_value
from ocr_provider_free_extended_gate_count import EXTENDED_GATE_COUNT
from ocr_root_cause_dashboard_markdown import (
    filesystem_path_leak_count,
    markdown_report,
    sensitive_leak_count,
)

LAB: Final[Path] = Path(__file__).resolve().parent
HIGH_PRIORITY_JSON: Final[Path] = LAB / "ocr_high_priority_mismatch_crop_quality.json"
TRAINING_PACK_JSON: Final[Path] = LAB / "ocr_training_pack_crop_fixture_spec_verification.json"
TRAINING_PACK_SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
PRIORITIES_JSON: Final[Path] = LAB / "ocr_accuracy_improvement_priorities.json"
EXTENDED_GATE_JSON: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_extended.json"
CANDIDATE_COMPARISON_JSON: Final[Path] = LAB / "ocr_digit_shape_candidate_comparison.json"
REPORT_JSON: Final[Path] = LAB / "ocr_root_cause_dashboard.json"
REPORT_MD: Final[Path] = LAB / "ocr_root_cause_dashboard.md"


class DashboardBucket(TypedDict):
    bucket: str
    item_count: int
    action: str


class Dashboard(TypedDict):
    ok: bool
    student_facing: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    production_default: str
    extended_gate_count: int
    high_priority_target_count: int
    high_priority_review_required_count: int
    high_priority_auto_fill_allowed_count: int
    wrong_safe_auto_grade: int
    digit_shape_candidate_comparison_row_count: int
    digit_shape_candidate_comparison_review_required_count: int
    digit_shape_candidate_comparison_auto_fill_allowed_count: int
    training_pack_source_assets_ready_count: int
    training_pack_cache_replay_payload_count: int
    buckets: list[DashboardBucket]
    blocker_order: list[str]
    next_actions: list[str]
    sensitive_field_leak_count: int
    filesystem_path_leak_count: int


class RootCauseDashboardError(Exception):
    pass


def main() -> int:
    dashboard = build_dashboard()
    require_dashboard(dashboard)
    REPORT_JSON.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(dashboard), encoding="utf-8")
    print(json.dumps(dashboard, ensure_ascii=False, indent=2))
    return 0


def build_dashboard() -> Dashboard:
    high_priority = read_json_object(HIGH_PRIORITY_JSON)
    training_pack = read_json_object(TRAINING_PACK_JSON)
    training_pack_source = read_json_object(TRAINING_PACK_SOURCE_JSON)
    priorities = read_json_object(PRIORITIES_JSON)
    extended_gate = read_json_object(EXTENDED_GATE_JSON)
    candidate_comparison = read_json_object(CANDIDATE_COMPARISON_JSON)
    buckets = [
        bucket(
            "relation_operator_confusion",
            int_value(high_priority.get("relation_operator_row_count"), "relation_operator_row_count"),
            "keep review_required and block symbol rewrite",
        ),
        bucket(
            "digit_shape_confusion",
            int_value(high_priority.get("digit_shape_row_count"), "digit_shape_row_count"),
            "add candidate handling without auto-fill on conflict",
        ),
        bucket(
            "fixture_missing",
            int_value(training_pack.get("capture_required_count"), "capture_required_count"),
            "promote existing route-upload sources into replay fixtures",
        ),
        bucket(
            "quality_gate",
            int_value(high_priority.get("quality_warning_row_count"), "quality_warning_row_count"),
            "do not broaden retake thresholds for the current four rows",
        ),
        bucket(
            "safe_gate",
            int_value(priorities.get("wrong_safe_auto_grade"), "wrong_safe_auto_grade"),
            "keep safe_auto_grade blocked on unresolved or conflicting signals",
        ),
    ]
    output: Dashboard = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "extended_gate_count": int_value(extended_gate.get("extended_gate_count"), "extended_gate_count"),
        "high_priority_target_count": int_value(high_priority.get("target_count"), "target_count"),
        "high_priority_review_required_count": int_value(
            high_priority.get("review_required_count"),
            "review_required_count",
        ),
        "high_priority_auto_fill_allowed_count": int_value(
            high_priority.get("auto_fill_allowed_count"),
            "auto_fill_allowed_count",
        ),
        "wrong_safe_auto_grade": int_value(priorities.get("wrong_safe_auto_grade"), "wrong_safe_auto_grade"),
        "digit_shape_candidate_comparison_row_count": int_value(candidate_comparison.get("row_count"), "row_count"),
        "digit_shape_candidate_comparison_review_required_count": int_value(
            candidate_comparison.get("review_required_count"),
            "review_required_count",
        ),
        "digit_shape_candidate_comparison_auto_fill_allowed_count": int_value(
            candidate_comparison.get("auto_fill_allowed_count"),
            "auto_fill_allowed_count",
        ),
        "training_pack_source_assets_ready_count": int_value(
            training_pack_source.get("source_assets_ready_count"),
            "source_assets_ready_count",
        ),
        "training_pack_cache_replay_payload_count": int_value(
            training_pack_source.get("cache_replay_payload_count"),
            "cache_replay_payload_count",
        ),
        "buckets": buckets,
        "blocker_order": [
            "fixture_missing",
            "digit_shape_confusion",
            "relation_operator_confusion",
            "quality_gate",
            "safe_gate",
        ],
        "next_actions": [
            "promote Training Pack route-upload sources to provider-free fixture variants",
            "accept only contract-valid Training Pack recognized cache payloads",
            "replace Training Pack replay skeletons with recognized cache payloads before claiming broad OCR replay",
            "use digit-shape candidate comparison while keeping conflict rows review_required",
            "keep arrow/equal and relation/operator conflicts out of automatic fill",
            "use quality gates for real crop failures, not for the current four high-priority rows",
        ],
        "sensitive_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    text = json.dumps(output, ensure_ascii=False)
    output["sensitive_field_leak_count"] = sensitive_leak_count(text)
    output["filesystem_path_leak_count"] = filesystem_path_leak_count(text)
    return output


def bucket(name: str, item_count: int, action: str) -> DashboardBucket:
    return {"bucket": name, "item_count": item_count, "action": action}


def require_dashboard(dashboard: Dashboard) -> None:
    require_zero(dashboard["provider_call_count"], "provider_call_count")
    require_zero(dashboard["external_ocr_api_call_count"], "external_ocr_api_call_count")
    require_zero(dashboard["submit_test_call_count"], "submit_test_call_count")
    require_zero(dashboard["ts_submit_click_count"], "ts_submit_click_count")
    require_zero(dashboard["high_priority_auto_fill_allowed_count"], "high_priority_auto_fill_allowed_count")
    require_zero(dashboard["wrong_safe_auto_grade"], "wrong_safe_auto_grade")
    require_zero(
        dashboard["digit_shape_candidate_comparison_auto_fill_allowed_count"],
        "digit_shape_candidate_comparison_auto_fill_allowed_count",
    )
    require_zero(dashboard["sensitive_field_leak_count"], "sensitive_field_leak_count")
    require_zero(dashboard["filesystem_path_leak_count"], "filesystem_path_leak_count")
    if dashboard["production_default"] != "NO_GO":
        raise RootCauseDashboardError("production default must remain NO_GO")
    if dashboard["extended_gate_count"] != EXTENDED_GATE_COUNT:
        raise RootCauseDashboardError("extended provider-free gate count changed")
    if dashboard["high_priority_target_count"] != 4 or dashboard["high_priority_review_required_count"] != 4:
        raise RootCauseDashboardError("high-priority target coverage changed")
    if dashboard["digit_shape_candidate_comparison_row_count"] != 6:
        raise RootCauseDashboardError("digit-shape candidate comparison coverage changed")
    if dashboard["digit_shape_candidate_comparison_review_required_count"] != 4:
        raise RootCauseDashboardError("digit-shape candidate comparison review count changed")
    if dashboard["training_pack_source_assets_ready_count"] != 4:
        raise RootCauseDashboardError("Training Pack source inventory coverage changed")
    if dashboard["training_pack_cache_replay_payload_count"] != 0:
        raise RootCauseDashboardError("Training Pack cache replay status changed")
    expected = {
        "relation_operator_confusion": 2,
        "digit_shape_confusion": 2,
        "fixture_missing": 4,
        "quality_gate": 0,
        "safe_gate": 0,
    }
    actual = {item["bucket"]: item["item_count"] for item in dashboard["buckets"]}
    if actual != expected:
        raise RootCauseDashboardError(f"unexpected dashboard buckets: {actual}")


def require_zero(value: int, label: str) -> None:
    if value != 0:
        raise RootCauseDashboardError(f"{label} must be zero")


if __name__ == "__main__":
    raise SystemExit(main())
