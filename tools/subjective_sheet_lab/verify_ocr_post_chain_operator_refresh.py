# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_post_chain_operator_refresh.py

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Final, assert_never

from ocr_post_chain_operator_refresh_model import PostChainOperatorRefreshReport, RefreshStepRow
from ocr_post_chain_operator_refresh_output import markdown
from ocr_preflight_environment_matrix_model import LAB, OCR_PYTHON, ROOT, TIMEOUT_SECONDS
from ocr_provider_free_extended_gate_common import (
    ExtendedGateError,
    assert_common_safety,
    read_json_object,
    require_text_value,
)

REPORT_JSON_OUT: Final[Path] = LAB / "ocr_post_chain_operator_refresh.json"
REPORT_MD_OUT: Final[Path] = LAB / "ocr_post_chain_operator_refresh.md"


@dataclass(frozen=True, slots=True)
class RefreshStep:
    label: str
    script: str
    report_path: Path
    expected_status: str


@dataclass(frozen=True, slots=True)
class FailedStep:
    order: int
    step: RefreshStep
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    issue: str


STEPS: Final[tuple[RefreshStep, ...]] = (
    RefreshStep(
        "rendered_steps",
        "tools/subjective_sheet_lab/verify_ocr_provider_free_gate_chain_rendered_steps.py",
        LAB / "ocr_provider_free_gate_chain_rendered_steps.json",
        "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_VERIFIED",
    ),
    RefreshStep(
        "rendered_steps_guard",
        "tools/subjective_sheet_lab/verify_ocr_provider_free_gate_chain_rendered_steps_guard.py",
        LAB / "ocr_provider_free_gate_chain_rendered_steps_guard.json",
        "OCR_PROVIDER_FREE_GATE_CHAIN_RENDERED_STEPS_GUARD_VERIFIED",
    ),
    RefreshStep(
        "post_chain_guard_manifest",
        "tools/subjective_sheet_lab/verify_ocr_post_chain_guard_manifest.py",
        LAB / "ocr_post_chain_guard_manifest.json",
        "OCR_POST_CHAIN_GUARD_MANIFEST_VERIFIED",
    ),
    RefreshStep(
        "post_chain_guard_manifest_guard",
        "tools/subjective_sheet_lab/verify_ocr_post_chain_guard_manifest_guard.py",
        LAB / "ocr_post_chain_guard_manifest_guard.json",
        "OCR_POST_CHAIN_GUARD_MANIFEST_GUARD_VERIFIED",
    ),
    RefreshStep(
        "post_chain_cleanup_candidate_manifest",
        "tools/subjective_sheet_lab/verify_ocr_post_chain_cleanup_candidate_manifest.py",
        LAB / "ocr_post_chain_cleanup_candidate_manifest.json",
        "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_VERIFIED",
    ),
    RefreshStep(
        "post_chain_cleanup_candidate_manifest_guard",
        "tools/subjective_sheet_lab/verify_ocr_post_chain_cleanup_candidate_manifest_guard.py",
        LAB / "ocr_post_chain_cleanup_candidate_manifest_guard.json",
        "OCR_POST_CHAIN_CLEANUP_CANDIDATE_MANIFEST_GUARD_VERIFIED",
    ),
    RefreshStep(
        "post_chain_operator_summary",
        "tools/subjective_sheet_lab/verify_ocr_post_chain_operator_summary.py",
        LAB / "ocr_post_chain_operator_summary.json",
        "OCR_POST_CHAIN_OPERATOR_SUMMARY_VERIFIED",
    ),
    RefreshStep(
        "post_chain_operator_summary_guard",
        "tools/subjective_sheet_lab/verify_ocr_post_chain_operator_summary_guard.py",
        LAB / "ocr_post_chain_operator_summary_guard.json",
        "OCR_POST_CHAIN_OPERATOR_SUMMARY_GUARD_VERIFIED",
    ),
)


