from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

import cv2
import numpy as np
import torch
from torch import Tensor, nn

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

MODEL_VERSION: Final[str] = "choice_digit_v1"
LABELS: Final[tuple[str, ...]] = ("1", "2", "3", "4", "5")
LABEL_TO_INDEX: Final[dict[str, int]] = {label: index for index, label in enumerate(LABELS)}
INPUT_SIZE: Final[int] = 48
MIN_INK_RATIO: Final[float] = 0.0015
MAX_INK_RATIO: Final[float] = 0.35
MAX_FOREGROUND_WIDTH_RATIO: Final[float] = 0.55
DEFAULT_CONFIDENCE_THRESHOLD: Final[float] = 0.95
DEFAULT_MARGIN_THRESHOLD: Final[float] = 0.55
PREPROCESS_VARIANTS: Final[tuple[str, ...]] = ("otsu", "adaptive")


class ChoiceDigitError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class InkGeometry:
    ink_ratio: float
    foreground_width_ratio: float
    foreground_height_ratio: float
    component_count: int
    blank: bool
    invalid_reason: str = ""


@dataclass(frozen=True, slots=True)
class PreparedDigit:
    tensor: Tensor | None
    geometry: InkGeometry
    variant: str


@dataclass(frozen=True, slots=True)
class VariantPrediction:
    label: str
    confidence: float
    margin: float
    variant: str


@dataclass(frozen=True, slots=True)
class ChoiceDigitPrediction:
    label: str | None
    status: str
    confidence: float
    margin: float
    variants_agree: bool
    reason: str
    variant_predictions: tuple[VariantPrediction, ...]

    @property
    def accepted(self) -> bool:
        return self.status == "accepted" and self.label in LABELS


class ChoiceDigitNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 12, 3, padding=1, bias=False),
            nn.BatchNorm2d(12),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(12, 24, 3, padding=1, bias=False),
            nn.BatchNorm2d(24),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(24, 48, 3, padding=1, bias=False),
            nn.BatchNorm2d(48),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(48, 64, 3, padding=1, bias=False),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(0.2), nn.Linear(64, len(LABELS)))

    def forward(self, inputs: Tensor) -> Tensor:
        return self.classifier(self.features(inputs))


def read_grayscale(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ChoiceDigitError(f"cannot read crop image: {path}")
    return image


def prepare_digit(path: Path, variant: str = "otsu") -> PreparedDigit:
    return prepare_digit_array(read_grayscale(path), variant)


def prepare_digit_array(gray: np.ndarray, variant: str = "otsu") -> PreparedDigit:
    if gray.ndim != 2 or gray.size == 0:
        raise ChoiceDigitError("digit crop must be a non-empty grayscale image")
    if variant not in PREPROCESS_VARIANTS:
        raise ChoiceDigitError(f"unsupported preprocessing variant: {variant}")
    mask, multiple_clusters = select_digit_components(threshold_ink(gray, variant))
    geometry = ink_geometry(mask)
    if multiple_clusters and not geometry.blank:
        geometry = InkGeometry(
            geometry.ink_ratio,
            geometry.foreground_width_ratio,
            geometry.foreground_height_ratio,
            geometry.component_count,
            False,
            "multiple_or_overwritten_marks",
        )
    if geometry.blank or geometry.invalid_reason:
        return PreparedDigit(None, geometry, variant)
    centered = center_foreground(mask)
    return PreparedDigit(torch.from_numpy(centered.astype(np.float32) / 255.0).unsqueeze(0), geometry, variant)


def threshold_ink(gray: np.ndarray, variant: str) -> np.ndarray:
    image = gray.astype(np.uint8, copy=False)
    background = cv2.GaussianBlur(image, (0, 0), sigmaX=15, sigmaY=15)
    local_ink_contrast = cv2.subtract(background, image)
    threshold = 16 if variant == "otsu" else 24
    return (local_ink_contrast >= threshold).astype(np.uint8) * 255


def select_digit_components(mask: np.ndarray) -> tuple[np.ndarray, bool]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    candidates: list[tuple[int, int, int, int, int, int]] = []
    for component in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[component])
        density = area / max(1, width * height)
        if area < 20 or height < 12 or width > 130:
            continue
        center_x = x + width / 2
        if center_x < mask.shape[1] * 0.15 or center_x > mask.shape[1] * 0.75:
            continue
        if height > mask.shape[0] * 0.95 or density < 0.04:
            continue
        if height > mask.shape[0] * 0.75 and (
            x < mask.shape[1] * 0.15 or x + width > mask.shape[1] * 0.80
        ):
            continue
        candidates.append((area, component, x, y, width, height))
    if not candidates:
        return np.zeros_like(mask), False

    primary = max(candidates)
    primary_area, primary_component, px, py, pwidth, pheight = primary
    primary_cx, primary_cy = px + pwidth / 2, py + pheight / 2
    selected: list[int] = []
    multiple_clusters = False
    for area, component, x, y, width, height in candidates:
        cx, cy = x + width / 2, y + height / 2
        nearby = (
            abs(cx - primary_cx) <= max(35, pwidth * 1.2)
            and abs(cy - primary_cy) <= max(30, pheight * 0.7)
        )
        if component == primary_component or (area >= primary_area * 0.08 and nearby):
            selected.append(component)
        elif area >= primary_area * 0.35 and height >= pheight * 0.45:
            multiple_clusters = True

    cleaned = np.zeros_like(mask)
    for component in selected:
        cleaned[labels == component] = 255
    return cleaned, multiple_clusters


