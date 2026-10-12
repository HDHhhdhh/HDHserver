# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\run_ocr_regression_suite.py --quick
# python tools\subjective_sheet_lab\run_ocr_regression_suite.py --full

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
SuiteGroup: TypeAlias = Literal["core", "slow", "submit_route"]
SuiteStatus: TypeAlias = Literal["pass", "fail", "skipped", "blocked"]

ROOT: Final = Path(__file__).resolve().parents[2]
LAB: Final = Path(__file__).resolve().parent
REPORT_JSON: Final = LAB / "ocr_regression_suite_report.json"
REPORT_MD: Final = LAB / "ocr_regression_suite_report.md"
DEFAULT_TIMEOUT_SECONDS: Final = 180
SLOW_TIMEOUT_SECONDS: Final = 420
SUBMIT_ROUTE_AUTHORIZATION: Final = "local submit-test verifier execution approved"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    group: SuiteGroup
    command: tuple[str, ...]
    required_path: Path
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class RunResult:
    name: str
    group: SuiteGroup
    status: SuiteStatus
    command: str
    exit_code: int | None
    duration_seconds: float
    reason: str
    stdout_tail: str = ""
    stderr_tail: str = ""


@dataclass(frozen=True, slots=True)
class SuiteOptions:
    full: bool
    include_submit_route: bool
    submit_route_authorization: str
    include_phase1_preflight: bool


def main() -> int:
    options = parse_args()
    results = run_suite(options)
    write_reports(options, results)
    failed = tuple(item for item in results if item.status == "fail")
    blocked = tuple(item for item in results if item.status == "blocked")
    print(json.dumps(summary_payload(results), ensure_ascii=False, indent=2))
    return 0 if results and all(item.status == "pass" for item in results) else 1


def parse_args() -> SuiteOptions:
    parser = argparse.ArgumentParser(
        description="Provider-free OCR lab regression suite with submit-route checks blocked by default.",
    )
    parser.add_argument("--quick", action="store_true", help="Run core provider-free checks only.")
    parser.add_argument("--full", action="store_true", help="Also run slower Phase 2 route/cache checks.")
    parser.add_argument("--skip-phase1-preflight", action="store_true", help="Avoid recursive preflight execution when called from preflight.")
    parser.add_argument("--include-submit-route", action="store_true", help="Run submit-route verifiers only with explicit authorization.")
    parser.add_argument("--submit-route-authorization", default="", help="Required exact authorization phrase for submit-route verifiers.")
    parsed = parser.parse_args()
    return SuiteOptions(
        full=bool(parsed.full and not parsed.quick),
        include_submit_route=bool(parsed.include_submit_route),
        submit_route_authorization=str(parsed.submit_route_authorization),
        include_phase1_preflight=not bool(parsed.skip_phase1_preflight),
    )


def run_suite(options: SuiteOptions) -> list[RunResult]:
    selected = [spec for spec in command_specs() if should_run(spec, options)]
    results = [run_command(spec) for spec in selected]
    results.extend(blocked_submit_results(options))
    return results


def should_run(spec: CommandSpec, options: SuiteOptions) -> bool:
    match spec.group:
        case "core":
            return options.include_phase1_preflight or spec.name != "phase1_preflight"
        case "slow":
            return options.full
        case "submit_route":
            return options.include_submit_route and options.submit_route_authorization == SUBMIT_ROUTE_AUTHORIZATION
        case unreachable:
            raise AssertionError(f"unreachable suite group: {unreachable}")


def blocked_submit_results(options: SuiteOptions) -> list[RunResult]:
    if not options.include_submit_route:
        return []
    if options.submit_route_authorization == SUBMIT_ROUTE_AUTHORIZATION:
        return []
    return [
        RunResult(
            name="submit_route_verifiers",
            group="submit_route",
            status="blocked",
            command="; ".join(command_text(spec.command) for spec in submit_specs()),
            exit_code=None,
            duration_seconds=0.0,
            reason="USER_APPROVAL_REQUIRED: submit route verifiers require the exact local authorization phrase.",
        ),
    ]


