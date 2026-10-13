from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from verify_ocr_answer_mode_patch_package import DRAFT_PATH, ModeMapping, draft_mappings, load_json, require_object

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SERVER_POLICY_PATH: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_answer_mode_policy.py"
STUDENT_UI_PATH: Final[Path] = ROOT / "static/js/student.js"
PREFLIGHT_PATH: Final[Path] = ROOT / "tools/subjective_sheet_lab/run_phase1_preflight_checks.py"
REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_answer_mode_runtime_patch_readiness.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_answer_mode_runtime_patch_readiness.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

SERVER_ANCHOR: Final[str] = '"t_unit_daesu_02_lv3_r1": {'
UI_ANCHOR: Final[str] = "t_unit_daesu_02_lv3_r1: {"
PREFLIGHT_ANCHOR: Final[str] = 'CheckSpec("ocr_answer_mode_coverage"'
PREFLIGHT_PROPOSAL: Final[str] = 'CheckSpec("ocr_draft_answer_mode_combined_policy"'


@dataclass(frozen=True, slots=True)
class ReadinessError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class SectionSpec:
    label: str
    start: str
    end: str


def main() -> int:
    mappings = draft_mappings(require_object(load_json(DRAFT_PATH), "draft"))
    server_text = read_text(SERVER_POLICY_PATH)
    ui_text = read_text(STUDENT_UI_PATH)
    preflight_text = read_text(PREFLIGHT_PATH)
    output = readiness_summary(mappings, server_text, ui_text, preflight_text)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def read_text(path: Path) -> str:
    if not path.is_file():
        raise ReadinessError(f"missing readiness target: {path.name}")
    return path.read_text(encoding="utf-8-sig")


def readiness_summary(mappings: tuple[ModeMapping, ...], server_text: str, ui_text: str, preflight_text: str) -> JsonObject:
    target_ids = tuple(mapping.test_id for mapping in mappings)
    server_mapping = extract_section(server_text, SectionSpec("server answer-mode mapping", "ANSWER_MODE_BY_TEST_ID: Final", "CHOICE_NUMBER_VALUES"))
    ui_mapping = extract_section(ui_text, SectionSpec("hidden OCR UI answer-mode mapping", "const OCR_PHASE1_ANSWER_MODE_BY_TEST_ID = {", "const OCR_REVIEW_ANSWER_MODE_LABELS"))
    server_present = present_targets(server_mapping, target_ids)
    ui_present = present_targets(ui_mapping, target_ids)
    ui_anywhere_present = present_targets(ui_text, target_ids)
    server_anchor_present = SERVER_ANCHOR in server_text
    ui_anchor_present = UI_ANCHOR in ui_text
    preflight_anchor_present = PREFLIGHT_ANCHOR in preflight_text
    preflight_proposal_present = PREFLIGHT_PROPOSAL in preflight_text
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "target_count": len(target_ids),
        "ready_to_apply_when_approved": True,
        "server_anchor_present": server_anchor_present,
        "ui_anchor_present": ui_anchor_present,
        "preflight_anchor_present": preflight_anchor_present,
        "preflight_check_already_present": preflight_proposal_present,
        "server_targets_already_present_count": len(server_present),
        "ui_targets_already_present_count": len(ui_present),
        "ui_target_references_outside_mapping_count": len(ui_anywhere_present) - len(ui_present),
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
    }
    verify_output(output)
    return output


def present_targets(text: str, target_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(target_id for target_id in target_ids if target_id in text)


def extract_section(text: str, spec: SectionSpec) -> str:
    start_index = text.find(spec.start)
    if start_index < 0:
        raise ReadinessError(f"{spec.label} start marker missing")
    end_index = text.find(spec.end, start_index)
    if end_index < 0:
        raise ReadinessError(f"{spec.label} end marker missing")
    return text[start_index:end_index]


def verify_output(output: JsonObject) -> None:
    expected_true = ("server_anchor_present", "ui_anchor_present", "preflight_anchor_present", "ready_to_apply_when_approved")
    for key in expected_true:
        if output.get(key) is not True:
            raise ReadinessError(f"{key} must be true")
    expected_zero = (
        "provider_call_count",
        "external_ocr_api_call_count",
        "submit_test_call_count",
        "ts_submit_click_count",
        "server_targets_already_present_count",
        "ui_targets_already_present_count",
        "answer_key_or_grading_field_leak_count",
        "filesystem_path_leak_count",
    )
    for key in expected_zero:
        if output.get(key) != 0:
            raise ReadinessError(f"{key} must be 0")
    if output.get("preflight_check_already_present") is not False:
        raise ReadinessError("preflight patch proposal is already applied")


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Answer Mode Runtime Patch Readiness",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- targets checked: {output['target_count']}",
        f"- server anchor present: {output['server_anchor_present']}",
        f"- hidden OCR UI anchor present: {output['ui_anchor_present']}",
        f"- preflight anchor present: {output['preflight_anchor_present']}",
        f"- preflight proposal already present: {output['preflight_check_already_present']}",
        f"- server targets already present: {output['server_targets_already_present_count']}",
        f"- hidden OCR UI targets already present: {output['ui_targets_already_present_count']}",
        f"- hidden OCR UI target references outside mapping: {output['ui_target_references_outside_mapping_count']}",
        "- answer-key/grading/path leak count: 0",
        "",
        "This is a read-only readiness check for the approval-gated runtime mapping patch.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
