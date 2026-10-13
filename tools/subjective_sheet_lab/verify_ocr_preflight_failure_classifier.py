# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_preflight_failure_classifier.py

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, TypeAlias, TypedDict, assert_never

from ocr_preflight_environment_matrix_model import LAB, REPORT_JSON, ROOT, JsonValue
from ocr_preflight_environment_matrix_output import parse_json
from ocr_report_field_access import bool_field, int_field, nullable_int_field, str_field

ClassifierStatus: TypeAlias = Literal["environment_split_verified", "action_required"]
REPORT_CLASSIFIER_JSON = LAB / "ocr_preflight_failure_classifier.json"
REPORT_CLASSIFIER_MD = LAB / "ocr_preflight_failure_classifier.md"


class PreflightFailureClassification(TypedDict):
    ok: bool
    status: ClassifierStatus
    matrix_report: str
    matrix_ok: bool
    environment_split_verified: bool
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    extended_gate_count: int | None
    command_probe_count: int
    failing_command_count: int
    preflight_script_modified: bool
    operator_decision: str
    user_approval_required: bool
    next_safe_action: str


def main() -> int:
    matrix = load_matrix()
    report = classify(matrix)
    REPORT_CLASSIFIER_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_CLASSIFIER_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def load_matrix() -> Mapping[str, JsonValue]:
    parsed = parse_json(REPORT_JSON.read_text(encoding="utf-8"))
    match parsed:
        case dict() as value:
            return value
        case None | bool() | int() | float() | str() | list():
            msg = f"matrix report is not a JSON object: {REPORT_JSON}"
            raise TypeError(msg)
        case unreachable:
            assert_never(unreachable)


def classify(matrix: Mapping[str, JsonValue]) -> PreflightFailureClassification:
    matrix_ok = bool_field(matrix, "ok")
    provider_count = int_field(matrix, "provider_call_count")
    external_ocr_count = int_field(matrix, "external_ocr_api_call_count")
    submit_count = int_field(matrix, "submit_test_call_count")
    ts_submit_count = int_field(matrix, "ts_submit_click_count")
    answer_key_leak_count = int_field(matrix, "answer_key_or_grading_field_leak_count")
    path_leak_count = int_field(matrix, "filesystem_path_leak_count")
    production_default = str_field(matrix, "production_default")
    preflight_modified = bool_field(matrix, "preflight_script_modified")
    failing_commands = failing_command_count(matrix)
    environment_split_verified = (
        matrix_ok
        and provider_count == 0
        and external_ocr_count == 0
        and submit_count == 0
        and ts_submit_count == 0
        and answer_key_leak_count == 0
        and path_leak_count == 0
        and production_default == "NO_GO"
        and not preflight_modified
        and failing_commands == 0
    )
    status: ClassifierStatus = "environment_split_verified" if environment_split_verified else "action_required"
    return {
        "ok": environment_split_verified,
        "status": status,
        "matrix_report": str(REPORT_JSON.relative_to(ROOT)),
        "matrix_ok": matrix_ok,
        "environment_split_verified": environment_split_verified,
        "provider_call_count": provider_count,
        "external_ocr_api_call_count": external_ocr_count,
        "submit_test_call_count": submit_count,
        "ts_submit_click_count": ts_submit_count,
        "answer_key_or_grading_field_leak_count": answer_key_leak_count,
        "filesystem_path_leak_count": path_leak_count,
        "production_default": production_default,
        "extended_gate_count": nullable_int_field(matrix, "extended_gate_count"),
        "command_probe_count": command_probe_count(matrix),
        "failing_command_count": failing_commands,
        "preflight_script_modified": preflight_modified,
        "operator_decision": operator_decision(environment_split_verified),
        "user_approval_required": False,
        "next_safe_action": "Keep using the env matrix gate unless preflight-list integration is explicitly approved.",
    }


def command_probe_count(matrix: Mapping[str, JsonValue]) -> int:
    match matrix.get("command_probes"):
        case list() as probes:
            return len(probes)
        case None | bool() | int() | float() | str() | dict():
            return 0
        case unreachable:
            assert_never(unreachable)


def failing_command_count(matrix: Mapping[str, JsonValue]) -> int:
    match matrix.get("command_probes"):
        case list() as probes:
            return sum(1 for probe in probes if command_failed(probe))
        case None | bool() | int() | float() | str() | dict():
            return 0
        case unreachable:
            assert_never(unreachable)


def command_failed(probe: JsonValue) -> bool:
    match probe:
        case {"ok": bool() as ok}:
            return not ok
        case None | bool() | int() | float() | str() | list() | dict():
            return True
        case unreachable:
            assert_never(unreachable)


def operator_decision(environment_split_verified: bool) -> str:
    if environment_split_verified:
        return "Provider-free OCR checks pass when image checks use OCR venv and app checks use app venv."
    return "Investigate the failing probe before treating preflight status as environment-only."


def markdown(report: PreflightFailureClassification) -> str:
    return "\n".join((
        "# OCR Preflight Failure Classifier",
        "",
        f"- ok: {report['ok']}",
        f"- status: {report['status']}",
        f"- environment_split_verified: {report['environment_split_verified']}",
        f"- production_default: {report['production_default']}",
        f"- extended_gate_count: {report['extended_gate_count']}",
        f"- command_probe_count: {report['command_probe_count']}",
        f"- failing_command_count: {report['failing_command_count']}",
        f"- provider_call_count: {report['provider_call_count']}",
        f"- external_ocr_api_call_count: {report['external_ocr_api_call_count']}",
        f"- submit_test_call_count: {report['submit_test_call_count']}",
        f"- ts_submit_click_count: {report['ts_submit_click_count']}",
        f"- answer_key_or_grading_field_leak_count: {report['answer_key_or_grading_field_leak_count']}",
        f"- filesystem_path_leak_count: {report['filesystem_path_leak_count']}",
        f"- preflight_script_modified: {report['preflight_script_modified']}",
        "",
        "## Operator Decision",
        report["operator_decision"],
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
