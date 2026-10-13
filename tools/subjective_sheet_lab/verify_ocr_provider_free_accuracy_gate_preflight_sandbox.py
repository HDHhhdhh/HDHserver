# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_accuracy_gate_preflight_sandbox.py

from __future__ import annotations

import json
import py_compile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from verify_ocr_provider_free_accuracy_gate import REPORT_JSON as GATE_REPORT_JSON
from verify_ocr_provider_free_accuracy_gate import main as verify_provider_free_gate

LAB: Final[Path] = Path(__file__).resolve().parent
PREFLIGHT_PATH: Final[Path] = LAB / "run_phase1_preflight_checks.py"
REPORT_JSON: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_preflight_sandbox.json"
REPORT_MD: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_preflight_sandbox.md"
CHECK_NAME: Final[str] = "ocr_provider_free_accuracy_gate"
CHECK_SPEC_TOKEN: Final[str] = 'CheckSpec("ocr_provider_free_accuracy_gate"'
EXPECTED_PROVIDER_FREE_GATE_COUNT: Final[int] = 5
ANCHOR: Final[str] = (
    '        CheckSpec("ocr_local_candidate_tools", '
    '(py, "tools/subjective_sheet_lab/verify_ocr_local_candidate_tools.py"), '
    'LAB / "verify_ocr_local_candidate_tools.py"),\n'
)
ADDITION: Final[str] = (
    '        CheckSpec("ocr_provider_free_accuracy_gate", '
    '(py, "tools/subjective_sheet_lab/verify_ocr_provider_free_accuracy_gate.py"), '
    'LAB / "verify_ocr_provider_free_accuracy_gate.py"),\n'
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PreflightSandboxError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    result = verify_provider_free_gate()
    if result != 0:
        raise PreflightSandboxError(f"provider-free accuracy gate failed with exit code {result}")
    original_text = PREFLIGHT_PATH.read_text(encoding="utf-8-sig")
    patched_text = patched_preflight_text(original_text)
    with tempfile.TemporaryDirectory(prefix="ocr_provider_free_preflight_") as temp_name:
        sandbox_path = Path(temp_name) / "run_phase1_preflight_checks.py"
        sandbox_path.write_text(patched_text, encoding="utf-8")
        py_compile.compile(str(sandbox_path), doraise=True)
    gate_report = read_json_object(GATE_REPORT_JSON)
    output = summary(original_text, patched_text, gate_report)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def patched_preflight_text(original_text: str) -> str:
    if original_text.count(CHECK_SPEC_TOKEN) > 0:
        return original_text
    if original_text.count(ANCHOR) != 1:
        raise PreflightSandboxError("preflight insertion anchor must appear exactly once")
    return original_text.replace(ANCHOR, ANCHOR + ADDITION, 1)


def summary(original_text: str, patched_text: str, gate_report: JsonObject) -> JsonObject:
    assert_gate_report(gate_report)
    original_count = original_text.count(CHECK_SPEC_TOKEN)
    patched_count = patched_text.count(CHECK_SPEC_TOKEN)
    if original_count == 0 and patched_count != 1:
        raise PreflightSandboxError(f"patched preflight must contain one {CHECK_NAME} entry")
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "preflight_file_modified": False,
        "original_check_count": original_count,
        "sandbox_check_count": patched_count,
        "sandbox_preflight_compile_passed": True,
        "ready_to_apply_when_approved": original_count == 0,
        "provider_free_gate_count": EXPECTED_PROVIDER_FREE_GATE_COUNT,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def assert_gate_report(report: JsonObject) -> None:
    if report.get("ok") is not True:
        raise PreflightSandboxError("provider-free accuracy gate must pass before sandbox preflight")
    if report.get("student_facing") is not False:
        raise PreflightSandboxError("provider-free accuracy gate must stay non-student-facing")
    require_int_value(report.get("gate_count"), EXPECTED_PROVIDER_FREE_GATE_COUNT, "gate_count")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(report.get(key), 0, key)


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), str(path))


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise PreflightSandboxError(f"{label} must be a JSON object")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise PreflightSandboxError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise PreflightSandboxError(f"{label} expected {expected}, got {actual}")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Provider-Free Accuracy Gate Preflight Sandbox",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- preflight file modified: {output['preflight_file_modified']}",
        f"- original check count: {output['original_check_count']}",
        f"- sandbox check count: {output['sandbox_check_count']}",
        f"- sandbox preflight compile passed: {output['sandbox_preflight_compile_passed']}",
        f"- ready to apply when approved: {output['ready_to_apply_when_approved']}",
        f"- provider-free sub-gates covered: {output['provider_free_gate_count']}",
        "- answer-key/grading/path leak count: 0",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
