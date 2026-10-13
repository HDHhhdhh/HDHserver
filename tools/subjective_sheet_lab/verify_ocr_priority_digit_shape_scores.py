# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_priority_digit_shape_scores.py

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
from tools.subjective_sheet_lab.verify_ocr_priority_crop_feature_targets import BoundingBox, answer_components  # noqa: E402

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CROP_ROOT: Final[Path] = Path("C:/server-ocr/crop_benchmark_inputs")
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_priority_digit_shape_scores.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_priority_digit_shape_scores.md"
FORBIDDEN_OUTPUT_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
    "C:\\",
    "C:/",
    "/c/",
)


@dataclass(frozen=True, slots=True)
class DigitShapeTarget:
    name: str
    case_id: str
    question_no: int
    recognized: str
    expected_status: str
    expected_warning: str
    required_signal: str


@dataclass(frozen=True, slots=True)
class ComponentScore:
    bbox: BoundingBox
    right_bias: float
    top_bias: float
    density: float
    holes: int
    aspect_ratio: float


@dataclass(frozen=True, slots=True)
class ShapeSummary:
    component_count: int
    cluster_component_count: int
    leading_holes: int
    second_holes: int
    leading_right_bias: float
    leading_top_bias: float
    signal_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShapeResult:
    name: str
    case_id: str
    question_no: int
    recognized: str
    status: str
    final_answer: str | None
    warnings: tuple[str, ...]
    shape_summary: ShapeSummary


class DigitShapeScoreError(Exception):
    pass


def main() -> int:
    cv2 = require_cv2()
    results = [verify_target(cv2, target) for target in targets()]
    output: JsonObject = {
        "ok": True,
        "student_facing": False,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "case_count": len(results),
        "status_counts": status_counts(results),
        "results": [asdict(result) for result in results],
    }
    text = json.dumps(output, ensure_ascii=False)
    output["sensitive_field_leak_count"] = leak_count(text)
    if output["sensitive_field_leak_count"] != 0:
        raise DigitShapeScoreError("sensitive field or path token leaked into output")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(results), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def targets() -> tuple[DigitShapeTarget, ...]:
    return (
        DigitShapeTarget("q003_n_blocks_against_three_like_shape", "person_03", 3, "n", "review_required", "choice_number_invalid_for_auto_grade", "three_n_shape_conflict"),
        DigitShapeTarget("q003_3_preserves_fill_against_three_like_shape", "person_03", 3, "3", "safe_auto_grade", "", "three_n_shape_conflict"),
        DigitShapeTarget("q018_90_blocks_against_non_nine_leader", "person_03", 18, "90", "review_required", "digit_shape_confusion", "leading_digit_not_nine_like"),
        DigitShapeTarget("q018_30_preserves_fill_against_zero_second", "person_03", 18, "30", "safe_auto_grade", "", "second_digit_zero_like"),
    )


def verify_target(cv2: OpenCvModule, target: DigitShapeTarget) -> ShapeResult:
    gray = read_grayscale_crop(cv2, CROP_ROOT / target.case_id / "crops" / f"q{target.question_no:03d}.png")
    summary = shape_summary(cv2, gray)
    item = item_for(target.question_no, target.recognized)
    status = text_value(item.get("status"))
    warnings = warning_tuple(item)
    final_answer = nullable_text(item.get("final_answer"))
    if status != target.expected_status:
        raise DigitShapeScoreError(f"{target.name} status {status} != {target.expected_status}")
    if target.expected_warning and target.expected_warning not in warnings:
        raise DigitShapeScoreError(f"{target.name} missing warning {target.expected_warning}: {warnings}")
    if target.expected_status != "safe_auto_grade" and final_answer is not None:
        raise DigitShapeScoreError(f"{target.name} kept final_answer: {final_answer}")
    if target.required_signal not in summary.signal_flags:
        raise DigitShapeScoreError(f"{target.name} missing signal {target.required_signal}: {summary}")
    return ShapeResult(target.name, target.case_id, target.question_no, target.recognized, status, final_answer, warnings, summary)


def shape_summary(cv2: OpenCvModule, gray: ImageArray) -> ShapeSummary:
    components = tuple(sorted(answer_components(cv2, gray), key=lambda box: box.x))
    cluster = answer_cluster(components)
    scores = tuple(component_score(cv2, gray, box) for box in cluster)
    leading = scores[0] if scores else empty_score()
    second = scores[1] if len(scores) > 1 else empty_score()
    flags = shape_flags(scores)
    return ShapeSummary(
        component_count=len(components),
        cluster_component_count=len(cluster),
        leading_holes=leading.holes,
        second_holes=second.holes,
        leading_right_bias=round(leading.right_bias, 3),
        leading_top_bias=round(leading.top_bias, 3),
        signal_flags=flags,
    )


def answer_cluster(components: tuple[BoundingBox, ...]) -> tuple[BoundingBox, ...]:
    if not components:
        return ()
    selected = [components[0]]
    previous = components[0]
    for component in components[1:]:
        gap = component.x - (previous.x + previous.width)
        if gap <= max(16, previous.width):
            selected.append(component)
            previous = component
    return tuple(selected)


def component_score(cv2: OpenCvModule, gray: ImageArray, box: BoundingBox) -> ComponentScore:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    roi = binary[box.y : box.y + box.height, box.x : box.x + box.width]
    height, width = roi.shape[:2]
    left_density = density(roi[:, : max(1, width // 2)])
    right_density = density(roi[:, width // 2 :])
    top_density = density(roi[: max(1, height // 2), :])
    bottom_density = density(roi[height // 2 :, :])
    return ComponentScore(
        bbox=box,
        right_bias=right_density - left_density,
        top_bias=top_density - bottom_density,
        density=density(roi),
        holes=hole_count(cv2, roi),
        aspect_ratio=round(width / max(1, height), 3),
    )


def shape_flags(scores: tuple[ComponentScore, ...]) -> tuple[str, ...]:
    flags: list[str] = []
    if len(scores) == 1 and scores[0].holes == 0 and scores[0].right_bias >= 0.1:
        flags.append("three_n_shape_conflict")
    if len(scores) >= 2 and scores[0].holes == 0 and scores[1].holes >= 1:
        flags.append("leading_digit_not_nine_like")
        flags.append("second_digit_zero_like")
    return tuple(flags)


def hole_count(cv2: OpenCvModule, roi: ImageArray) -> int:
    _, threshold = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, hierarchy = cv2.findContours(threshold, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return 0
    return sum(1 for row in hierarchy[0] if row[3] != -1)


def density(roi: ImageArray) -> float:
    return float(roi.mean() / 255.0)


def empty_score() -> ComponentScore:
    return ComponentScore(BoundingBox(0, 0, 0, 0, 0), 0.0, 0.0, 0.0, 0, 0.0)


def status_counts(results: list[ShapeResult]) -> JsonObject:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def markdown_report(results: list[ShapeResult]) -> str:
    lines = [
        "# OCR Priority Digit Shape Scores",
        "",
        "Provider-free digit-shape scoring for ranked q003/q018 OCR misses.",
        "",
        "| Case | q | OCR | Status | Cluster | Leading holes | Second holes | Signals |",
        "|---|---:|---|---|---:|---:|---:|---|",
    ]
    for result in results:
        summary = result.shape_summary
        lines.append(
            f"| `{result.case_id}` | {result.question_no} | `{result.recognized}` | `{result.status}` | "
            f"{summary.cluster_component_count} | {summary.leading_holes} | {summary.second_holes} | "
            f"`{', '.join(summary.signal_flags)}` |"
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
