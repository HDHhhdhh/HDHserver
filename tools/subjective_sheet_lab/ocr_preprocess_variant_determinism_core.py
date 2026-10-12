# /// script
# requires-python = ">=3.11"
# dependencies = ["opencv-python", "numpy"]
# ///
#
# --- How to run ---
# Imported by verify_ocr_preprocess_variant_determinism.py

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.subjective_sheet_lab.ocr_preprocess_variants import (
    ImageArray,
    QUESTION_COUNT,
    JsonObject,
    build_variants,
    image_metrics,
    read_grayscale_crop,
    require_cv2,
)

VARIANT_NAMES: Final[tuple[str, ...]] = (
    "original_grayscale",
    "contrast_sharpen",
    "otsu_threshold",
    "adaptive_threshold",
    "denoise_threshold",
    "enlarged_grayscale",
)
ENLARGE_SCALE: Final[int] = 2


@dataclass(frozen=True, slots=True)
class VariantFingerprint:
    question_no: int
    variant_name: str
    pixel_sha256: str
    metrics_sha256: str
    quality_warning_count: int


@dataclass(frozen=True, slots=True)
class PreprocessVariantDeterminismCoreError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def collect_fingerprints(crop_dir: Path, question_numbers: tuple[int, ...]) -> tuple[VariantFingerprint, ...]:
    validate_questions(question_numbers)
    cv2 = require_cv2()
    fingerprints: list[VariantFingerprint] = []
    for question_no in question_numbers:
        crop_path = crop_dir / f"q{question_no:03d}.png"
        gray = read_grayscale_crop(cv2, crop_path)
        variants = build_variants(cv2, gray, ENLARGE_SCALE)
        names = tuple(variant.name for variant in variants)
        if names != VARIANT_NAMES:
            raise PreprocessVariantDeterminismCoreError("preprocess variant names changed")
        fingerprints.extend(
            fingerprint(question_no, variant.name, variant.pixels, image_metrics(cv2, variant.pixels))
            for variant in variants
        )
    return tuple(fingerprints)


def validate_questions(question_numbers: tuple[int, ...]) -> None:
    if not question_numbers:
        raise PreprocessVariantDeterminismCoreError("at least one question is required")
    if len(set(question_numbers)) != len(question_numbers):
        raise PreprocessVariantDeterminismCoreError("question numbers must be unique")
    if any(question_no < 1 or question_no > QUESTION_COUNT for question_no in question_numbers):
        raise PreprocessVariantDeterminismCoreError("question numbers must stay within 1..20")


def fingerprint(question_no: int, variant_name: str, pixels: ImageArray, metrics: JsonObject) -> VariantFingerprint:
    warnings = metrics.get("warnings")
    warning_count = len(warnings) if isinstance(warnings, list) else 0
    return VariantFingerprint(
        question_no=question_no,
        variant_name=variant_name,
        pixel_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
        metrics_sha256=hashlib.sha256(canonical_json(metrics).encode("utf-8")).hexdigest(),
        quality_warning_count=warning_count,
    )


def matching_fingerprint_count(
    first: tuple[VariantFingerprint, ...],
    second: tuple[VariantFingerprint, ...],
) -> int:
    if len(first) != len(second):
        return 0
    return sum(1 for left, right in zip(first, second, strict=True) if left == right)


def canonical_json(value: JsonObject) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