def command_specs() -> tuple[CommandSpec, ...]:
    py = sys.executable
    return (
        CommandSpec("student_js_syntax", "core", ("node", "--check", "static/js/student.js"), ROOT / "static/js/student.js"),
        CommandSpec("ocr_review_contract", "core", (py, "-B", "tools/subjective_sheet_lab/validate_ocr_review_contract.py"), LAB / "validate_ocr_review_contract.py"),
        CommandSpec("ocr_review_contract_negative", "core", (py, "-B", "tools/subjective_sheet_lab/verify_ocr_review_contract_negative.py"), LAB / "verify_ocr_review_contract_negative.py"),
        CommandSpec("final_review_payload_bridge", "core", (py, "-B", "tools/subjective_sheet_lab/verify_final_review_payload_bridge.py"), LAB / "verify_final_review_payload_bridge.py"),
        CommandSpec("erased_overwritten_policy", "core", (py, "-B", "tools/subjective_sheet_lab/verify_erased_overwritten_answer_safety_policy.py"), LAB / "verify_erased_overwritten_answer_safety_policy.py"),
        CommandSpec("ocr_postprocessing_gate", "core", (py, "-B", "tools/subjective_sheet_lab/verify_ocr_postprocessing_gate_matrix.py"), LAB / "verify_ocr_postprocessing_gate_matrix.py"),
        CommandSpec("evaluate_ocr_policy", "core", (py, "-B", "tools/subjective_sheet_lab/verify_evaluate_ocr_policy.py"), LAB / "verify_evaluate_ocr_policy.py"),
        CommandSpec("ocr_benchmark_gate", "core", (py, "-B", "tools/subjective_sheet_lab/verify_ocr_benchmark_gate.py"), LAB / "verify_ocr_benchmark_gate.py"),
        CommandSpec("student_ocr_answers_text_ui", "core", ("node", "tools/subjective_sheet_lab/verify_student_ocr_answers_text_ui_bridge.js"), LAB / "verify_student_ocr_answers_text_ui_bridge.js"),
        CommandSpec("student_ocr_submit_guard", "core", ("node", "tools/subjective_sheet_lab/verify_student_ocr_submit_guard.js"), LAB / "verify_student_ocr_submit_guard.js"),
        CommandSpec("student_ocr_cached_fixture", "core", ("node", "tools/subjective_sheet_lab/verify_student_ocr_cached_fixture_qa.js"), LAB / "verify_student_ocr_cached_fixture_qa.js"),
        CommandSpec("student_ocr_review_confirmation", "core", ("node", "tools/subjective_sheet_lab/verify_student_ocr_review_confirmation_flow.js"), LAB / "verify_student_ocr_review_confirmation_flow.js"),
        CommandSpec("student_ocr_review_prefill", "core", ("node", "tools/subjective_sheet_lab/verify_student_ocr_review_prefill_policy.js"), LAB / "verify_student_ocr_review_prefill_policy.js"),
        CommandSpec("student_result_summary_ui", "core", ("node", "tools/subjective_sheet_lab/verify_student_test_result_summary_ui.js"), LAB / "verify_student_test_result_summary_ui.js"),
        CommandSpec("student_answer_preview", "core", ("node", "tools/subjective_sheet_lab/verify_student_test_result_answer_preview.js"), LAB / "verify_student_test_result_answer_preview.js"),
        CommandSpec("phase1_preflight", "core", (py, "-B", "tools/subjective_sheet_lab/run_phase1_preflight_checks.py"), LAB / "run_phase1_preflight_checks.py", SLOW_TIMEOUT_SECONDS),
        CommandSpec("phase2a_route_stub", "slow", (py, "-B", "tools/subjective_sheet_lab/verify_phase2a_internal_ocr_route_stub.py"), LAB / "verify_phase2a_internal_ocr_route_stub.py", SLOW_TIMEOUT_SECONDS),
        CommandSpec("phase2c_crop_route", "slow", (py, "-B", "tools/subjective_sheet_lab/verify_phase2c_crop_pipeline_route.py"), LAB / "verify_phase2c_crop_pipeline_route.py", SLOW_TIMEOUT_SECONDS),
        CommandSpec("phase2d_cached_route", "slow", (py, "-B", "tools/subjective_sheet_lab/verify_phase2d_cached_review_payload_route.py"), LAB / "verify_phase2d_cached_review_payload_route.py", SLOW_TIMEOUT_SECONDS),
        CommandSpec("phase2e_adapter_simulated", "slow", (py, "-B", "tools/subjective_sheet_lab/verify_phase2e_gemini_live_ocr_adapter.py"), LAB / "verify_phase2e_gemini_live_ocr_adapter.py", SLOW_TIMEOUT_SECONDS),
        *submit_specs(),
    )


