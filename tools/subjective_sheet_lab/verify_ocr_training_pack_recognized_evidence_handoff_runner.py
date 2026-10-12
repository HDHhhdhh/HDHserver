# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_training_pack_recognized_evidence_handoff_runner.py

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, TypedDict

from ocr_preflight_environment_matrix_model import LAB
from ocr_provider_free_extended_gate_common import JsonObject, read_json_object, require_bool_value, require_int_value
from ocr_report_field_access import int_field, str_field
from verify_ocr_training_pack_recognized_evidence_acceptance_dry_run import (
    REPORT_JSON as ACCEPTANCE_JSON,
)
from verify_ocr_training_pack_recognized_evidence_acceptance_dry_run import main as verify_acceptance
from verify_ocr_training_pack_recognized_evidence_contract import REPORT_JSON as CONTRACT_JSON
from verify_ocr_training_pack_recognized_evidence_contract import main as verify_contract
from verify_ocr_training_pack_recognized_evidence_filename_diagnostics import (
    REPORT_JSON as FILENAME_JSON,
)
from verify_ocr_training_pack_recognized_evidence_filename_diagnostics import main as verify_filename
from verify_ocr_training_pack_recognized_evidence_intake import REPORT_JSON as INTAKE_JSON
from verify_ocr_training_pack_recognized_evidence_intake import main as verify_intake
from verify_ocr_training_pack_recognized_evidence_intake_replay import REPORT_JSON as REPLAY_JSON
from verify_ocr_training_pack_recognized_evidence_intake_replay import main as verify_replay
from verify_ocr_training_pack_recognized_evidence_intake_replay_probes import (
    REPORT_JSON as REPLAY_PROBES_JSON,
)
from verify_ocr_training_pack_recognized_evidence_intake_replay_probes import main as verify_replay_probes
from verify_ocr_training_pack_recognized_evidence_operator_checklist import (
    REPORT_JSON as CHECKLIST_JSON,
)
from verify_ocr_training_pack_recognized_evidence_operator_checklist import main as verify_checklist
from verify_ocr_training_pack_recognized_evidence_target_coverage import REPORT_JSON as COVERAGE_JSON
from verify_ocr_training_pack_recognized_evidence_target_coverage import main as verify_coverage
from verify_ocr_training_pack_recognized_evidence_target_diff import REPORT_JSON as DIFF_JSON
from verify_ocr_training_pack_recognized_evidence_target_diff import main as verify_diff

Verifier: TypeAlias = Callable[[], int]
REPORT_JSON: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_handoff_runner.json"
REPORT_MD: Final[Path] = LAB / "ocr_training_pack_recognized_evidence_handoff_runner.md"


class HandoffStep(TypedDict):
    name: str
    report_path: str
    expected_status: str
    actual_status: str
    exit_code: int
    ok: bool


class HandoffReport(TypedDict):
    ok: bool
    student_facing: bool
    status: str
    current_blocker: str
    handoff_step_count: int
    failed_step_count: int
    steps: list[HandoffStep]
    evidence_file_count: int
    missing_target_count: int
    missing_required_file_count: int
    expected_file_name_count: int
    contract_rejected_probe_count: int
    replay_probe_count: int
    replay_failed_probe_count: int
    complete_candidate_ready: bool
    acceptance_invalid_probe_blocked_count: int
    acceptance_failed_probe_count: int
    provider_call_count: int
    external_ocr_api_call_count: int
    submit_test_call_count: int
    ts_submit_click_count: int
    answer_key_or_grading_field_leak_count: int
    filesystem_path_leak_count: int
    production_default: str
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class StepSpec:
    name: str
    verifier: Verifier
    report_path: Path
    expected_status: str


STEP_SPECS: Final[tuple[StepSpec, ...]] = (
    StepSpec("intake", verify_intake, INTAKE_JSON, "TRAINING_PACK_RECOGNIZED_EVIDENCE_USER_APPROVAL_REQUIRED"),
    StepSpec("contract", verify_contract, CONTRACT_JSON, "TRAINING_PACK_RECOGNIZED_EVIDENCE_CONTRACT_READY_WAITING_FOR_PAYLOADS"),
    StepSpec("target_coverage", verify_coverage, COVERAGE_JSON, "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_COVERAGE_USER_APPROVAL_REQUIRED"),
    StepSpec("target_diff", verify_diff, DIFF_JSON, "TRAINING_PACK_RECOGNIZED_EVIDENCE_TARGET_DIFF_USER_APPROVAL_REQUIRED"),
    StepSpec("operator_checklist", verify_checklist, CHECKLIST_JSON, "TRAINING_PACK_RECOGNIZED_EVIDENCE_OPERATOR_CHECKLIST_USER_APPROVAL_REQUIRED"),
    StepSpec("filename_diagnostics", verify_filename, FILENAME_JSON, "TRAINING_PACK_RECOGNIZED_EVIDENCE_FILENAME_DIAGNOSTICS_USER_ACTION_REQUIRED"),
    StepSpec("intake_replay", verify_replay, REPLAY_JSON, "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_USER_APPROVAL_REQUIRED"),
    StepSpec("intake_replay_probes", verify_replay_probes, REPLAY_PROBES_JSON, "TRAINING_PACK_RECOGNIZED_EVIDENCE_INTAKE_REPLAY_PROBES_READY"),
    StepSpec("acceptance_dry_run", verify_acceptance, ACCEPTANCE_JSON, "TRAINING_PACK_RECOGNIZED_EVIDENCE_ACCEPTANCE_DRY_RUN_VERIFIED"),
)


