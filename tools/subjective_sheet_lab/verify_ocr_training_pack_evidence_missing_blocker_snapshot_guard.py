# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_evidence_missing_blocker_snapshot_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    read_json_object,
    require_bool_value,
    require_int_value,
    require_text_value,
)
from verify_ocr_training_pack_evidence_missing_blocker_snapshot import (
    REPORT_JSON as SNAPSHOT_JSON,
)
from verify_ocr_training_pack_evidence_missing_blocker_snapshot import main as verify_snapshot
from verify_ocr_training_pack_evidence_missing_blocker_snapshot import require_snapshot

LAB: Final[Path] = Path(__file__).resolve().parent
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_evidence_missing_blocker_snapshot_guard.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_evidence_missing_blocker_snapshot_guard.md"


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    payload: JsonObject
    expected_blocked: bool


class ProbeReport(TypedDict):
    name: str
    blocked: bool
    ok: bool
    error_message: str


class GuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    live_snapshot_passed: bool
    ready_now_true_blocked: bool
    ready_after_files_false_blocked: bool
    zero_missing_files_blocked: bool
    payload_parse_before_smoke_blocked: bool
    weakened_arrival_sequence_blocked: bool
    weakened_authorization_blocked: bool
    nonzero_provider_count_blocked: bool
    production_default_enable_blocked: bool
    probes: list[ProbeReport]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    verify_snapshot()
    snapshot = read_json_object(SNAPSHOT_JSON)
    report = build_report(snapshot)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(snapshot: JsonObject) -> GuardReport:
    probe_specs = probes(snapshot)
    probe_reports = [run_probe(probe) for probe in probe_specs]
    failed_probe_count = sum(
        1
        for probe, result in zip(probe_specs, probe_reports, strict=True)
        if result["blocked"] is not probe.expected_blocked
    )
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_GUARD_VERIFIED"
        if ok
        else "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_GUARD_FAILED",
        "probe_count": len(probe_reports),
        "failed_probe_count": failed_probe_count,
        "live_snapshot_passed": probe_passed(probe_reports, "live_snapshot"),
        "ready_now_true_blocked": probe_blocked(probe_reports, "ready_now_true"),
        "ready_after_files_false_blocked": probe_blocked(probe_reports, "ready_after_files_false"),
        "zero_missing_files_blocked": probe_blocked(probe_reports, "zero_missing_files"),
        "payload_parse_before_smoke_blocked": probe_blocked(probe_reports, "payload_parse_before_smoke"),
        "weakened_arrival_sequence_blocked": probe_blocked(probe_reports, "weakened_arrival_sequence"),
        "weakened_authorization_blocked": probe_blocked(probe_reports, "weakened_authorization"),
        "nonzero_provider_count_blocked": probe_blocked(probe_reports, "nonzero_provider_count"),
        "production_default_enable_blocked": probe_blocked(probe_reports, "production_default_enable"),
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


def probes(snapshot: JsonObject) -> tuple[Probe, ...]:
    return (
        Probe("live_snapshot", snapshot, False),
        Probe("ready_now_true", with_field(snapshot, "ready_now", True), True),
        Probe("ready_after_files_false", with_field(snapshot, "ready_after_required_files", False), True),
        Probe("zero_missing_files", with_field(snapshot, "missing_file_count", 0), True),
        Probe("payload_parse_before_smoke", with_field(snapshot, "payload_parse_before_arrival_smoke_allowed", True), True),
        Probe(
            "weakened_arrival_sequence",
            with_field(snapshot, "allowed_after_files_arrive", "payload_parse_only"),
            True,
        ),
        Probe("weakened_authorization", with_field(snapshot, "blocked_without_separate_authorization", ""), True),
        Probe("nonzero_provider_count", with_field(snapshot, "provider_call_count", 1), True),
        Probe("production_default_enable", with_field(snapshot, "production_default", "GO"), True),
    )


def with_field(source: JsonObject, field: str, value: JsonValue) -> JsonObject:
    copied: JsonObject = dict(source)
    copied[field] = value
    return copied


