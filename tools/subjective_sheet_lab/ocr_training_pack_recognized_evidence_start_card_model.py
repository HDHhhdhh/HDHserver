# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_training_pack_recognized_evidence_start_card.py.

from __future__ import annotations

from typing import Final, TypedDict, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    assert_common_safety,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_report_field_access import int_field, str_field

FORBIDDEN_SNIPPETS: Final[tuple[str, ...]] = (
    "C:\\server",
    "C:/server",
    "/api/submit-test",
    "canonical_answer",
    "accepted_answers",
    "grading fields",
)


class RequiredFile(TypedDict):
    test_id: str
    required_file_name: str


class StartCardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    start_card_path: str
    current_blocker: str
    next_action: str
    handoff_runner_status: str
    rendered_summary_status: str
    rendered_summary_guard_status: str
    required_file_count: int
    missing_file_count: int
    required_files: list[RequiredFile]
    handoff_step_count: int
    handoff_failed_step_count: int
    rendered_summary_required_snippet_count: int
    rendered_summary_missing_snippet_count: int
    rendered_summary_guard_probe_count: int
    rendered_summary_guard_failed_probe_count: int
    card_required_snippet_count: int
    card_missing_snippet_count: int
    card_forbidden_snippet_count: int
    card_missing_snippets: list[str]
    card_forbidden_snippets: list[str]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def build_report(
    runner: JsonObject,
    summary: JsonObject,
    guard: JsonObject,
    filename: JsonObject,
) -> StartCardReport:
    assert_common_safety("handoff_runner", runner)
    assert_common_safety("handoff_runner_rendered_summary", summary)
    assert_common_safety("handoff_runner_rendered_summary_guard", guard)
    assert_common_safety("filename_diagnostics", filename)
    require_text_value(
        runner.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_READY",
        "handoff_runner.status",
    )
    require_text_value(
        summary.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_RENDERED_SUMMARY_VERIFIED",
        "rendered_summary.status",
    )
    require_text_value(
        guard.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_RENDERED_SUMMARY_GUARD_VERIFIED",
        "rendered_summary_guard.status",
    )
    require_bool_value(guard.get("forbidden_path_snippet_blocked"), True, "rendered_summary_guard.forbidden_path_snippet_blocked")
    require_int_value(runner.get("handoff_step_count"), 9, "handoff_runner.handoff_step_count")
    require_int_value(runner.get("failed_step_count"), 0, "handoff_runner.failed_step_count")
    require_int_value(summary.get("missing_snippet_count"), 0, "rendered_summary.missing_snippet_count")
    require_int_value(summary.get("forbidden_snippet_count"), 0, "rendered_summary.forbidden_snippet_count")
    require_int_value(guard.get("failed_probe_count"), 0, "rendered_summary_guard.failed_probe_count")
    files = required_files(filename)
    missing_file_count = sum(1 for item in expected_file_entries(filename) if item.get("present") is False)
    return {
        "ok": True,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_START_CARD_READY",
        "start_card_path": "tools/subjective_sheet_lab/OCR_TRAINING_PACK_RECOGNIZED_EVIDENCE_START_HERE.md",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "next_action": "copy_four_contract_valid_training_pack_recognized_evidence_files",
        "handoff_runner_status": str_field(runner, "status"),
        "rendered_summary_status": str_field(summary, "status"),
        "rendered_summary_guard_status": str_field(guard, "status"),
        "required_file_count": len(files),
        "missing_file_count": missing_file_count,
        "required_files": files,
        "handoff_step_count": 9,
        "handoff_failed_step_count": 0,
        "rendered_summary_required_snippet_count": int_field(summary, "required_snippet_count"),
        "rendered_summary_missing_snippet_count": 0,
        "rendered_summary_guard_probe_count": int_field(guard, "probe_count"),
        "rendered_summary_guard_failed_probe_count": 0,
        "card_required_snippet_count": 0,
        "card_missing_snippet_count": 0,
        "card_forbidden_snippet_count": 0,
        "card_missing_snippets": [],
        "card_forbidden_snippets": [],
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": "Use this start card before running Training Pack evidence intake after files arrive.",
    }


def expected_file_entries(filename: JsonObject) -> list[JsonObject]:
    entries = filename.get("expected_files")
    match entries:
        case list():
            return [entry for entry in entries if isinstance(entry, dict)]
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("filename_diagnostics.expected_files must be a list")
        case unreachable:
            assert_never(unreachable)


def required_files(filename: JsonObject) -> list[RequiredFile]:
    return [
        {
            "test_id": str_field(entry, "test_id"),
            "required_file_name": str_field(entry, "required_file_name"),
        }
        for entry in expected_file_entries(filename)
    ]


def with_card_checks(report: StartCardReport, card_text: str) -> StartCardReport:
    required = required_card_snippets(report)
    missing = [snippet for snippet in required if snippet not in card_text]
    forbidden = [snippet for snippet in FORBIDDEN_SNIPPETS if snippet in card_text]
    checked = dict(report)
    checked["ok"] = not missing and not forbidden and report["missing_file_count"] == 4
    checked["status"] = "TRAINING_PACK_RECOGNIZED_EVIDENCE_START_CARD_READY" if checked["ok"] else "TRAINING_PACK_RECOGNIZED_EVIDENCE_START_CARD_FAILED"
    checked["card_required_snippet_count"] = len(required)
    checked["card_missing_snippet_count"] = len(missing)
    checked["card_forbidden_snippet_count"] = len(forbidden)
    checked["card_missing_snippets"] = missing
    checked["card_forbidden_snippets"] = forbidden
    return checked


def required_card_snippets(report: StartCardReport) -> tuple[str, ...]:
    file_snippets = tuple(f"`{item['required_file_name']}`" for item in report["required_files"])
    return (
        "# OCR Training Pack Recognized Evidence Start Here",
        f"- status: `{report['status']}`",
        f"- current_blocker: `{report['current_blocker']}`",
        f"- next_action: `{report['next_action']}`",
        f"- required_file_count: `{report['required_file_count']}`",
        f"- missing_file_count: `{report['missing_file_count']}`",
        "- provider_call_count: `0`",
        "- external_ocr_api_call_count: `0`",
        "- submit_test_call_count: `0`",
        "- ts_submit_click_count: `0`",
        "- production_default: `NO_GO`",
        "python tools/subjective_sheet_lab/verify_ocr_training_pack_recognized_evidence_handoff_runner.py",
        *file_snippets,
    )
