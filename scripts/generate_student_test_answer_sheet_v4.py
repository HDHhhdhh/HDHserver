from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CANVAS_WIDTH = 1600
CANVAS_HEIGHT = 2200
MARKER_CENTERS = ((140, 140), (1460, 140), (1460, 2060), (140, 2060))
MARKER_SIZE = 64
QUIET_MARGIN = 36


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the ArUco v4 fixed student answer sheet.")
    parser.add_argument("--source-preview", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    source_path = args.source_preview.resolve()
    output_dir = args.output_dir.resolve()
    if not source_path.is_file():
        raise ValueError("v3 source preview is missing")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("v4 output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)

    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    encoded = np.fromfile(str(source_path), dtype=np.uint8)
    source = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    if source is None:
        raise ValueError("v3 source preview could not be decoded")
    height, width = source.shape[:2]
    scale_x = width / CANVAS_WIDTH
    scale_y = height / CANVAS_HEIGHT
    physical_marker_size = max(48, round(MARKER_SIZE * min(scale_x, scale_y)))
    clear_half_width = round((MARKER_SIZE / 2 + QUIET_MARGIN) * scale_x)
    clear_half_height = round((MARKER_SIZE / 2 + QUIET_MARGIN) * scale_y)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    output = source.copy()
    markers = []
    for marker_id, (center_x, center_y) in enumerate(MARKER_CENTERS):
        pixel_x = round(center_x * scale_x)
        pixel_y = round(center_y * scale_y)
        cv2.rectangle(
            output,
            (pixel_x - clear_half_width, pixel_y - clear_half_height),
            (pixel_x + clear_half_width, pixel_y + clear_half_height),
            (255, 255, 255),
            thickness=-1,
        )
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, physical_marker_size, borderBits=1)
        marker_bgr = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        x0 = pixel_x - physical_marker_size // 2
        y0 = pixel_y - physical_marker_size // 2
        output[y0 : y0 + physical_marker_size, x0 : x0 + physical_marker_size] = marker_bgr
        markers.append(
            {
                "id": marker_id,
                "centerCanonical": [center_x, center_y],
                "centerPreview": [pixel_x, pixel_y],
                "previewSize": physical_marker_size,
            }
        )

    pil = Image.fromarray(cv2.cvtColor(output, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    title_left = round(198 * scale_x)
    title_top = round(76 * scale_y)
    title_right = round(640 * scale_x)
    title_bottom = round(148 * scale_y)
    draw.rectangle((title_left, title_top, title_right, title_bottom), fill="white")
    font_path = Path(r"C:\Windows\Fonts\malgunbd.ttf")
    font = ImageFont.truetype(str(font_path), max(20, round(31 * scale_y))) if font_path.is_file() else ImageFont.load_default()
    draw.text((title_left, title_top), "주관식 답안지 v4", fill="black", font=font)
    output = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

    preview_path = output_dir / "answer_sheet_v4_preview.png"
    preview_ok, preview_bytes = cv2.imencode(".png", output)
    if not preview_ok:
        raise RuntimeError("v4 preview encoding failed")
    preview_bytes.tofile(str(preview_path))
    warped = cv2.resize(output, (CANVAS_WIDTH, CANVAS_HEIGHT), interpolation=cv2.INTER_AREA)
    warped_path = output_dir / "answer_sheet_v4_warped_reference.png"
    warped_ok, warped_bytes = cv2.imencode(".png", warped)
    if not warped_ok:
        raise RuntimeError("v4 template encoding failed")
    warped_bytes.tofile(str(warped_path))
    pdf_path = output_dir / "answer_sheet_v4.pdf"
    Image.fromarray(cv2.cvtColor(output, cv2.COLOR_BGR2RGB)).convert("RGB").save(
        pdf_path,
        "PDF",
        resolution=300.0,
    )
    coordinates_path = output_dir / "answer_sheet_v4_coordinates.json"
    coordinates = {
        "format": "student_test_answer_sheet_v4",
        "canvas": {"width": CANVAS_WIDTH, "height": CANVAS_HEIGHT},
        "markerDictionary": "DICT_4X4_50",
        "markers": markers,
        "markerSizeCanonical": MARKER_SIZE,
        "legacySquareCompatible": True,
        "files": {
            "preview": preview_path.name,
            "warpedReference": warped_path.name,
            "pdf": pdf_path.name,
        },
    }
    coordinates_path.write_text(json.dumps(coordinates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "ok": True,
        "outputDir": str(output_dir),
        "preview": str(preview_path),
        "warpedReference": str(warped_path),
        "pdf": str(pdf_path),
        "sha256": {path.name: sha256(path) for path in (preview_path, warped_path, pdf_path, coordinates_path)},
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
