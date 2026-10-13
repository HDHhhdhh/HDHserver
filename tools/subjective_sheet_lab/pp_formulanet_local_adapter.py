from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Final, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.short_answer import normalize_short_answer
from core.test_answer_modes import ANSWER_VALUE
from tools.subjective_sheet_lab.ocr_payload_leak_policy import forbidden_paths, path_exposures


MODEL_NAME: Final[str] = "PP-FormulaNet-S"
DEFAULT_MODEL_DIR: Final[Path] = Path(
    "C:/server-ocr/paddlex-cache/official_models/PP-FormulaNet-S"
)
QUESTION_FILE_RE: Final[re.Pattern[str]] = re.compile(r"^q(\d{3})\.[A-Za-z0-9]+$")
LOCAL_FORMULA_UNVERIFIED: Final[str] = "local_formula_unverified"
FORMULA_PARSE_UNSUPPORTED: Final[str] = "formula_parse_unsupported"
REVIEW_REQUIRED: Final[str] = "review_required"
ModelFactory = Callable[[str, Path, str, int], Any]


class LocalFormulaPilotError(ValueError):
    pass


def preprocess_formula_crop(image_path: Path) -> Any:
    cv2, np = _image_modules()
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise LocalFormulaPilotError(f"unreadable crop: {image_path.name}")
    height, width = image.shape[:2]
    if height < 20 or width < 20:
        raise LocalFormulaPilotError(f"crop is too small: {image_path.name}")

    sigma = max(3.0, min(height, width) / 18.0)
    background = cv2.GaussianBlur(image, (0, 0), sigmaX=sigma, sigmaY=sigma)
    normalized = cv2.divide(image, background, scale=255)
    normalized = cv2.GaussianBlur(normalized, (3, 3), 0)
    _, foreground = cv2.threshold(
        normalized, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(25, width // 3), 1)
    )
    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(20, height // 3))
    )
    long_horizontal = cv2.morphologyEx(
        foreground, cv2.MORPH_OPEN, horizontal_kernel
    )
    long_vertical = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, vertical_kernel)
    long_lines = cv2.bitwise_or(long_horizontal, long_vertical)
    foreground = cv2.bitwise_and(foreground, cv2.bitwise_not(long_lines))

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        foreground, connectivity=8
    )
    cleaned = np.zeros_like(foreground)
    minimum_area = max(12, int(height * width * 0.00005))
    for component_id in range(1, component_count):
        x, y, component_width, component_height, area = map(
            int, stats[component_id]
        )
        if area < minimum_area:
            continue
        if component_width >= int(width * 0.45) or component_height >= int(
            height * 0.80
        ):
            continue
        touches_left = x <= 1
        touches_top = y <= 1
        touches_right = x + component_width >= width - 1
        if touches_left and component_width >= int(width * 0.15):
            continue
        if touches_top and component_width >= int(width * 0.15):
            continue
        if (
            touches_right
            and component_width <= max(6, int(width * 0.03))
            and component_height >= int(height * 0.25)
        ):
            continue
        cleaned[labels == component_id] = 255

    coordinates = cv2.findNonZero(cleaned)
    if coordinates is None:
        raise LocalFormulaPilotError(f"no stable handwriting found: {image_path.name}")
    x, y, box_width, box_height = cv2.boundingRect(coordinates)
    ink = np.full_like(normalized, 255)
    ink_pixels = cleaned > 0
    ink[ink_pixels] = np.minimum(normalized[ink_pixels], 96)
    cropped = ink[y : y + box_height, x : x + box_width]

    padding = max(12, int(max(box_width, box_height) * 0.14))
    cropped = cv2.copyMakeBorder(
        cropped,
        padding,
        padding,
        padding,
        padding,
        cv2.BORDER_CONSTANT,
        value=255,
    )
    if cropped.shape[0] < 128:
        scale = 128.0 / cropped.shape[0]
        cropped = cv2.resize(
            cropped,
            (max(1, int(round(cropped.shape[1] * scale))), 128),
            interpolation=cv2.INTER_CUBIC,
        )
    return cv2.cvtColor(cropped, cv2.COLOR_GRAY2BGR)


