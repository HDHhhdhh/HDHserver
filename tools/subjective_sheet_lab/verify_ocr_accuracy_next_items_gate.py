# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_accuracy_next_items_gate.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypeAlias

from ocr_accuracy_next_items_candidate_checks import (
    dependency_readiness,
    q016_q017_local_candidate_tools,
    route_upload_visible_digit_generalization,
)
from ocr_accuracy_next_items_scope_checks import mijeok_training_fixture_scope, q003_threshold_tuning

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_accuracy_next_items_gate.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_accuracy_next_items_gate.md")
FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
    "C:\\",
    "C:/",
    "/c/",
)


class AccuracyNextItemsGateError(Exception):
    pass


def main() -> int:
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "gate_count": 5,
        "q016_q017_local_candidate_tools": q016_q017_local_candidate_tools(),
        "extended_gate_dependency_readiness": dependency_readiness(),
        "mijeok_training_fixture_scope": mijeok_training_fixture_scope(),
        "route_upload_visible_digit_generalization": route_upload_visible_digit_generalization(),
        "q003_threshold_tuning": q003_threshold_tuning(),
    }
    if leak_count(json.dumps(output, ensure_ascii=False)) != 0:
        raise AccuracyNextItemsGateError("sensitive field or path token leaked into next-items output")
    output["answer_key_or_grading_field_leak_count"] = 0
    output["filesystem_path_leak_count"] = 0
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


def markdown(output: JsonObject) -> str:
    local = require_object(output["q016_q017_local_candidate_tools"], "local")
    deps = require_object(output["extended_gate_dependency_readiness"], "deps")
    fixtures = require_object(output["mijeok_training_fixture_scope"], "fixtures")
    route = require_object(output["route_upload_visible_digit_generalization"], "route")
    q003 = require_object(output["q003_threshold_tuning"], "q003")
    lines = [
        "# OCR Accuracy Next Items Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        "- answer-key/grading/path leak count: 0",
        "",
        f"- q016/q017 local candidate questions: {local['questions']}",
        f"- local tesseract status: `{local['tesseract_status']}`",
        f"- extended gate dependencies ready: {deps['ready']}",
        f"- mijeok/training targets checked: {fixtures['target_count']}",
        f"- complete mijeok/training crop sets found: {fixtures['complete_crop_set_count']}",
        f"- route-upload visible-digit q016/q017 scans: {route['question_scan_count']}",
        f"- route-upload visible-digit signals: {route['visible_digit_signal_count']}",
        f"- q003 signal/no-signal separation margin: {q003['separation_margin']}",
    ]
    return "\n".join(lines) + "\n"


def require_object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise AccuracyNextItemsGateError(f"{label} must be a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
