#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_handoff_command_checklist.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_command_checklist.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_handoff_command_checklist.md"
EXPECTED_COMMAND_COUNT: Final[int] = 16
STEP_CATALOG_GUARD_LABEL: Final[str] = "step_catalog_rendered_summary_guard"
HANDOFF_RUNNER_LABEL: Final[str] = "evidence_handoff_runner"
FORBIDDEN_COMMAND_SNIPPETS: Final[tuple[str, ...]] = (
    "/api/submit-test",
    "#tsSubmit",
    "GEMINI_API_KEY",
    "OCR_PHASE2E_GEMINI_LIVE_ENABLED=true",
)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    label: str
    command: str
    report_name: str


class CommandRow(TypedDict):
    order: int
    label: str
    command: str
    report_path: str


class HandoffCommandChecklistReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    ordered_command_count: int
    expected_command_count: int
    required_report_count: int
    missing_report_count: int
    missing_reports: list[str]
    step_catalog_guard_order: int
    evidence_handoff_runner_order: int
    step_catalog_guard_before_runner: bool
    forbidden_command_snippet_count: int
    forbidden_command_snippets: list[str]
    commands: list[CommandRow]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


COMMAND_SPECS: Final[tuple[CommandSpec, ...]] = (
    CommandSpec("retention_manifest", "python tools/subjective_sheet_lab/verify_ocr_post_chain_handoff_retention_manifest.py", "ocr_post_chain_handoff_retention_manifest.json"),
    CommandSpec("retention_manifest_guard", "python tools/subjective_sheet_lab/verify_ocr_post_chain_handoff_retention_manifest_guard.py", "ocr_post_chain_handoff_retention_manifest_guard.json"),
    CommandSpec("retention_manifest_guard_rendered_summary", "python tools/subjective_sheet_lab/verify_ocr_post_chain_handoff_retention_manifest_guard_rendered_summary.py", "ocr_post_chain_handoff_retention_manifest_guard_rendered_summary.json"),
    CommandSpec("cleanup_candidate_manifest", "python tools/subjective_sheet_lab/verify_ocr_post_chain_cleanup_candidate_manifest.py", "ocr_post_chain_cleanup_candidate_manifest.json"),
    CommandSpec("cleanup_candidate_manifest_rendered_summary", "python tools/subjective_sheet_lab/verify_ocr_post_chain_cleanup_candidate_manifest_rendered_summary.py", "ocr_post_chain_cleanup_candidate_manifest_rendered_summary.json"),
    CommandSpec("cleanup_candidate_manifest_guard", "python tools/subjective_sheet_lab/verify_ocr_post_chain_cleanup_candidate_manifest_guard.py", "ocr_post_chain_cleanup_candidate_manifest_guard.json"),
    CommandSpec("step_catalog_rendered_summary", "python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_handoff_runner_steps_rendered_summary.py", "ocr_post_chain_evidence_handoff_runner_steps_rendered_summary.json"),
    CommandSpec(STEP_CATALOG_GUARD_LABEL, "python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_handoff_runner_steps_rendered_summary_guard.py", "ocr_post_chain_evidence_handoff_runner_steps_rendered_summary_guard.json"),
    CommandSpec("operator_summary", "python tools/subjective_sheet_lab/verify_ocr_post_chain_operator_summary.py", "ocr_post_chain_operator_summary.json"),
    CommandSpec("operator_summary_guard", "python tools/subjective_sheet_lab/verify_ocr_post_chain_operator_summary_guard.py", "ocr_post_chain_operator_summary_guard.json"),
    CommandSpec("evidence_index_common_self_check", "python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_index_common_self_check.py", "ocr_post_chain_evidence_index_common_self_check.json"),
    CommandSpec("evidence_index_freshness_guard", "python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_index_freshness_guard.py", "ocr_post_chain_evidence_index_freshness_guard.json"),
    CommandSpec("evidence_index", "python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_index.py", "ocr_post_chain_evidence_index.json"),
    CommandSpec("evidence_index_rendered_summary_guard", "python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_index_rendered_summary_guard.py", "ocr_post_chain_evidence_index_rendered_summary_guard.json"),
    CommandSpec(HANDOFF_RUNNER_LABEL, "python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_handoff_runner.py", "ocr_post_chain_evidence_handoff_runner.json"),
    CommandSpec("evidence_handoff_runner_guard", "python tools/subjective_sheet_lab/verify_ocr_post_chain_evidence_handoff_runner_guard.py", "ocr_post_chain_evidence_handoff_runner_guard.json"),
)