def submit_specs() -> tuple[CommandSpec, ...]:
    py = sys.executable
    return (
        CommandSpec("submit_offset_guard", "submit_route", (py, "-B", "tools/subjective_sheet_lab/verify_submit_test_offset_guard.py"), LAB / "verify_submit_test_offset_guard.py"),
        CommandSpec("submit_progress_status_policy", "submit_route", (py, "-B", "tools/subjective_sheet_lab/verify_submit_test_progress_status_policy.py"), LAB / "verify_submit_test_progress_status_policy.py"),
        CommandSpec("submit_wrong_details_response", "submit_route", (py, "-B", "tools/subjective_sheet_lab/verify_submit_test_wrong_details_response.py"), LAB / "verify_submit_test_wrong_details_response.py"),
    )


def run_command(spec: CommandSpec) -> RunResult:
    if not spec.required_path.exists():
        return RunResult(spec.name, spec.group, "blocked", command_text(spec.command), None, 0.0, f"required verifier missing: {spec.required_path}")
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            spec.command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=spec.timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        return RunResult(spec.name, spec.group, "fail", command_text(spec.command), None, 0.0, f"command not found: {exc.filename}")
    except subprocess.TimeoutExpired as exc:
        return RunResult(spec.name, spec.group, "fail", command_text(spec.command), None, float(spec.timeout_seconds), f"timeout after {spec.timeout_seconds}s", tail(exc.stdout), tail(exc.stderr))
    except OSError as exc:
        return RunResult(spec.name, spec.group, "fail", command_text(spec.command), None, 0.0, f"os error: {exc}")
    duration = round(time.perf_counter() - started, 3)
    status: SuiteStatus = "pass" if completed.returncode == 0 else "fail"
    reason = "ok" if status == "pass" else f"exit {completed.returncode}"
    return RunResult(spec.name, spec.group, status, command_text(spec.command), completed.returncode, duration, reason, tail(completed.stdout), tail(completed.stderr))


def write_reports(options: SuiteOptions, results: list[RunResult]) -> None:
    REPORT_JSON.write_text(json.dumps(report_payload(options, results), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(options, results), encoding="utf-8")


def report_payload(options: SuiteOptions, results: list[RunResult]) -> dict[str, JsonValue]:
    return {
        "suite": "ocr_regression_suite",
        "mode": "full" if options.full else "quick",
        "include_submit_route": options.include_submit_route,
        "gemini_api_calls": 0,
        "automatic_submit_test_calls": 0,
        "ts_submit_clicks": 0,
        "production_default_changed": False,
        "results": [result_payload(item) for item in results],
        "summary": summary_payload(results),
    }


def result_payload(item: RunResult) -> dict[str, JsonValue]:
    return {
        "name": item.name,
        "group": item.group,
        "status": item.status,
        "command": item.command,
        "exit_code": item.exit_code,
        "duration_seconds": item.duration_seconds,
        "reason": item.reason,
        "stdout_tail": item.stdout_tail,
        "stderr_tail": item.stderr_tail,
    }


def summary_payload(results: list[RunResult]) -> dict[str, JsonValue]:
    return {
        "ok": bool(results) and all(item.status == "pass" for item in results),
        "total": len(results),
        "pass": sum(1 for item in results if item.status == "pass"),
        "fail": sum(1 for item in results if item.status == "fail"),
        "skipped": sum(1 for item in results if item.status == "skipped"),
        "blocked": sum(1 for item in results if item.status == "blocked"),
        "report_json": str(REPORT_JSON),
        "report_md": str(REPORT_MD),
    }


def markdown_report(options: SuiteOptions, results: list[RunResult]) -> str:
    lines = [
        "# OCR Regression Suite Report",
        "",
        f"- Mode: `{'full' if options.full else 'quick'}`",
        f"- Submit-route group requested: `{'yes' if options.include_submit_route else 'no'}`",
        "- Gemini/API calls: `0`",
        "- Automatic `/api/submit-test` calls: `0`",
        "- `#tsSubmit` clicks: `0`",
        "- Production default changed: `no`",
        "",
        "| Group | Check | Status | Seconds | Reason |",
        "| --- | --- | --- | ---: | --- |",
    ]
    lines.extend(f"| `{item.group}` | `{item.name}` | `{item.status}` | {item.duration_seconds:.3f} | {escape_cell(item.reason)} |" for item in results)
    lines.extend(["", "## Blocked Actions", "", "- Live Gemini/API OCR is not part of this runner.", "- Submit-route verifiers require `--include-submit-route` plus the exact local authorization phrase."])
    return "\n".join(lines) + "\n"


def command_text(command: tuple[str, ...]) -> str:
    return " ".join(command)


def tail(value: str | bytes | None, limit: int = 1600) -> str:
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    return text[-limit:]


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
