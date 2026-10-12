from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Final, Mapping


SCHEMA: Final = "student_test_ocr_worker_v1"
ENGINE: Final = "choice_digit"
DEFAULT_MODEL_PATH: Final = Path(r"C:\server-ocr\choice_digit_classifier_v3\choice_digit_v3.pt")
V3_LABELS: Final = ("1", "2", "3", "4", "5")
REJECT_LABEL: Final = "__reject__"
V4_LABELS: Final = (*V3_LABELS, REJECT_LABEL)
_RUNTIME = None


class WorkerInputError(ValueError):
    pass


def parse_request(payload: object) -> list[tuple[int, Path]]:
    if not isinstance(payload, dict) or set(payload) != {"schema", "items"} or payload.get("schema") != SCHEMA:
        raise WorkerInputError("invalid worker request schema")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 20:
        raise WorkerInputError("worker request must contain 1 through 20 items")
    indexed: dict[int, Path] = {}
    for raw in raw_items:
        if not isinstance(raw, dict) or set(raw) != {"questionNo", "imagePath"}:
            raise WorkerInputError("worker item contract is invalid")
        number = raw.get("questionNo")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 20 or number in indexed:
            raise WorkerInputError("worker questions must be unique and between 1 and 20")
        path = Path(str(raw.get("imagePath") or "")).resolve()
        if not path.is_file():
            raise WorkerInputError(f"missing image for question {number}")
        indexed[number] = path
    return [(number, indexed[number]) for number in sorted(indexed)]


def build_model(torch, *, output_count: int):
    nn = torch.nn

    class DigitNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 32, 3, padding=1),
                nn.BatchNorm2d(32),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(32, 64, 3, padding=1),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(64, 96, 3, padding=1),
                nn.BatchNorm2d(96),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(96, 128, 3, padding=1),
                nn.BatchNorm2d(128),
                nn.ReLU(inplace=True),
                nn.AdaptiveAvgPool2d(1),
            )
            self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(0.15), nn.Linear(128, output_count))

        def forward(self, value):
            return self.classifier(self.features(value))

    return DigitNet()


def checkpoint_contract(checkpoint: object) -> tuple[str, tuple[str, ...], int]:
    if not isinstance(checkpoint, dict):
        raise RuntimeError("choice digit checkpoint is invalid")
    model_version = str(checkpoint.get("model_version") or "")
    labels = tuple(str(value) for value in checkpoint.get("labels") or ())
    if model_version == "choice_digit_v3" and labels == V3_LABELS:
        return model_version, labels, int(checkpoint.get("input_size") or 48)
    if model_version == "choice_digit_v4" and labels == V4_LABELS:
        return model_version, labels, int(checkpoint.get("input_size") or 48)
    raise RuntimeError("choice digit model contract is unsupported")


def worker_decision(rows, *, minimum: float, margin_minimum: float) -> dict:
    if len(rows) != 2:
        raise RuntimeError("choice digit worker requires two preprocessing variants")
    agreed = bool(rows[0][0] and rows[0][0] == rows[1][0])
    score = min(float(rows[0][1]), float(rows[1][1]))
    margin = min(float(rows[0][2]), float(rows[1][2]))
    label = str(rows[0][0])
    rejected = agreed and label == REJECT_LABEL
    accepted = agreed and not rejected and score >= minimum and margin >= margin_minimum
    return {
        "text": "" if label == REJECT_LABEL else label,
        "score": score,
        "margin": margin,
        "variantText": "" if str(rows[1][0]) == REJECT_LABEL else str(rows[1][0]),
        "variantAgreed": agreed,
        "accepted": accepted,
        "blank": False,
        "rejected": rejected,
    }


