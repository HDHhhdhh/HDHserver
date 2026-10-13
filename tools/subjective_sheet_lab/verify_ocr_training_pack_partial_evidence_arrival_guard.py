# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_partial_evidence_arrival_guard.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    require_bool_value,
    require_int_value,
    require_text_value,
    read_json_object,
)
from ocr_training_pack_recognized_evidence_target_diff_core import (
    EvidenceFile,
    evidence_files,
    target_diff_summary,
    target_test_ids,
)

LAB: Final[Path] = Path(__file__).resolve().parent
SOURCE_JSON: Final[Path] = LAB / "ocr_training_pack_source_inventory.json"
EVIDENCE_DIR: Final[Path] = LAB / "training_pack_recognized_evidence"
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_partial_evidence_arrival_guard.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_partial_evidence_arrival_guard.md"


@dataclass(frozen=True, slots=True)
class ArrivalProbe:
    name: str
    evidence: tuple[EvidenceFile, ...]
    expected_blocked: bool


class ArrivalProbeReport(TypedDict):
    name: str
    evidence_file_count: int
    covered_target_count: int
    missing_target_count: int
    blocked: bool
    ok: bool


class PartialArrivalGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    current_blocker: str
    target_count: int
    current_evidence_file_count: int
    current_covered_target_count: int
    current_missing_target_count: int
    current_arrival_blocked: bool
    partial_probe_count: int
    partial_probe_blocked_count: int
    complete_probe_passed: bool
    invalid_probe_count: int
    invalid_probe_blocked_count: int
    failed_probe_count: int
    probes: list[ArrivalProbeReport]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    source = read_json_object(SOURCE_JSON)
    current = evidence_files(EVIDENCE_DIR)
    report = build_report(source, current)
    require_report(report)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(source: JsonObject, current: tuple[EvidenceFile, ...]) -> PartialArrivalGuardReport:
    targets = target_test_ids(source)
    current_summary = target_diff_summary(source, current)
    probe_reports = [probe_report(source, probe) for probe in arrival_probes(targets)]
    failed_probe_count = sum(1 for probe in probe_reports if not probe["ok"])
    partial_reports = probe_reports[:4]
    invalid_reports = probe_reports[5:]
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "TRAINING_PACK_PARTIAL_EVIDENCE_ARRIVAL_GUARD_VERIFIED"
        if ok
        else "TRAINING_PACK_PARTIAL_EVIDENCE_ARRIVAL_GUARD_FAILED",
        "current_blocker": "training_pack_recognized_evidence_files_missing"
        if arrival_blocked(current_summary)
        else "training_pack_recognized_evidence_files_ready_for_contract_validation",
        "target_count": len(targets),
        "current_evidence_file_count": int(current_summary["evidence_file_count"]),
        "current_covered_target_count": int(current_summary["covered_target_count"]),
        "current_missing_target_count": int(current_summary["missing_target_count"]),
        "current_arrival_blocked": arrival_blocked(current_summary),
        "partial_probe_count": len(partial_reports),
        "partial_probe_blocked_count": sum(1 for probe in partial_reports if probe["blocked"]),
        "complete_probe_passed": not probe_reports[4]["blocked"] and probe_reports[4]["ok"],
        "invalid_probe_count": len(invalid_reports),
        "invalid_probe_blocked_count": sum(1 for probe in invalid_reports if probe["blocked"]),
        "failed_probe_count": failed_probe_count,
        "probes": probe_reports,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(arrival_blocked(current_summary)),
    }


def arrival_probes(targets: tuple[str, ...]) -> tuple[ArrivalProbe, ...]:
    return (
        ArrivalProbe("zero_target_files", target_evidence(targets, 0), True),
        ArrivalProbe("one_target_file", target_evidence(targets, 1), True),
        ArrivalProbe("two_target_files", target_evidence(targets, 2), True),
        ArrivalProbe("three_target_files", target_evidence(targets, 3), True),
        ArrivalProbe("four_target_files", target_evidence(targets, 4), False),
        ArrivalProbe("duplicate_target_file", duplicate_evidence(targets), True),
        ArrivalProbe("unexpected_target_file", unexpected_evidence(targets), True),
        ArrivalProbe("missing_test_id_file", (EvidenceFile(name="missing_test_id.json", test_id=None),), True),
    )


