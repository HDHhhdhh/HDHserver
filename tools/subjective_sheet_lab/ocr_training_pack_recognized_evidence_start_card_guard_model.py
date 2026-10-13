# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# Imported by verify_ocr_training_pack_recognized_evidence_start_card_guard.py.

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypedDict, assert_never

from ocr_preflight_environment_matrix_model import JsonValue
from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    assert_common_safety,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from ocr_report_field_access import int_field, str_field
import verify_ocr_training_pack_recognized_evidence_start_card as start_card

OK_STATUS: Final[str] = "TRAINING_PACK_RECOGNIZED_EVIDENCE_START_CARD_GUARD_VERIFIED"
FAILED_STATUS: Final[str] = "TRAINING_PACK_RECOGNIZED_EVIDENCE_START_CARD_GUARD_FAILED"


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    payload: JsonObject
    markdown_text: str


class ProbeReport(TypedDict):
    name: str
    ok: bool
    blocked: bool
    missing_snippet_count: int
    forbidden_snippet_count: int
    error: str


class StartCardGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_start_card_passed: bool
    missing_status_line_blocked: bool
    missing_command_line_blocked: bool
    missing_required_file_line_blocked: bool
    copied_bad_missing_file_count_blocked: bool
    copied_nonzero_provider_count_blocked: bool
    missing_provider_zero_line_blocked: bool
    forbidden_path_snippet_blocked: bool
    forbidden_submit_path_blocked: bool
    probes: list[ProbeReport]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def build_probes(payload: JsonObject, markdown_text: str) -> tuple[Probe, ...]:
    first_file_line = f"- `{required_file_names(payload)[0]}`"
    return (
        Probe("current_start_card", payload, markdown_text),
        Probe("missing_status_line", payload, without_line(markdown_text, "- status: `")),
        Probe("missing_command_line", payload, without_line(markdown_text, "verify_ocr_training_pack_recognized_evidence_handoff_runner.py")),
        Probe("missing_required_file_line", payload, without_line(markdown_text, first_file_line)),
        Probe("copied_bad_missing_file_count", copied_payload_with(payload, "missing_file_count", 3), markdown_text),
        Probe("copied_nonzero_provider_count", copied_payload_with(payload, "provider_call_count", 1), markdown_text),
        Probe("missing_provider_zero_line", payload, without_line(markdown_text, "- provider_call_count: `0`")),
        Probe("forbidden_path_snippet", payload, f"{markdown_text}\nC:/server synthetic probe\n"),
        Probe("forbidden_submit_path", payload, f"{markdown_text}\n/api/submit-test synthetic probe\n"),
    )


def copied_payload_with(payload: JsonObject, key: str, value: JsonValue) -> JsonObject:
    copied = {item_key: item_value for item_key, item_value in payload.items()}
    copied[key] = value
    return copied


def without_line(text: str, snippet: str) -> str:
    return "\n".join(line for line in text.splitlines() if snippet not in line)


def required_file_names(payload: JsonObject) -> tuple[str, ...]:
    files = payload.get("required_files")
    match files:
        case list():
            names: list[str] = []
            for item in files:
                match item:
                    case dict():
                        names.append(str_field(item, "required_file_name"))
                    case None | bool() | int() | float() | str() | list():
                        raise ExtendedGateError("start_card.required_files contains a non-object item")
                    case unreachable:
                        assert_never(unreachable)
            return tuple(names)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("start_card.required_files must be a list")
        case unreachable:
            assert_never(unreachable)


def run_probe(probe: Probe) -> ProbeReport:
    try:
        missing, forbidden = evaluate_payload_and_markdown(probe.payload, probe.markdown_text)
    except ExtendedGateError as exc:
        return {
            "name": probe.name,
            "ok": False,
            "blocked": True,
            "missing_snippet_count": -1,
            "forbidden_snippet_count": -1,
            "error": str(exc),
        }
    ok = not missing and not forbidden
    return {
        "name": probe.name,
        "ok": ok,
        "blocked": not ok,
        "missing_snippet_count": len(missing),
        "forbidden_snippet_count": len(forbidden),
        "error": "",
    }


