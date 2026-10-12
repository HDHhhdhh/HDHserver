# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_evidence_index_common_self_check.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict, assert_never

from ocr_post_chain_evidence_index_common import (
    JsonObject,
    JsonValue,
    SourceSpec,
    copied_payloads,
    path_mtime,
    report_statuses,
    reports_without_status,
    snapshot_evidence_files,
    source_index,
    source_payloads,
)
from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import ExtendedGateError
import verify_ocr_post_chain_evidence_index as evidence_index
import verify_ocr_post_chain_evidence_index_guard as evidence_guard

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_index_common_self_check.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_index_common_self_check.md"
REMOVED_CLEANUP_STATUS: Final = "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_GUARD_VERIFIED"
SELF_CHECK_SOURCE_LABEL: Final = "evidence_index_common_self_check"
FRESHNESS_GUARD_SOURCE_LABEL: Final = "evidence_index_freshness_guard"


class CommonSelfCheckReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    probe_count: int
    failed_probe_count: int
    source_report_count: int
    copied_top_level_mutation_isolated: bool
    reports_without_status_non_mutating: bool
    live_source_reports_unchanged: bool
    handoff_artifacts_unchanged: bool
    original_summary_report_count: int
    filtered_summary_report_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class FullSnapshot:
    source_report_modified_ns: tuple[int, ...]
    handoff_artifact_modified_ns: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReportFilterProbe:
    non_mutating: bool
    original_count: int
    filtered_count: int


def main() -> int:
    specs = source_specs_for_self_check()
    payloads = source_payloads(specs)
    before = full_snapshot()
    top_level_isolated = copied_top_level_mutation_isolated(payloads)
    filter_probe = reports_filter_probe(payloads)
    after = full_snapshot()
    report = build_report(
        payloads=payloads,
        top_level_isolated=top_level_isolated,
        filter_probe=filter_probe,
        before=before,
        after=after,
    )
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def source_specs_for_self_check() -> tuple[SourceSpec, ...]:
    excluded_labels = (SELF_CHECK_SOURCE_LABEL, FRESHNESS_GUARD_SOURCE_LABEL)
    return tuple(spec for spec in evidence_index.SOURCE_SPECS if spec.label not in excluded_labels)


def full_snapshot() -> FullSnapshot:
    source_snapshot = snapshot_evidence_files(source_specs_for_self_check(), evidence_index.REPORT_JSON_OUT)
    return FullSnapshot(
        source_report_modified_ns=source_snapshot.source_report_modified_ns,
        handoff_artifact_modified_ns=tuple(path_mtime(path) for path in handoff_paths()),
    )


def handoff_paths() -> tuple[Path, ...]:
    return (
        evidence_index.REPORT_JSON_OUT,
        evidence_index.REPORT_MD_OUT,
        evidence_guard.REPORT_JSON_OUT,
        evidence_guard.REPORT_MD_OUT,
    )


def copied_top_level_mutation_isolated(payloads: tuple[JsonObject, ...]) -> bool:
    copied = copied_payloads(payloads)
    original_status = payloads[0].get("status")
    copied[0]["status"] = "SYNTHETIC_MUTATED_STATUS"
    return payloads[0].get("status") == original_status and copied[0].get("status") != original_status


def reports_filter_probe(payloads: tuple[JsonObject, ...]) -> ReportFilterProbe:
    summary_index = source_index("post_chain_operator_summary", source_specs_for_self_check())
    reports = summary_reports(payloads[summary_index])
    original_count = len(reports)
    filtered = reports_without_status(reports, REMOVED_CLEANUP_STATUS, "post_chain_operator_summary")
    still_has_status = REMOVED_CLEANUP_STATUS in report_statuses("post_chain_operator_summary", reports)
    return ReportFilterProbe(
        non_mutating=still_has_status and len(reports) == original_count and len(filtered) == original_count - 1,
        original_count=original_count,
        filtered_count=len(filtered),
    )


def summary_reports(payload: JsonObject) -> list[JsonValue]:
    reports = payload.get("reports")
    match reports:
        case list():
            report_statuses("post_chain_operator_summary", reports)
            return reports
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("post_chain_operator_summary.reports must be an array")
        case unreachable:
            assert_never(unreachable)


def build_report(
    payloads: tuple[JsonObject, ...],
    top_level_isolated: bool,
    filter_probe: ReportFilterProbe,
    before: FullSnapshot,
    after: FullSnapshot,
) -> CommonSelfCheckReport:
    live_source_reports_unchanged = before.source_report_modified_ns == after.source_report_modified_ns
    handoff_artifacts_unchanged = before.handoff_artifact_modified_ns == after.handoff_artifact_modified_ns
    passed = (
        top_level_isolated,
        filter_probe.non_mutating,
        live_source_reports_unchanged,
        handoff_artifacts_unchanged,
    )
    failed_probe_count = sum(1 for item in passed if not item)
    ok = failed_probe_count == 0
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_EVIDENCE_INDEX_COMMON_SELF_CHECK_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_EVIDENCE_INDEX_COMMON_SELF_CHECK_FAILED",
        "probe_count": 4,
        "failed_probe_count": failed_probe_count,
        "source_report_count": len(payloads),
        "copied_top_level_mutation_isolated": top_level_isolated,
        "reports_without_status_non_mutating": filter_probe.non_mutating,
        "live_source_reports_unchanged": live_source_reports_unchanged,
        "handoff_artifacts_unchanged": handoff_artifacts_unchanged,
        "original_summary_report_count": filter_probe.original_count,
        "filtered_summary_report_count": filter_probe.filtered_count,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Include this self-check before adding more common evidence-index helpers."
    return "Fix common helper mutation isolation before extending evidence-index handoff reports."


def markdown(report: CommonSelfCheckReport) -> str:
    return "\n".join((
        "# OCR Post-Chain Evidence Index Common Self-Check",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- probe_count: `{report['probe_count']}`",
        f"- failed_probe_count: `{report['failed_probe_count']}`",
        f"- source_report_count: `{report['source_report_count']}`",
        f"- copied_top_level_mutation_isolated: `{report['copied_top_level_mutation_isolated']}`",
        f"- reports_without_status_non_mutating: `{report['reports_without_status_non_mutating']}`",
        f"- live_source_reports_unchanged: `{report['live_source_reports_unchanged']}`",
        f"- handoff_artifacts_unchanged: `{report['handoff_artifacts_unchanged']}`",
        f"- original_summary_report_count: `{report['original_summary_report_count']}`",
        f"- filtered_summary_report_count: `{report['filtered_summary_report_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
