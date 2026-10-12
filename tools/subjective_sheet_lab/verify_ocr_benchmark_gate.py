#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# 1. Install uv if needed: https://docs.astral.sh/uv/
# 2. Generate the report first:
#      uv run tools/subjective_sheet_lab/ocr_benchmark_gate.py
# 3. Run this verifier:
#      uv run tools/subjective_sheet_lab/verify_ocr_benchmark_gate.py
# 4. Or use the project Python for both commands.
# ------------------

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from ocr_benchmark_gate import REPORT_JSON
from ocr_review_schema import JsonObject, JsonValue
from ocr_review_payload_validator import require_array, require_object, require_string

EXPECTED_CASES: Final = frozenset(
    {
        "person_02_same_contact",
        "daesu_jisu1_lv3_r1_photo01_same_contact",
        "photo_1_same_contact",
        "photo_2_same_contact",
    },
)


def main() -> int:
    report = read_report(REPORT_JSON)
    assert_expected_case_set(report)
    assert_gate_status(report)
    assert_diagnostic_metrics(report)
    assert_validation_flags(report)
    print("ok: OCR benchmark gate report is valid")
    return 0


def read_report(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), str(path))


def assert_expected_case_set(report: JsonObject) -> None:
    cases = case_map(report)
    if frozenset(cases) != EXPECTED_CASES:
        raise AssertionError(f"unexpected case set: {sorted(cases)}")


def assert_gate_status(report: JsonObject) -> None:
    if report.get("gate_status") != "GO_FOR_FEATURE_FLAG_INTEGRATION_WITH_CONDITIONS":
        raise AssertionError("feature-flag gate status changed")
    if report.get("production_default_status") != "NO_GO":
        raise AssertionError("production default must remain no-go")
    if report.get("feature_flag_integration_allowed") is not True:
        raise AssertionError("feature-flag integration must be allowed after pre-integration validation closure")
    if report.get("production_default_allowed") is not False:
        raise AssertionError("production default must remain disallowed")
    if report.get("preferred_strategy") != "same-contact":
        raise AssertionError("same-contact must remain preferred")


def assert_diagnostic_metrics(report: JsonObject) -> None:
    aggregate = require_object(report.get("aggregate"), "aggregate")
    if aggregate.get("cases_with_human_transcription") != 2:
        raise AssertionError("benchmark must include both independent human transcription evals")
    if aggregate.get("wrong_safe_auto_grade_total") != 0:
        raise AssertionError("aggregate wrong_safe_auto_grade_total must stay 0")
    if aggregate.get("missing_total") != 0:
        raise AssertionError("aggregate missing_total must stay 0")
    cases = case_map(report)
    daesu = cases["daesu_jisu1_lv3_r1_photo01_same_contact"]
    daesu_transcription = require_object(daesu.get("transcription"), "daesu.transcription")
    if daesu_transcription.get("accuracy_percent") != 100.0:
        raise AssertionError("daesu OCR transcription accuracy must be 100.0")
    person_transcription = require_object(cases["person_02_same_contact"].get("transcription"), "person.transcription")
    if person_transcription.get("available") is not True:
        raise AssertionError("person_02 transcription must be available")
    if person_transcription.get("correct") != 14 or person_transcription.get("total") != 16:
        raise AssertionError("person_02 transcription must report 14/16 high-confidence matches")
    if person_transcription.get("accuracy_percent") != 87.5:
        raise AssertionError("person_02 OCR transcription accuracy must be 87.5")
    if person_transcription.get("passes_threshold") is not False:
        raise AssertionError("person_02 transcription should remain below the 90% production diagnostic threshold")
    for name in ("photo_1_same_contact", "photo_2_same_contact"):
        if cases[name].get("capture_condition_case") is not True:
            raise AssertionError(f"{name} must be marked as capture-condition case")
    if any(case.get("wrong_safe_auto_grade") != 0 for case in cases.values()):
        raise AssertionError("wrong_safe_auto_grade must stay 0 for all included cases")


def assert_validation_flags(report: JsonObject) -> None:
    if require_array(report.get("feature_flag_blockers"), "feature_flag_blockers"):
        raise AssertionError("feature_flag_blockers must be empty")
    if not require_array(report.get("production_blockers"), "production_blockers"):
        raise AssertionError("production_blockers must document why production default remains no-go")
    validation = require_object(report.get("validation"), "validation")
    for key in ("gemini_api_called", "submit_test_called", "operating_app_code_touched", "api_key_or_env_exposed"):
        if validation.get(key) is not False:
            raise AssertionError(f"{key} must be false")


def case_map(report: JsonObject) -> dict[str, JsonObject]:
    output: dict[str, JsonObject] = {}
    for value in require_array(report.get("cases"), "cases"):
        case = require_object(value, "case")
        output[require_string(case.get("case_id"), "case_id")] = case
    return output


if __name__ == "__main__":
    raise SystemExit(main())