def run_local_formula_pilot(
    crop_paths: Sequence[Path],
    *,
    model_name: str = MODEL_NAME,
    model_dir: Path = DEFAULT_MODEL_DIR,
    device: str = "cpu",
    cpu_threads: int = 6,
    model_factory: ModelFactory | None = None,
) -> dict[str, Any]:
    ordered = _validated_crop_paths(crop_paths)
    prepared = [preprocess_formula_crop(path) for _, path in ordered]
    factory = model_factory or _build_model

    started = time.perf_counter()
    model = factory(model_name, model_dir, device, cpu_threads)
    model_init_ms = round((time.perf_counter() - started) * 1000, 2)
    started = time.perf_counter()
    results = list(model.predict(input=prepared, batch_size=1))
    inference_ms = round((time.perf_counter() - started) * 1000, 2)
    if len(results) != len(ordered):
        raise LocalFormulaPilotError(
            f"model returned {len(results)} results for {len(ordered)} crops"
        )

    items: list[dict[str, Any]] = []
    for (question_no, _), result in zip(ordered, results, strict=True):
        raw_latex = _extract_rec_formula(result)
        normalized = normalize_short_answer(raw_latex, ANSWER_VALUE)
        warnings = [LOCAL_FORMULA_UNVERIFIED]
        if normalized is None:
            warnings.append(FORMULA_PARSE_UNSUPPORTED)
        items.append(
            {
                "question": question_no,
                "recognized": normalized or "?",
                "raw_latex": raw_latex,
                "status": REVIEW_REQUIRED,
                "warnings": warnings,
            }
        )

    payload: dict[str, Any] = {
        "source": "pp_formulanet_s_local_pilot",
        "model": model_name,
        "device": device,
        "provider_calls": 0,
        "problem_count": len(items),
        "timing": {
            "model_init_ms": model_init_ms,
            "inference_ms": inference_ms,
            "per_crop_ms": round(inference_ms / len(items), 2),
        },
        "items": items,
    }
    _validate_safe_payload(payload)
    return payload


def write_preprocessed_crops(crop_paths: Sequence[Path], output_dir: Path) -> None:
    cv2, _ = _image_modules()
    output_dir.mkdir(parents=True, exist_ok=True)
    for question_no, path in _validated_crop_paths(crop_paths):
        output_path = output_dir / f"q{question_no:03d}.png"
        if not cv2.imwrite(str(output_path), preprocess_formula_crop(path)):
            raise LocalFormulaPilotError(
                f"could not write preprocessed crop: {output_path.name}"
            )


def write_payload(payload: dict[str, Any], output_path: Path) -> None:
    _validate_safe_payload(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _validated_crop_paths(
    crop_paths: Sequence[Path],
) -> list[tuple[int, Path]]:
    if not crop_paths:
        raise LocalFormulaPilotError("at least one crop is required")
    ordered: list[tuple[int, Path]] = []
    seen: set[int] = set()
    for candidate in crop_paths:
        path = candidate.resolve()
        if not path.is_file():
            raise LocalFormulaPilotError(f"crop not found: {candidate}")
        matched = QUESTION_FILE_RE.fullmatch(path.name)
        if matched is None:
            raise LocalFormulaPilotError(
                f"crop filename must look like q001.png: {path.name}"
            )
        question_no = int(matched.group(1))
        if not 1 <= question_no <= 20 or question_no in seen:
            raise LocalFormulaPilotError(f"invalid or duplicate question: {question_no}")
        seen.add(question_no)
        ordered.append((question_no, path))
    return sorted(ordered)


def _build_model(
    model_name: str, model_dir: Path, device: str, cpu_threads: int
) -> Any:
    if not model_dir.is_dir():
        raise LocalFormulaPilotError(
            "formula model is not cached; download it in an explicitly authorized setup step"
        )
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import FormulaRecognition

    return FormulaRecognition(
        model_name=model_name,
        model_dir=str(model_dir),
        device=device,
        cpu_threads=cpu_threads,
    )


def _extract_rec_formula(result: Any) -> str:
    value = getattr(result, "json", result)
    if callable(value):
        value = value()
    if isinstance(value, dict) and isinstance(value.get("res"), dict):
        value = value["res"]
    raw_latex = value.get("rec_formula") if isinstance(value, dict) else None
    if not isinstance(raw_latex, str) or not raw_latex.strip():
        raise LocalFormulaPilotError("formula model result has no rec_formula")
    return " ".join(raw_latex.replace("\r", " ").replace("\n", " ").split())


def _validate_safe_payload(payload: dict[str, Any]) -> None:
    if forbidden_paths(payload):
        raise LocalFormulaPilotError("formula pilot payload contains forbidden fields")
    if path_exposures(payload):
        raise LocalFormulaPilotError("formula pilot payload exposes a local path")
    if payload.get("provider_calls") != 0:
        raise LocalFormulaPilotError("local formula pilot must report zero provider calls")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise LocalFormulaPilotError("formula pilot payload has no items")
    if any(
        not isinstance(item, dict) or item.get("status") != REVIEW_REQUIRED
        for item in items
    ):
        raise LocalFormulaPilotError("local formula pilot cannot auto-grade")


def _image_modules() -> tuple[Any, Any]:
    try:
        import cv2
        import numpy as np
    except (ImportError, ModuleNotFoundError) as exc:
        raise LocalFormulaPilotError("opencv-python and numpy are required") from exc
    return cv2, np


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local, review-only PP-FormulaNet-S crop pilot."
    )
    parser.add_argument("--crop", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--save-preprocessed", type=Path)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--cpu-threads", type=int, default=6)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.cpu_threads < 1:
        raise LocalFormulaPilotError("cpu threads must be positive")
    if args.save_preprocessed is not None:
        write_preprocessed_crops(args.crop, args.save_preprocessed)
    payload = run_local_formula_pilot(
        args.crop,
        model_dir=args.model_dir,
        device=args.device,
        cpu_threads=args.cpu_threads,
    )
    write_payload(payload, args.out)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LocalFormulaPilotError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from None