def _center_mask(cv2, np, mask, input_size: int):
    points = cv2.findNonZero(mask)
    canvas = np.zeros((input_size, input_size), dtype=np.float32)
    if points is None:
        return canvas
    x, y, width, height = cv2.boundingRect(points)
    content = mask[y : y + height, x : x + width]
    target_extent = max(12, input_size - 10)
    scale = min(target_extent / max(1, width), target_extent / max(1, height))
    resized = cv2.resize(
        content,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    moments = cv2.moments(resized)
    center_x = resized.shape[1] / 2
    center_y = resized.shape[0] / 2
    if moments["m00"]:
        center_x = moments["m10"] / moments["m00"]
        center_y = moments["m01"] / moments["m00"]
    target_x = round(input_size / 2 - center_x)
    target_y = round(input_size / 2 - center_y)
    x0 = max(0, target_x)
    y0 = max(0, target_y)
    source_x = max(0, -target_x)
    source_y = max(0, -target_y)
    copy_width = min(resized.shape[1] - source_x, input_size - x0)
    copy_height = min(resized.shape[0] - source_y, input_size - y0)
    if copy_width > 0 and copy_height > 0:
        canvas[y0 : y0 + copy_height, x0 : x0 + copy_width] = (
            resized[source_y : source_y + copy_height, source_x : source_x + copy_width] / 255.0
        )
    return canvas


def prepare_array_variants(cv2, np, gray, input_size: int):
    _threshold, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        21,
        9,
    )
    for mask in (otsu, adaptive):
        mask[:2, :] = 0
        mask[-2:, :] = 0
        mask[:, :2] = 0
        mask[:, -2:] = 0
    density = float((otsu > 0).mean())
    if density < 0.002:
        return (), density
    return (
        _center_mask(cv2, np, otsu, input_size),
        _center_mask(cv2, np, adaptive, input_size),
    ), density


def prepare_variants(cv2, np, path: Path, input_size: int):
    encoded = np.fromfile(str(path), dtype=np.uint8)
    gray = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE) if encoded.size else None
    if gray is None:
        raise RuntimeError("choice image could not be decoded")
    return prepare_array_variants(cv2, np, gray, input_size)


def load_runtime():
    import cv2
    import numpy as np
    import torch

    model_path = Path(os.environ.get("STUDENT_TEST_OCR_CHOICE_MODEL_PATH", str(DEFAULT_MODEL_PATH))).resolve()
    if not model_path.is_file():
        raise RuntimeError("choice digit model is missing")
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
    _model_version, labels, input_size = checkpoint_contract(checkpoint)
    model = build_model(torch, output_count=len(labels))
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    return cv2, np, torch, model, labels, input_size, checkpoint


def cached_runtime():
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = load_runtime()
    return _RUNTIME


def run(items: list[tuple[int, Path]]) -> list[dict]:
    cv2, np, torch, model, labels, input_size, checkpoint = cached_runtime()
    minimum = float(checkpoint.get("confidence_threshold") or 0.995)
    margin_minimum = float(checkpoint.get("margin_threshold") or 0.9)
    output: list[dict] = []
    for number, path in items:
        variants, density = prepare_variants(cv2, np, path, input_size)
        if not variants:
            output.append(
                {
                    "questionNo": number,
                    "text": "",
                    "score": None,
                    "margin": None,
                    "variantText": "",
                    "variantAgreed": False,
                    "accepted": False,
                    "blank": True,
                    "rejected": False,
                    "inkDensity": round(density, 6),
                }
            )
            continue
        batch = torch.from_numpy(np.stack(variants)[:, None, :, :]).float()
        with torch.inference_mode():
            probabilities = torch.softmax(model(batch), dim=1)
        rows = []
        for probability in probabilities:
            values, indices = torch.topk(probability, k=2)
            top_index = int(indices[0])
            score = float(values[0])
            margin = float(values[0] - values[1])
            rows.append((labels[top_index], score, margin))
        decision = worker_decision(rows, minimum=minimum, margin_minimum=margin_minimum)
        output.append(
            {
                "questionNo": number,
                **decision,
                "inkDensity": round(density, 6),
            }
        )
    return output


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    if sys.argv[1:] == ["--serve-jsonl"]:
        if __package__:
            from .student_test_ocr_worker_server import serve
        else:
            from student_test_ocr_worker_server import serve
        return serve(engine=ENGINE, parse_request=parse_request, run=lambda items, options: run(items))
    try:
        payload = json.load(sys.stdin)
        items = parse_request(payload)
        result = run(items)
    except Exception as error:
        emit({"ok": False, "engine": ENGINE, "error": type(error).__name__})
        print(f"{ENGINE} worker failed: {error}", file=sys.stderr)
        return 1
    emit({"ok": True, "engine": ENGINE, "items": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
