#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pillow",
# ]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run create_answer_sheet_v3.py
# 3. Or run with the local OCR runtime on this machine:
#      C:\server-ocr\.venv\Scripts\python.exe C:\server\tools\subjective_sheet_lab\create_answer_sheet_v3.py
# ──────────────────

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Final

from answer_sheet_v3_reports import write_markdown_reports
from answer_sheet_v3_types import (
    A4_DPI,
    A4_H_PX,
    A4_W_PX,
    CANVAS_H,
    CANVAS_W,
    QUESTION_COUNT,
    AnswerBox,
    DashLine,
    OutputPaths,
    Point,
    ProbeResult,
    Rect,
    SheetSpec,
    default_sheet_spec,
)
from PIL import Image, ImageDraw, ImageFont

SERVER_OCR_DIR: Final[Path] = Path("C:/server-ocr")
OUTPUT_DIR: Final[Path] = SERVER_OCR_DIR / "answer_sheet_v3"
LAB_DIR: Final[Path] = Path(__file__).resolve().parent
EXTRACTOR: Final[Path] = SERVER_OCR_DIR / "extract_answer_sheet_crops.py"
OCR_PYTHON: Final[Path] = SERVER_OCR_DIR / ".venv" / "Scripts" / "python.exe"


def sheet_spec() -> SheetSpec:
    return default_sheet_spec()


def output_paths() -> OutputPaths:
    return OutputPaths(
        canonical_png=OUTPUT_DIR / "answer_sheet_v3_warped_reference.png",
        a4_png=OUTPUT_DIR / "answer_sheet_v3_preview.png",
        pdf=OUTPUT_DIR / "answer_sheet_v3.pdf",
        coordinates_json=OUTPUT_DIR / "answer_sheet_v3_coordinates.json",
        coordinate_report=OUTPUT_DIR / "coordinate_spec_report.md",
        visual_qa_report=OUTPUT_DIR / "visual_qa_report.md",
        comparison_report=OUTPUT_DIR / "comparison_against_current.md",
        design_notes=LAB_DIR / "answer_sheet_v3_design_notes.md",
        probe_dir=OUTPUT_DIR / "crop_policy_probe",
    )


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/malgunbd.ttf") if bold else Path("C:/Windows/Fonts/malgun.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf") if bold else Path("C:/Windows/Fonts/arial.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def draw_sheet(spec: SheetSpec) -> Image.Image:
    image = Image.new("RGB", (spec.canvas.w, spec.canvas.h), "white")
    draw = ImageDraw.Draw(image)
    draw_markers(draw, spec)
    draw_header(draw)
    draw_answer_boxes(draw, spec)
    return image


def draw_markers(draw: ImageDraw.ImageDraw, spec: SheetSpec) -> None:
    half = spec.marker_size // 2
    for point in spec.marker_centers:
        draw.rectangle((point.x - half, point.y - half, point.x + half, point.y + half), fill=(0, 0, 0))


def draw_header(draw: ImageDraw.ImageDraw) -> None:
    title_font = load_font(34, bold=True)
    body_font = load_font(22)
    small_font = load_font(18)
    draw.text((245, 104), "주관식 답안지 v3", fill=(25, 25, 25), font=title_font)
    draw.text((245, 150), "칸 중앙에 크게 작성 | 아래 선에 붙이지 않기 | 칸 밖으로 나가지 않기", fill=(45, 45, 45), font=body_font)
    draw.text((245, 183), "0/6, 0/O, 1/7, x/n 구분 | ㄱ/ㄴ/ㄷ/ㄹ은 숫자처럼 쓰지 않기 | < 와 <= 명확히 작성", fill=(45, 45, 45), font=body_font)
    draw.text((245, 240), "Name:", fill=(70, 70, 70), font=small_font)
    draw.line((315, 256, 610, 256), fill=(170, 170, 170), width=2)
    draw.text((680, 240), "Student ID:", fill=(70, 70, 70), font=small_font)
    draw.line((800, 256, 1165, 256), fill=(170, 170, 170), width=2)
    draw.line((190, 334, 1410, 334), fill=(210, 210, 210), width=2)


def draw_answer_boxes(draw: ImageDraw.ImageDraw, spec: SheetSpec) -> None:
    number_font = load_font(20, bold=True)
    for box in spec.boxes():
        rect = box.outer
        draw.rectangle((rect.x, rect.y, rect.right, rect.bottom), outline=(150, 150, 150), width=2)
        separator_x = rect.x + spec.answer_gutter_w - 3
        draw.line((separator_x, rect.y, separator_x, rect.bottom), fill=(180, 180, 180), width=2)
        draw.text((rect.x + 18, rect.y + 21), f"{box.question:02d}", fill=(65, 65, 65), font=number_font)
        draw_safe_guides(draw, box)


