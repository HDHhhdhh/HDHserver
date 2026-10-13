# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_operator_summary.py

from __future__ import annotations

import json
import contextlib
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_provider_free_extended_gate_common import (
    JsonObject,
    assert_common_safety,
    read_json_object,
    require_int_value,
    require_text_value,
)
from ocr_preflight_environment_matrix_model import LAB
from ocr_qa_start_here_core import EXPECTED_CHAIN_STEP_COUNT
from verify_ocr_post_chain_cleanup_candidate_manifest import REPORT_JSON_OUT as CLEANUP_JSON
from verify_ocr_post_chain_cleanup_candidate_manifest import main as cleanup_main
from verify_ocr_post_chain_cleanup_candidate_manifest_guard import REPORT_JSON_OUT as CLEANUP_GUARD_JSON
from verify_ocr_post_chain_cleanup_candidate_manifest_guard import main as cleanup_guard_main
from verify_ocr_post_chain_guard_manifest import REPORT_JSON_OUT as MANIFEST_JSON
from verify_ocr_post_chain_guard_manifest import main as manifest_main
from verify_ocr_post_chain_guard_manifest_guard import REPORT_JSON_OUT as MANIFEST_GUARD_JSON
from verify_ocr_post_chain_guard_manifest_guard import main as manifest_guard_main
from verify_ocr_provider_free_gate_chain import REPORT_JSON_OUT as CHAIN_JSON
from verify_ocr_provider_free_gate_chain_rendered_steps import REPORT_JSON_OUT as RENDERED_STEPS_JSON
from verify_ocr_provider_free_gate_chain_rendered_steps import main as rendered_steps_main
from verify_ocr_provider_free_gate_chain_rendered_steps_guard import (
    REPORT_JSON_OUT as RENDERED_STEPS_GUARD_JSON,
)
from verify_ocr_provider_free_gate_chain_rendered_steps_guard import main as rendered_steps_guard_main

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_operator_summary.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_operator_summary.md"
RefreshRunner = Callable[[], int]


class PostChainCommandRow(TypedDict):
    order: int
    label: str
    command: str
    report_path: str


class PostChainReportRow(TypedDict):
    label: str
    report_path: str
    status: str
    newer_than_chain: bool


class PostChainOperatorSummaryReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    ordered_command_count: int
    ordered_commands: list[PostChainCommandRow]
    report_count: int
    stale_report_count: int
    stale_reports: list[str]
    reports: list[PostChainReportRow]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class ReportSpec:
    label: str
    command: str
    path: Path
    expected_status: str


REPORT_SPECS: Final[tuple[ReportSpec, ...]] = (
    ReportSpec(
        "rendered_steps",
        "python tools/subjective_sheet_lab/verify_ocr_provider_free_gate_chain_rendered_steps.py",
        RENDERED_STEPS_JSON,
        "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_VERIFIED",
    ),
    ReportSpec(
        "rendered_steps_guard",
        "python tools/subjective_sheet_lab/verify_ocr_provider_free_gate_chain_rendered_steps_guard.py",
        RENDERED_STEPS_GUARD_JSON,
        "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_GUARD_VERIFIED",
    ),
    ReportSpec(
        "post_chain_guard_manifest",
        "python tools/subjective_sheet_lab/verify_ocr_post_chain_guard_manifest.py",
        MANIFEST_JSON,
        "OCR_POST_CHAIN_GUARD_MANIFEST_VERIFIED",
    ),
    ReportSpec(
        "post_chain_guard_manifest_guard",
        "python tools/subjective_sheet_lab/verify_ocr_post_chain_guard_manifest_guard.py",
        MANIFEST_GUARD_JSON,
        "OCR_POST_CHAIN_GUARD_MANIFEST_GUARD_VERIFIED",
    ),
    ReportSpec(
        "post_chain_cleanup_candidate_manifest",
        "python tools/subjective_sheet_lab/verify_ocr_post_chain_cleanup_candidate_manifest.py",
        CLEANUP_JSON,
        "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_VERIFIED",
    ),
    ReportSpec(
        "post_chain_cleanup_candidate_manifest_guard",
        "python tools/subjective_sheet_lab/verify_ocr_post_chain_cleanup_candidate_manifest_guard.py",
        CLEANUP_GUARD_JSON,
        "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_GUARD_VERIFIED",
    ),
)


