# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_q003_signal_audit.py

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_preprocess_variants import ImageArray, OpenCvModule, read_grayscale_crop, require_cv2  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_postprocessing_gate_matrix import item_for, warning_tuple  # noqa: E402
from tools.subjective_sheet_lab.verify_ocr_priority_digit_shape_scores import ShapeSummary, shape_summary  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CROP_ROOT: Final[Path] = Path("C:/server-ocr/crop_benchmark_inputs")
ARTIFACT_DIR: Final[Path] = ROOT / "tools/subjective_sheet_lab/visual_evidence/q003_signal_audit"
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_q003_signal_audit.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_q003_signal_audit.md"
CONTACT_SHEET_FILE: Final[str] = "q003_signal_audit_contact.png"
FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "grading", "C:\\", "C:/", "/c/")


@dataclass(frozen=True, slots=True)
class AuditCase:
    case_id: str
    probe_text: str
    required_status: str
    required_signal: str
    interpretation: str


@dataclass(frozen=True, slots=True)
class AuditResult:
    case_id: str
    probe_text: str
    status: str
    final_answer: str | None
    warnings: tuple[str, ...]
    cluster_component_count: int
    leading_holes: int
    leading_right_bias: float
    signal_flags: tuple[str, ...]
    interpretation: str


class Q003SignalAuditError(Exception):
    pass


def main() -> int:
    cv2 = require_cv2()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    results = [audit_case(cv2, case) for case in audit_cases()]
    write_contact_sheet(cv2, results)
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "answer_key_used": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "case_count": len(results),
        "review_required_count": sum(1 for result in results if result.status == "review_required"),
        "safe_auto_grade_count": sum(1 for result in results if result.status == "safe_auto_grade"),
        "three_n_signal_count": sum(1 for result in results if "three_n_shape_conflict" in result.signal_flags),
        "visual_evidence_file": CONTACT_SHEET_FILE,
        "results": [asdict(result) for result in results],
    }
    leak_text = json.dumps(output, ensure_ascii=False)
    if leak_count(leak_text) != 0:
        raise Q003SignalAuditError("sensitive field or path token leaked into output")
    output["answer_key_or_grading_field_leak_count"] = 0
    output["filesystem_path_leak_count"] = 0
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(results), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def audit_cases() -> tuple[AuditCase, ...]:
    return (
        AuditCase("person_02_tilted", "x->n", "review_required", "three_n_shape_conflict", "useful_review_signal"),
        AuditCase("person_02_good", "x->n", "review_required", "", "relation_policy_covers_no_shape_signal"),
        AuditCase("person_03", "n", "review_required", "three_n_shape_conflict", "three_n_confusion_blocks_autofill"),
        AuditCase("person_03", "3", "safe_auto_grade", "three_n_shape_conflict", "clean_digit_text_stays_fillable"),
    )


def audit_case(cv2: OpenCvModule, case: AuditCase) -> AuditResult:
    summary = crop_shape_summary(cv2, case.case_id)
    item = item_for(3, case.probe_text)
    status = text_value(item.get("status"))
    final_answer = nullable_text(item.get("final_answer"))
    warnings = warning_tuple(item)
    if status != case.required_status:
        raise Q003SignalAuditError(f"{case.case_id}:{case.probe_text} status {status} != {case.required_status}")
    if case.required_status != "safe_auto_grade" and final_answer is not None:
        raise Q003SignalAuditError(f"{case.case_id}:{case.probe_text} kept final answer")
    if case.required_signal and case.required_signal not in summary.signal_flags:
        raise Q003SignalAuditError(f"{case.case_id}:{case.probe_text} missing signal {case.required_signal}")
    return AuditResult(
        case_id=case.case_id,
        probe_text=case.probe_text,
        status=status,
        final_answer=final_answer,
        warnings=warnings,
        cluster_component_count=summary.cluster_component_count,
        leading_holes=summary.leading_holes,
        leading_right_bias=summary.leading_right_bias,
        signal_flags=summary.signal_flags,
        interpretation=case.interpretation,
    )


def crop_shape_summary(cv2: OpenCvModule, case_id: str) -> ShapeSummary:
    return shape_summary(cv2, read_grayscale_crop(cv2, CROP_ROOT / case_id / "crops/q003.png"))


def write_contact_sheet(cv2: OpenCvModule, results: list[AuditResult]) -> None:
    panels = tuple(panel_image(cv2, result) for result in results[:3])
    height = max(panel.shape[0] for panel in panels)
    width = sum(panel.shape[1] for panel in panels)
    sheet = cv2.cvtColor(blank_image(height, width), cv2.COLOR_GRAY2BGR)
    x_offset = 0
    for panel in panels:
        panel_height, panel_width = panel.shape[:2]
        sheet[:panel_height, x_offset : x_offset + panel_width] = panel
        x_offset += panel_width
    if not cv2.imwrite(str(ARTIFACT_DIR / CONTACT_SHEET_FILE), sheet):
        raise Q003SignalAuditError("failed to write q003 contact sheet")


def panel_image(cv2: OpenCvModule, result: AuditResult) -> ImageArray:
    gray = read_grayscale_crop(cv2, CROP_ROOT / result.case_id / "crops/q003.png")
    label_height = 42
    panel = cv2.cvtColor(blank_image(gray.shape[0] + label_height, gray.shape[1]), cv2.COLOR_GRAY2BGR)
    panel[label_height:, :] = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.putText(panel, f"{result.case_id} {result.probe_text} {result.status}", (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    return panel


def blank_image(height: int, width: int) -> ImageArray:
    import numpy as np

    return np.full((height, width), 255, dtype=np.uint8)


def markdown_report(results: list[AuditResult]) -> str:
    lines = [
        "# OCR q003 Signal Audit",
        "",
        "Provider-free audit for q003 three/n and relation-like handwriting signals.",
        "",
        f"- Visual evidence: `{CONTACT_SHEET_FILE}`",
        "",
        "| Case | Probe | Status | Warnings | Signal | Interpretation |",
        "|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| `{result.case_id}` | `{result.probe_text}` | `{result.status}` | "
            f"`{', '.join(result.warnings)}` | `{', '.join(result.signal_flags)}` | `{result.interpretation}` |"
        )
    lines.extend(("", "- Gemini/API calls: 0", "- External OCR API calls: 0", "- `/api/submit-test` calls: 0", "- `#tsSubmit` clicks: 0"))
    return "\n".join(lines) + "\n"


def nullable_text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""


def leak_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for token in FORBIDDEN_OUTPUT_TOKENS if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
