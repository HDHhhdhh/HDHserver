from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from verify_ocr_answer_mode_patch_sandbox_apply import REPORT_JSON as SANDBOX_REPORT_JSON
from verify_ocr_answer_mode_patch_sandbox_apply import main as verify_sandbox_apply
from verify_ocr_draft_answer_mode_combined_policy import REPORT_JSON as COMBINED_REPORT_JSON
from verify_ocr_draft_answer_mode_combined_policy import main as verify_combined_policy

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_answer_mode_pre_apply_gate.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_answer_mode_pre_apply_gate.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
VerifierAction: TypeAlias = Callable[[], int]


@dataclass(frozen=True, slots=True)
class PreApplyGateError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    run_verifier("combined answer-mode policy", verify_combined_policy)
    run_verifier("sandbox patch apply", verify_sandbox_apply)
    combined = require_object(load_json(COMBINED_REPORT_JSON), "combined report")
    sandbox = require_object(load_json(SANDBOX_REPORT_JSON), "sandbox report")
    output = pre_apply_summary(combined, sandbox)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def run_verifier(label: str, action: "VerifierAction") -> None:
    result = action()
    if result != 0:
        raise PreApplyGateError(f"{label} failed with exit code {result}")


def pre_apply_summary(combined: JsonObject, sandbox: JsonObject) -> JsonObject:
    assert_common_zero_counts(combined, "combined")
    assert_common_zero_counts(sandbox, "sandbox")
    require_true(combined.get("runtime_patch_ready_to_apply_when_approved"), "combined.runtime_patch_ready")
    for key in ("runtime_patch_server_anchor_present", "runtime_patch_ui_anchor_present", "runtime_patch_preflight_anchor_present"):
        require_true(combined.get(key), f"combined.{key}")
    require_int_value(combined.get("runtime_patch_server_targets_already_present_count"), 0, "combined.server_targets_already_present")
    require_int_value(combined.get("runtime_patch_ui_targets_already_present_count"), 0, "combined.ui_targets_already_present")
    require_false(combined.get("runtime_patch_preflight_check_already_present"), "combined.preflight_check_already_present")
    require_int_value(sandbox.get("target_count"), 5, "sandbox.target_count")
    for key in ("sandbox_server_compile_passed", "sandbox_ui_node_check_passed", "sandbox_preflight_compile_passed"):
        require_true(sandbox.get(key), f"sandbox.{key}")
    require_false(sandbox.get("runtime_files_modified"), "sandbox.runtime_files_modified")
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "ready_to_apply_when_approved": True,
        "target_count": 5,
        "combined_runtime_gap_count": require_int(combined.get("mijeok1_runtime_gap_count"), "combined.mijeok1_gap")
        + require_int(combined.get("training_pack_runtime_gap_count"), "combined.training_pack_gap"),
        "post_approval_invalid_choice_blocked_count": require_int(
            combined.get("post_approval_invalid_choice_blocked_count"),
            "combined.invalid_choice_blocked",
        ),
        "post_approval_valid_answer_value_safe_count": require_int(
            combined.get("post_approval_valid_answer_value_safe_count"),
            "combined.valid_answer_value_safe",
        ),
        "sandbox_server_compile_passed": True,
        "sandbox_ui_node_check_passed": True,
        "sandbox_preflight_compile_passed": True,
        "protected_runtime_files_modified": False,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    assert_common_zero_counts(output, "output")
    return output


def assert_common_zero_counts(payload: JsonObject, label: str) -> None:
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(payload.get(key), 0, f"{label}.{key}")
    require_false(payload.get("student_facing"), f"{label}.student_facing")
    if payload.get("production_default") != "NO_GO":
        raise PreApplyGateError(f"{label}.production_default must be NO_GO")
    require_int_value(payload.get("answer_key_or_grading_field_leak_count"), 0, f"{label}.answer_key_or_grading_field_leak_count")
    require_int_value(payload.get("filesystem_path_leak_count"), 0, f"{label}.filesystem_path_leak_count")


def load_json(path: Path) -> JsonValue:
    return json.loads(path.read_text(encoding="utf-8"))


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise PreApplyGateError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise PreApplyGateError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise PreApplyGateError(f"{label} must be {expected}, got {actual}")


def require_true(value: JsonValue, label: str) -> None:
    if value is not True:
        raise PreApplyGateError(f"{label} must be true")


def require_false(value: JsonValue, label: str) -> None:
    if value is not False:
        raise PreApplyGateError(f"{label} must be false")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Answer Mode Pre-Apply Gate",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        "- ready to apply when approved: true",
        f"- mapping targets: {output['target_count']}",
        f"- current runtime gap covered by proposed patch: {output['combined_runtime_gap_count']}",
        f"- post-approval invalid choice cases blocked: {output['post_approval_invalid_choice_blocked_count']}",
        "- sandbox server compile passed: true",
        "- sandbox hidden OCR UI node check passed: true",
        "- sandbox preflight compile passed: true",
        "- protected runtime files modified: false",
        "- answer-key/grading/path leak count: 0",
        "",
        "This gate is provider-free approval evidence. It does not apply the runtime patch.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
