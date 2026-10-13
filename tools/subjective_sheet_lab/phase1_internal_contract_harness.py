# /// script
# requires-python = ">=3.11"
# ///
#
# --- How to run ---
# python tools/subjective_sheet_lab/phase1_internal_contract_harness.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from final_review_payload_bridge import JsonValue, find_forbidden_answer_key_paths
from subjective_review_dry_run_core import (
    DryRunError,
    DryRunResult,
    require_array,
    require_int,
    require_object,
    require_string,
    run_dry_flow,
)

JsonObject: TypeAlias = dict[str, JsonValue]

ROOT: Final = Path(__file__).resolve().parent
FIXTURE_PATH: Final = ROOT / "phase1_internal_contract_fixture.json"
REVIEW_FIXTURE_DEFAULT: Final = ROOT / "subjective_review_dry_run_fixture.json"
REVIEW_OUTPUT_PATH: Final = ROOT / "phase1_internal_contract_review_payload.json"
REPORT_PATH: Final = ROOT / "phase1_internal_contract_report.md"
MANIFEST_PATH: Final = ROOT / "phase1_internal_contract_manifest.json"
FORBIDDEN_STUDENT_FIELDS: Final = frozenset(
    {"expected", "canonical_answer", "accepted_answers"},
)


@dataclass(frozen=True, slots=True)
class Phase1ContractError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class HarnessResult:
    response: JsonObject
    manifest: JsonObject
    report: str


def read_json(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), str(path))


def write_json(path: Path, value: JsonObject) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_review_fixture_path(contract_fixture: JsonObject) -> Path:
    raw_path = require_string(
        contract_fixture.get("source_review_fixture"),
        "source_review_fixture",
    )
    path = ROOT / raw_path
    if not path.is_file():
        return REVIEW_FIXTURE_DEFAULT
    return path


def build_phase1_response(
    contract_fixture: JsonObject,
    dry_result: DryRunResult,
) -> JsonObject:
    request = require_object(contract_fixture.get("request"), "request")
    review_payload = dry_result.outputs.review_payload
    problem_count = require_int(review_payload.get("problem_count"), "review_payload.problem_count")
    checks = tuple(require_string(value, "contract_checks[]") for value in require_array(contract_fixture.get("contract_checks"), "contract_checks"))
    return {
        "ok": True,
        "mode": require_string(contract_fixture.get("mode"), "mode"),
        "feature_flag": "internal_contract_only_default_off",
        "enabled_by_default": False,
        "linked_from_student_page": False,
        "submit_test_called": False,
        "student_record_write_allowed": False,
        "gemini_api_called": False,
        "request": {
            "sid": require_string(request.get("sid"), "request.sid"),
            "testId": require_string(request.get("testId"), "request.testId"),
            "round": require_string(request.get("round"), "request.round"),
            "inputKind": require_string(request.get("inputKind"), "request.inputKind"),
            "imagePath": require_string(request.get("imagePath"), "request.imagePath"),
        },
        "review_payload": review_payload,
        "contract_checks": list(checks),
        "problem_count": problem_count,
    }


def ensure_phase1_contract(response: JsonObject) -> None:
    if response.get("enabled_by_default") is not False:
        raise Phase1ContractError("Phase 1 harness must be default-off")
    if response.get("linked_from_student_page") is not False:
        raise Phase1ContractError("Phase 1 harness must not be linked from student page")
    if response.get("submit_test_called") is not False:
        raise Phase1ContractError("Phase 1 harness must not call /api/submit-test")
    if response.get("student_record_write_allowed") is not False:
        raise Phase1ContractError("Phase 1 harness must not write student records")
    if response.get("gemini_api_called") is not False:
        raise Phase1ContractError("Phase 1 harness must not call Gemini/API")
    review_payload = require_object(response.get("review_payload"), "review_payload")
    items = require_array(review_payload.get("items"), "review_payload.items")
    expected_count = require_int(response.get("problem_count"), "problem_count")
    if len(items) != expected_count:
        raise Phase1ContractError("review payload item count does not match problem_count")
    leak_paths = find_forbidden_answer_key_paths(response)
    if leak_paths:
        raise Phase1ContractError(f"student-facing response leaked answer-key fields: {', '.join(leak_paths)}")