def main() -> int:
    refresh_dependency_reports()
    chain_report = read_json_object(CHAIN_JSON)
    report_payloads = tuple(read_json_object(spec.path) for spec in REPORT_SPECS)
    report = build_report(chain_report, report_payloads)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def refresh_dependency_reports() -> None:
    for label, runner in (
        ("rendered_steps", rendered_steps_main),
        ("rendered_steps_guard", rendered_steps_guard_main),
        ("post_chain_guard_manifest", manifest_main),
        ("post_chain_guard_manifest_guard", manifest_guard_main),
        ("post_chain_cleanup_candidate_manifest", cleanup_main),
        ("post_chain_cleanup_candidate_manifest_guard", cleanup_guard_main),
    ):
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = runner()
        if exit_code != 0:
            raise SystemExit(f"{label} refresh failed with exit code {exit_code}")


def build_report(
    chain_report: JsonObject,
    report_payloads: tuple[JsonObject, ...],
) -> PostChainOperatorSummaryReport:
    assert_chain_report(chain_report)
    chain_modified_ns = CHAIN_JSON.stat().st_mtime_ns
    report_rows = [report_row(spec, payload, chain_modified_ns) for spec, payload in zip(REPORT_SPECS, report_payloads, strict=True)]
    stale_reports = [row["label"] for row in report_rows if not row["newer_than_chain"]]
    ok = not stale_reports
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_OPERATOR_SUMMARY_VERIFIED" if ok else "OCR_POST_CHAIN_OPERATOR_SUMMARY_STALE",
        "ordered_command_count": len(REPORT_SPECS) + 1,
        "ordered_commands": ordered_commands(),
        "report_count": len(report_rows),
        "stale_report_count": len(stale_reports),
        "stale_reports": stale_reports,
        "reports": report_rows,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def assert_chain_report(report: JsonObject) -> None:
    assert_common_safety("chain", report)
    require_int_value(report.get("chain_step_count"), EXPECTED_CHAIN_STEP_COUNT, "chain.chain_step_count")
    require_int_value(report.get("failed_step_count"), 0, "chain.failed_step_count")
    require_int_value(report.get("issue_count"), 0, "chain.issue_count")
    require_text_value(report.get("production_default"), "NO_GO", "chain.production_default")


def report_row(spec: ReportSpec, payload: JsonObject, chain_modified_ns: int) -> PostChainReportRow:
    assert_common_safety(spec.label, payload)
    require_text_value(payload.get("status"), spec.expected_status, f"{spec.label}.status")
    modified_ns = spec.path.stat().st_mtime_ns
    return {
        "label": spec.label,
        "report_path": display_path(spec.path),
        "status": spec.expected_status,
        "newer_than_chain": modified_ns >= chain_modified_ns,
    }


def ordered_commands() -> list[PostChainCommandRow]:
    return [
        {
            "order": order,
            "label": spec.label,
            "command": spec.command,
            "report_path": display_path(spec.path),
        }
        for order, spec in enumerate(REPORT_SPECS, start=1)
    ] + [
        {
            "order": len(REPORT_SPECS) + 1,
            "label": "post_chain_operator_summary",
            "command": "python tools/subjective_sheet_lab/verify_ocr_post_chain_operator_summary.py",
            "report_path": display_path(REPORT_JSON_OUT),
        },
    ]


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Run this summary after the post-chain manifest guard whenever the provider-free chain is refreshed."
    return "Rerun the ordered post-chain command sequence after refreshing the provider-free chain."


def markdown(report: PostChainOperatorSummaryReport) -> str:
    command_lines = [
        f"- {row['order']}. `{row['command']}` -> `{row['report_path']}`"
        for row in report["ordered_commands"]
    ]
    report_lines = [
        f"- {row['label']}: `{row['status']}`, newer_than_chain `{row['newer_than_chain']}`"
        for row in report["reports"]
    ]
    stale_lines = [f"- {label}" for label in report["stale_reports"]] or ["- none"]
    return "\n".join((
        "# OCR Post-Chain Operator Summary",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- ordered_command_count: `{report['ordered_command_count']}`",
        f"- report_count: `{report['report_count']}`",
        f"- stale_report_count: `{report['stale_report_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Ordered Commands",
        *command_lines,
        "",
        "## Report Freshness",
        *report_lines,
        "",
        "## Stale Reports",
        *stale_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
