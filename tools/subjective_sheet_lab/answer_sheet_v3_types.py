from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

CANVAS_W: Final[int] = 1600
CANVAS_H: Final[int] = 2200
A4_W_PX: Final[int] = 2480
A4_H_PX: Final[int] = 3508
A4_DPI: Final[float] = 300.0
QUESTION_COUNT: Final[int] = 20


@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def intersects(self, other: Rect) -> bool:
        return self.x < other.right and self.right > other.x and self.y < other.bottom and self.bottom > other.y


@dataclass(frozen=True, slots=True)
class AnswerBox:
    question: int
    outer: Rect
    crop: Rect
    safe_top_y: int
    safe_mid_y: int
    safe_bottom_y: int


@dataclass(frozen=True, slots=True)
class SheetSpec:
    canvas: Rect
    marker_centers: tuple[Point, Point, Point, Point]
    marker_size: int
    quiet_margin: int
    left_outer_x: int
    right_outer_x: int
    outer_y0: int
    outer_w: int
    outer_h: int
    row_pitch: int
    answer_gutter_w: int

    def boxes(self) -> tuple[AnswerBox, ...]:
        boxes: list[AnswerBox] = []
        for question in range(1, QUESTION_COUNT + 1):
            column_x = self.left_outer_x if question <= 10 else self.right_outer_x
            row = (question - 1) % 10
            outer = Rect(column_x, self.outer_y0 + row * self.row_pitch, self.outer_w, self.outer_h)
            crop = Rect(outer.x + self.answer_gutter_w + 10, outer.y + 10, outer.w - self.answer_gutter_w - 30, outer.h - 20)
            boxes.append(
                AnswerBox(
                    question=question,
                    outer=outer,
                    crop=crop,
                    safe_top_y=crop.y + 26,
                    safe_mid_y=crop.y + crop.h // 2,
                    safe_bottom_y=crop.bottom - 34,
                )
            )
        return tuple(boxes)

    def marker_quiet_zones(self) -> tuple[Rect, Rect, Rect, Rect]:
        half = self.marker_size // 2 + self.quiet_margin
        return tuple(Rect(point.x - half, point.y - half, half * 2, half * 2) for point in self.marker_centers)


def default_sheet_spec() -> SheetSpec:
    return SheetSpec(
        canvas=Rect(0, 0, CANVAS_W, CANVAS_H),
        marker_centers=(Point(140, 140), Point(1460, 140), Point(1460, 2060), Point(140, 2060)),
        marker_size=64,
        quiet_margin=36,
        left_outer_x=200,
        right_outer_x=825,
        outer_y0=428,
        outer_w=600,
        outer_h=136,
        row_pitch=151,
        answer_gutter_w=85,
    )



@dataclass(frozen=True, slots=True)
class OutputPaths:
    canonical_png: Path
    a4_png: Path
    pdf: Path
    coordinates_json: Path
    coordinate_report: Path
    visual_qa_report: Path
    comparison_report: Path
    design_notes: Path
    probe_dir: Path


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    crop_count: int
    marker_count: int
    crop_sizes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DashLine:
    x1: int
    x2: int
    y: int
    fill: tuple[int, int, int]
    width: int
    dash: int
    gap: int
