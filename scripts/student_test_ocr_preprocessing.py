"""Label-blind crop candidates for offline ablation; not a runtime default."""
from __future__ import annotations

VARIANTS = ("raw", "current", "border_ink")


def border_ink_crop(cv2, np, image):
    """Remove peripheral frame fragments, then preserve the remaining ink's aspect.

    Never erase long horizontal lines in the middle: they may be fraction bars.
    Peripheral removal is an experimental assumption, not evidence of correctness.
    """
    from scripts.student_test_sheet_crop_worker import _normalize_illumination

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    normalized = _normalize_illumination(cv2, gray)
    _, ink = cv2.threshold(normalized, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    height, width = ink.shape
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(20, int(width * .55))), np.uint8))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(16, int(height * .6)), 1), np.uint8))
    horizontal[int(height * .20):int(height * .88), :] = 0
    vertical[:, int(width * .08):int(width * .92)] = 0
    frame = cv2.bitwise_or(horizontal, vertical)
    frame = cv2.dilate(frame, np.ones((3, 3), np.uint8))
    filtered = cv2.bitwise_and(ink, cv2.bitwise_not(frame))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(filtered, connectivity=8)
    kept = np.zeros_like(ink)
    removed_components = 0
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        # Dotted guide remnants lie near an outer edge and are shallow. A tall
        # handwritten glyph beginning near an edge is retained, including roots.
        peripheral = ((y + h <= height * .23 or y >= height * .90) and h <= max(3, height * .055))
        peripheral |= ((x + w <= width * .06 or x >= width * .94) and w <= max(3, width * .018))
        if area < 2 or peripheral:
            removed_components += 1
            continue
        kept[labels == index] = 255
    points = cv2.findNonZero(kept)
    metadata = {"removedInkPixels": int(((ink > 0) & (kept == 0)).sum()),
                "inputInkPixels": int((ink > 0).sum()), "removedComponents": removed_components,
                "experimental": True}
    if points is None:
        metadata["blank"] = True
        return np.full_like(gray, 255), metadata
    x, y, w, h = cv2.boundingRect(points)
    padding = max(8, round(h * .15))
    content = 255 - kept[y:y+h, x:x+w]
    output = cv2.copyMakeBorder(content, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=255)
    metadata.update({"blank": False, "contentBox": [x, y, w, h], "padding": padding})
    return output, metadata


def prepare_crop(cv2, np, image, template, variant):
    if variant == "raw":
        return image.copy(), {"experimental": False}
    if variant == "current":
        from scripts.student_test_sheet_crop_worker import recognition_crop
        result, density = recognition_crop(cv2, np, image, template)
        return result, {"inkDensity": density, "experimental": False}
    if variant == "border_ink":
        return border_ink_crop(cv2, np, image)
    raise ValueError("unknown OCR preprocessing candidate")
