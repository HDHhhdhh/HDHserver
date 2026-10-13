# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_high_priority_mismatch_crop_quality.py

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_preprocess_variants import image_metrics, read_grayscale_crop, require_cv2  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CROP_ROOT: Final[Path] = Path("C:/server-ocr/crop_benchmark_inputs")
PRIORITIES_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_accuracy_improvement_priorities.json"
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_high_priority_mismatch_crop_quality.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_high_priority_mismatch_crop_quality.md"
TARGETS: Final[tuple[tuple[str, str, int], ...]] = (
    ("person_02_same_contact", "person_02", 15),
    ("person_02_same_contact", "person_02", 16),
    ("person_03_same_contact", "person_03", 3),
    ("person_03_same_contact", "person_03", 18),
)


@dataclass(frozen=True, slots=True)
class CropQualityRow:
    case_id: str
    question_no: int
    issue_type: str
    recognized: str
    human_answer: str
    policy_status: str
    width: int
    height: int
    blur_variance: float
    brightness_std: float
    ink_density: float
    border_ink_ratio: float
    quality_warnings: tuple[str, ...]
    diagnosis: str
    auto_fill_allowed: bool


class HighPriorityCropQualityError(Exception):
    pass


def main() -> int:
    rows = build_rows()
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "target_count": len(rows),
        "review_required_count": sum(1 for row in rows if row.policy_status == "review_required"),
        "auto_fill_allowed_count": sum(1 for row in rows if row.auto_fill_allowed),
        "quality_warning_row_count": sum(1 for row in rows if row.quality_warnings),
        "relation_operator_row_count": sum(1 for row in rows if row.diagnosis == "relation_operator_review_required"),
        "digit_shape_row_count": sum(1 for row in rows if row.diagnosis == "digit_shape_review_required"),
        "rows": [asdict(row) for row in rows],
    }
    output["sensitive_field_leak_count"] = sensitive_leak_count(json.dumps(output, ensure_ascii=False))
    output["filesystem_path_leak_count"] = filesystem_path_leak_count(json.dumps(output, ensure_ascii=False))
    require_output(output)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(rows), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def build_rows() -> list[CropQualityRow]:
    cv2 = require_cv2()
    priority_rows = priority_rows_by_key()
    rows: list[CropQualityRow] = []
    for case_id, crop_case, question_no in TARGETS:
        source = priority_rows[(case_id, question_no)]
        metrics = image_metrics(cv2, read_grayscale_crop(cv2, CROP_ROOT / crop_case / "crops" / f"q{question_no:03d}.png"))
        row = crop_quality_row(case_id, question_no, source, metrics)
        if row.policy_status != "review_required":
            raise HighPriorityCropQualityError(f"{case_id} q{question_no:03d} must stay review_required")
        rows.append(row)
    return rows


def crop_quality_row(case_id: str, question_no: int, source: JsonObject, metrics: JsonObject) -> CropQualityRow:
    warnings = warning_tuple(metrics)
    return CropQualityRow(
        case_id=case_id,
        question_no=question_no,
        issue_type=text_value(source.get("issue_type"), "issue_type"),
        recognized=text_value(source.get("recognized"), "recognized"),
        human_answer=text_value(source.get("human_answer"), "human_answer"),
        policy_status=text_value(source.get("policy_status"), "policy_status"),
        width=int_value(metrics.get("width"), "width"),
        height=int_value(metrics.get("height"), "height"),
        blur_variance=number_value(metrics.get("blur_variance"), "blur_variance"),
        brightness_std=number_value(metrics.get("brightness_std"), "brightness_std"),
        ink_density=number_value(metrics.get("ink_density"), "ink_density"),
        border_ink_ratio=number_value(metrics.get("border_ink_ratio"), "border_ink_ratio"),
        quality_warnings=warnings,
        diagnosis=diagnosis_for(question_no, warnings),
        auto_fill_allowed=False,
    )


def priority_rows_by_key() -> dict[tuple[str, int], JsonObject]:
    payload = read_json_object(PRIORITIES_JSON)
    rows = array_value(payload.get("top_row_priorities"), "top_row_priorities")
    indexed: dict[tuple[str, int], JsonObject] = {}
    for row in rows:
        item = object_value(row, "top_row_priorities[]")
        key = (text_value(item.get("case_id"), "case_id"), int_value(item.get("question_no"), "question_no"))
        indexed[key] = item
    missing = [f"{case_id} q{question_no:03d}" for case_id, _, question_no in TARGETS if (case_id, question_no) not in indexed]
    if missing:
        raise HighPriorityCropQualityError(f"missing priority rows: {', '.join(missing)}")
    return indexed


def diagnosis_for(question_no: int, warnings: tuple[str, ...]) -> str:
    if warnings:
        return "quality_gate_review_required"
    if question_no in (15, 16):
        return "relation_operator_review_required"
    return "digit_shape_review_required"


def markdown_report(rows: list[CropQualityRow]) -> str:
    lines = [
        "# OCR High Priority Mismatch Crop Quality",
        "",
        "| case | q | OCR | human | diagnosis | warnings |",
        "|---|---:|---|---|---|---|",
    ]
    for row in rows:
        warnings = ", ".join(row.quality_warnings)
        lines.append(f"| `{row.case_id}` | {row.question_no} | `{row.recognized}` | `{row.human_answer}` | `{row.diagnosis}` | `{warnings}` |")
    lines.extend(("", "- Gemini/API calls: 0", "- `/api/submit-test` calls: 0", "- `#tsSubmit` clicks: 0", "- Auto-fill allowed rows: 0", ""))
    return "\n".join(lines)


def require_output(output: JsonObject) -> None:
    if output["auto_fill_allowed_count"] != 0:
        raise HighPriorityCropQualityError("high-priority mismatches must not auto-fill")
    if output["target_count"] != 4 or output["review_required_count"] != 4:
        raise HighPriorityCropQualityError("high-priority mismatch target coverage changed")
    if output["sensitive_field_leak_count"] != 0 or output["filesystem_path_leak_count"] != 0:
        raise HighPriorityCropQualityError("sensitive token leaked into output")


def sensitive_leak_count(text: str) -> int:
    forbidden = ("expected", "canonical_answer", "accepted_answers", "correct", "incorrect", "grading")
    return sum(text.count(token) for token in forbidden)


def filesystem_path_leak_count(text: str) -> int:
    return text.count("C:\\") + text.count("C:/") + text.count("/c/")


def read_json_object(path: Path) -> JsonObject:
    return object_value(json.loads(path.read_text(encoding="utf-8-sig")), path.name)


def object_value(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise HighPriorityCropQualityError(f"{label} must be an object")
    return value


def array_value(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise HighPriorityCropQualityError(f"{label} must be an array")
    return value


def text_value(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise HighPriorityCropQualityError(f"{label} must be text")
    return value


def int_value(value: JsonValue, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise HighPriorityCropQualityError(f"{label} must be an integer")
    return value


def number_value(value: JsonValue, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise HighPriorityCropQualityError(f"{label} must be numeric")
    return float(value)


def warning_tuple(metrics: JsonObject) -> tuple[str, ...]:
    warnings = array_value(metrics.get("warnings"), "metrics.warnings")
    return tuple(text_value(item, "metrics.warnings[]") for item in warnings)


if __name__ == "__main__":
    raise SystemExit(main())