def evaluate_payload_and_markdown(payload: JsonObject, markdown_text: str) -> tuple[list[str], list[str]]:
    assert_common_safety("start_card", payload)
    require_bool_value(payload.get("ok"), True, "start_card.ok")
    require_bool_value(payload.get("student_facing"), False, "start_card.student_facing")
    require_text_value(payload.get("status"), "TRAINING_PACK_RECOGNIZED_EVIDENCE_START_CARD_READY", "start_card.status")
    require_text_value(payload.get("current_blocker"), "training_pack_recognized_evidence_files_missing", "start_card.current_blocker")
    require_text_value(payload.get("next_action"), "copy_four_contract_valid_training_pack_recognized_evidence_files", "start_card.next_action")
    require_int_value(payload.get("required_file_count"), 4, "start_card.required_file_count")
    require_int_value(payload.get("missing_file_count"), 4, "start_card.missing_file_count")
    require_int_value(payload.get("card_missing_snippet_count"), 0, "start_card.card_missing_snippet_count")
    require_int_value(payload.get("card_forbidden_snippet_count"), 0, "start_card.card_forbidden_snippet_count")
    require_text_value(payload.get("production_default"), "NO_GO", "start_card.production_default")
    file_names = required_file_names(payload)
    if len(file_names) != 4:
        raise ExtendedGateError("start_card.required_files must contain exactly four files")
    required = required_snippets(payload, file_names)
    missing = [snippet for snippet in required if snippet not in markdown_text]
    forbidden = [snippet for snippet in start_card.FORBIDDEN_SNIPPETS if snippet in markdown_text]
    return missing, forbidden


def required_snippets(payload: JsonObject, file_names: tuple[str, ...]) -> tuple[str, ...]:
    file_snippets = tuple(f"`{file_name}`" for file_name in file_names)
    return (
        "# OCR Training Pack Recognized Evidence Start Here",
        f"- status: `{str_field(payload, 'status')}`",
        f"- current_blocker: `{str_field(payload, 'current_blocker')}`",
        f"- next_action: `{str_field(payload, 'next_action')}`",
        f"- required_file_count: `{int_field(payload, 'required_file_count')}`",
        f"- missing_file_count: `{int_field(payload, 'missing_file_count')}`",
        "- provider_call_count: `0`",
        "- external_ocr_api_call_count: `0`",
        "- submit_test_call_count: `0`",
        "- ts_submit_click_count: `0`",
        "- production_default: `NO_GO`",
        "python tools/subjective_sheet_lab/verify_ocr_training_pack_recognized_evidence_handoff_runner.py",
        *file_snippets,
    )


def build_guard_report(probe_reports: list[ProbeReport]) -> StartCardGuardReport:
    failed_probe_count = sum(1 for probe in probe_reports if not expected_probe_result(probe))
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": OK_STATUS if ok else FAILED_STATUS,
        "probe_count": len(probe_reports),
        "failed_probe_count": failed_probe_count,
        "live_start_card_passed": probe_state(probe_reports, "current_start_card", False),
        "missing_status_line_blocked": probe_state(probe_reports, "missing_status_line", True),
        "missing_command_line_blocked": probe_state(probe_reports, "missing_command_line", True),
        "missing_required_file_line_blocked": probe_state(probe_reports, "missing_required_file_line", True),
        "copied_bad_missing_file_count_blocked": probe_state(probe_reports, "copied_bad_missing_file_count", True),
        "copied_nonzero_provider_count_blocked": probe_state(probe_reports, "copied_nonzero_provider_count", True),
        "missing_provider_zero_line_blocked": probe_state(probe_reports, "missing_provider_zero_line", True),
        "forbidden_path_snippet_blocked": probe_state(probe_reports, "forbidden_path_snippet", True),
        "forbidden_submit_path_blocked": probe_state(probe_reports, "forbidden_submit_path", True),
        "probes": probe_reports,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def expected_probe_result(probe: ProbeReport) -> bool:
    if probe["name"] == "current_start_card":
        return probe["ok"] and not probe["blocked"]
    return probe["blocked"] and not probe["ok"]


def probe_state(probe_reports: list[ProbeReport], name: str, blocked: bool) -> bool:
    matches = [probe for probe in probe_reports if probe["name"] == name]
    return bool(matches) and matches[0]["ok"] is (not blocked) and matches[0]["blocked"] is blocked


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this guard with the Training Pack recognized evidence start card."
    return "Fix the Training Pack recognized evidence start card before operator handoff."
