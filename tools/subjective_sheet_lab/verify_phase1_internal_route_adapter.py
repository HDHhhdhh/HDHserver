# /// script
# requires-python = ">=3.11"
# ///
#
# --- How to run ---
# python tools/subjective_sheet_lab/verify_phase1_internal_route_adapter.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from final_review_payload_bridge import find_forbidden_answer_key_paths
from phase1_internal_route_adapter import (
    SUCCESS_STATUS,
    handle_internal_review_request,
    require_object,
    write_json,
)
from subjective_review_dry_run_core import JsonObject, require_array, require_string

ROOT: Final = Path(__file__).resolve().parent
FIXTURE_PATH: Final = ROOT / "phase1_internal_route_adapter_fixture.json"
SUCCESS_OUTPUT_PATH: Final = ROOT / "phase1_internal_route_adapter_success.json"
ERROR_OUTPUT_PATH: Final = ROOT / "phase1_internal_route_adapter_errors.json"
REPORT_PATH: Final = ROOT / "phase1_internal_route_adapter_report.md"


def read_fixture() -> JsonObject:
    return require_object(json.loads(FIXTURE_PATH.read_text(encoding="utf-8-sig")), "fixture")


def verify_success(fixture: JsonObject) -> JsonObject:
    request = require_object(fixture.get("happy_request"), "happy_request")
    result = handle_internal_review_request(request)
    if result.http_status != SUCCESS_STATUS:
        raise AssertionError(f"happy request returned {result.http_status}")
    payload = result.payload
    if payload.get("ok") is not True:
        raise AssertionError("happy request did not return ok=true")
    review_payload = require_object(payload.get("review_payload"), "review_payload")
    items = require_array(review_payload.get("items"), "review_payload.items")
    if len(items) != 20:
        raise AssertionError("review payload must contain 20 items")
    leak_paths = find_forbidden_answer_key_paths(payload)
    if leak_paths:
        raise AssertionError(f"student-facing payload leaked answer-key fields: {', '.join(leak_paths)}")
    if payload.get("submit_test_called") is not False:
        raise AssertionError("adapter must not call /api/submit-test")
    if payload.get("student_record_write_allowed") is not False:
        raise AssertionError("adapter must not allow student record writes")
    return payload


def verify_error_cases(fixture: JsonObject) -> JsonObject:
    cases = (
        ("disabled_request", 404, "feature_disabled"),
        ("missing_image_request", 400, "invalid_request"),
        ("wrong_mode_request", 400, "invalid_mode"),
    )
    errors: list[JsonObject] = []
    for name, status, code in cases:
        result = handle_internal_review_request(require_object(fixture.get(name), name))
        if result.http_status != status:
            raise AssertionError(f"{name} returned {result.http_status}, wanted {status}")
        if require_string(result.payload.get("code"), f"{name}.code") != code:
            raise AssertionError(f"{name} returned wrong code")
        if "review_payload" in result.payload:
            raise AssertionError(f"{name} must not include review_payload")
        errors.append({"case": name, "http_status": result.http_status, "code": code})
    return {"ok": True, "errors": errors}


def build_report(success_payload: JsonObject, error_payload: JsonObject) -> str:
    status_counts = count_statuses(require_object(success_payload.get("review_payload"), "review_payload"))
    error_lines = "\n".join(
        f"- {require_string(require_object(value, 'error').get('case'), 'case')}: {require_string(require_object(value, 'error').get('code'), 'code')}"
        for value in require_array(error_payload.get("errors"), "errors")
    )
    status_lines = "\n".join(f"- {status}: {count}" for status, count in status_counts.items())
    return "\n".join(
        [
            "# Phase 1 Internal Route Adapter Verification",
            "",
            "## Scope",
            "",
            "- Lab-only route adapter verification.",
            "- No Gemini/API call.",
            "- No `/api/submit-test` call.",
            "- No operating app, route, static, data, or DB file modified.",
            "",
            "## Success Response",
            "",
            status_lines,
            "",
            "## Error Responses",
            "",
            error_lines,
            "",
            "## Result",
            "",
            "The adapter accepts only enabled internal-mode requests and returns the same student-safe review payload contract as the Phase 1 harness.",
        ],
    ) + "\n"


def count_statuses(review_payload: JsonObject) -> JsonObject:
    counts: dict[str, int] = {}
    for value in require_array(review_payload.get("items"), "review_payload.items"):
        item = require_object(value, "review_payload.items[]")
        status = require_string(item.get("status"), "item.status")
        counts[status] = counts.get(status, 0) + 1
    return counts


def main() -> int:
    fixture = read_fixture()
    success_payload = verify_success(fixture)
    error_payload = verify_error_cases(fixture)
    write_json(SUCCESS_OUTPUT_PATH, success_payload)
    write_json(ERROR_OUTPUT_PATH, error_payload)
    REPORT_PATH.write_text(build_report(success_payload, error_payload), encoding="utf-8")
    print(json.dumps({"ok": True, "success": str(SUCCESS_OUTPUT_PATH), "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
