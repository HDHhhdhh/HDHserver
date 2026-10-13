from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

MIN_CROP_WIDTH: Final[int] = 360
MIN_CROP_HEIGHT: Final[int] = 80
MIN_BLUR_VARIANCE: Final[float] = 12.0
MIN_CONTRAST_STDDEV: Final[float] = 8.0
MIN_INK_DENSITY: Final[float] = 0.008
MAX_BORDER_INK_RATIO: Final[float] = 0.65
LOW_EXPOSURE_MEAN: Final[float] = 45.0
HIGH_EXPOSURE_MEAN: Final[float] = 248.0
RETAKE_QUALITY_WARNINGS: Final[frozenset[str]] = frozenset(
    (
        "crop_quality_too_small",
        "crop_quality_blurry",
        "crop_quality_low_contrast",
        "crop_quality_exposure",
        "crop_quality_cutoff_risk",
    )
)


@dataclass(frozen=True, slots=True)
class CropQualityDecision:
    question_no: int
    warnings: tuple[str, ...]
    retake_required: bool


def crop_quality_decision(crop_quality_path: Path, question_no: int) -> CropQualityDecision:
    warnings = crop_quality_warnings(crop_quality_path, question_no)
    return CropQualityDecision(
        question_no=question_no,
        warnings=warnings,
        retake_required=bool(RETAKE_QUALITY_WARNINGS.intersection(warnings)),
    )


def crop_quality_warnings(crop_quality_path: Path, question_no: int) -> tuple[str, ...]:
    payload = read_json_object(crop_quality_path)
    metrics = payload.get("crop_metrics")
    if not isinstance(metrics, list):
        return ()
    for value in metrics:
        if not isinstance(value, dict):
            continue
        raw_question = value.get("question")
        if isinstance(raw_question, int) and not isinstance(raw_question, bool) and raw_question == question_no:
            return tuple(dict.fromkeys(existing_warning_strings(value) + computed_metric_warnings(value)))
    return ()


def read_json_object(path: Path) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def existing_warning_strings(value: JsonObject) -> list[str]:
    raw = value.get("warnings")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


def computed_metric_warnings(metric: JsonObject) -> list[str]:
    warnings: list[str] = []
    width = number_value(metric.get("width"))
    height = number_value(metric.get("height"))
    blur = number_value(metric.get("blur_variance"))
    brightness = number_value(metric.get("brightness_mean"))
    contrast = number_value(metric.get("brightness_std"))
    ink_density = number_value(metric.get("ink_density"))
    border_ink = number_value(metric.get("border_ink_ratio"))
    if width < MIN_CROP_WIDTH or height < MIN_CROP_HEIGHT:
        warnings.append("crop_quality_too_small")
    if blur < MIN_BLUR_VARIANCE:
        warnings.append("crop_quality_blurry")
    if brightness < LOW_EXPOSURE_MEAN or brightness > HIGH_EXPOSURE_MEAN:
        warnings.append("crop_quality_exposure")
    if contrast < MIN_CONTRAST_STDDEV:
        warnings.append("crop_quality_low_contrast")
    if ink_density < MIN_INK_DENSITY:
        warnings.append("crop_quality_blank_like")
    if border_ink > MAX_BORDER_INK_RATIO:
        warnings.append("crop_quality_cutoff_risk")
    return warnings


def number_value(value: JsonValue) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0
