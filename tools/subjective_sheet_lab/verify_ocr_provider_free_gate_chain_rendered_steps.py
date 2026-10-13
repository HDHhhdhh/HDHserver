# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_gate_chain_rendered_steps.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict, assert_never

from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    JsonObject,
    JsonValue,
    assert_common_safety,
    read_json_object,
    require_int_value,
    require_object,
    require_text_value,
)
from ocr_preflight_environment_matrix_model import LAB
from verify_ocr_provider_free_gate_chain import CHAIN_STEPS
from verify_ocr_provider_free_gate_chain import REPORT_JSON_OUT as CHAIN_JSON
from verify_ocr_provider_free_gate_chain import REPORT_MD_OUT as CHAIN_MD

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_provider_free_gate_chain_rendered_steps.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_provider_free_gate_chain_rendered_steps.md"
FORBIDDEN_MARKDOWN_SNIPPETS: Final[tuple[str, ...]] = (
    "C:\\server",
    "C:/server",
    "canonical_answer",
    "accepted_answers",
    "correct/incorrect",
    "grading fields",
)


class ChainRenderedStepsReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    chain_json_path: str
    chain_markdown_path: str
    expected_chain_step_count: int
    rendered_step_count: int
    missing_step_count: int
    missing_steps: list[str]
    missing_snippet_count: int
    missing_snippets: list[str]
    forbidden_snippet_count: int
    forbidden_snippets: list[str]
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


def main() -> int:
    report = build_report(read_json_object(CHAIN_JSON), CHAIN_MD.read_text(encoding="utf-8"))
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(chain_report: JsonObject, markdown_text: str) -> ChainRenderedStepsReport:
    assert_common_safety("chain", chain_report)
    expected_names = expected_step_names()
    actual_names = rendered_step_names(chain_report)
    require_int_value(chain_report.get("chain_step_count"), len(expected_names), "chain.chain_step_count")
    require_int_value(chain_report.get("failed_step_count"), 0, "chain.failed_step_count")
    require_int_value(chain_report.get("issue_count"), 0, "chain.issue_count")
    require_text_value(chain_report.get("production_default"), "NO_GO", "chain.production_default")
    if actual_names != expected_names:
        raise ExtendedGateError("chain JSON step order does not match current CHAIN_STEPS")
    required_snippets = required_markdown_snippets(expected_names)
    missing_snippets = [snippet for snippet in required_snippets if snippet not in markdown_text]
    missing_steps = [name for name in expected_names if f"- {name}: exit 0, ok True" not in markdown_text]
    forbidden_snippets = [snippet for snippet in FORBIDDEN_MARKDOWN_SNIPPETS if snippet in markdown_text]
    ok = not missing_snippets and not forbidden_snippets
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_VERIFIED"
        if ok
        else "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_STALE",
        "chain_json_path": "tools/subjective_sheet_lab/ocr_provider_free_gate_chain.json",
        "chain_markdown_path": "tools/subjective_sheet_lab/ocr_provider_free_gate_chain.md",
        "expected_chain_step_count": len(expected_names),
        "rendered_step_count": len(actual_names),
        "missing_step_count": len(missing_steps),
        "missing_steps": missing_steps,
        "missing_snippet_count": len(missing_snippets),
        "missing_snippets": missing_snippets,
        "forbidden_snippet_count": len(forbidden_snippets),
        "forbidden_snippets": forbidden_snippets,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def expected_step_names() -> tuple[str, ...]:
    return tuple(step[0] for step in CHAIN_STEPS)


def rendered_step_names(chain_report: JsonObject) -> tuple[str, ...]:
    match chain_report.get("steps"):
        case list() as values:
            return tuple(step_name(value, index) for index, value in enumerate(values, start=1))
        case None | bool() | int() | float() | str() | dict():
            raise ExtendedGateError("chain.steps must be a list")
        case unreachable:
            assert_never(unreachable)


def step_name(value: JsonValue, index: int) -> str:
    row = require_object(value, f"chain.steps[{index}]")
    match row.get("name"):
        case str() as name:
            return name
        case None | bool() | int() | float() | list() | dict():
            raise ExtendedGateError(f"chain.steps[{index}].name must be text")
        case unreachable:
            assert_never(unreachable)


def required_markdown_snippets(step_names: tuple[str, ...]) -> tuple[str, ...]:
    return (
        f"- chain_step_count: {len(step_names)}",
        "- failed_step_count: 0",
        "- provider_call_count: 0",
        "- external_ocr_api_call_count: 0",
        "- submit_test_call_count: 0",
        "- ts_submit_click_count: 0",
        "- answer_key_or_grading_field_leak_count: 0",
        "- filesystem_path_leak_count: 0",
        "- production_default: NO_GO",
        "operator_runbook_rendered_summary_guard",
        *(f"- {name}: exit 0, ok True" for name in step_names),
    )


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Run this verifier after provider-free chain refreshes to lock rendered chain evidence."
    return "Rerun verify_ocr_provider_free_gate_chain.py, then rerun this rendered-step verifier."


def markdown(report: ChainRenderedStepsReport) -> str:
    missing_lines = [f"- {snippet}" for snippet in report["missing_snippets"]] or ["- none"]
    missing_step_lines = [f"- {step}" for step in report["missing_steps"]] or ["- none"]
    forbidden_lines = [f"- {snippet}" for snippet in report["forbidden_snippets"]] or ["- none"]
    return "\n".join((
        "# OCR Provider-Free Gate Chain Rendered Steps",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- expected_chain_step_count: `{report['expected_chain_step_count']}`",
        f"- rendered_step_count: `{report['rendered_step_count']}`",
        f"- missing_step_count: `{report['missing_step_count']}`",
        f"- missing_snippet_count: `{report['missing_snippet_count']}`",
        f"- forbidden_snippet_count: `{report['forbidden_snippet_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Missing Steps",
        *missing_step_lines,
        "",
        "## Missing Snippets",
        *missing_lines,
        "",
        "## Forbidden Snippets",
        *forbidden_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
