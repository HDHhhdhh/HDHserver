# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_provider_free_accuracy_gate_preflight_readiness.py

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias, assert_never

from ocr_provider_free_extended_gate_count import EXTENDED_GATE_COUNT
from verify_ocr_provider_free_accuracy_gate_extended import REPORT_JSON as GATE_REPORT_JSON

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
LAB: Final[Path] = Path(__file__).resolve().parent
OCR_VENV_PYTHON: Final[Path] = Path("C:/server-ocr/.venv/Scripts/python.exe")
PREFLIGHT_PATH: Final[Path] = LAB / "run_phase1_preflight_checks.py"
GATE_PATH: Final[Path] = LAB / "verify_ocr_provider_free_accuracy_gate_extended.py"
REPORT_JSON: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_preflight_readiness.json"
REPORT_MD: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_preflight_readiness.md"
PATCH_PATH: Final[Path] = LAB / "ocr_provider_free_accuracy_gate_preflight_proposed.patch"
CHECK_NAME: Final[str] = "ocr_provider_free_accuracy_gate_extended"
EXPECTED_EXTENDED_GATE_COUNT: Final[int] = EXTENDED_GATE_COUNT
EXPECTED_BASE_GATE_COUNT: Final[int] = 5
EXPECTED_COPY_CHECKLIST_ACTIONS: Final[int] = 4

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PreflightReadinessError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    run_provider_free_gate()
    gate_report = read_json_object(GATE_REPORT_JSON)
    preflight_text = PREFLIGHT_PATH.read_text(encoding="utf-8-sig")
    patch_text = proposed_patch(preflight_text)
    PATCH_PATH.write_text(patch_text, encoding="utf-8")
    output = readiness_summary(gate_report, preflight_text)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def run_provider_free_gate() -> None:
    completed = subprocess.run(
        (str(gate_python()), str(GATE_PATH)),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PreflightReadinessError(f"provider-free accuracy gate failed with exit code {completed.returncode}")


def gate_python() -> Path:
    if OCR_VENV_PYTHON.is_file():
        return OCR_VENV_PYTHON
    return Path(sys.executable)


def readiness_summary(gate_report: JsonObject, preflight_text: str) -> JsonObject:
    assert_gate_report(gate_report)
    gate_in_preflight = CHECK_NAME in preflight_text
    anchor_present = preflight_anchor() in preflight_text
    if not anchor_present:
        raise PreflightReadinessError("preflight insertion anchor missing")
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "gate_script_exists": GATE_PATH.is_file(),
        "preflight_file_modified": False,
        "preflight_check_already_present": gate_in_preflight,
        "ready_to_add_when_approved": not gate_in_preflight,
        "proposed_patch_path": PATCH_PATH.name,
        "proposed_check_name": CHECK_NAME,
        "proposed_required_path": "tools/subjective_sheet_lab/verify_ocr_provider_free_accuracy_gate_extended.py",
        "provider_free_base_gate_count": EXPECTED_BASE_GATE_COUNT,
        "provider_free_extended_gate_count": EXPECTED_EXTENDED_GATE_COUNT,
        "operator_copy_checklist_action_required_count": EXPECTED_COPY_CHECKLIST_ACTIONS,
        "operator_copy_checklist_ready": False,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }


def assert_gate_report(report: JsonObject) -> None:
    if report.get("ok") is not True:
        raise PreflightReadinessError("provider-free accuracy gate report is not ok")
    if report.get("student_facing") is not False:
        raise PreflightReadinessError("provider-free accuracy gate must remain non-student-facing")
    if report.get("production_default") != "NO_GO":
        raise PreflightReadinessError("production default must remain NO_GO")
    require_int_value(report.get("base_gate_count"), EXPECTED_BASE_GATE_COUNT, "base_gate_count")
    require_int_value(report.get("extended_gate_count"), EXPECTED_EXTENDED_GATE_COUNT, "extended_gate_count")
    require_int_value(
        report.get("training_pack_operator_copy_checklist_action_required_count"),
        EXPECTED_COPY_CHECKLIST_ACTIONS,
        "training_pack_operator_copy_checklist_action_required_count",
    )
    if report.get("training_pack_operator_copy_checklist_ready") is not False:
        raise PreflightReadinessError("operator copy checklist must remain blocked until evidence files exist")
    for key in ("provider_call_count", "external_ocr_api_call_count", "submit_test_call_count", "ts_submit_click_count"):
        require_int_value(report.get(key), 0, key)
    require_int_value(report.get("answer_key_or_grading_field_leak_count"), 0, "answer_key_or_grading_field_leak_count")
    require_int_value(report.get("filesystem_path_leak_count"), 0, "filesystem_path_leak_count")


def proposed_patch(preflight_text: str) -> str:
    anchor = preflight_anchor()
    if anchor not in preflight_text:
        raise PreflightReadinessError("preflight anchor missing")
    addition = (
        '        CheckSpec("ocr_provider_free_accuracy_gate_extended", '
        '(py, "tools/subjective_sheet_lab/verify_ocr_provider_free_accuracy_gate_extended.py"), '
        'LAB / "verify_ocr_provider_free_accuracy_gate_extended.py"),\n'
    )
    return "".join(
        (
            "*** Begin Patch\n",
            "*** Update File: C:\\server\\tools\\subjective_sheet_lab\\run_phase1_preflight_checks.py\n",
            "@@\n",
            anchor,
            "+",
            addition,
            "*** End Patch\n",
        )
    )


def preflight_anchor() -> str:
    return '        CheckSpec("ocr_local_candidate_tools", (py, "tools/subjective_sheet_lab/verify_ocr_local_candidate_tools.py"), LAB / "verify_ocr_local_candidate_tools.py"),\n'


def read_json_object(path: Path) -> JsonObject:
    return require_object(json.loads(path.read_text(encoding="utf-8-sig")), str(path))


def require_object(value: JsonValue, label: str) -> JsonObject:
    match value:
        case dict():
            return value
        case None | bool() | int() | float() | str() | list():
            raise PreflightReadinessError(f"{label} must be a JSON mapping")
        case unreachable:
            assert_never(unreachable)


def require_int(value: JsonValue, label: str) -> int:
    match value:
        case int() if not isinstance(value, bool):
            return value
        case None | bool() | float() | str() | list() | dict():
            raise PreflightReadinessError(f"{label} must be an integer")
        case unreachable:
            assert_never(unreachable)


def require_int_value(value: JsonValue, expected: int, label: str) -> None:
    actual = require_int(value, label)
    if actual != expected:
        raise PreflightReadinessError(f"{label} expected {expected}, got {actual}")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Provider-Free Accuracy Gate Preflight Readiness",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- gate script exists: {output['gate_script_exists']}",
        f"- preflight file modified: {output['preflight_file_modified']}",
        f"- preflight check already present: {output['preflight_check_already_present']}",
        f"- ready to add when approved: {output['ready_to_add_when_approved']}",
        f"- proposed patch: `{output['proposed_patch_path']}`",
        f"- proposed check name: `{output['proposed_check_name']}`",
        f"- provider-free base gates covered: {output['provider_free_base_gate_count']}",
        f"- provider-free extended gates covered: {output['provider_free_extended_gate_count']}",
        f"- operator copy checklist actions required: {output['operator_copy_checklist_action_required_count']}",
        f"- operator copy checklist ready: {output['operator_copy_checklist_ready']}",
        "- answer-key/grading/path leak count: 0",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
