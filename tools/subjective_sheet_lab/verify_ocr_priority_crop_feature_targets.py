# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\verify_ocr_priority_crop_feature_targets.py

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, TypeAlias

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_preprocess_variants import (  # noqa: E402
    ImageArray,
    OpenCvModule,
    image_metrics,
    read_grayscale_crop,
    require_cv2,
)
from tools.subjective_sheet_lab.verify_ocr_postprocessing_gate_matrix import (  # noqa: E402
    item_for,
    warning_tuple,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

CROP_ROOT: Final[Path] = Path("C:/server-ocr/crop_benchmark_inputs")
REPORT_JSON: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_priority_crop_feature_targets.json"
REPORT_MD: Final[Path] = ROOT / "tools/subjective_sheet_lab/ocr_priority_crop_feature_targets.md"
ANSWER_KEY_OR_GRADING_TOKENS: Final[tuple[str, ...]] = (
    "expected",
    "canonical_answer",
    "accepted_answers",
    "correct",
    "incorrect",
    "grading",
)
FILESYSTEM_PATH_TOKENS: Final[tuple[str, ...]] = (
    "C:\\",
    "C:/",
    "/c/",
)


@dataclass(frozen=True, slots=True)
class CropTarget:
    name: str
    case_id: str
    question_no: int
    recognized: str
    required_status: str
    required_warning: str
    feature_rule: str


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x: int
    y: int
    width: int
    height: int
    area: int


@dataclass(frozen=True, slots=True)
class ImageSize:
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class FeatureSummary:
    component_count: int
    primary_bbox: BoundingBox | None
    cluster_width: int
    cluster_height: int
    quality_warnings: tuple[str, ...]
    feature_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetResult:
    name: str
    case_id: str
    question_no: int
    recognized: str
    status: str
    final_answer: str | None
    warnings: tuple[str, ...]
    feature_summary: FeatureSummary


class PriorityCropFeatureError(Exception):
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
    leak_text = json.dumps(output, ensure_ascii=False)
    answer_key_leaks = leak_count(leak_text, ANSWER_KEY_OR_GRADING_TOKENS)
    path_leaks = leak_count(leak_text, FILESYSTEM_PATH_TOKENS)
    output["answer_key_or_grading_field_leak_count"] = answer_key_leaks
    output["filesystem_path_leak_count"] = path_leaks
    output["sensitive_field_leak_count"] = answer_key_leaks + path_leaks
    output["production_default"] = "NO_GO"
    output["next_safe_action"] = "Keep q003/q018 crop-feature targets in provider-free regression before live OCR QA."
    if output["sensitive_field_leak_count"] != 0:
        raise PriorityCropFeatureError("sensitive field or path token leaked into output")
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown_report(results), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def targets() -> tuple[CropTarget, ...]:
    return (
        CropTarget("q003_n_blocks_with_digit_ink", "person_03", 3, "n", "review_required", "choice_number_invalid_for_auto_grade", "central_digit_ink"),
        CropTarget("q003_digit_3_can_fill_with_digit_ink", "person_03", 3, "3", "safe_auto_grade", "", "central_digit_ink"),
        CropTarget("q018_90_blocks_with_multidigit_ink", "person_03", 18, "90", "review_required", "digit_shape_confusion", "multi_digit_ink"),
        CropTarget("q018_30_can_fill_with_multidigit_ink", "person_03", 18, "30", "safe_auto_grade", "", "multi_digit_ink"),
    )


def verify_target(cv2: OpenCvModule, target: CropTarget) -> TargetResult:
    gray = read_grayscale_crop(cv2, CROP_ROOT / target.case_id / "crops" / f"q{target.question_no:03d}.png")
    features = summarize_features(cv2, gray)
    item = item_for(target.question_no, target.recognized)
    status = text_value(item.get("status"))
    warnings = warning_tuple(item)
    final_answer = nullable_text(item.get("final_answer"))
    if status != target.required_status:
        raise PriorityCropFeatureError(f"{target.name} status {status} != {target.required_status}")
    if target.required_warning and target.required_warning not in warnings:
        raise PriorityCropFeatureError(f"{target.name} missing warning {target.required_warning}: {warnings}")
    if target.required_status != "safe_auto_grade" and final_answer is not None:
        raise PriorityCropFeatureError(f"{target.name} kept final_answer: {final_answer}")
    if target.feature_rule not in features.feature_flags:
        raise PriorityCropFeatureError(f"{target.name} missing feature {target.feature_rule}: {features}")
    if features.quality_warnings:
        raise PriorityCropFeatureError(f"{target.name} unexpectedly failed crop quality: {features.quality_warnings}")
    return TargetResult(target.name, target.case_id, target.question_no, target.recognized, status, final_answer, warnings, features)


def summarize_features(cv2: OpenCvModule, gray: ImageArray) -> FeatureSummary:
    metrics = image_metrics(cv2, gray)
    components = answer_components(cv2, gray)
    primary = components[0] if components else None
    flags: list[str] = []
    if components:
        flags.append("central_digit_ink")
    if len(components) >= 2:
        flags.append("multi_digit_ink")
    cluster = cluster_bbox(components)
    return FeatureSummary(
        component_count=len(components),
        primary_bbox=primary,
        cluster_width=cluster.width if cluster else 0,
        cluster_height=cluster.height if cluster else 0,
        quality_warnings=warning_strings(metrics),
        feature_flags=tuple(flags),
    )


def answer_components(cv2: OpenCvModule, gray: ImageArray) -> tuple[BoundingBox, ...]:
    height, width = gray.shape[:2]
    size = ImageSize(width=int(width), height=int(height))
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    margin = max(8, min(height, width) // 20)
    binary[:margin, :] = 0
    binary[-margin:, :] = 0
    binary[:, :margin] = 0
    binary[:, -margin:] = 0
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    components: list[BoundingBox] = []
    for index in range(1, count):
        x, y, box_width, box_height, area = (int(value) for value in stats[index])
        box = BoundingBox(x, y, box_width, box_height, area)
        if is_answer_component(size, box):
            components.append(box)
    return tuple(sorted(components, key=lambda box: box.area, reverse=True))


def is_answer_component(size: ImageSize, box: BoundingBox) -> bool:
    return (
        box.area >= 50
        and box.height >= 14
        and box.width <= int(size.width * 0.65)
        and box.height <= int(size.height * 0.7)
        and box.x >= int(size.width * 0.08)
        and box.x + box.width <= int(size.width * 0.92)
        and box.y >= int(size.height * 0.2)
    )


def cluster_bbox(components: tuple[BoundingBox, ...]) -> BoundingBox | None:
    if not components:
        return None
    left = min(component.x for component in components)
    top = min(component.y for component in components)
    right = max(component.x + component.width for component in components)
    bottom = max(component.y + component.height for component in components)
    return BoundingBox(left, top, right - left, bottom - top, sum(component.area for component in components))


def status_counts(results: list[TargetResult]) -> JsonObject:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def markdown_report(results: list[TargetResult]) -> str:
    lines = [
        "# OCR Priority Crop Feature Targets",
        "",
        "Provider-free crop-feature regression for ranked q003/q018 recognition targets.",
        "",
        "| Case | q | OCR | Status | Components | Flags | Warnings |",
        "|---|---:|---|---|---:|---|---|",
    ]
    for result in results:
        lines.append(
            f"| `{result.case_id}` | {result.question_no} | `{result.recognized}` | `{result.status}` | "
            f"{result.feature_summary.component_count} | `{', '.join(result.feature_summary.feature_flags)}` | "
            f"`{', '.join(result.warnings)}` |"
        )
    lines.extend(
        (
            "",
            "- Gemini/API calls: 0",
            "- External OCR API calls: 0",
            "- `/api/submit-test` calls: 0",
            "- `#tsSubmit` clicks: 0",
            "- Answer-key/grading leak count: 0",
            "- Filesystem path leak count: 0",
            "- Production default: NO_GO",
            "- Student-facing output: false",
        )
    )
    return "\n".join(lines) + "\n"


def warning_strings(metrics: JsonObject) -> tuple[str, ...]:
    warnings = metrics.get("warnings")
    return tuple(value for value in warnings if isinstance(value, str)) if isinstance(warnings, list) else ()


def nullable_text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


def text_value(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""


def leak_count(text: str, tokens: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for token in tokens if token.lower() in lowered)


if __name__ == "__main__":
    raise SystemExit(main())
