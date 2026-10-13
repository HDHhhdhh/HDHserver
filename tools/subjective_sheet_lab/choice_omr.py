from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from answer_sheet_v3_types import CANVAS_H, CANVAS_W, QUESTION_COUNT, AnswerBox, Point, Rect, SheetSpec, default_sheet_spec

REFERENCE_CROP_W: Final[int] = 485
REFERENCE_CROP_H: Final[int] = 116
BUBBLE_XS: Final[tuple[int, ...]] = (50, 145, 240, 335, 430)
BUBBLE_Y: Final[int] = 73
BUBBLE_RADIUS: Final[int] = 22
FILL_RADIUS: Final[int] = 14
MIN_MARK_SCORE: Final[float] = 0.18
MULTIPLE_MARK_SCORE: Final[float] = 0.16
MIN_SCORE_MARGIN: Final[float] = 0.08


@dataclass(frozen=True, slots=True)
class OmrReading:
    status: str
    selected: int | None
    scores: tuple[float, float, float, float, float]
    top_score: float
    margin: float
    reason: str

    @property
    def accepted(self) -> bool:
        return self.status == "accepted" and self.selected in range(1, 6)


def sheet_spec() -> SheetSpec:
    return default_sheet_spec()


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/malgunbd.ttf") if bold else Path("C:/Windows/Fonts/malgun.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf") if bold else Path("C:/Windows/Fonts/arial.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def draw_blank_sheet() -> Image.Image:
    spec = sheet_spec()
    image = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    draw = ImageDraw.Draw(image)
    draw_markers(draw, spec)
    draw_header(draw)
    draw_rows(draw, spec)
    return image


def draw_markers(draw: ImageDraw.ImageDraw, spec: SheetSpec) -> None:
    half = spec.marker_size // 2
    for point in spec.marker_centers:
        draw.rectangle((point.x - half, point.y - half, point.x + half, point.y + half), fill=(0, 0, 0))


def draw_header(draw: ImageDraw.ImageDraw) -> None:
    title = load_font(34, bold=True)
    body = load_font(23)
    small = load_font(18)
    draw.text((245, 104), "객관식 OMR 답안지 v1", fill=(25, 25, 25), font=title)
    draw.text((245, 154), "각 문항에서 1~5 중 하나의 원 안을 진하게 채우세요.", fill=(45, 45, 45), font=body)
    draw.text((245, 192), "숫자를 쓰지 마세요 | 원을 벗어나지 마세요 | 수정 시 새 답안지를 사용하세요.", fill=(65, 65, 65), font=small)
    draw.text((245, 245), "Name:", fill=(70, 70, 70), font=small)
    draw.line((315, 261, 610, 261), fill=(170, 170, 170), width=2)
    draw.text((680, 245), "Student ID:", fill=(70, 70, 70), font=small)
    draw.line((800, 261, 1165, 261), fill=(170, 170, 170), width=2)
    draw.line((190, 334, 1410, 334), fill=(210, 210, 210), width=2)


def draw_rows(draw: ImageDraw.ImageDraw, spec: SheetSpec) -> None:
    number_font = load_font(20, bold=True)
    choice_font = load_font(17, bold=True)
    for box in spec.boxes():
        outer = box.outer
        draw.rectangle((outer.x, outer.y, outer.right, outer.bottom), outline=(165, 165, 165), width=2)
        separator_x = outer.x + spec.answer_gutter_w - 3
        draw.line((separator_x, outer.y, separator_x, outer.bottom), fill=(185, 185, 185), width=2)
        draw.text((outer.x + 18, outer.y + 50), f"{box.question:02d}", fill=(55, 55, 55), font=number_font)
        for choice, relative_x in enumerate(BUBBLE_XS, start=1):
            center_x = box.crop.x + relative_x
            center_y = box.crop.y + BUBBLE_Y
            draw.text((center_x - 5, box.crop.y + 5), str(choice), fill=(70, 70, 70), font=choice_font)
            draw.ellipse(
                (
                    center_x - BUBBLE_RADIUS,
                    center_y - BUBBLE_RADIUS,
                    center_x + BUBBLE_RADIUS,
                    center_y + BUBBLE_RADIUS,
                ),
                outline=(85, 85, 85),
                width=3,
            )


