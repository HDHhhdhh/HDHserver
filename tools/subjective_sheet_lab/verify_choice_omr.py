from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Final

import cv2
import numpy as np
from PIL import Image

from answer_sheet_v3_types import A4_H_PX, A4_W_PX
from choice_omr import detect_crop, draw_answers, draw_blank_sheet

OCR_ROOT: Final[Path] = Path(r"C:\server-ocr")
OUTPUT_DIR: Final[Path] = OCR_ROOT / "choice_omr_v1"
EXTRACTOR: Final[Path] = OCR_ROOT / "extract_answer_sheet_crops.py"
OCR_PYTHON: Final[Path] = OCR_ROOT / ".venv" / "Scripts" / "python.exe"
EXPECTED: Final[dict[int, int]] = {question: (question - 1) % 5 + 1 for question in range(1, 21)}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scenarios: dict[str, dict[str, object]] = {}

    blank = draw_blank_sheet()
    blank_path = OUTPUT_DIR / "verify_blank.png"
    save_a4(blank, blank_path)
    blank_dir = OUTPUT_DIR / "verify_blank"
    extract(blank_path, blank_dir)
    blank_readings = [detect_crop(blank_dir / "crops" / f"q{question:03d}.png") for question in range(1, 21)]
    scenarios["blank"] = {
        "evaluated": 20,
        "blank": sum(item.status == "blank" for item in blank_readings),
        "false_accepted": sum(item.accepted for item in blank_readings),
    }

    marked = draw_answers(blank, EXPECTED)
    clean_path = OUTPUT_DIR / "verify_clean.png"
    save_a4(marked, clean_path)
    scenarios["clean"] = evaluate_sheet(clean_path, OUTPUT_DIR / "verify_clean", EXPECTED)

    photo_path = OUTPUT_DIR / "verify_photo_like.jpg"
    save_photo_like(marked, photo_path)
    scenarios["photo_like"] = evaluate_sheet(photo_path, OUTPUT_DIR / "verify_photo_like", EXPECTED)

    multiple_answers: dict[int, int | tuple[int, ...]] = dict(EXPECTED)
    multiple_answers[1] = (2, 4)
    multiple_path = OUTPUT_DIR / "verify_multiple.png"
    save_a4(draw_answers(blank, multiple_answers), multiple_path)
    multiple_dir = OUTPUT_DIR / "verify_multiple"
    extract(multiple_path, multiple_dir)
    first = detect_crop(multiple_dir / "crops" / "q001.png")
    remaining = {
        question: EXPECTED[question]
        for question in range(2, 21)
    }
    remaining_metrics = evaluate_crop_dir(multiple_dir / "crops", remaining)
    scenarios["multiple"] = {
        "q001_status": first.status,
        "q001_accepted": first.accepted,
        "q001_scores": first.scores,
        "remaining": remaining_metrics,
    }

    wrong_auto = sum(
        int(metrics.get("wrong_auto_grades", 0))
        for name, metrics in scenarios.items()
        if name in {"clean", "photo_like"}
    )
    ok = (
        scenarios["blank"]["blank"] == 20
        and scenarios["blank"]["false_accepted"] == 0
        and scenarios["clean"]["correct"] == 20
        and scenarios["photo_like"]["correct"] == 20
        and scenarios["multiple"]["q001_status"] == "multiple"
        and scenarios["multiple"]["remaining"]["correct"] == 19
        and wrong_auto == 0
    )
    report = {
        "ok": ok,
        "format": "choice_omr_v1",
        "scenarios": scenarios,
        "wrong_auto_grades": wrong_auto,
        "provider_call_count": 0,
        "external_ocr_api_call_count": 0,
        "submit_test_call_count": 0,
        "production_route_modified": False,
        "scope": "synthetic_lab_only",
    }
    report_path = OUTPUT_DIR / "verification_metrics.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": ok, "report": str(report_path), "scenarios": scenarios}, ensure_ascii=False, indent=2))
    return 0 if ok else 2


def save_a4(canonical: Image.Image, path: Path) -> None:
    canonical.resize((A4_W_PX, A4_H_PX), Image.Resampling.LANCZOS).save(path)


def save_photo_like(canonical: Image.Image, path: Path) -> None:
    rgb = np.asarray(canonical.resize((A4_W_PX, A4_H_PX), Image.Resampling.LANCZOS))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    target = np.float32([[32, 45], [width - 48, 18], [width - 24, height - 38], [46, height - 12]])
    matrix = cv2.getPerspectiveTransform(source, target)
    warped = cv2.warpPerspective(bgr, matrix, (width, height), borderValue=(255, 255, 255))
    gradient = np.linspace(1.03, 0.78, width, dtype=np.float32)[None, :, None]
    shaded = np.clip(warped.astype(np.float32) * gradient, 0, 255).astype(np.uint8)
    blurred = cv2.GaussianBlur(shaded, (3, 3), 0.7)
    cv2.imwrite(str(path), blurred, [cv2.IMWRITE_JPEG_QUALITY, 84])


def evaluate_sheet(image_path: Path, output_dir: Path, expected: dict[int, int]) -> dict[str, object]:
    extract(image_path, output_dir)
    return evaluate_crop_dir(output_dir / "crops", expected)


def evaluate_crop_dir(crop_dir: Path, expected: dict[int, int]) -> dict[str, object]:
    correct = 0
    accepted = 0
    wrong_auto = 0
    statuses: dict[str, int] = {}
    rows: list[dict[str, object]] = []
    for question, answer in sorted(expected.items()):
        reading = detect_crop(crop_dir / f"q{question:03d}.png")
        statuses[reading.status] = statuses.get(reading.status, 0) + 1
        accepted += int(reading.accepted)
        is_correct = reading.accepted and reading.selected == answer
        correct += int(is_correct)
        wrong_auto += int(reading.accepted and reading.selected != answer)
        rows.append(
            {
                "question": question,
                "selected": reading.selected,
                "status": reading.status,
                "correct": is_correct,
                "top_score": reading.top_score,
                "margin": reading.margin,
            }
        )
    return {
        "evaluated": len(expected),
        "correct": correct,
        "accepted": accepted,
        "wrong_auto_grades": wrong_auto,
        "statuses": statuses,
        "rows": rows,
    }


def extract(image_path: Path, output_dir: Path) -> None:
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
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"crop extraction failed for {image_path.name}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    crops = tuple((output_dir / "crops").glob("q*.png"))
    if len(crops) != 20:
        raise RuntimeError(f"crop extraction returned {len(crops)} crops for {image_path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