def main() -> int:
    report = build_report(COMMAND_SPECS)
    write_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(specs: tuple[CommandSpec, ...]) -> HandoffCommandChecklistReport:
    commands = command_rows(specs)
    missing_reports = [row["report_path"] for row in commands if not (LAB.parents[1] / row["report_path"]).is_file()]
    forbidden_snippets = forbidden_command_snippets(commands)
    guard_order = command_order(commands, STEP_CATALOG_GUARD_LABEL)
    runner_order = command_order(commands, HANDOFF_RUNNER_LABEL)
    guard_before_runner = 0 < guard_order < runner_order
    ok = (
        len(commands) == EXPECTED_COMMAND_COUNT
        and not missing_reports
        and guard_before_runner
        and not forbidden_snippets
    )
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_READY"
        if ok
        else "OCR_POST_CHAIN_HANDOFF_COMMAND_CHECKLIST_FAILED",
        "ordered_command_count": len(commands),
        "expected_command_count": EXPECTED_COMMAND_COUNT,
        "required_report_count": len(commands),
        "missing_report_count": len(missing_reports),
        "missing_reports": missing_reports,
        "step_catalog_guard_order": guard_order,
        "evidence_handoff_runner_order": runner_order,
        "step_catalog_guard_before_runner": guard_before_runner,
        "forbidden_command_snippet_count": len(forbidden_snippets),
        "forbidden_command_snippets": forbidden_snippets,
        "commands": commands,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def write_report(report: HandoffCommandChecklistReport) -> None:
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")


def command_rows(specs: tuple[CommandSpec, ...]) -> list[CommandRow]:
    return [
        {
            "order": order,
            "label": spec.label,
            "command": spec.command,
            "report_path": f"tools/subjective_sheet_lab/{spec.report_name}",
        }
        for order, spec in enumerate(specs, start=1)
    ]


def command_order(commands: list[CommandRow], label: str) -> int:
    orders = [row["order"] for row in commands if row["label"] == label]
    return orders[0] if orders else 0


def forbidden_command_snippets(commands: list[CommandRow]) -> list[str]:
    command_text = "\n".join(row["command"] for row in commands)
    return [snippet for snippet in FORBIDDEN_COMMAND_SNIPPETS if snippet in command_text]


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Use this ordered command block for provider-free post-chain maintenance."
    return "Fix the post-chain command checklist before running operator handoff maintenance."


def markdown(report: HandoffCommandChecklistReport) -> str:
    command_lines = [f"- {row['order']}. `{row['command']}` -> `{row['report_path']}`" for row in report["commands"]]
    missing_lines = [f"- `{path}`" for path in report["missing_reports"]] or ["- none"]
    forbidden_lines = [f"- `{snippet}`" for snippet in report["forbidden_command_snippets"]] or ["- none"]
    return "\n".join((
        "# OCR Post-Chain Handoff Command Checklist",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- ordered_command_count: `{report['ordered_command_count']}`",
        f"- expected_command_count: `{report['expected_command_count']}`",
        f"- required_report_count: `{report['required_report_count']}`",
        f"- missing_report_count: `{report['missing_report_count']}`",
        f"- step_catalog_guard_order: `{report['step_catalog_guard_order']}`",
        f"- evidence_handoff_runner_order: `{report['evidence_handoff_runner_order']}`",
        f"- step_catalog_guard_before_runner: `{report['step_catalog_guard_before_runner']}`",
        f"- forbidden_command_snippet_count: `{report['forbidden_command_snippet_count']}`",
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
        "## Missing Reports",
        *missing_lines,
        "",
        "## Forbidden Command Snippets",
        *forbidden_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
