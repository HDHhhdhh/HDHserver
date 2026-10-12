# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_accuracy_improvement_priorities.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_accuracy_improvement_priorities_model import (
    CasePriority,
    JsonObject,
    PriorityError,
    RowPriority,
    assert_no_output_leaks,
    markdown,
    number_or_none,
    read_json_object,
    report,
    require_array,
    require_dashboard,
    require_int,
    require_object,
    text_value,
)
from verify_ocr_case_accuracy_dashboard import REPORT_JSON as DASHBOARD_JSON
from verify_ocr_case_accuracy_dashboard import main as verify_dashboard

LAB: Final[Path] = Path(__file__).resolve().parent
SERVER_OCR: Final[Path] = Path("C:/server-ocr")
REPORT_JSON: Final[Path] = LAB / "ocr_accuracy_improvement_priorities.json"
REPORT_MD: Final[Path] = LAB / "ocr_accuracy_improvement_priorities.md"


HUMAN_EVALS: Final[tuple[tuple[str, Path], ...]] = (
    ("person_02_same_contact", SERVER_OCR / "gemini_outputs" / "person_02_same_contact" / "human_transcription_eval.json"),
    ("person_03_same_contact", SERVER_OCR / "gemini_outputs" / "person_03_same_contact" / "human_transcription_eval.json"),
    ("person_04_same_contact", SERVER_OCR / "gemini_outputs" / "person_04_same_contact" / "human_transcription_eval.json"),
)
GANG_EVAL: Final[Path] = LAB / "gangyuhyun849_current_crop_human_eval.json"


def main() -> int:
    if verify_dashboard() != 0:
        raise PriorityError("case accuracy dashboard failed")
    dashboard = read_json_object(DASHBOARD_JSON)
    require_dashboard(dashboard)
    row_priorities = sorted(load_row_priorities(), key=lambda item: (-item.priority, item.case_id, item.question_no))
    case_priorities = sorted(load_case_priorities(dashboard), key=lambda item: (-item.priority, item.case_id))
    output = report(row_priorities, case_priorities, dashboard)
    assert_no_output_leaks(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output, row_priorities, case_priorities), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def load_row_priorities() -> tuple[RowPriority, ...]:
    rows: list[RowPriority] = []
    rows.extend(gang_priorities())
    for case_id, path in HUMAN_EVALS:
        payload = read_json_object(path)
        for raw_item in require_array(payload.get("items"), f"{case_id}.items"):
            priority = priority_for_human_eval_item(case_id, require_object(raw_item, "eval item"))
            if priority is not None:
                rows.append(priority)
    return tuple(rows)


def gang_priorities() -> list[RowPriority]:
    payload = read_json_object(GANG_EVAL)
    rows: list[RowPriority] = []
    for raw_item in require_array(payload.get("items"), "gang items"):
        item = require_object(raw_item, "gang item")
        recognized = text_value(item.get("recognized"))
        confidence = text_value(item.get("confidence"))
        status = text_value(item.get("status"))
        if status == "match":
            continue
        question_no = require_int(item.get("question_no"), "gang question_no")
        issue_type = "high_confidence_unresolved" if recognized == "?" and confidence == "high" else "mismatch_or_unresolved"
        rows.append(
            RowPriority(
                "gangyuhyun849_current_crop",
                question_no,
                90 if issue_type == "high_confidence_unresolved" else 70,
                issue_type,
                confidence,
                recognized,
                text_value(item.get("human_answer")),
                text_value(item.get("review_status")),
                "clear human-visible answer but OCR did not provide a usable recognized value",
            ),
        )
    return rows


def priority_for_human_eval_item(case_id: str, item: JsonObject) -> RowPriority | None:
    recognized = text_value(item.get("recognized"))
    confidence = text_value(item.get("human_confidence"))
    matched = item.get("match_to_human") is True
    if matched:
        return None
    question_no = require_int(item.get("question_no"), "question_no")
    policy_status = text_value(item.get("effective_policy")) or text_value(item.get("source_final_policy"))
    if recognized == "?":
        issue_type = "high_confidence_unresolved" if confidence == "high" else "ambiguous_unresolved"
        priority = 90 if confidence == "high" else 55
        reason = "OCR abstained on a human-transcribed answer"
    elif confidence == "high":
        issue_type = "high_confidence_mismatch"
        priority = 95
        reason = "OCR produced a wrong value against high-confidence human transcription"
    else:
        issue_type = "low_confidence_mismatch"
        priority = 45
        reason = "human label is low-confidence; keep review routing while collecting more evidence"
    return RowPriority(case_id, question_no, priority, issue_type, confidence, recognized, text_value(item.get("human_answer")), policy_status, reason)


def load_case_priorities(dashboard: JsonObject) -> tuple[CasePriority, ...]:
    priorities: list[CasePriority] = []
    for raw_case in require_array(dashboard.get("cases"), "dashboard.cases"):
        case = require_object(raw_case, "dashboard case")
        total = require_int(case.get("total"), "case.total")
        review = require_int(case.get("review_required"), "case.review_required")
        missing = require_int(case.get("missing"), "case.missing")
        safe = require_int(case.get("safe_auto_grade"), "case.safe_auto_grade")
        if review < 10 and missing == 0:
            continue
        case_id = text_value(case.get("case_id"))
        issue_type = "review_load" if review >= 10 else "missing_load"
        priorities.append(
            CasePriority(
                case_id,
                min(80, review * 3 + missing * 5),
                issue_type,
                review,
                safe,
                missing,
                number_or_none(case.get("ocr_vs_human_accuracy")),
                f"{review}/{total} review-required and {missing} missing/unresolved",
            ),
        )
    return tuple(priorities)


if __name__ == "__main__":
    raise SystemExit(main())
