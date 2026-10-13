from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab import ocr_image_quality_gate as gate

REPORT_JSON: Final[Path] = Path(__file__).with_name("ocr_crop_quality_thresholds.json")
REPORT_MD: Final[Path] = Path(__file__).with_name("ocr_crop_quality_thresholds.md")


class CropQualityThresholdReportError(Exception):
    pass


def main() -> int:
    output = {
        "ok": True,
        "provider_call_count": 0,
        "submit_test_call_count": 0,
        "ts_submit_click_count": 0,
        "thresholds": {
            "min_crop_width": gate.MIN_CROP_WIDTH,
            "min_crop_height": gate.MIN_CROP_HEIGHT,
            "min_blur_variance": gate.MIN_BLUR_VARIANCE,
            "min_contrast_stddev": gate.MIN_CONTRAST_STDDEV,
            "min_ink_density": gate.MIN_INK_DENSITY,
            "max_border_ink_ratio": gate.MAX_BORDER_INK_RATIO,
            "low_exposure_mean": gate.LOW_EXPOSURE_MEAN,
            "high_exposure_mean": gate.HIGH_EXPOSURE_MEAN,
        },
        "retake_quality_warnings": sorted(gate.RETAKE_QUALITY_WARNINGS),
        "review_quality_warnings": ["crop_quality_blank_like"],
        "policy": {
            "safe_auto_grade": "allowed only when crop quality warnings do not indicate retake/review and answer-mode validation passes",
            "review_required": "blank-like or ambiguous quality signals",
            "retake_required": "too small, blurry, low contrast, exposure, or cutoff-risk crop signals",
        },
    }
    REPORT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(markdown(output), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def markdown(output: dict[str, object]) -> str:
    raw_thresholds = output["thresholds"]
    if not isinstance(raw_thresholds, dict):
        raise CropQualityThresholdReportError("thresholds must be a dictionary")
    thresholds = raw_thresholds
    lines = [
        "# OCR Crop Quality Thresholds",
        "",
        "- provider calls: 0",
        "- submit-test calls: 0",
        "",
        "| Metric | Threshold | Meaning |",
        "| --- | ---: | --- |",
        f"| minimum crop width | {thresholds['min_crop_width']} | crop below this is too small |",
        f"| minimum crop height | {thresholds['min_crop_height']} | crop below this is too small |",
        f"| minimum blur variance | {thresholds['min_blur_variance']} | lower means blurry |",
        f"| minimum contrast stddev | {thresholds['min_contrast_stddev']} | lower means faint/low contrast |",
        f"| minimum ink density | {thresholds['min_ink_density']} | lower means blank-like |",
        f"| maximum border ink ratio | {thresholds['max_border_ink_ratio']} | higher means cutoff risk |",
        f"| low exposure mean | {thresholds['low_exposure_mean']} | lower means too dark |",
        f"| high exposure mean | {thresholds['high_exposure_mean']} | higher means too bright |",
        "",
        "## Routing",
        "",
        "- `retake_required`: too small, blurry, low contrast, exposure, or cutoff-risk.",
        "- `review_required`: blank-like or ambiguous quality signal.",
        "- `safe_auto_grade`: only after quality and answer-mode validation both pass.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
