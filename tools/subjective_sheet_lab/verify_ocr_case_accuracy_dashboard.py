# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_case_accuracy_dashboard.py

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Final

from ocr_case_accuracy_dashboard_model import (
    CaseSummary,
    DashboardError,
    JsonObject,
    assert_no_output_leaks,
    accuracy,
    dashboard,
    markdown,
    read_json_object,
    recognized_value,
    require_array,
    require_common_zero_calls,
    require_int,
    require_int_value,
    require_number_or_none,
    require_object,
    text_value,
)
from verify_ocr_provider_free_accuracy_gate import REPORT_JSON as PROVIDER_GATE_JSON
from verify_ocr_provider_free_accuracy_gate import main as verify_provider_free_gate

LAB: Final[Path] = Path(__file__).resolve().parent
SERVER_OCR: Final[Path] = Path("C:/server-ocr")
REPORT_JSON: Final[Path] = LAB / "ocr_case_accuracy_dashboard.json"
REPORT_MD: Final[Path] = LAB / "ocr_case_accuracy_dashboard.md"
EXPECTED_PROVIDER_FREE_GATE_COUNT: Final[int] = 5


EVAL_SOURCES: Final[tuple[tuple[str, Path], ...]] = (
    ("person_02_same_contact", SERVER_OCR / "gemini_outputs" / "person_02_same_contact" / "human_transcription_eval.json"),
    ("person_03_same_contact", SERVER_OCR / "gemini_outputs" / "person_03_same_contact" / "human_transcription_eval.json"),
    ("person_04_same_contact", SERVER_OCR / "gemini_outputs" / "person_04_same_contact" / "human_transcription_eval.json"),
)
GANG_CURRENT_EVAL: Final[Path] = LAB / "gangyuhyun849_current_crop_human_eval.json"


def main() -> int:
    gate_report = run_provider_free_gate()
    cases = (summarize_gang_current(),) + tuple(summarize_human_eval(source) for source in EVAL_SOURCES)
    output = dashboard(cases, gate_report)
    assert_no_output_leaks(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output, cases), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def run_provider_free_gate() -> JsonObject:
    buffer = StringIO()
    with redirect_stdout(buffer):
        result = verify_provider_free_gate()
    if result != 0:
        raise DashboardError(f"provider-free accuracy gate failed with exit code {result}")
    report = read_json_object(PROVIDER_GATE_JSON)
    require_int_value(report.get("gate_count"), EXPECTED_PROVIDER_FREE_GATE_COUNT, "provider gate_count")
    require_common_zero_calls(report)
    return report


def summarize_human_eval(source: tuple[str, Path]) -> CaseSummary:
    case_id, path = source
    payload = read_json_object(path)
    if payload.get("student_facing") is not False:
        raise DashboardError(f"{case_id} eval must be non-student-facing")
    summary = require_object(payload.get("summary"), f"{case_id}.summary")
    items = require_array(payload.get("items"), f"{case_id}.items")
    high_items = tuple(item for item in (require_object(value, "eval item") for value in items) if text_value(item.get("human_confidence")) == "high" and recognized_value(item))
    return CaseSummary(
        case_id=case_id,
        source="existing_human_transcription_eval_summary",
        total=require_int(summary.get("total"), "total"),
        evaluated_total=require_int(summary.get("ocr_evaluated_total"), "ocr_evaluated_total"),
        exact_matches=require_int(summary.get("exact_or_normalized_match"), "exact_or_normalized_match"),
        ocr_vs_human_accuracy=require_number_or_none(summary.get("ocr_recognition_accuracy_against_human_transcription"), "ocr accuracy"),
        high_confidence_evaluated_total=len(high_items),
        high_confidence_exact_matches=sum(1 for item in high_items if item.get("match_to_human") is True),
        high_confidence_ocr_vs_human_accuracy=accuracy(sum(1 for item in high_items if item.get("match_to_human") is True), len(high_items)),
        safe_auto_grade=require_int(summary.get("safe_auto_grade"), "safe_auto_grade"),
        review_required=require_int(summary.get("review_required"), "review_required"),
        retake_required=require_int(summary.get("retake_required", 0), "retake_required"),
        data_check_required=require_int(summary.get("data_check_required"), "data_check_required"),
        missing=require_int(summary.get("missing"), "missing"),
        wrong_safe_auto_grade=require_int(summary.get("wrong_safe_auto_grade_against_human_transcription"), "wrong_safe_auto_grade"),
        ambiguous_human_labels=require_int(summary.get("ambiguous_human_label_count"), "ambiguous_human_label_count"),
    )


def summarize_gang_current() -> CaseSummary:
    payload = read_json_object(GANG_CURRENT_EVAL)
    summary = require_object(payload.get("summary"), "gang current summary")
    items = require_array(payload.get("items"), "gang current items")
    high_items = tuple(item for item in (require_object(value, "gang item") for value in items) if text_value(item.get("confidence")) == "high" and recognized_value(item))
    exact_matches = require_int(summary.get("exact_matches"), "gang exact_matches")
    return CaseSummary(
        case_id="gangyuhyun849_current_crop",
        source="current_crop_human_eval_summary",
        total=require_int(summary.get("total"), "gang total"),
        evaluated_total=require_int(summary.get("evaluated_total"), "gang evaluated_total"),
        exact_matches=exact_matches,
        ocr_vs_human_accuracy=require_number_or_none(summary.get("ocr_vs_human_accuracy"), "gang accuracy"),
        high_confidence_evaluated_total=len(high_items),
        high_confidence_exact_matches=sum(1 for item in high_items if text_value(item.get("status")) == "match"),
        high_confidence_ocr_vs_human_accuracy=accuracy(sum(1 for item in high_items if text_value(item.get("status")) == "match"), len(high_items)),
        safe_auto_grade=require_int(summary.get("safe_auto_grade"), "gang safe_auto_grade"),
        review_required=require_int(summary.get("provider_review_required"), "gang provider_review_required"),
        retake_required=require_int(summary.get("retake_required"), "gang retake_required"),
        data_check_required=require_int(summary.get("data_check_required"), "gang data_check_required"),
        missing=require_int(summary.get("missing_or_unresolved"), "gang missing_or_unresolved"),
        wrong_safe_auto_grade=require_int(summary.get("wrong_safe_auto_grade_against_current_crop_human"), "gang wrong_safe_auto_grade"),
        ambiguous_human_labels=require_int(summary.get("ambiguous_or_low_confidence_human_labels"), "gang ambiguous_human_labels"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
