from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from verify_ocr_answer_mode_draft_targets import REPORT_JSON as DRAFT_REPORT_JSON, main as verify_draft_targets
from verify_ocr_answer_mode_patch_package import REPORT_JSON as PATCH_PACKAGE_REPORT_JSON, main as verify_patch_package
from verify_ocr_answer_mode_post_approval_simulation import REPORT_JSON as SIMULATION_REPORT_JSON, main as verify_post_approval_simulation
from verify_ocr_answer_mode_runtime_patch_readiness import REPORT_JSON as READINESS_REPORT_JSON, main as verify_runtime_patch_readiness
from verify_ocr_mijeok1_draft_postprocess_policy import REPORT_JSON as MIJEOK1_REPORT_JSON, main as verify_mijeok1
from verify_ocr_training_pack_draft_postprocess_policy import REPORT_JSON as TRAINING_PACK_REPORT_JSON, main as verify_training_pack

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_draft_answer_mode_combined_policy.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_draft_answer_mode_combined_policy.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CombinedPolicyError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    run_verifiers()
    draft = require_object(load_json(DRAFT_REPORT_JSON), "draft report")
    mijeok1 = require_object(load_json(MIJEOK1_REPORT_JSON), "mijeok1 report")
    training_pack = require_object(load_json(TRAINING_PACK_REPORT_JSON), "training pack report")
    patch_package = require_object(load_json(PATCH_PACKAGE_REPORT_JSON), "patch package report")
    simulation = require_object(load_json(SIMULATION_REPORT_JSON), "post-approval simulation report")
    readiness = require_object(load_json(READINESS_REPORT_JSON), "runtime patch readiness report")
    summary = combined_summary(draft, mijeok1, training_pack, patch_package, simulation, readiness)
    REPORT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def run_verifiers() -> None:
    for label, action in (
        ("draft targets", verify_draft_targets),
        ("mijeok1 postprocess", verify_mijeok1),
        ("training pack postprocess", verify_training_pack),
        ("patch package", verify_patch_package),
        ("post-approval simulation", verify_post_approval_simulation),
        ("runtime patch readiness", verify_runtime_patch_readiness),
    ):
        result = action()
        if result != 0:
            raise CombinedPolicyError(f"{label} verifier failed with exit code {result}")


def combined_summary(
    draft: JsonObject,
    mijeok1: JsonObject,
    training_pack: JsonObject,
    patch_package: JsonObject,
    simulation: JsonObject,
    readiness: JsonObject,
) -> JsonObject:
    assert_zero_counts(draft, "draft")
    assert_zero_counts(mijeok1, "mijeok1")
    assert_zero_counts(training_pack, "training_pack")
    assert_zero_counts(patch_package, "patch_package")
    assert_zero_counts(simulation, "post_approval_simulation")
    assert_zero_counts(readiness, "runtime_patch_readiness")
    assert_patch_package_ready(patch_package)
    assert_runtime_patch_ready(readiness)
    mijeok1_summary = require_object(mijeok1.get("summary"), "mijeok1.summary")
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "draft_target_count": require_int(draft.get("target_count"), "draft.target_count"),
        "draft_fully_classified_count": require_int(draft.get("fully_classified_draft_count"), "draft.fully_classified"),
        "draft_runtime_ready_count": require_int(draft.get("ready_for_runtime_integration_count"), "draft.runtime_ready"),
        "mijeok1_choice_question_count": require_int(mijeok1_summary.get("choice_question_count"), "mijeok1.choice"),
        "mijeok1_runtime_gap_count": require_int(mijeok1_summary.get("current_runtime_gap_count"), "mijeok1.gap"),
        "training_pack_target_count": require_int(training_pack.get("target_count"), "training_pack.target_count"),
        "training_pack_choice_question_count": require_int(training_pack.get("total_choice_question_count"), "training_pack.choice"),
        "training_pack_runtime_gap_count": require_int(training_pack.get("total_current_runtime_gap_count"), "training_pack.gap"),
        "patch_package_target_count": require_int(patch_package.get("target_count"), "patch_package.target_count"),
        "patch_package_preflight_check_present": True,
        "patch_package_runtime_files_modified": False,
        "post_approval_simulation_target_count": require_int(simulation.get("target_count"), "simulation.target_count"),
        "post_approval_invalid_choice_blocked_count": require_int(
            simulation.get("invalid_choice_blocked_count"),
            "simulation.invalid_choice_blocked",
        ),
        "post_approval_valid_answer_value_safe_count": require_int(
            simulation.get("valid_answer_value_safe_count"),
            "simulation.valid_answer_value_safe",
        ),
        "runtime_patch_ready_to_apply_when_approved": True,
        "runtime_patch_server_anchor_present": True,
        "runtime_patch_ui_anchor_present": True,
        "runtime_patch_preflight_anchor_present": True,
        "runtime_patch_server_targets_already_present_count": require_int(
            readiness.get("server_targets_already_present_count"),
            "readiness.server_targets_already_present",
        ),
        "runtime_patch_ui_targets_already_present_count": require_int(
            readiness.get("ui_targets_already_present_count"),
            "readiness.ui_targets_already_present",
        ),
        "runtime_patch_preflight_check_already_present": False,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "runtime_wiring_status": "not_wired",
    }
    verify_expected_summary(output)
    return output


