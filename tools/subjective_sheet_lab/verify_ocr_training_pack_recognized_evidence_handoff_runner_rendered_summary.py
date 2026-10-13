# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_handoff_runner_rendered_summary.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import (
    JsonObject,
    assert_common_safety,
    read_json_object,
    require_int_value,
    require_text_value,
)
import verify_ocr_training_pack_recognized_evidence_handoff_runner as handoff_runner

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_handoff_runner_rendered_summary.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_handoff_runner_rendered_summary.md"
REQUIRED_SNIPPETS: Final[tuple[str, ...]] = (
    "# OCR Training Pack Recognized Evidence Handoff Runner",
    "- ok: `True`",
    "- status: `TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_READY`",
    "- current_blocker: `training_pack_recognized_evidence_files_missing`",
    "- handoff_step_count: `9`",
    "- failed_step_count: `0`",
    "- missing_target_count: `4`",
    "- missing_required_file_count: `4`",
    "- contract_rejected_probe_count: `9`",
    "- replay_probe_count: `4`",
    "- replay_failed_probe_count: `0`",
    "- acceptance_invalid_probe_blocked_count: `6`",
    "- acceptance_failed_probe_count: `0`",
    "- provider_call_count: `0`",
    "- external_ocr_api_call_count: `0`",
    "- submit_test_call_count: `0`",
    "- ts_submit_click_count: `0`",
    "- answer_key_or_grading_field_leak_count: `0`",
    "- filesystem_path_leak_count: `0`",
    "- production_default: `NO_GO`",
    "- contract: exit `0`, ok `True`, status `TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS`",
    "- acceptance_dry_run: exit `0`, ok `True`, status `TRAINING_PACK_RECOGNIZED_EVIDENCE_ACCEPTANCE_DRY_RUN_VERIFIED`",
    "Use this runner after the four Training Pack recognized evidence files arrive, before cached browser QA.",
)
FORBIDDEN_SNIPPETS: Final[tuple[str, ...]] = (
    "C:\\server",
    "C:/server",
    "/api/submit-test",
    "canonical_answer",
    "accepted_answers",
    "correct/incorrect",
    "grading fields",
)


class HandoffRunnerRenderedSummaryReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    handoff_runner_json_path: str
    handoff_runner_markdown_path: str
    required_snippet_count: int
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
    report = build_report(
        read_json_object(handoff_runner.REPORT_JSON),
        handoff_runner.REPORT_MD.read_text(encoding="utf-8"),
    )
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_report(payload: JsonObject, markdown_text: str) -> HandoffRunnerRenderedSummaryReport:
    assert_common_safety("training_pack_handoff_runner", payload)
    require_text_value(
        payload.get("status"),
        "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_READY",
        "training_pack_handoff_runner.status",
    )
    require_text_value(
        payload.get("current_blocker"),
        "training_pack_recognized_evidence_files_missing",
        "training_pack_handoff_runner.current_blocker",
    )
    require_int_value(payload.get("handoff_step_count"), 9, "training_pack_handoff_runner.handoff_step_count")
    require_int_value(payload.get("failed_step_count"), 0, "training_pack_handoff_runner.failed_step_count")
    require_int_value(payload.get("missing_target_count"), 4, "training_pack_handoff_runner.missing_target_count")
    require_int_value(
        payload.get("missing_required_file_count"),
        4,
        "training_pack_handoff_runner.missing_required_file_count",
    )
    require_int_value(
        payload.get("acceptance_failed_probe_count"),
        0,
        "training_pack_handoff_runner.acceptance_failed_probe_count",
    )
    missing_snippets = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in markdown_text]
    forbidden_snippets = [snippet for snippet in FORBIDDEN_SNIPPETS if snippet in markdown_text]
    ok = not missing_snippets and not forbidden_snippets
    return {
        "ok": ok,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_RENDERED_SUMMARY_VERIFIED"
        if ok
        else "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_RENDERED_SUMMARY_FAILED",
        "handoff_runner_json_path": handoff_runner.REPORT_JSON.name,
        "handoff_runner_markdown_path": handoff_runner.REPORT_MD.name,
        "required_snippet_count": len(REQUIRED_SNIPPETS),
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


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Keep this rendered-summary verifier with the Training Pack evidence handoff runner."
    return "Refresh the Training Pack evidence handoff runner markdown before cached browser QA."


def markdown(report: HandoffRunnerRenderedSummaryReport) -> str:
    return "\n".join((
        "# OCR Training Pack Recognized Evidence Handoff Runner Rendered Summary",
        "",
        f"- ok: `{report['ok']}`",
        f"- student_facing: `{report['student_facing']}`",
        f"- status: `{report['status']}`",
        f"- required_snippet_count: `{report['required_snippet_count']}`",
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
        "## Missing Snippets",
        *[f"- `{snippet}`" for snippet in report["missing_snippets"]],
        "",
        "## Forbidden Snippets",
        *[f"- `{snippet}`" for snippet in report["forbidden_snippets"]],
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


if __name__ == "__main__":
    raise SystemExit(main())
