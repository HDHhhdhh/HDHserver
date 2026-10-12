# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_intake_only_command_checklist_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    read_json_object,
    require_int,
    require_object,
)
from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_intake_commands import (
    BLANK_EVIDENCE_COMMAND_STEP,
    require_training_pack_intake_only_command_checklist,
)
from verify_ocr_training_pack_intake_only_command_checklist import REPORT_JSON as COMMAND_CHECKLIST_JSON

REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_intake_only_command_checklist_guard.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_intake_only_command_checklist_guard.md"


class ProbeReport(TypedDict):
    name: str
    blocked: bool
    ok: bool
    error_message: str


class ChecklistGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    current_checklist_passed: bool
    missing_blank_evidence_command_blocked: bool
    live_checklist_write_attempted: bool
    probes: list[ProbeReport]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    checklist: JsonObject


def main() -> int:
    before_mtime = COMMAND_CHECKLIST_JSON.stat().st_mtime_ns
    live_checklist = read_json_object(COMMAND_CHECKLIST_JSON)
    report = build_report(live_checklist, before_mtime)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(live_checklist: JsonObject, before_mtime: int) -> ChecklistGuardReport:
    probe_reports = [run_probe(probe) for probe in probes(live_checklist)]
    current_passed = probe_reports[0]["ok"] and not probe_reports[0]["blocked"]
    missing_blank_blocked = probe_reports[1]["blocked"]
    write_attempted = COMMAND_CHECKLIST_JSON.stat().st_mtime_ns != before_mtime
    failed_probe_count = sum(1 for probe in probe_reports if not expected_probe_outcome(probe))
    ok = failed_probe_count == 0 and not write_attempted
    return {
        "ok": ok,
        "student_facing": False,
        "status": "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_GUARD_VERIFIED"
        if ok
        else "TRAINING_PACK_INTAKE_ONLY_COMMAND_CHECKLIST_GUARD_FAILED",
        "probe_count": len(probe_reports),
        "failed_probe_count": failed_probe_count,
        "current_checklist_passed": current_passed,
        "missing_blank_evidence_command_blocked": missing_blank_blocked,
        "live_checklist_write_attempted": write_attempted,
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


def probes(live_checklist: JsonObject) -> tuple[Probe, ...]:
    return (
        Probe("current_checklist", live_checklist),
        Probe("missing_blank_evidence_command", checklist_without_blank_command(live_checklist)),
    )


def checklist_without_blank_command(checklist: JsonObject) -> JsonObject:
    copied: JsonObject = dict(checklist)
    commands: list[JsonValue] = [
        command for command in command_rows(checklist.get("commands")) if command_step(command) != BLANK_EVIDENCE_COMMAND_STEP
    ]
    copied["commands"] = commands
    return copied


def command_rows(value: JsonValue) -> tuple[JsonObject, ...]:
    match value:
        case list() as rows:
            return tuple(require_object(row, "commands[]") for row in rows)
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("commands must be a list")
        case unreachable:
            assert_never(unreachable)


def command_step(command: JsonObject) -> int:
    return require_int(command.get("step_no"), "commands[].step_no")


def run_probe(probe: Probe) -> ProbeReport:
    try:
        require_training_pack_intake_only_command_checklist(probe.checklist)
    except ExtendedGateError as error:
        return {
            "name": probe.name,
            "blocked": True,
            "ok": False,
            "error_message": str(error),
        }
    return {
        "name": probe.name,
        "blocked": False,
        "ok": True,
        "error_message": "",
    }


def expected_probe_outcome(probe: ProbeReport) -> bool:
    if probe["name"] == "current_checklist":
        return probe["ok"] and not probe["blocked"]
    return probe["blocked"]


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this guard in the provider-free chain before training-pack evidence promotion."
    return "Restore the blank-evidence rejection command before any training-pack evidence promotion."


def markdown(report: ChecklistGuardReport) -> str:
    probe_lines = [
        f"- {probe['name']}: blocked `{probe['blocked']}`, ok `{probe['ok']}`, error `{probe['error_message']}`"
        for probe in report["probes"]
    ]
    return "\n".join((
        "# OCR Training Pack Intake-Only Command Checklist Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- current_checklist_passed: `{report['current_checklist_passed']}`",
        f"- missing_blank_evidence_command_blocked: `{report['missing_blank_evidence_command_blocked']}`",
        f"- live_checklist_write_attempted: `{report['live_checklist_write_attempted']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Probes",
        *probe_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