def assert_zero_counts(payload: JsonObject, label: str) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        if payload.get(key) != 0:
            raise CombinedPolicyError(f"{label}.{key} must be 0")
    if payload.get("student_facing") is not False:
        raise CombinedPolicyError(f"{label}.student_facing must be false")
    if payload.get("answer_key_or_grading_field_leak_count") != 0:
        raise CombinedPolicyError(f"{label} leaked answer-key/grading fields")
    if payload.get("filesystem_path_leak_count") != 0:
        raise CombinedPolicyError(f"{label} leaked filesystem paths")


def assert_patch_package_ready(patch_package: JsonObject) -> None:
    if patch_package.get("preflight_check_present") is not True:
        raise CombinedPolicyError("patch_package.preflight_check_present must be true")
    if patch_package.get("runtime_files_modified_by_this_check") is not False:
        raise CombinedPolicyError("patch_package must not modify runtime files")


def assert_runtime_patch_ready(readiness: JsonObject) -> None:
    for key in ("ready_to_apply_when_approved", "server_anchor_present", "ui_anchor_present", "preflight_anchor_present"):
        if readiness.get(key) is not True:
            raise CombinedPolicyError(f"readiness.{key} must be true")
    if readiness.get("preflight_check_already_present") is not False:
        raise CombinedPolicyError("readiness.preflight_check_already_present must be false")


def verify_expected_summary(summary: JsonObject) -> None:
    expected = {
        "draft_target_count": 5,
        "draft_fully_classified_count": 5,
        "draft_runtime_ready_count": 0,
        "mijeok1_choice_question_count": 17,
        "mijeok1_runtime_gap_count": 17,
        "training_pack_target_count": 4,
        "training_pack_choice_question_count": 80,
        "training_pack_runtime_gap_count": 80,
        "patch_package_target_count": 5,
        "post_approval_simulation_target_count": 5,
        "post_approval_invalid_choice_blocked_count": 776,
        "post_approval_valid_answer_value_safe_count": 15,
        "runtime_patch_server_targets_already_present_count": 0,
        "runtime_patch_ui_targets_already_present_count": 0,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise CombinedPolicyError(f"{key} expected {value}, got {summary.get(key)}")


def markdown(summary: JsonObject) -> str:
    lines = [
        "# OCR Draft Answer Mode Combined Policy",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        "- runtime wiring status: not wired",
        "- answer-key/grading/path leak count: 0",
        "",
        "## Summary",
        "",
        f"- draft targets fully classified: {summary['draft_fully_classified_count']} / {summary['draft_target_count']}",
        f"- Mijeok1 choice questions with missing-mode runtime gap: {summary['mijeok1_runtime_gap_count']}",
        f"- Training Pack choice questions with missing-mode runtime gap: {summary['training_pack_runtime_gap_count']}",
        f"- patch package targets verified: {summary['patch_package_target_count']}",
        f"- post-approval invalid choice cases blocked: {summary['post_approval_invalid_choice_blocked_count']}",
        f"- post-approval valid answer-value cases safe: {summary['post_approval_valid_answer_value_safe_count']}",
        f"- runtime patch ready to apply when approved: {summary['runtime_patch_ready_to_apply_when_approved']}",
        "",
        "This combined verifier is provider-free evidence for a future reviewed answer-mode wiring step.",
    ]
    return "\n".join(lines) + "\n"


def load_json(path: Path) -> JsonValue:
    return json.loads(path.read_text(encoding="utf-8"))


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise CombinedPolicyError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise CombinedPolicyError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
