from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Final, Mapping


SCHEMA: Final = "student_test_sheet_crop_worker_v1"
ENGINE: Final = "crop"
CANVAS_WIDTH: Final = 1600
CANVAS_HEIGHT: Final = 2200
QUESTION_COUNT: Final = 20
LEFT_X: Final = 295
RIGHT_X: Final = 920
CROP_Y0: Final = 438
CROP_W: Final = 485
CROP_H: Final = 116
ROW_PITCH: Final = 151
MARKER_SIZE: Final = 64
MARKER_CENTERS: Final = (
    (140.0, 140.0),
    (1460.0, 140.0),
    (1460.0, 2060.0),
    (140.0, 2060.0),
)


class CropWorkerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Marker:
    x: int
    y: int
    width: int
    height: int
    area: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)


@dataclass(frozen=True, slots=True)
class DocumentTransform:
    matrix: object
    marker_mode: str
    reprojection_error: float


@dataclass(frozen=True, slots=True)
class AnswerBoxDetection:
    boxes: dict[int, tuple[int, int, int, int]]
    source: str
    detected_rect_count: int
    left_column_count: int
    right_column_count: int


def _inside(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as error:
        raise CropWorkerError("asset path escapes the configured root") from error
    return resolved


def parse_request(payload: object, *, asset_root: Path) -> tuple[Path, Path]:
    if not isinstance(payload, dict) or set(payload) != {"schema", "imagePath", "outputDir"}:
        raise CropWorkerError("invalid crop worker request")
    if payload.get("schema") != SCHEMA:
        raise CropWorkerError("unsupported crop worker schema")
    image_path = _inside(asset_root, Path(str(payload.get("imagePath") or "")))
    output_dir = _inside(asset_root, Path(str(payload.get("outputDir") or "")))
    if not image_path.is_file():
        raise CropWorkerError("capture image is missing")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise CropWorkerError("crop output directory is not empty")
    return image_path, output_dir


def _marker_candidates(cv2, image, threshold) -> list[Marker]:
    contours, _ = cv2.findContours(threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = image.shape[0] * image.shape[1]
    candidates: list[Marker] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        if not image_area * 0.00025 <= area <= image_area * 0.01:
            continue
        ratio = width / max(1, height)
        extent = area / max(1, width * height)
        if 0.65 <= ratio <= 1.35 and extent >= 0.55:
            candidates.append(Marker(x, y, width, height, area))
    return candidates


def find_legacy_markers(cv2, image) -> tuple[Marker, Marker, Marker, Marker]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found: list[Marker] = []
    for threshold_value in (50, 70, 90, 110):
        _, threshold = cv2.threshold(gray, threshold_value, 255, cv2.THRESH_BINARY_INV)
        found.extend(_marker_candidates(cv2, image, threshold))
    deduped: list[Marker] = []
    for candidate in sorted(found, key=lambda item: item.area, reverse=True):
        x, y = candidate.center
        if all(abs(x - other.center[0]) > 12 or abs(y - other.center[1]) > 12 for other in deduped):
            deduped.append(candidate)
    if len(deduped) < 4:
        raise CropWorkerError("marker_detection_failed")
    top_left = min(deduped, key=lambda marker: marker.center[0] + marker.center[1])
    top_right = max(deduped, key=lambda marker: marker.center[0] - marker.center[1])
    bottom_right = max(deduped, key=lambda marker: marker.center[0] + marker.center[1])
    bottom_left = min(deduped, key=lambda marker: marker.center[0] - marker.center[1])
    selected = (top_left, top_right, bottom_right, bottom_left)
    if len({marker.center for marker in selected}) != 4:
        raise CropWorkerError("marker_selection_failed")
    return selected


def _aruco_destination_points(np, marker_id: int):
    center_x, center_y = MARKER_CENTERS[marker_id]
    half = MARKER_SIZE / 2
    return np.array(
        [
            [center_x - half, center_y - half],
            [center_x + half, center_y - half],
            [center_x + half, center_y + half],
            [center_x - half, center_y + half],
        ],
        dtype=np.float32,
    )


def document_transform(cv2, np, image) -> DocumentTransform:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    aruco = getattr(cv2, "aruco", None)
    if aruco is not None and hasattr(aruco, "ArucoDetector"):
        parameters = aruco.DetectorParameters()
        if hasattr(aruco, "CORNER_REFINE_SUBPIX"):
            parameters.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX
        detector = aruco.ArucoDetector(aruco.getPredefinedDictionary(aruco.DICT_4X4_50), parameters)
        corners, ids, _rejected = detector.detectMarkers(gray)
        by_id: dict[int, object] = {}
        if ids is not None:
            for marker_corners, raw_id in zip(corners, ids.reshape(-1)):
                marker_id = int(raw_id)
                if marker_id in range(4) and marker_id not in by_id:
                    by_id[marker_id] = marker_corners.reshape(4, 2).astype(np.float32)
        if set(by_id) == {0, 1, 2, 3}:
            source = np.concatenate([by_id[marker_id] for marker_id in range(4)], axis=0)
            destination = np.concatenate(
                [_aruco_destination_points(np, marker_id) for marker_id in range(4)],
                axis=0,
            )
            matrix, inliers = cv2.findHomography(source, destination, cv2.RANSAC, 3.0)
            if matrix is not None and inliers is not None and int(inliers.sum()) >= 12:
                projected = cv2.perspectiveTransform(source.reshape(-1, 1, 2), matrix).reshape(-1, 2)
                error = float(np.linalg.norm(projected - destination, axis=1).mean())
                if error <= 8.0:
                    return DocumentTransform(matrix, "aruco_4x4_50", error)

    markers = find_legacy_markers(cv2, image)
    source_points = np.array([marker.center for marker in markers], dtype=np.float32)
    destination_points = np.array(MARKER_CENTERS, dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source_points, destination_points)
    return DocumentTransform(matrix, "legacy_square", 0.0)


def fixed_boxes() -> dict[int, tuple[int, int, int, int]]:
    boxes = {}
    for question_no in range(1, QUESTION_COUNT + 1):
        column = 0 if question_no <= 10 else 1
        row = (question_no - 1) % 10
        boxes[question_no] = (
            LEFT_X if column == 0 else RIGHT_X,
            CROP_Y0 + row * ROW_PITCH,
            CROP_W,
            CROP_H,
        )
    return boxes


def _answer_region(rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x, y, width, height = rect
    return (x + 95, y + 10, max(1, width - 115), max(1, height - 20))


def _full_width_rects(rects: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    return [rect for rect in rects if rect[2] >= 450 and 90 <= rect[3] <= 170]


def _clustered_rows(values: list[int]) -> list[int]:
    rows: list[list[int]] = []
    for value in sorted(values):
        if not rows or value - rows[-1][-1] > 35:
            rows.append([value])
        else:
            rows[-1].append(value)
    return [int(round(median(row))) for row in rows]


def _column_geometry(rects: list[tuple[int, int, int, int]]) -> tuple[int, int, int]:
    return (
        int(round(median(rect[0] for rect in rects))),
        int(round(median(rect[2] for rect in rects))),
        int(round(median(rect[3] for rect in rects))),
    )


def _repaired_grid(
    left_column: list[tuple[int, int, int, int]],
    right_column: list[tuple[int, int, int, int]],
) -> dict[int, tuple[int, int, int, int]] | None:
    left_full = _full_width_rects(left_column)
    right_full = _full_width_rects(right_column)
    if len(left_full) < 6 or len(right_full) < 6:
        return None
    row_ys = _clustered_rows([rect[1] for rect in left_full + right_full])
    if len(row_ys) < 8:
        return None
    gaps = [right - left for left, right in zip(row_ys, row_ys[1:]) if right - left > 40]
    if not gaps:
        return None
    pitch = int(round(median(gaps)))
    if not 125 <= pitch <= 175:
        return None
    top_y = min(row_ys)
    left_x, left_width, left_height = _column_geometry(left_full)
    right_x, right_width, right_height = _column_geometry(right_full)
    boxes: dict[int, tuple[int, int, int, int]] = {}
    for row in range(10):
        y = int(round(top_y + row * pitch))
        boxes[row + 1] = _answer_region((left_x, y, left_width, left_height))
        boxes[row + 11] = _answer_region((right_x, y, right_width, right_height))
    return boxes


def detect_answer_boxes(cv2, np, warped) -> AnswerBoxDetection:
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    dilated = cv2.dilate(edges, np.ones((3, 3), dtype=np.uint8), iterations=1)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if 100 <= x <= 1200 and 300 <= y <= 2000 and 350 <= width <= 650 and 60 <= height <= 170:
            rects.append((x, y, width, height))
    left_column = sorted((rect for rect in rects if rect[0] < CANVAS_WIDTH // 2), key=lambda item: item[1])
    right_column = sorted((rect for rect in rects if rect[0] >= CANVAS_WIDTH // 2), key=lambda item: item[1])
    if len(rects) == QUESTION_COUNT and len(left_column) == 10 and len(right_column) == 10:
        boxes: dict[int, tuple[int, int, int, int]] = {}
        for row in range(10):
            boxes[row + 1] = _answer_region(left_column[row])
            boxes[row + 11] = _answer_region(right_column[row])
        return AnswerBoxDetection(boxes, "detected", len(rects), len(left_column), len(right_column))
    repaired = _repaired_grid(left_column, right_column)
    if repaired is not None:
        return AnswerBoxDetection(
            repaired,
            "detected_grid_repaired",
            len(rects),
            len(left_column),
            len(right_column),
        )
    return AnswerBoxDetection(fixed_boxes(), "fixed_fallback", len(rects), len(left_column), len(right_column))


def crop_warnings(cv2, gray, box: tuple[int, int, int, int], ink_density: float) -> list[str]:
    x, y, width, height = box
    crop = gray[y : y + height, x : x + width]
    blur = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    brightness = float(crop.mean())
    contrast = float(crop.std())
    warnings: list[str] = []
    if blur < 12:
        warnings.append("crop_blurry")
    if brightness < 45 or brightness > 248:
        warnings.append("crop_exposure")
    if contrast < 8:
        warnings.append("crop_low_contrast")
    if ink_density < 0.0015:
        warnings.append("crop_blank_like")
    return warnings


def _decode_image(cv2, np, path: Path):
    encoded = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None


def _load_template(cv2, np):
    template_text = os.environ.get("STUDENT_TEST_OCR_TEMPLATE_PATH", "").strip()
    if not template_text:
        return None
    template_path = Path(template_text).resolve()
    if not template_path.is_file():
        return None
    template = _decode_image(cv2, np, template_path)
    if template is None:
        return None
    if template.shape[:2] != (CANVAS_HEIGHT, CANVAS_WIDTH):
        template = cv2.resize(template, (CANVAS_WIDTH, CANVAS_HEIGHT), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)


def _normalize_illumination(cv2, gray):
    background = cv2.GaussianBlur(gray, (0, 0), 15)
    return cv2.divide(gray, background, scale=255)


def recognition_crop(cv2, np, raw_crop, template_crop):
    gray = cv2.cvtColor(raw_crop, cv2.COLOR_BGR2GRAY)
    normalized = _normalize_illumination(cv2, gray)
    if template_crop is None:
        template_normalized = np.full_like(normalized, 255)
    else:
        template_normalized = _normalize_illumination(cv2, template_crop)
    difference = cv2.absdiff(normalized, template_normalized)
    ink = ((normalized < 205) & ((difference > 16) | (template_normalized > 225))) | (normalized < 120)
    mask = np.where(ink, 255, 0).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), dtype=np.uint8))

    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    filtered = np.zeros_like(mask)
    for component in range(1, component_count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        if area >= 3:
            filtered[labels == component] = 255
    ink_density = float((filtered > 0).mean())

    cleaned = np.full_like(gray, 255)
    cleaned[filtered > 0] = 0
    points = cv2.findNonZero(filtered)
    if points is None:
        return cleaned, ink_density
    x, y, width, height = cv2.boundingRect(points)
    padding = 8
    x0 = max(0, x - padding)
    y0 = max(0, y - padding)
    x1 = min(cleaned.shape[1], x + width + padding)
    y1 = min(cleaned.shape[0], y + height + padding)
    content = cleaned[y0:y1, x0:x1]
    target = np.full_like(cleaned, 255)
    maximum_width = target.shape[1] - 24
    maximum_height = target.shape[0] - 16
    scale = min(1.0, maximum_width / max(1, content.shape[1]), maximum_height / max(1, content.shape[0]))
    if scale < 1.0:
        content = cv2.resize(
            content,
            (max(1, round(content.shape[1] * scale)), max(1, round(content.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
    target_y = (target.shape[0] - content.shape[0]) // 2
    target_x = (target.shape[1] - content.shape[1]) // 2
    target[target_y : target_y + content.shape[0], target_x : target_x + content.shape[1]] = content
    return target, ink_density


def process(image_path: Path, output_dir: Path) -> dict:
    import cv2
    import numpy as np

    image = _decode_image(cv2, np, image_path)
    if image is None:
        raise CropWorkerError("capture_decode_failed")
    transform = document_transform(cv2, np, image)
    warped = cv2.warpPerspective(
        image,
        transform.matrix,
        (CANVAS_WIDTH, CANVAS_HEIGHT),
        flags=cv2.INTER_LINEAR,
        borderValue=(255, 255, 255),
    )
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    contrast = float(gray.std())
    small = cv2.resize(gray, (20, 20), interpolation=cv2.INTER_AREA)
    shadow_spread = float(np.percentile(small, 95) - np.percentile(small, 5))
    failures: list[str] = []
    if blur < 8:
        failures.append("blur_detected")
    if brightness < 45 or brightness > 248:
        failures.append("exposure_out_of_range")
    if contrast < 8:
        failures.append("low_contrast_detected")
    if shadow_spread > 180:
        failures.append("shadow_detected")
    detection = detect_answer_boxes(cv2, np, warped)
    if detection.source == "fixed_fallback":
        failures.append("answer_box_detection_failed")

    output_dir.mkdir(parents=True, exist_ok=True)
    template_gray = _load_template(cv2, np)
    boxes = detection.boxes
    items: list[dict] = []
    for question_no in range(1, QUESTION_COUNT + 1):
        x, y, width, height = boxes[question_no]
        crop = warped[y : y + height, x : x + width]
        crop_path = output_dir / f"q{question_no:03d}.png"
        recognition_path = output_dir / f"q{question_no:03d}-recognition.png"
        encoded_ok, encoded_crop = cv2.imencode(".png", crop)
        if not encoded_ok:
            raise CropWorkerError("crop_write_failed")
        encoded_crop.tofile(str(crop_path))
        template_crop = None if template_gray is None else template_gray[y : y + height, x : x + width]
        cleaned, ink_density = recognition_crop(cv2, np, crop, template_crop)
        recognition_ok, encoded_recognition = cv2.imencode(".png", cleaned)
        if not recognition_ok:
            raise CropWorkerError("recognition_crop_write_failed")
        encoded_recognition.tofile(str(recognition_path))
        warnings = crop_warnings(cv2, gray, boxes[question_no], ink_density)
        items.append(
            {
                "questionNo": question_no,
                "imagePath": str(crop_path),
                "recognitionImagePath": str(recognition_path),
                "warnings": warnings,
                "blockingWarnings": [
                    warning for warning in warnings if warning in {"crop_exposure", "crop_blank_like"}
                ],
                "inkDensity": round(ink_density, 6),
            }
        )
    return {
        "quality": {
            "ok": not failures,
            "failures": failures,
            "blurVariance": round(blur, 3),
            "brightnessMean": round(brightness, 3),
            "brightnessStd": round(contrast, 3),
            "shadowSpread": round(shadow_spread, 3),
            "markerMode": transform.marker_mode,
            "reprojectionErrorPx": round(transform.reprojection_error, 3),
            "templateApplied": template_gray is not None,
            "answerBoxSource": detection.source,
            "detectedRectCount": detection.detected_rect_count,
            "leftColumnCount": detection.left_column_count,
            "rightColumnCount": detection.right_column_count,
        },
        "items": items,
    }


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        asset_root_text = os.environ.get("STUDENT_TEST_OCR_ASSET_ROOT", "").strip()
        if not asset_root_text:
            raise CropWorkerError("asset root is not configured")
        payload = json.load(sys.stdin)
        image_path, output_dir = parse_request(payload, asset_root=Path(asset_root_text))
        result = process(image_path, output_dir)
    except Exception as error:
        emit({"ok": False, "engine": ENGINE, "error": str(error)[:120]})
        print(f"{ENGINE} worker failed: {error}", file=sys.stderr)
        return 1
    emit({"ok": True, "engine": ENGINE, **result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