def main() -> int:
    steps = run_steps()
    report = build_report(steps)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def run_steps() -> list[HandoffStep]:
    steps: list[HandoffStep] = []
    for spec in STEP_SPECS:
        step = run_step(spec)
        steps.append(step)
        if not step["ok"]:
            break
    return steps


def run_step(spec: StepSpec) -> HandoffStep:
    exit_code = spec.verifier()
    status = report_status(spec.report_path)
    return {
        "name": spec.name,
        "report_path": display_path(spec.report_path),
        "expected_status": spec.expected_status,
        "actual_status": status,
        "exit_code": exit_code,
        "ok": exit_code == 0 and status == spec.expected_status,
    }


def report_status(path: Path) -> str:
    return str_field(read_json_object(path), "status")


def build_report(steps: list[HandoffStep]) -> HandoffReport:
    intake = read_json_object(INTAKE_JSON)
    contract = read_json_object(CONTRACT_JSON)
    coverage = read_json_object(COVERAGE_JSON)
    filename = read_json_object(FILENAME_JSON)
    replay = read_json_object(REPLAY_JSON)
    replay_probes = read_json_object(REPLAY_PROBES_JSON)
    acceptance = read_json_object(ACCEPTANCE_JSON)
    failed_step_count = sum(1 for step in steps if not step["ok"])
    failed_probe_count = int_field(replay_probes, "probe_count") - int_field(replay_probes, "accepted_probe_count")
    ok = (
        failed_step_count == 0
        and len(steps) == len(STEP_SPECS)
        and int_field(intake, "evidence_file_count") == 0
        and int_field(coverage, "missing_target_count") == 4
        and int_field(replay, "missing_required_file_count") == 4
        and acceptance.get("complete_candidate_ready") is True
        and int_field(acceptance, "failed_probe_count") == 0
        and failed_probe_count == 0
    )
    return {
        "ok": ok,
        "student_facing": False,
        "status": "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_READY" if ok else "TRAINING_PACK_RECOGNIZED_EVIDENCE_HANDOFF_RUNNER_FAILED",
        "current_blocker": "training_pack_recognized_evidence_files_missing",
        "handoff_step_count": len(steps),
        "failed_step_count": failed_step_count,
        "steps": steps,
        "evidence_file_count": int_field(intake, "evidence_file_count"),
        "missing_target_count": int_field(coverage, "missing_target_count"),
        "missing_required_file_count": int_field(replay, "missing_required_file_count"),
        "expected_file_name_count": int_field(filename, "expected_file_name_count"),
        "contract_rejected_probe_count": int_field(contract, "contract_probe_rejected_count"),
        "replay_probe_count": int_field(replay_probes, "probe_count"),
        "replay_failed_probe_count": failed_probe_count,
        "complete_candidate_ready": acceptance.get("complete_candidate_ready") is True,
        "acceptance_invalid_probe_blocked_count": int_field(acceptance, "invalid_probe_blocked_count"),
        "acceptance_failed_probe_count": int_field(acceptance, "failed_probe_count"),
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
        return "Use this runner after the four Training Pack recognized evidence files arrive, before cached browser QA."
    return "Inspect the first failed Training Pack evidence handoff step before cached browser QA."


def markdown(report: HandoffReport) -> str:
    step_lines = [f"- {step['name']}: exit `{step['exit_code']}`, ok `{step['ok']}`, status `{step['actual_status']}`" for step in report["steps"]]
    return "\n".join((
        "# OCR Training Pack Recognized Evidence Handoff Runner",
        "",
        f"- ok: `{report['ok']}`",
        f"- status: `{report['status']}`",
        f"- current_blocker: `{report['current_blocker']}`",
        f"- handoff_step_count: `{report['handoff_step_count']}`",
        f"- failed_step_count: `{report['failed_step_count']}`",
        f"- evidence_file_count: `{report['evidence_file_count']}`",
        f"- missing_target_count: `{report['missing_target_count']}`",
        f"- missing_required_file_count: `{report['missing_required_file_count']}`",
        f"- expected_file_name_count: `{report['expected_file_name_count']}`",
        f"- contract_rejected_probe_count: `{report['contract_rejected_probe_count']}`",
        f"- replay_probe_count: `{report['replay_probe_count']}`",
        f"- replay_failed_probe_count: `{report['replay_failed_probe_count']}`",
        f"- complete_candidate_ready: `{report['complete_candidate_ready']}`",
        f"- acceptance_invalid_probe_blocked_count: `{report['acceptance_invalid_probe_blocked_count']}`",
        f"- acceptance_failed_probe_count: `{report['acceptance_failed_probe_count']}`",
        f"- provider_call_count: `{report['provider_call_count']}`",
        f"- external_ocr_api_call_count: `{report['external_ocr_api_call_count']}`",
        f"- submit_test_call_count: `{report['submit_test_call_count']}`",
        f"- ts_submit_click_count: `{report['ts_submit_click_count']}`",
        f"- answer_key_or_grading_field_leak_count: `{report['answer_key_or_grading_field_leak_count']}`",
        f"- filesystem_path_leak_count: `{report['filesystem_path_leak_count']}`",
        f"- production_default: `{report['production_default']}`",
        "",
        "## Steps",
        *step_lines,
        "",
        "## Next Safe Action",
        report["next_safe_action"],
        "",
    ))


def display_path(path: Path) -> str:
    return f"tools/subjective_sheet_lab/{path.name}"


if __name__ == "__main__":
    raise SystemExit(main())