def build_manifest(
    contract_fixture: JsonObject,
    dry_result: DryRunResult,
    review_fixture_path: Path,
) -> JsonObject:
    statuses = count_statuses(dry_result.outputs.review_payload)
    forbidden_targets = tuple(require_string(value, "forbidden_write_targets[]") for value in require_array(contract_fixture.get("forbidden_write_targets"), "forbidden_write_targets"))
    return {
        "ok": True,
        "contract_fixture": str(FIXTURE_PATH),
        "source_review_fixture": str(review_fixture_path),
        "review_output": str(REVIEW_OUTPUT_PATH),
        "report": str(REPORT_PATH),
        "forbidden_write_targets": list(forbidden_targets),
        "status_counts": statuses,
        "blocking_checks": [
            {"name": check.name, "passed": check.passed, "detail": check.detail}
            for check in dry_result.blocking_checks
        ],
    }


def count_statuses(review_payload: JsonObject) -> JsonObject:
    counts: dict[str, int] = {}
    for value in require_array(review_payload.get("items"), "review_payload.items"):
        item = require_object(value, "review_payload.items[]")
        status = require_string(item.get("status"), "item.status")
        counts[status] = counts.get(status, 0) + 1
    return counts


def build_report(response: JsonObject, manifest: JsonObject) -> str:
    status_lines = "\n".join(
        f"- {status}: {count}"
        for status, count in require_object(manifest.get("status_counts"), "status_counts").items()
    )
    check_lines = "\n".join(
        f"- {require_string(require_object(value, 'blocking_check').get('name'), 'blocking_check.name')}: pass"
        for value in require_array(manifest.get("blocking_checks"), "blocking_checks")
    )
    leak_paths = find_forbidden_answer_key_paths(response)
    leak_line = "none" if not leak_paths else ", ".join(leak_paths)
    return f"""# Phase 1 Internal Contract Harness Report

## Scope

- Lab-only Phase 1 backend contract harness.
- No Gemini/API call.
- No `/api/submit-test` call.
- No student record write.
- No operating student page link.

## Response Contract

- Default-off: {response.get("enabled_by_default") is False}
- Linked from student page: {response.get("linked_from_student_page") is True}
- Problem count: {response.get("problem_count")}
- Student-facing answer-key leak scan: {leak_line}

## Review Status Counts

{status_lines}

## Blocking Checks Reused From Lab Dry Run

{check_lines}

## Output Files

- Review response: `{REVIEW_OUTPUT_PATH}`
- Manifest: `{MANIFEST_PATH}`

## Guardrail

This harness only proves the local contract shape. It does not enable the real
student OCR flow, does not submit answers, and does not write `tests.json`,
logs, SQLite, or `data/**`.
"""


def run_harness() -> HarnessResult:
    contract_fixture = read_json(FIXTURE_PATH)
    review_fixture_path = resolve_review_fixture_path(contract_fixture)
    dry_result = run_dry_flow(read_json(review_fixture_path))
    response = build_phase1_response(contract_fixture, dry_result)
    ensure_phase1_contract(response)
    manifest = build_manifest(contract_fixture, dry_result, review_fixture_path)
    report = build_report(response, manifest)
    return HarnessResult(response, manifest, report)


def main() -> int:
    try:
        result = run_harness()
    except (DryRunError, Phase1ContractError) as exc:
        raise SystemExit(str(exc)) from exc
    write_json(REVIEW_OUTPUT_PATH, result.response)
    write_json(MANIFEST_PATH, result.manifest)
    REPORT_PATH.write_text(result.report, encoding="utf-8")
    print(json.dumps({"ok": True, "review": str(REVIEW_OUTPUT_PATH), "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
