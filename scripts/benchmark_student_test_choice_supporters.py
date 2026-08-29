from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.student_test_ocr_rules import CHOICE_NUMBER, normalize_recognized_answer


WORKER_SCHEMA = "student_test_ocr_worker_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Blindly compare the local choice classifier alone with Paddle agreement."
    )
    parser.add_argument("--crops", type=Path, required=True)
    parser.add_argument("--transcription", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--choice-model", type=Path, required=True)
    parser.add_argument("--choice-python", type=Path, required=True)
    parser.add_argument("--paddle-python", type=Path, required=True)
    parser.add_argument("--paddle-model-dir", type=Path, required=True)
    parser.add_argument("--paddle-cache-dir", type=Path, required=True)
    parser.add_argument("--choice-confidence", type=float, default=0.995)
    parser.add_argument("--choice-margin", type=float, default=0.90)
    parser.add_argument("--paddle-confidence", type=float, default=0.98)
    return parser.parse_args()


def human_labels(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, list):
        raise ValueError("human transcription answers are missing")
    labels = {}
    for answer in answers:
        if not isinstance(answer, dict) or str(answer.get("confidence") or "").lower() != "high":
            continue
        value = str(answer.get("human_answer") or "").strip()
        if value in {"1", "2", "3", "4", "5"}:
            labels[int(answer["question_no"])] = value
    return labels


def recognition_crops(crops: Path, template: Path, output: Path) -> list[tuple[int, Path]]:
    import cv2
    import numpy as np

    from scripts.student_test_sheet_crop_worker import fixed_boxes, recognition_crop

    template_bytes = np.fromfile(str(template.resolve()), dtype=np.uint8)
    template_gray = cv2.imdecode(template_bytes, cv2.IMREAD_GRAYSCALE)
    if template_gray is None:
        raise ValueError("answer-sheet template could not be decoded")
    template_gray = cv2.resize(template_gray, (1600, 2200), interpolation=cv2.INTER_AREA)
    boxes = fixed_boxes()
    items = []
    for number in range(1, 21):
        source = crops / f"q{number:03d}.png"
        encoded = np.fromfile(str(source.resolve()), dtype=np.uint8)
        raw = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
        if raw is None:
            raise ValueError(f"crop {number} could not be decoded")
        x, y, width, height = boxes[number]
        template_crop = template_gray[y : y + height, x : x + width]
        if template_crop.shape[:2] != raw.shape[:2]:
            template_crop = cv2.resize(template_crop, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_AREA)
        cleaned, _density = recognition_crop(cv2, np, raw, template_crop)
        target = output / f"q{number:03d}.png"
        ok, content = cv2.imencode(".png", cleaned)
        if not ok:
            raise ValueError(f"recognition crop {number} could not be encoded")
        content.tofile(str(target))
        items.append((number, target))
    return items


def run_worker(python_path: Path, script: Path, items, environment: dict[str, str]) -> dict[int, dict]:
    payload = {
        "schema": WORKER_SCHEMA,
        "items": [{"questionNo": number, "imagePath": str(path)} for number, path in items],
    }
    completed = subprocess.run(
        [str(python_path.resolve()), "-B", str(script.resolve())],
        input=json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
        env={**os.environ, **environment},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "worker failed")
    response = json.loads(completed.stdout.strip().splitlines()[-1])
    if response.get("ok") is not True or not isinstance(response.get("items"), list):
        raise RuntimeError("worker returned an invalid response")
    return {int(item["questionNo"]): item for item in response["items"]}


def evaluate(labels: dict[int, str], digit: dict[int, dict], paddle: dict[int, dict], args) -> dict:
    rows = []
    for number, expected in sorted(labels.items()):
        digit_item = digit[number]
        digit_value = normalize_recognized_answer(CHOICE_NUMBER, digit_item.get("text"))
        digit_confident = bool(
            digit_item.get("variantAgreed") is True
            and digit_value
            and float(digit_item.get("score") or 0) >= args.choice_confidence
            and float(digit_item.get("margin") or 0) >= args.choice_margin
        )
        paddle_item = paddle[number]
        paddle_value = normalize_recognized_answer(CHOICE_NUMBER, paddle_item.get("text"))
        paddle_variant = normalize_recognized_answer(CHOICE_NUMBER, paddle_item.get("variantText"))
        paddle_confident = bool(
            paddle_item.get("variantAgreed") is True
            and paddle_value
            and paddle_value == paddle_variant
            and float(paddle_item.get("score") or 0) >= args.paddle_confidence
            and float(paddle_item.get("variantScore") or 0) >= args.paddle_confidence
        )
        consensus = digit_confident and paddle_confident and digit_value == paddle_value
        rows.append(
            {
                "questionNo": number,
                "humanLabel": expected,
                "digit": digit_value,
                "digitConfident": digit_confident,
                "digitCorrect": digit_value == expected,
                "paddle": paddle_value,
                "paddleConfident": paddle_confident,
                "paddleCorrect": paddle_value == expected,
                "consensusAccepted": consensus,
                "consensusCorrect": consensus and digit_value == expected,
            }
        )
    digit_accepted = [row for row in rows if row["digitConfident"]]
    consensus_accepted = [row for row in rows if row["consensusAccepted"]]
    return {
        "evaluated": len(rows),
        "digitOnly": {
            "accepted": len(digit_accepted),
            "wrong": sum(not row["digitCorrect"] for row in digit_accepted),
        },
        "paddle": {
            "confident": sum(row["paddleConfident"] for row in rows),
            "wrongWhenConfident": sum(row["paddleConfident"] and not row["paddleCorrect"] for row in rows),
        },
        "consensus": {
            "accepted": len(consensus_accepted),
            "wrong": sum(not row["consensusCorrect"] for row in consensus_accepted),
        },
        "rows": rows,
        "answerKeyFieldsUsed": 0,
        "providerCallCount": 0,
    }


def main() -> int:
    args = parse_args()
    labels = human_labels(args.transcription.resolve())
    with tempfile.TemporaryDirectory(prefix="choice-supporter-benchmark-") as temp_dir:
        items = recognition_crops(args.crops.resolve(), args.template.resolve(), Path(temp_dir))
        digit = run_worker(
            args.choice_python,
            ROOT / "scripts" / "student_test_choice_worker.py",
            items,
            {"STUDENT_TEST_OCR_CHOICE_MODEL_PATH": str(args.choice_model.resolve())},
        )
        paddle = run_worker(
            args.paddle_python,
            ROOT / "scripts" / "student_test_paddle_worker.py",
            items,
            {
                "STUDENT_TEST_OCR_DEVICE": "cpu",
                "STUDENT_TEST_OCR_PADDLE_MODEL_DIR": str(args.paddle_model_dir.resolve()),
                "STUDENT_TEST_OCR_PADDLE_CACHE_DIR": str(args.paddle_cache_dir.resolve()),
            },
        )
    print(json.dumps(evaluate(labels, digit, paddle, args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
