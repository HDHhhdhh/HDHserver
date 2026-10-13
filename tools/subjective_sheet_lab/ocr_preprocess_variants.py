# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\ocr_preprocess_variants.py --crop-dir C:\server-ocr\crop_benchmark_inputs\person_03\crops --out-dir C:\tmp\ocr_preprocess_variants_person03

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, TypeAlias

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_image_quality_gate import (  # noqa: E402
    HIGH_EXPOSURE_MEAN,
    LOW_EXPOSURE_MEAN,
    MAX_BORDER_INK_RATIO,
    MIN_BLUR_VARIANCE,
    MIN_CONTRAST_STDDEV,
    MIN_CROP_HEIGHT,
    MIN_CROP_WIDTH,
    MIN_INK_DENSITY,
)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

QUESTION_COUNT: Final[int] = 20
DARK_PIXEL_THRESHOLD: Final[int] = 180


class OpenCvModule(Protocol):
    COLOR_BGR2GRAY: int
    ADAPTIVE_THRESH_GAUSSIAN_C: int
    CV_64F: int
    INTER_CUBIC: int
    NORM_MINMAX: int
    THRESH_BINARY: int
    THRESH_OTSU: int


@dataclass(frozen=True, slots=True)
class VariantConfig:
    crop_dir: Path
    out_dir: Path
    questions: tuple[int, ...]
    enlarge_scale: int


@dataclass(frozen=True, slots=True)
class VariantImage:
    name: str
    pixels: ImageArray


ImageArray: TypeAlias = "NDArray[np.uint8]"


class PreprocessVariantError(Exception):
    pass


