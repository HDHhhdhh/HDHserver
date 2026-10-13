from __future__ import annotations

from pathlib import Path
from typing import Any

from core.short_answer import normalize_short_answer
from core.test_answer_modes import ANSWER_VALUE


class FormulaCropCleanupError(ValueError):
    pass


def preprocess_formula_crop(image_path: Path) -> Any:
    try:
        import cv2
        import numpy as np
    except (ImportError, ModuleNotFoundError) as exc:
        raise FormulaCropCleanupError("opencv-python and numpy are required") from exc

    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FormulaCropCleanupError(f"unreadable crop: {image_path.name}")
    height, width = image.shape[:2]
    if height < 20 or width < 20:
        raise FormulaCropCleanupError(f"crop is too small: {image_path.name}")

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
    long_lines = cv2.bitwise_or(
        cv2.morphologyEx(foreground, cv2.MORPH_OPEN, horizontal_kernel),
        cv2.morphologyEx(foreground, cv2.MORPH_OPEN, vertical_kernel),
    )
    foreground = cv2.bitwise_and(foreground, cv2.bitwise_not(long_lines))

    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        foreground, connectivity=8
    )
    cleaned = np.zeros_like(foreground)
    minimum_area = max(24, int(height * width * 0.00008))
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
        if (
            y < int(height * 0.38)
            and component_height <= 5
            and component_width >= 18
            and component_width >= component_height * 5
        ):
            continue
        if (
            x > int(width * 0.85)
            and component_width <= 5
            and component_height >= 18
            and component_height >= component_width * 5
        ):
            continue
        cleaned[labels == component_id] = 255

    coordinates = cv2.findNonZero(cleaned)
    if coordinates is None:
        raise FormulaCropCleanupError(
            f"no stable handwriting found: {image_path.name}"
        )
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


def normalize_rec_formula(raw_latex: str) -> str | None:
    candidates = [raw_latex]
    without_terminal_slashes = raw_latex.rstrip("\\").rstrip()
    if without_terminal_slashes and without_terminal_slashes != raw_latex:
        candidates.append(without_terminal_slashes)
    for candidate in candidates:
        normalized = normalize_short_answer(candidate, ANSWER_VALUE)
        if normalized is not None:
            return normalized
    return None
