from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Final

from PIL import Image

from answer_sheet_v3_types import A4_DPI, A4_H_PX, A4_W_PX
from choice_omr import (
    BUBBLE_RADIUS,
    BUBBLE_XS,
    BUBBLE_Y,
    REFERENCE_CROP_H,
    REFERENCE_CROP_W,
    draw_blank_sheet,
    sheet_spec,
)

OCR_ROOT: Final[Path] = Path(r"C:\server-ocr")
OUTPUT_DIR: Final[Path] = OCR_ROOT / "choice_omr_v1"
EXTRACTOR: Final[Path] = OCR_ROOT / "extract_answer_sheet_crops.py"
OCR_PYTHON: Final[Path] = OCR_ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    canonical = draw_blank_sheet()
    canonical_path = OUTPUT_DIR / "choice_omr_v1_warped_reference.png"
    preview_path = OUTPUT_DIR / "choice_omr_v1_preview.png"
    pdf_path = OUTPUT_DIR / "choice_omr_v1.pdf"
    canonical.save(canonical_path)
    preview = canonical.resize((A4_W_PX, A4_H_PX), Image.Resampling.LANCZOS)
    preview.save(preview_path)
    preview.save(pdf_path, "PDF", resolution=A4_DPI)

    probe = run_crop_probe(preview_path, OUTPUT_DIR / "crop_policy_probe")
    coordinates = {
        "format": "choice_omr_v1",
        "canvas": {"w": canonical.width, "h": canonical.height},
        "markers": [asdict(point) for point in sheet_spec().marker_centers],
        "reference_crop": {"w": REFERENCE_CROP_W, "h": REFERENCE_CROP_H},
        "bubble_relative_centers": [
            {"choice": choice, "x": x, "y": BUBBLE_Y, "radius": BUBBLE_RADIUS}
            for choice, x in enumerate(BUBBLE_XS, start=1)
        ],
        "crop_probe": probe,
        "provider_call_count": 0,
        "submit_flow_touched": False,
        "production_route_modified": False,
    }
    (OUTPUT_DIR / "choice_omr_v1_coordinates.json").write_text(
        json.dumps(coordinates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": bool(probe["ok"]),
                "output_dir": str(OUTPUT_DIR),
                "pdf": str(pdf_path),
                "crop_probe": probe,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if probe["ok"] else 2


def run_crop_probe(image_path: Path, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            str(OCR_PYTHON),
            str(EXTRACTOR),
            "--image",
            str(image_path),
            "--out-dir",
            str(output_dir),
            "--strict-answer-boxes",
        ],
        cwd=OCR_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=45,
    )
    crops = tuple(sorted((output_dir / "crops").glob("q*.png")))
    marker_path = output_dir / "detected_markers.json"
    markers = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.is_file() else []
    return {
        "ok": completed.returncode == 0 and len(crops) == 20 and isinstance(markers, list) and len(markers) == 4,
        "returncode": completed.returncode,
        "crop_count": len(crops),
        "marker_count": len(markers) if isinstance(markers, list) else 0,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