def main() -> int:
    rows = [run_step(order, step) for order, step in enumerate(STEPS, start=1)]
    report = build_report(rows)
    REPORT_JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD_OUT.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def run_step(order: int, step: RefreshStep) -> RefreshStepRow:
    before_mtime = step.report_path.stat().st_mtime_ns if step.report_path.exists() else -1
    started = time.monotonic()
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            [str(OCR_PYTHON), step.script],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        duration = time.monotonic() - started
        return failed_row(FailedStep(
            order=order,
            step=step,
            exit_code=None,
            duration_seconds=duration,
            stdout=safe_text(error.stdout),
            stderr=safe_text(error.stderr),
            issue="timeout",
        ))
    except FileNotFoundError as error:
        duration = time.monotonic() - started
        return failed_row(FailedStep(
            order=order,
            step=step,
            exit_code=None,
            duration_seconds=duration,
            stdout="",
            stderr="",
            issue=str(error),
        ))
    duration = time.monotonic() - started
    status_ok, report_status, issue = report_status_check(step)
    rewritten = step.report_path.exists() and step.report_path.stat().st_mtime_ns > before_mtime
    ok = result.returncode == 0 and status_ok and rewritten
    return {
        "order": order,
        "label": step.label,
        "command": f"python {step.script}",
        "report_path": display_path(step.report_path),
        "exit_code": result.returncode,
        "ok": ok,
        "report_status": report_status,
        "report_rewritten": rewritten,
        "duration_seconds": round(duration, 3),
        "stdout_tail": "" if ok else tail(result.stdout),
        "stderr_tail": "" if ok else tail(result.stderr),
        "issue": "" if ok else issue,
    }


def failed_row(failed: FailedStep) -> RefreshStepRow:
    return {
        "order": failed.order,
        "label": failed.step.label,
        "command": f"python {failed.step.script}",
        "report_path": display_path(failed.step.report_path),
        "exit_code": failed.exit_code,
        "ok": False,
        "report_status": "",
        "report_rewritten": False,
        "duration_seconds": round(failed.duration_seconds, 3),
        "stdout_tail": tail(failed.stdout),
        "stderr_tail": tail(failed.stderr),
        "issue": failed.issue,
    }


def report_status_check(step: RefreshStep) -> tuple[bool, str, str]:
    try:
        payload = read_json_object(step.report_path)
        assert_common_safety(step.label, payload)
        require_text_value(payload.get("status"), step.expected_status, f"{step.label}.status")
    except (ExtendedGateError, FileNotFoundError, JSONDecodeError) as error:
        return False, "", str(error)
    return True, step.expected_status, ""


def build_report(rows: list[RefreshStepRow]) -> PostChainOperatorRefreshReport:
    failed = [row for row in rows if not row["ok"]]
    ok = not failed and len(rows) == len(STEPS)
    return {
        "ok": ok,
        "student_facing": False,
        "status": "OCR_POST_CHAIN_OPERATOR_REFRESH_VERIFIED" if ok else "OCR_POST_CHAIN_OPERATOR_REFRESH_FAILED",
        "ordered_step_count": len(rows),
        "failed_step_count": len(failed),
        "steps": rows,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "production_default": "NO_GO",
        "next_safe_action": next_safe_action(ok),
    }


def safe_text(value: str | bytes | None) -> str:
    match value:
        case str():
            return value
        case bytes():
            return value.decode("utf-8", errors="replace")
        case None:
            return ""
        case unreachable:
            assert_never(unreachable)


def tail(value: str) -> str:
    return value[-1200:]


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"


def next_safe_action(ok: bool) -> str:
    if ok:
        return "Use this wrapper after provider-free chain refreshes before trusting post-chain evidence."
    return "Inspect failed post-chain refresh rows and rerun this wrapper after fixing the listed issue."


if __name__ == "__main__":
    raise SystemExit(main())