def main() -> int:
    config = parse_args()
    result = generate_preprocess_variants(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> VariantConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--questions", default="all")
    parser.add_argument("--enlarge-scale", default=2, type=int)
    args = parser.parse_args()
    return VariantConfig(
        crop_dir=args.crop_dir.resolve(),
        out_dir=args.out_dir.resolve(),
        questions=parse_questions(str(args.questions)),
        enlarge_scale=max(1, int(args.enlarge_scale)),
    )


def parse_questions(raw: str) -> tuple[int, ...]:
    value = raw.strip().lower()
    if value == "all":
        return tuple(range(1, QUESTION_COUNT + 1))
    questions = tuple(sorted({int(part.strip()) for part in value.split(",") if part.strip()}))
    if not questions or any(question < 1 or question > QUESTION_COUNT for question in questions):
        raise PreprocessVariantError("--questions must be all or comma-separated values in 1..20")
    return questions


def generate_preprocess_variants(config: VariantConfig) -> JsonObject:
    cv2 = require_cv2()
    config.out_dir.mkdir(parents=True, exist_ok=True)
    items: list[JsonObject] = []
    for question in config.questions:
        crop_path = config.crop_dir / f"q{question:03d}.png"
        gray = read_grayscale_crop(cv2, crop_path)
        question_dir = config.out_dir / f"q{question:03d}"
        question_dir.mkdir(parents=True, exist_ok=True)
        variants = build_variants(cv2, gray, config.enlarge_scale)
        items.append(write_question_variants(cv2, question, question_dir, variants))
    manifest: JsonObject = {
        "source": "opencv_crop_preprocess_variants",
        "student_facing": False,
        "crop_dir": str(config.crop_dir),
        "variant_root": str(config.out_dir),
        "question_count": len(items),
        "variants": items,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
    }
    manifest_path = config.out_dir / "preprocess_variant_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "manifest": str(manifest_path), "question_count": len(items), "provider_call_count": 0}


def require_cv2() -> OpenCvModule:
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise PreprocessVariantError("opencv-python is not installed in this Python environment") from exc
    return cv2


def read_grayscale_crop(cv2: OpenCvModule, crop_path: Path) -> ImageArray:
    image = cv2.imread(str(crop_path))
    if image is None:
        raise PreprocessVariantError(f"cannot read crop: {crop_path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def build_variants(cv2: OpenCvModule, gray: ImageArray, enlarge_scale: int) -> tuple[VariantImage, ...]:
    contrast = contrast_sharpen(cv2, gray)
    return (
        VariantImage("original_grayscale", gray),
        VariantImage("contrast_sharpen", contrast),
        VariantImage("otsu_threshold", otsu_threshold(cv2, gray)),
        VariantImage("adaptive_threshold", adaptive_threshold(cv2, gray)),
        VariantImage("denoise_threshold", denoise_threshold(cv2, gray)),
        VariantImage("enlarged_grayscale", enlarged(cv2, gray, enlarge_scale)),
    )


def contrast_sharpen(cv2: OpenCvModule, gray: ImageArray) -> ImageArray:
    normalized = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    blurred = cv2.GaussianBlur(normalized, (0, 0), 1.0)
    return cv2.addWeighted(normalized, 1.7, blurred, -0.7, 0)


def otsu_threshold(cv2: OpenCvModule, gray: ImageArray) -> ImageArray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, threshold = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return threshold


def adaptive_threshold(cv2: OpenCvModule, gray: ImageArray) -> ImageArray:
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9)


def denoise_threshold(cv2: OpenCvModule, gray: ImageArray) -> ImageArray:
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    return otsu_threshold(cv2, denoised)


def enlarged(cv2: OpenCvModule, gray: ImageArray, scale: int) -> ImageArray:
    if scale == 1:
        return gray
    height, width = gray.shape[:2]
    return cv2.resize(gray, (width * scale, height * scale), interpolation=cv2.INTER_CUBIC)


def write_question_variants(cv2: OpenCvModule, question: int, question_dir: Path, variants: tuple[VariantImage, ...]) -> JsonObject:
    outputs: list[JsonObject] = []
    for variant in variants:
        path = question_dir / f"{variant.name}.png"
        cv2.imwrite(str(path), variant.pixels)
        outputs.append({"name": variant.name, "artifact": str(path), "metrics": image_metrics(cv2, variant.pixels)})
    return {"question_no": question, "variants": outputs}


def image_metrics(cv2: OpenCvModule, gray: ImageArray) -> JsonObject:
    height, width = gray.shape[:2]
    dark_pixels = gray < DARK_PIXEL_THRESHOLD
    margin = max(1, min(6, height // 4, width // 4))
    border_mask = border_pixels(gray.shape, margin)
    ink_density = float(dark_pixels.mean())
    border_ink_ratio = float((dark_pixels & border_mask).sum() / max(1, border_mask.sum()))
    blur_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness_mean = float(gray.mean())
    brightness_std = float(gray.std())
    return {
        "width": int(width),
        "height": int(height),
        "blur_variance": round(blur_variance, 3),
        "brightness_mean": round(brightness_mean, 3),
        "brightness_std": round(brightness_std, 3),
        "ink_density": round(ink_density, 5),
        "border_ink_ratio": round(border_ink_ratio, 5),
        "warnings": metric_warnings(width, height, blur_variance, brightness_mean, brightness_std, ink_density, border_ink_ratio),
    }


def border_pixels(shape: tuple[int, int], margin: int) -> ImageArray:
    import numpy as np

    mask = np.zeros(shape, dtype=bool)
    mask[:margin, :] = True
    mask[-margin:, :] = True
    mask[:, :margin] = True
    mask[:, -margin:] = True
    return mask


def metric_warnings(
    width: int,
    height: int,
    blur_variance: float,
    brightness_mean: float,
    brightness_std: float,
    ink_density: float,
    border_ink_ratio: float,
) -> list[str]:
    warnings: list[str] = []
    if width < MIN_CROP_WIDTH or height < MIN_CROP_HEIGHT:
        warnings.append("crop_quality_too_small")
    if blur_variance < MIN_BLUR_VARIANCE:
        warnings.append("crop_quality_blurry")
    if brightness_mean < LOW_EXPOSURE_MEAN or brightness_mean > HIGH_EXPOSURE_MEAN:
        warnings.append("crop_quality_exposure")
    if brightness_std < MIN_CONTRAST_STDDEV:
        warnings.append("crop_quality_low_contrast")
    if ink_density < MIN_INK_DENSITY:
        warnings.append("crop_quality_blank_like")
    if border_ink_ratio > MAX_BORDER_INK_RATIO:
        warnings.append("crop_quality_cutoff_risk")
    return warnings


if __name__ == "__main__":
    raise SystemExit(main())