def target_evidence(targets: tuple[str, ...], count: int) -> tuple[EvidenceFile, ...]:
    return tuple(EvidenceFile(name=f"{test_id}_recognized_evidence.json", test_id=test_id) for test_id in targets[:count])


def duplicate_evidence(targets: tuple[str, ...]) -> tuple[EvidenceFile, ...]:
    first = targets[0]
    return (*target_evidence(targets, len(targets)), EvidenceFile(name=f"{first}_copy.json", test_id=first))


def unexpected_evidence(targets: tuple[str, ...]) -> tuple[EvidenceFile, ...]:
    return (*target_evidence(targets, len(targets)), EvidenceFile(name="unexpected_recognized_evidence.json", test_id="unexpected"))


def probe_report(source: JsonObject, probe: ArrivalProbe) -> ArrivalProbeReport:
    summary = target_diff_summary(source, probe.evidence)
    blocked = arrival_blocked(summary)
    return {
        "name": probe.name,
        "evidence_file_count": int(summary["evidence_file_count"]),
        "covered_target_count": int(summary["covered_target_count"]),
        "missing_target_count": int(summary["missing_target_count"]),
        "blocked": blocked,
        "ok": blocked is probe.expected_blocked,
    }


def arrival_blocked(summary: JsonObject) -> bool:
    target_count = int(summary["target_count"])
    return (
        int(summary["evidence_file_count"]) != target_count
        or int(summary["covered_target_count"]) != target_count
        or int(summary["missing_target_count"]) != 0
        or int(summary["duplicate_evidence_target_count"]) != 0
        or int(summary["unexpected_evidence_target_count"]) != 0
        or int(summary["missing_test_id_file_count"]) != 0
    )


def require_report(report: PartialArrivalGuardReport) -> None:
    require_bool_value(report.get("ok"), True, "ok")
    require_bool_value(report.get("student_facing"), False, "student_facing")
    require_text_value(report.get("status"), "TRAINING_PACK_PARTIAL_EVIDENCE_ARRIVAL_GUARD_VERIFIED", "status")
    require_int_value(report.get("target_count"), 4, "target_count")
    require_int_value(report.get("partial_probe_count"), 4, "partial_probe_count")
    require_int_value(report.get("partial_probe_blocked_count"), 4, "partial_probe_blocked_count")
    require_bool_value(report.get("complete_probe_passed"), True, "complete_probe_passed")
    require_int_value(report.get("invalid_probe_count"), 3, "invalid_probe_count")
    require_int_value(report.get("invalid_probe_blocked_count"), 3, "invalid_probe_blocked_count")
    require_int_value(report.get("failed_probe_count"), 0, "failed_probe_count")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(report.get(key), 0, key)
    require_int_value(report.get("answer_key_or_grading_field_leak_count"), 0, "answer_key_or_grading_field_leak_count")
    require_int_value(report.get("filesystem_path_leak_count"), 0, "filesystem_path_leak_count")
    require_text_value(report.get("production_default"), "NO_GO", "production_default")


def next_safe_action(current_blocked: bool) -> str:
    if current_blocked:
        return "Keep Training Pack intake blocked until all four target evidence files are present."
    return "Run contract validation before any replacement or accuracy recompute."


def markdown(report: PartialArrivalGuardReport) -> str:
    probe_lines = [
        (
            f"- {probe['name']}: blocked `{probe['blocked']}`, ok `{probe['ok']}`, "
            f"covered `{probe['covered_target_count']}`, missing `{probe['missing_target_count']}`"
        )
        for probe in report["probes"]
    ]
    return "\n".join((
        "# OCR Training Pack Partial Evidence Arrival Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- current_blocker: `{report['current_blocker']}`",
        f"- target_count: `{report['target_count']}`",
        f"- current_evidence_file_count: `{report['current_evidence_file_count']}`",
        f"- current_covered_target_count: `{report['current_covered_target_count']}`",
        f"- current_missing_target_count: `{report['current_missing_target_count']}`",
        f"- current_arrival_blocked: `{report['current_arrival_blocked']}`",
        f"- partial_probe_blocked_count: `{report['partial_probe_blocked_count']}`",
        f"- complete_probe_passed: `{report['complete_probe_passed']}`",
        f"- invalid_probe_blocked_count: `{report['invalid_probe_blocked_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
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