def draw_safe_guides(draw: ImageDraw.ImageDraw, box: AnswerBox) -> None:
    fill = (235, 235, 235)
    left = box.crop.x + 26
    right = box.crop.right - 26
    draw_dashed(draw, DashLine(left, right, box.safe_mid_y, fill, 1, 18, 14))
    draw_dashed(draw, DashLine(left, right, box.safe_bottom_y, fill, 1, 16, 12))


def draw_dashed(draw: ImageDraw.ImageDraw, line: DashLine) -> None:
    x = line.x1
    while x < line.x2:
        end = min(x + line.dash, line.x2)
        draw.line((x, line.y, end, line.y), fill=line.fill, width=line.width)
        x = end + line.gap


def write_images(paths: OutputPaths, canonical: Image.Image) -> None:
    paths.canonical_png.parent.mkdir(parents=True, exist_ok=True)
    a4 = canonical.resize((A4_W_PX, A4_H_PX), Image.Resampling.LANCZOS)
    canonical.save(paths.canonical_png)
    a4.save(paths.a4_png)
    a4.save(paths.pdf, "PDF", resolution=A4_DPI)


def run_crop_probe(paths: OutputPaths) -> ProbeResult:
    paths.probe_dir.mkdir(parents=True, exist_ok=True)
    command = [str(OCR_PYTHON), str(EXTRACTOR), "--image", str(paths.a4_png), "--out-dir", str(paths.probe_dir)]
    try:
        completed = subprocess.run(
            command,
            cwd=SERVER_OCR_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30.0,
        )
    except OSError as exc:
        return ProbeResult(False, -1, "", str(exc), 0, 0, ())
    except subprocess.TimeoutExpired as exc:
        return ProbeResult(False, -2, str(exc.stdout or ""), str(exc.stderr or "timeout"), 0, 0, ())
    if completed.returncode != 0:
        return ProbeResult(False, completed.returncode, completed.stdout.strip(), completed.stderr.strip(), 0, 0, ())
    return summarize_probe(paths, completed.returncode, completed.stdout.strip(), completed.stderr.strip())


def summarize_probe(paths: OutputPaths, returncode: int, stdout: str, stderr: str) -> ProbeResult:
    crop_dir = paths.probe_dir / "crops"
    crop_paths = tuple(crop_dir / f"q{question:03d}.png" for question in range(1, QUESTION_COUNT + 1))
    sizes: list[str] = []
    for path in crop_paths:
        if path.is_file():
            with Image.open(path) as image:
                sizes.append(f"{path.name}:{image.width}x{image.height}")
    marker_count = marker_count_from(paths.probe_dir / "detected_markers.json")
    return ProbeResult(len(sizes) == QUESTION_COUNT and marker_count == 4, returncode, stdout, stderr, len(sizes), marker_count, tuple(sizes))


def marker_count_from(path: Path) -> int:
    if not path.is_file():
        return 0
    marker_payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(marker_payload, list):
        return len(marker_payload)
    return 0


def write_coordinate_json(paths: OutputPaths, spec: SheetSpec, probe: ProbeResult) -> None:
    payload = {
        "canvas": asdict(spec.canvas),
        "a4_preview_px": {"w": A4_W_PX, "h": A4_H_PX, "dpi": A4_DPI},
        "markers": [asdict(point) for point in spec.marker_centers],
        "marker_size": spec.marker_size,
        "marker_quiet_margin": spec.quiet_margin,
        "answer_boxes": [box_payload(box) for box in spec.boxes()],
        "crop_probe": asdict(probe),
    }
    paths.coordinates_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def box_payload(box: AnswerBox) -> dict[str, int | dict[str, int]]:
    return {
        "question": box.question,
        "outer": asdict(box.outer),
        "answer_crop": asdict(box.crop),
        "safe_top_y": box.safe_top_y,
        "safe_mid_y": box.safe_mid_y,
        "safe_bottom_y": box.safe_bottom_y,
    }


def main() -> None:
    spec = sheet_spec()
    paths = output_paths()
    canonical = draw_sheet(spec)
    write_images(paths, canonical)
    probe = run_crop_probe(paths)
    write_coordinate_json(paths, spec, probe)
    write_markdown_reports(paths, spec, probe)
    print(json.dumps({"ok": True, "out_dir": str(OUTPUT_DIR), "crop_probe_ok": probe.ok}, ensure_ascii=False))


if __name__ == "__main__":
    main()