def run_probe(probe: Probe) -> ProbeReport:
    try:
        require_guard_invariants(probe.payload)
    except ExtendedGateError as error:
        return {"name": probe.name, "blocked": True, "ok": False, "error_message": str(error)}
    return {"name": probe.name, "blocked": False, "ok": True, "error_message": ""}


def require_guard_invariants(report: JsonObject) -> None:
    require_text_value(
        report.get("status"),
        "TRAINING_PACK_EVIDENCE_MISSING_BLOCKER_SNAPSHOT_READY",
        "missing_blocker.status",
    )
    require_bool_value(report.get("ok"), True, "missing_blocker.ok")
    require_bool_value(report.get("student_facing"), False, "missing_blocker.student_facing")
    require_snapshot(report)
    require_text_value(
        report.get("allowed_after_files_arrive"),
        "smoke_then_blank_rejection_then_contract_validate_then_intake_replay_only",
        "missing_blocker.allowed_after_files_arrive",
    )
    require_text_value(
        report.get("blocked_without_separate_authorization"),
        "promotion_replacement_accuracy_recompute_or_runtime_write",
        "missing_blocker.blocked_without_separate_authorization",
    )
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(report.get(key), 0, f"missing_blocker.{key}")
    require_int_value(
        report.get("answer_key_or_grading_field_leak_count"),
        0,
        "missing_blocker.answer_key_or_grading_field_leak_count",
    )
    require_int_value(report.get("filesystem_path_leak_count"), 0, "missing_blocker.filesystem_path_leak_count")
    require_text_value(report.get("production_default"), "NO_GO", "missing_blocker.production_default")


def probe_passed(probe_reports: list[ProbeReport], name: str) -> bool:
    for probe in probe_reports:
        if probe["name"] == name:
            return probe["ok"] and not probe["blocked"]
    return False


def probe_blocked(probe_reports: list[ProbeReport], name: str) -> bool:
    for probe in probe_reports:
        if probe["name"] == name:
            return probe["blocked"]
    return False


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep training-pack recognized evidence blocked until the four target-named files arrive."
    return "Fix missing-evidence blocker invariants before treating Training Pack evidence as ready."


def markdown(report: GuardReport) -> str:
    probe_lines = [
        f"- {probe['name']}: blocked `{probe['blocked']}`, ok `{probe['ok']}`, error `{probe['error_message']}`"
        for probe in report["probes"]
    ]
    return "\n".join(
        (
            "# OCR Training Pack Evidence Missing Blocker Guard",
            "",
            f"- ok: `{report['ok']}`",
            f"- student_facing: `{report['student_facing']}`",
            f"- status: `{report['status']}`",
            f"- probe_count: `{report['probe_count']}`",
            f"- failed_probe_count: `{report['failed_probe_count']}`",
            f"- live_snapshot_passed: `{report['live_snapshot_passed']}`",
            f"- ready_now_true_blocked: `{report['ready_now_true_blocked']}`",
            f"- ready_after_files_false_blocked: `{report['ready_after_files_false_blocked']}`",
            f"- zero_missing_files_blocked: `{report['zero_missing_files_blocked']}`",
            f"- payload_parse_before_smoke_blocked: `{report['payload_parse_before_smoke_blocked']}`",
            f"- weakened_arrival_sequence_blocked: `{report['weakened_arrival_sequence_blocked']}`",
            f"- weakened_authorization_blocked: `{report['weakened_authorization_blocked']}`",
            f"- nonzero_provider_count_blocked: `{report['nonzero_provider_count_blocked']}`",
            f"- production_default_enable_blocked: `{report['production_default_enable_blocked']}`",
            "- provider_call_count: `0`",
            "- external_ocr_api_call_count: `0`",
            "- submit_test_call_count: `0`",
            "- ts_submit_click_count: `0`",
            "- answer_key_or_grading_field_leak_count: `0`",
            "- filesystem_path_leak_count: `0`",
            "- production_default: `NO_GO`",
            "",
            "## Probes",
            *probe_lines,
            "",
            "## Next Safe Action",
            report["next_safe_action"],
            "",
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
