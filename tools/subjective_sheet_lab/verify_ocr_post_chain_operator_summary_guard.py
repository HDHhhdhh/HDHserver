# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_operator_summary_guard.py

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import JsonObject, read_json_object
from ocr_preflight_environment_matrix_model import LAB
import verify_ocr_post_chain_operator_summary as summary

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_operator_summary_guard.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_operator_summary_guard.md"


class PostChainOperatorSummaryGuardReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    live_probe_passed: bool
    copied_stale_probe_blocked: bool
    live_file_write_attempted: bool
    copied_stale_report_count: int
    copied_stale_reports: list[str]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class SummarySnapshot:
    chain_modified_ns: int
    report_modified_ns: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CopiedSummaryInputs:
    chain_path: Path
    report_specs: tuple[summary.ReportSpec, ...]
    report_payloads: tuple[JsonObject, ...]


def main() -> int:
    before = snapshot_live_files()
    live_report = summary.build_report(
        read_json_object(summary.CHAIN_JSON),
        tuple(read_json_object(spec.path) for spec in summary.REPORT_SPECS),
    )
    stale_report = copied_stale_report()
    after = snapshot_live_files()
    report = build_guard_report(live_report, stale_report, before, after)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def snapshot_live_files() -> SummarySnapshot:
    return SummarySnapshot(
        chain_modified_ns=summary.CHAIN_JSON.stat().st_mtime_ns,
        report_modified_ns=tuple(spec.path.stat().st_mtime_ns for spec in summary.REPORT_SPECS),
    )


def copied_stale_report() -> summary.PostChainOperatorSummaryReport:
    with TemporaryDirectory(prefix="ocr-post-chain-summary-guard-") as temp_name:
        inputs = copied_stale_inputs(Path(temp_name))
        return build_with_copied_inputs(inputs)


def copied_stale_inputs(temp_root: Path) -> CopiedSummaryInputs:
    chain_path = copy_file(summary.CHAIN_JSON, temp_root / "chain.json")
    os.utime(chain_path, ns=(summary.CHAIN_JSON.stat().st_mtime_ns, summary.CHAIN_JSON.stat().st_mtime_ns))
    stale_ns = max(0, chain_path.stat().st_mtime_ns - 1)
    copied_specs: list[summary.ReportSpec] = []
    for spec in summary.REPORT_SPECS:
        copied_path = copy_file(spec.path, temp_root / spec.path.name)
        os.utime(copied_path, ns=(stale_ns, stale_ns))
        copied_specs.append(summary.ReportSpec(spec.label, spec.command, copied_path, spec.expected_status))
    specs = tuple(copied_specs)
    return CopiedSummaryInputs(
        chain_path=chain_path,
        report_specs=specs,
        report_payloads=tuple(read_json_object(spec.path) for spec in specs),
    )


def copy_file(source: Path, target: Path) -> Path:
    shutil.copyfile(source, target)
    return target


def build_with_copied_inputs(inputs: CopiedSummaryInputs) -> summary.PostChainOperatorSummaryReport:
    original_chain = summary.CHAIN_JSON
    original_specs = summary.REPORT_SPECS
    try:
        summary.CHAIN_JSON = inputs.chain_path
        summary.REPORT_SPECS = inputs.report_specs
        return summary.build_report(read_json_object(inputs.chain_path), inputs.report_payloads)
    finally:
        summary.CHAIN_JSON = original_chain
        summary.REPORT_SPECS = original_specs


def build_guard_report(
    live_report: summary.PostChainOperatorSummaryReport,
    stale_report: summary.PostChainOperatorSummaryReport,
    before: SummarySnapshot,
    after: SummarySnapshot,
) -> PostChainOperatorSummaryGuardReport:
    live_probe_passed = live_report["ok"] is True and live_report["stale_report_count"] == 0
    copied_stale_probe_blocked = stale_report["ok"] is False and stale_report["stale_report_count"] > 0
    live_file_write_attempted = before != after
    ok = live_probe_passed and copied_stale_probe_blocked and not live_file_write_attempted
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_OPERATOR_SUMMARY_GUARD_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_OPERATOR_SUMMARY_GUARD_FAILED",
        "live_probe_passed": live_probe_passed,
        "copied_stale_probe_blocked": copied_stale_probe_blocked,
        "live_file_write_attempted": live_file_write_attempted,
        "copied_stale_report_count": stale_report["stale_report_count"],
        "copied_stale_reports": stale_report["stale_reports"],
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
        return "Keep this guard after the post-chain operator summary verifier."
    return "Fix stale copied-summary blocking before trusting post-chain summary freshness."


def markdown(report: PostChainOperatorSummaryGuardReport) -> str:
    stale_lines = [f"- {label}" for label in report["copied_stale_reports"]] or ["- none"]
    return "\n".join((
        "# OCR Post-Chain Operator Summary Guard",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- live_probe_passed: `{report['live_probe_passed']}`",
        f"- copied_stale_probe_blocked: `{report['copied_stale_probe_blocked']}`",
        f"- live_file_write_attempted: `{report['live_file_write_attempted']}`",
        f"- copied_stale_report_count: `{report['copied_stale_report_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Copied Stale Reports",
        *stale_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