def draw_answers(
    image: Image.Image,
    answers: dict[int, int | tuple[int, ...]],
    *,
    fill: tuple[int, int, int] = (20, 20, 20),
) -> Image.Image:
    output = image.copy()
    draw = ImageDraw.Draw(output)
    boxes = {box.question: box for box in sheet_spec().boxes()}
    for question, raw_choices in answers.items():
        choices = (raw_choices,) if isinstance(raw_choices, int) else raw_choices
        if question not in boxes:
            raise ValueError(f"question out of range: {question}")
        for choice in choices:
            if choice not in range(1, 6):
                raise ValueError(f"choice out of range: {choice}")
            center_x, center_y = bubble_center(boxes[question], choice)
            draw.ellipse(
                (
                    center_x - FILL_RADIUS,
                    center_y - FILL_RADIUS,
                    center_x + FILL_RADIUS,
                    center_y + FILL_RADIUS,
                ),
                fill=fill,
            )
    return output


def bubble_center(box: AnswerBox, choice: int) -> tuple[int, int]:
    return box.crop.x + BUBBLE_XS[choice - 1], box.crop.y + BUBBLE_Y


def detect_crop(path: Path) -> OmrReading:
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise OSError(f"cannot read OMR crop: {path}")
    return detect_crop_array(gray)


def detect_crop_array(gray: np.ndarray) -> OmrReading:
    if gray.ndim != 2 or gray.size == 0:
        raise ValueError("OMR crop must be a non-empty grayscale image")
    scale_x = gray.shape[1] / REFERENCE_CROP_W
    scale_y = gray.shape[0] / REFERENCE_CROP_H
    scores = tuple(
        mark_score(
            gray,
            int(round(relative_x * scale_x)),
            int(round(BUBBLE_Y * scale_y)),
            max(5, int(round(FILL_RADIUS * min(scale_x, scale_y)))),
        )
        for relative_x in BUBBLE_XS
    )
    order = sorted(range(5), key=lambda index: scores[index], reverse=True)
    top_index, second_index = order[0], order[1]
    top, second = scores[top_index], scores[second_index]
    margin = top - second
    marked = [index for index, score in enumerate(scores) if score >= MULTIPLE_MARK_SCORE]
    rounded = tuple(round(score, 6) for score in scores)
    if top < MIN_MARK_SCORE:
        return OmrReading("blank", None, rounded, round(top, 6), round(margin, 6), "no_filled_bubble")
    if len(marked) > 1:
        return OmrReading("multiple", None, rounded, round(top, 6), round(margin, 6), "multiple_filled_bubbles")
    if margin < MIN_SCORE_MARGIN:
        return OmrReading("ambiguous", None, rounded, round(top, 6), round(margin, 6), "low_score_margin")
    return OmrReading("accepted", top_index + 1, rounded, round(top, 6), round(margin, 6), "")


def mark_score(gray: np.ndarray, center_x: int, center_y: int, radius: int) -> float:
    y0, y1 = max(0, center_y - radius), min(gray.shape[0], center_y + radius + 1)
    x0, x1 = max(0, center_x - radius), min(gray.shape[1], center_x + radius + 1)
    region = gray[y0:y1, x0:x1].astype(np.float32)
    yy, xx = np.ogrid[y0:y1, x0:x1]
    disk = (xx - center_x) ** 2 + (yy - center_y) ** 2 <= radius**2
    if not np.any(disk):
        return 0.0

    local_radius = max(radius + 6, int(radius * 1.7))
    ly0, ly1 = max(0, center_y - local_radius), min(gray.shape[0], center_y + local_radius + 1)
    lx0, lx1 = max(0, center_x - local_radius), min(gray.shape[1], center_x + local_radius + 1)
    local = gray[ly0:ly1, lx0:lx1].astype(np.float32)
    local_background = float(np.percentile(local, 82))
    pixels = region[disk]
    contrast = np.clip(local_background - pixels, 0.0, 255.0)
    dark_fraction = float(np.mean(contrast >= 28.0))
    mean_darkness = float(np.mean(contrast) / 255.0)
    return 0.72 * dark_fraction + 0.28 * mean_darkness
