from __future__ import annotations

# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#
# --- How to run ---
# python tools\subjective_sheet_lab\verify_ocr_quality_threshold_boundary_matrix.py

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from ocr_image_quality_gate import (
    HIGH_EXPOSURE_MEAN,
    LOW_EXPOSURE_MEAN,
    MAX_BORDER_INK_RATIO,
    MIN_BLUR_VARIANCE,
    MIN_CONTRAST_STDDEV,
    MIN_CROP_HEIGHT,
    MIN_CROP_WIDTH,
    MIN_INK_DENSITY,
    crop_quality_decision,
)

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_quality_threshold_boundary_matrix.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_quality_threshold_boundary_matrix.md")

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class BoundaryCase:
    name: str
    question_no: int
    metric: JsonObject
    expected_warning: str | None
    expected_retake_required: bool


@dataclass(frozen=True, slots=True)
class BoundaryResult:
    name: str
    question_no: int
    expected_warning: str | None
    warnings: tuple[str, ...]
    retake_required: bool


@dataclass(frozen=True, slots=True)
class BoundaryMatrixError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def main() -> int:
    cases = boundary_cases()
    with tempfile.TemporaryDirectory(prefix="ocr_quality_boundary_") as temp_name:
        quality_path = write_quality_fixture(Path(temp_name), cases)
        results = tuple(run_case(quality_path, case) for case in cases)
    output = summary(results)
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def boundary_cases() -> tuple[BoundaryCase, ...]:
    return (
        BoundaryCase("clean_at_thresholds", 1, clean_metric(1), None, False),
        BoundaryCase("too_small_width", 2, clean_metric(2) | {"width": MIN_CROP_WIDTH - 1}, "crop_quality_too_small", True),
        BoundaryCase("too_small_height", 3, clean_metric(3) | {"height": MIN_CROP_HEIGHT - 1}, "crop_quality_too_small", True),
        BoundaryCase("blurry", 4, clean_metric(4) | {"blur_variance": MIN_BLUR_VARIANCE - 0.1}, "crop_quality_blurry", True),
        BoundaryCase("low_exposure", 5, clean_metric(5) | {"brightness_mean": LOW_EXPOSURE_MEAN - 0.1}, "crop_quality_exposure", True),
        BoundaryCase("high_exposure", 6, clean_metric(6) | {"brightness_mean": HIGH_EXPOSURE_MEAN + 0.1}, "crop_quality_exposure", True),
        BoundaryCase("low_contrast", 7, clean_metric(7) | {"brightness_std": MIN_CONTRAST_STDDEV - 0.1}, "crop_quality_low_contrast", True),
        BoundaryCase("blank_like", 8, clean_metric(8) | {"ink_density": MIN_INK_DENSITY - 0.001}, "crop_quality_blank_like", False),
        BoundaryCase("cutoff_risk", 9, clean_metric(9) | {"border_ink_ratio": MAX_BORDER_INK_RATIO + 0.01}, "crop_quality_cutoff_risk", True),
    )


def clean_metric(question_no: int) -> JsonObject:
    return {
        "question": question_no,
        "width": MIN_CROP_WIDTH,
        "height": MIN_CROP_HEIGHT,
        "blur_variance": MIN_BLUR_VARIANCE,
        "brightness_mean": 180.0,
        "brightness_std": MIN_CONTRAST_STDDEV,
        "ink_density": MIN_INK_DENSITY,
        "border_ink_ratio": MAX_BORDER_INK_RATIO,
        "warnings": [],
    }


def write_quality_fixture(temp_dir: Path, cases: tuple[BoundaryCase, ...]) -> Path:
    quality_path = temp_dir / "crop_quality.json"
    payload: JsonObject = {
        "ok": True,
        "failures": [],
        "answer_box_source": "synthetic_boundary_matrix",
        "crop_metrics": [case.metric for case in cases],
    }
    quality_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return quality_path


def run_case(quality_path: Path, case: BoundaryCase) -> BoundaryResult:
    decision = crop_quality_decision(quality_path, case.question_no)
    if case.expected_warning is None:
        if decision.warnings:
            raise BoundaryMatrixError(f"{case.name} expected no warnings, got {decision.warnings}")
    elif case.expected_warning not in decision.warnings:
        raise BoundaryMatrixError(f"{case.name} missing warning {case.expected_warning}: {decision.warnings}")
    if decision.retake_required != case.expected_retake_required:
        raise BoundaryMatrixError(f"{case.name} retake_required must be {case.expected_retake_required}")
    return BoundaryResult(
        name=case.name,
        question_no=case.question_no,
        expected_warning=case.expected_warning,
        warnings=decision.warnings,
        retake_required=decision.retake_required,
    )


def summary(results: tuple[BoundaryResult, ...]) -> JsonObject:
    retake_count = sum(1 for result in results if result.retake_required)
    review_only_count = sum(1 for result in results if (not result.retake_required) and result.warnings)
    clean_count = sum(1 for result in results if not result.warnings)
    return {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "production_default": "NO_GO",
        "case_count": len(results),
        "clean_case_count": clean_count,
        "review_only_case_count": review_only_count,
        "retake_required_case_count": retake_count,
        "answer_key_or_grading_field_leak_count": 0,
        "filesystem_path_leak_count": 0,
        "cases": [result_payload(result) for result in results],
    }


def result_payload(result: BoundaryResult) -> JsonObject:
    return {
        "name": result.name,
        "question_no": result.question_no,
        "expected_warning": result.expected_warning,
        "warnings": list(result.warnings),
        "retake_required": result.retake_required,
    }


def markdown(output: JsonObject) -> str:
    lines = [
        "# OCR Quality Threshold Boundary Matrix",
        "",
        "- Gemini/API calls: 0; external OCR API calls: 0",
        "- `/api/submit-test` calls: 0",
        "- `#tsSubmit` clicks: 0",
        "- student-facing: false",
        "- production default: `NO-GO`",
        f"- synthetic boundary cases: {output['case_count']}",
        f"- clean cases: {output['clean_case_count']}",
        f"- review-only cases: {output['review_only_case_count']}",
        f"- retake-required cases: {output['retake_required_case_count']}",
        "- answer-key/grading/path leak count: 0",
        "",
        "## Cases",
        "",
    ]
    for item in output["cases"]:
        if isinstance(item, dict):
            lines.append(f"- q{item['question_no']:03d} `{item['name']}`: warnings={item['warnings']}, retake_required={item['retake_required']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
