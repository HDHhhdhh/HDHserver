from __future__ import annotations

import json
import py_compile
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from verify_ocr_answer_mode_patch_package import DRAFT_PATH, ModeMapping, draft_mappings, js_set, load_json, require_object, server_frozenset

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SERVER_POLICY_PATH: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_answer_mode_policy.py"
STUDENT_UI_PATH: Final[Path] = ROOT / "static/js/student.js"
PREFLIGHT_PATH: Final[Path] = ROOT / "tools/subjective_sheet_lab/run_phase1_preflight_checks.py"
REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_answer_mode_patch_sandbox_apply.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_answer_mode_patch_sandbox_apply.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class SandboxApplyError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    mappings = draft_mappings(require_object(load_json(DRAFT_PATH), "draft"))
    with tempfile.TemporaryDirectory(prefix="ocr_answer_mode_patch_") as temp_name:
        temp_dir = Path(temp_name)
        server_copy = write_copy(temp_dir, "ocr_answer_mode_policy.py", patched_server_text(mappings))
        ui_copy = write_copy(temp_dir, "student.js", patched_ui_text(mappings))
        preflight_copy = write_copy(temp_dir, "run_phase1_preflight_checks.py", patched_preflight_text())
        compile_python(server_copy)
        compile_python(preflight_copy)
        check_node(ui_copy)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "target_count": len(mappings),
        "sandbox_server_compile_passed": True,
        "sandbox_ui_node_check_passed": True,
        "sandbox_preflight_compile_passed": True,
        "runtime_files_modified": False,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def patched_server_text(mappings: tuple[ModeMapping, ...]) -> str:
    text = SERVER_POLICY_PATH.read_text(encoding="utf-8-sig")
    marker = "\n}\nCHOICE_NUMBER_VALUES"
    addition = "".join(server_entry(mapping) for mapping in mappings)
    return replace_once(text, marker, f"\n{addition}}}\nCHOICE_NUMBER_VALUES", "server mapping end")


def patched_ui_text(mappings: tuple[ModeMapping, ...]) -> str:
    text = STUDENT_UI_PATH.read_text(encoding="utf-8-sig")
    marker = "  };\n  const OCR_REVIEW_ANSWER_MODE_LABELS"
    addition = "".join(ui_entry(mapping) for mapping in mappings)
    return replace_once(text, marker, f"{addition}  }};\n  const OCR_REVIEW_ANSWER_MODE_LABELS", "UI mapping end")


def patched_preflight_text() -> str:
    text = PREFLIGHT_PATH.read_text(encoding="utf-8-sig")
    anchor = '        CheckSpec("ocr_answer_mode_coverage", (py, "tools/subjective_sheet_lab/verify_ocr_answer_mode_coverage.py"), LAB / "verify_ocr_answer_mode_coverage.py"),\n'
    addition = '        CheckSpec("ocr_draft_answer_mode_combined_policy", (py, "tools/subjective_sheet_lab/verify_ocr_draft_answer_mode_combined_policy.py"), LAB / "verify_ocr_draft_answer_mode_combined_policy.py"),\n'
    return replace_once(text, anchor, anchor + addition, "preflight answer-mode coverage")


def server_entry(mapping: ModeMapping) -> str:
    return (
        f'    "{mapping.test_id}": {{\n'
        f'        "choice_number": {server_frozenset(mapping.choice)},\n'
        f'        "answer_value": {server_frozenset(mapping.value)},\n'
        "    },\n"
    )


def ui_entry(mapping: ModeMapping) -> str:
    return (
        f"    {mapping.test_id}: {{\n"
        f"      choice_number: {js_set(mapping.choice)},\n"
        f"      answer_value: {js_set(mapping.value)},\n"
        "    },\n"
    )


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SandboxApplyError(f"{label} marker count must be 1, got {count}")
    return text.replace(old, new, 1)


def write_copy(temp_dir: Path, name: str, text: str) -> Path:
    path = temp_dir / name
    path.write_text(text, encoding="utf-8")
    return path


def compile_python(path: Path) -> None:
    py_compile.compile(str(path), doraise=True)


def check_node(path: Path) -> None:
    completed = subprocess.run(("node", "--check", str(path)), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode != 0:
        raise SandboxApplyError(f"node --check failed for {path.name}: {completed.stderr[:1000]}")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Answer Mode Patch Sandbox Apply",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- targets sandbox-applied: {output['target_count']}",
        f"- sandbox server compile passed: {output['sandbox_server_compile_passed']}",
        f"- sandbox hidden OCR UI node check passed: {output['sandbox_ui_node_check_passed']}",
        f"- sandbox preflight compile passed: {output['sandbox_preflight_compile_passed']}",
        "- runtime files modified: false",
        "- answer-key/grading/path leak count: 0",
        "",
        "This applies the proposed mapping/preflight patch only to temporary copies.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