def ink_geometry(mask: np.ndarray) -> InkGeometry:
    ink = mask > 0
    ink_ratio = float(ink.mean())
    if ink_ratio < MIN_INK_RATIO:
        return InkGeometry(ink_ratio, 0.0, 0.0, 0, True)
    if ink_ratio > MAX_INK_RATIO:
        return InkGeometry(ink_ratio, 1.0, 1.0, 0, False, "excessive_ink")
    ys, xs = np.where(ink)
    width_ratio = float((int(xs.max()) - int(xs.min()) + 1) / mask.shape[1])
    height_ratio = float((int(ys.max()) - int(ys.min()) + 1) / mask.shape[0])
    components, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    substantial = sum(
        int(stats[index, cv2.CC_STAT_AREA]) >= max(12, int(mask.size * 0.0004))
        for index in range(1, components)
    )
    reason = ""
    if width_ratio > MAX_FOREGROUND_WIDTH_RATIO:
        reason = "multiple_or_overwritten_marks"
    elif height_ratio < 0.12:
        reason = "mark_too_short"
    elif substantial > 4:
        reason = "too_many_ink_components"
    return InkGeometry(ink_ratio, width_ratio, height_ratio, substantial, False, reason)


def center_foreground(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.where(mask > 0)
    if not len(xs):
        raise ChoiceDigitError("cannot center an empty foreground")
    glyph = mask[int(ys.min()) : int(ys.max()) + 1, int(xs.min()) : int(xs.max()) + 1]
    extent = INPUT_SIZE - 16
    scale = min(extent / glyph.shape[1], extent / glyph.shape[0])
    width = max(1, int(round(glyph.shape[1] * scale)))
    height = max(1, int(round(glyph.shape[0] * scale)))
    resized = cv2.resize(glyph, (width, height), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    canvas = np.zeros((INPUT_SIZE, INPUT_SIZE), dtype=np.uint8)
    x, y = (INPUT_SIZE - width) // 2, (INPUT_SIZE - height) // 2
    canvas[y : y + height, x : x + width] = resized
    return canvas


@torch.inference_mode()
def predict_array(
    model: nn.Module,
    gray: np.ndarray,
    *,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
) -> ChoiceDigitPrediction:
    model.eval()
    prepared = tuple(prepare_digit_array(gray, variant) for variant in PREPROCESS_VARIANTS)
    if all(item.geometry.blank for item in prepared):
        return ChoiceDigitPrediction(None, "blank", 0.0, 0.0, True, "blank_crop", ())
    invalid = next((item.geometry.invalid_reason for item in prepared if item.geometry.invalid_reason), "")
    if invalid:
        return ChoiceDigitPrediction(None, "rejected", 0.0, 0.0, False, invalid, ())
    if any(item.tensor is None for item in prepared):
        return ChoiceDigitPrediction(None, "rejected", 0.0, 0.0, False, "preprocess_disagreement", ())
    batch = torch.stack([item.tensor for item in prepared if item.tensor is not None])
    probabilities = torch.softmax(model(batch), dim=1)
    variants: list[VariantPrediction] = []
    for item, row in zip(prepared, probabilities, strict=True):
        values, indices = torch.topk(row, 2)
        variants.append(
            VariantPrediction(
                LABELS[int(indices[0])], float(values[0]), float(values[0] - values[1]), item.variant
            )
        )
    predictions = tuple(variants)
    agree = len({item.label for item in predictions}) == 1
    confidence = min(item.confidence for item in predictions)
    margin = min(item.margin for item in predictions)
    label = predictions[0].label if agree else None
    if not agree:
        return ChoiceDigitPrediction(None, "rejected", confidence, margin, False, "variant_disagreement", predictions)
    if confidence < confidence_threshold:
        return ChoiceDigitPrediction(label, "rejected", confidence, margin, True, "low_confidence", predictions)
    if margin < margin_threshold:
        return ChoiceDigitPrediction(label, "rejected", confidence, margin, True, "low_margin", predictions)
    return ChoiceDigitPrediction(label, "accepted", confidence, margin, True, "", predictions)


def predict_path(
    model: nn.Module,
    path: Path,
    *,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    margin_threshold: float = DEFAULT_MARGIN_THRESHOLD,
) -> ChoiceDigitPrediction:
    return predict_array(
        model,
        read_grayscale(path),
        confidence_threshold=confidence_threshold,
        margin_threshold=margin_threshold,
    )


def checkpoint_payload(
    model: nn.Module,
    *,
    confidence_threshold: float,
    margin_threshold: float,
    metadata: dict[str, JsonValue],
) -> dict[str, object]:
    return {
        "model_version": MODEL_VERSION,
        "labels": LABELS,
        "input_size": INPUT_SIZE,
        "confidence_threshold": float(confidence_threshold),
        "margin_threshold": float(margin_threshold),
        "model_state": model.state_dict(),
        "metadata": metadata,
    }


def load_checkpoint(path: Path) -> tuple[ChoiceDigitNet, float, float, dict[str, JsonValue]]:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, dict) or payload.get("model_version") != MODEL_VERSION:
        raise ChoiceDigitError("unsupported choice digit checkpoint")
    if tuple(payload.get("labels", ())) != LABELS or not isinstance(payload.get("model_state"), dict):
        raise ChoiceDigitError("checkpoint contract mismatch")
    model = ChoiceDigitNet()
    model.load_state_dict(payload["model_state"])
    model.eval()
    metadata = payload.get("metadata")
    return (
        model,
        float(payload.get("confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD)),
        float(payload.get("margin_threshold", DEFAULT_MARGIN_THRESHOLD)),
        metadata if isinstance(metadata, dict) else {},
    )
