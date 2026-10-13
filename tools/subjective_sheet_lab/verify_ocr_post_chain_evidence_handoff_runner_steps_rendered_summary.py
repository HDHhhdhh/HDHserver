#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_evidence_handoff_runner_steps_rendered_summary.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypeAlias, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_post_chain_evidence_handoff_runner_steps import HandoffStepSpec, STEP_SPECS

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_handoff_runner_steps_rendered_summary.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_evidence_handoff_runner_steps_rendered_summary.md"
EXPECTED_STEP_COUNT: Final[int] = 17
FIRST_STEP_NAME: Final[str] = "qa_start_here_freshness_guard"
LAST_STEP_NAME: Final[str] = "qa_start_here_evidence_index_freshness"
CLEANUP_STEP_NAME: Final[str] = "cleanup_candidate_manifest_rendered_summary"
CLEANUP_EXPECTED_STATUS: Final[str] = "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_RENDERED_SUMMARY_VERIFIED"
EVIDENCE_INDEX_GUARD_STEP_NAME: Final[str] = "evidence_index_guard"
StepSpecs: TypeAlias = tuple[HandoffStepSpec, ...]


class HandoffStepRow(TypedDict):
    ordinal: int
    name: str
    report_path: str
    expected_status: str


class HandoffStepCatalogSummaryReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    step_count: int
    expected_step_count: int
    unique_step_name_count: int
    duplicate_step_name_count: int
    duplicate_step_names: list[str]
    first_step_name: str
    last_step_name: str
    cleanup_step_present: bool
    cleanup_step_expected_status: str
    cleanup_step_position: int
    evidence_index_guard_position: int
    cleanup_before_evidence_index_guard: bool
    step_rows: list[HandoffStepRow]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    report = build_report(STEP_SPECS)
    write_report(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(specs: StepSpecs) -> HandoffStepCatalogSummaryReport:
    rows = step_rows(specs)
    duplicate_names = duplicate_step_names(rows)
    cleanup_position = step_position(rows, CLEANUP_STEP_NAME)
    evidence_guard_position = step_position(rows, EVIDENCE_INDEX_GUARD_STEP_NAME)
    cleanup_status = step_expected_status(rows, CLEANUP_STEP_NAME)
    first_step_name = rows[0]["name"] if rows else ""
    last_step_name = rows[-1]["name"] if rows else ""
    cleanup_before_guard = 0 < cleanup_position < evidence_guard_position
    path_leak_count = filesystem_path_leak_count(rows)
    ok = (
        len(rows) == EXPECTED_STEP_COUNT
        and len(rows) == len({row["name"] for row in rows})
        and first_step_name == FIRST_STEP_NAME
        and last_step_name == LAST_STEP_NAME
        and cleanup_status == CLEANUP_EXPECTED_STATUS
        and cleanup_before_guard
        and path_leak_count == 0
    )
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_STEPS_RENDERED_SUMMARY_VERIFIED"
        if ok
        else "OCR_POST_CHAIN_EVIDENCE_HANDOFF_RUNNER_STEPS_RENDERED_SUMMARY_FAILED",
        "step_count": len(rows),
        "expected_step_count": EXPECTED_STEP_COUNT,
        "unique_step_name_count": len({row["name"] for row in rows}),
        "duplicate_step_name_count": len(duplicate_names),
        "duplicate_step_names": duplicate_names,
        "first_step_name": first_step_name,
        "last_step_name": last_step_name,
        "cleanup_step_present": cleanup_position > 0,
        "cleanup_step_expected_status": cleanup_status,
        "cleanup_step_position": cleanup_position,
        "evidence_index_guard_position": evidence_guard_position,
        "cleanup_before_evidence_index_guard": cleanup_before_guard,
        "step_rows": rows,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": path_leak_count,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def write_report(report: HandoffStepCatalogSummaryReport) -> None:
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")


def step_rows(specs: StepSpecs) -> list[HandoffStepRow]:
    return [
        {
            "ordinal": index,
            "name": spec.name,
            "report_path": relative_report_path(spec.report_path),
            "expected_status": spec.expected_status,
        }
        for index, spec in enumerate(specs, start=1)
    ]


def relative_report_path(path: Path) -> str:
    return str(path.relative_to(LAB.parents[1])).replace("\\", "/")


def duplicate_step_names(rows: list[HandoffStepRow]) -> list[str]:
    names = [row["name"] for row in rows]
    return sorted({name for name in names if names.count(name) > 1})


def step_position(rows: list[HandoffStepRow], name: str) -> int:
    positions = [row["ordinal"] for row in rows if row["name"] == name]
    return positions[0] if positions else 0


def step_expected_status(rows: list[HandoffStepRow], name: str) -> str:
    statuses = [row["expected_status"] for row in rows if row["name"] == name]
    return statuses[0] if statuses else ""


def filesystem_path_leak_count(rows: list[HandoffStepRow]) -> int:
    return sum(1 for row in rows if "C:" in row["report_path"] or "\\server" in row["report_path"])


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this step-catalog rendered summary before the live evidence handoff runner."
    return "Fix the split evidence handoff runner step catalog before running the handoff runner."


def markdown(report: HandoffStepCatalogSummaryReport) -> str:
    duplicate_lines = [f"- `{name}`" for name in report["duplicate_step_names"]] or ["- none"]
    step_lines = [
        "- "
        f"{row['ordinal']}. `{row['name']}` -> `{row['report_path']}` "
        f"expects `{row['expected_status']}`"
        for row in report["step_rows"]
    ]
    return "\n".join((
        "# OCR Post-Chain Evidence Handoff Runner Step Catalog Rendered Summary",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- step_count: `{report['step_count']}`",
        f"- expected_step_count: `{report['expected_step_count']}`",
        f"- unique_step_name_count: `{report['unique_step_name_count']}`",
        f"- duplicate_step_name_count: `{report['duplicate_step_name_count']}`",
        f"- first_step_name: `{report['first_step_name']}`",
        f"- last_step_name: `{report['last_step_name']}`",
        f"- cleanup_step_present: `{report['cleanup_step_present']}`",
        f"- cleanup_step_expected_status: `{report['cleanup_step_expected_status']}`",
        f"- cleanup_step_position: `{report['cleanup_step_position']}`",
        f"- evidence_index_guard_position: `{report['evidence_index_guard_position']}`",
        f"- cleanup_before_evidence_index_guard: `{report['cleanup_before_evidence_index_guard']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Duplicate Step Names",
        *duplicate_lines,
        "",
        "## Step Rows",
        *step_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
