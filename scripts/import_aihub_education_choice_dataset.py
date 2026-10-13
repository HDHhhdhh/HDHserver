from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Final


CHOICE_LABELS: Final = ("1", "2", "3", "4", "5")
REJECT_LABEL: Final = "__reject__"
IMAGE_SUFFIXES: Final = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert approved AI Hub education OCR Bbox annotations into choice/reject crops."
    )
    parser.add_argument("--labels", type=Path, required=True, help="One approved split's label root.")
    parser.add_argument("--images", type=Path, required=True, help="The matching image root.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--choice-limit-per-class", type=int, default=0, help="Zero keeps every crop.")
    parser.add_argument("--reject-limit", type=int, default=0, help="Zero keeps every reject crop.")
    parser.add_argument("--minimum-side", type=int, default=8)
    parser.add_argument("--padding-ratio", type=float, default=0.12)
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--max-choice-per-writer", type=int, default=8)
    parser.add_argument("--max-reject-per-writer", type=int, default=16)
    return parser.parse_args()


def normalized_boxes(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("Bbox"), list):
        return []
    boxes = []
    for raw in payload["Bbox"]:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("data") or "").strip()
        xs = raw.get("x")
        ys = raw.get("y")
        if not text or not isinstance(xs, list) or not isinstance(ys, list) or not xs or not ys:
            continue
        try:
            x_values = [float(value) for value in xs]
            y_values = [float(value) for value in ys]
        except (TypeError, ValueError):
            continue
        boxes.append(
            {
                "id": str(raw.get("id") or ""),
                "text": text,
                "label": text if text in CHOICE_LABELS else REJECT_LABEL,
                "left": min(x_values),
                "top": min(y_values),
                "right": max(x_values),
                "bottom": max(y_values),
            }
        )
    return boxes


def image_filename(payload: object) -> str:
    images = payload.get("Images") if isinstance(payload, dict) else None
    if not isinstance(images, dict):
        return ""
    identifier = Path(str(images.get("identifier") or "")).name
    if not identifier:
        return ""
    if Path(identifier).suffix.lower() in IMAGE_SUFFIXES:
        return identifier
    extension = str(images.get("type") or "png").strip().lower().lstrip(".")
    return f"{identifier}.{extension}"


def build_image_index(root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            index.setdefault(path.name.casefold(), path.resolve())
    return index


def resolve_image(
    *,
    payload: object,
    label_path: Path,
    labels_root: Path,
    images_root: Path,
    image_index: dict[str, Path],
) -> Path | None:
    name = image_filename(payload)
    if not name:
        return None
    relative_parent = label_path.relative_to(labels_root).parent
    candidates = (images_root / relative_parent / name, images_root / name)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(images_root) and resolved.is_file():
            return resolved
    return image_index.get(name.casefold())


def crop_box(box: dict, *, width: int, height: int, padding_ratio: float) -> tuple[int, int, int, int] | None:
    left = float(box["left"])
    top = float(box["top"])
    right = float(box["right"])
    bottom = float(box["bottom"])
    padding = max(right - left, bottom - top) * max(0.0, float(padding_ratio))
    x0 = max(0, int(left - padding))
    y0 = max(0, int(top - padding))
    x1 = min(width, int(right + padding + 1))
    y1 = min(height, int(bottom + padding + 1))
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def ink_square(image, bounds):
    from PIL import Image, ImageOps

    gray = ImageOps.grayscale(image.crop(bounds))
    ink = ImageOps.invert(ImageOps.autocontrast(gray))
    side = max(ink.width, ink.height)
    canvas = Image.new("L", (side, side), 0)
    canvas.paste(ink, ((side - ink.width) // 2, (side - ink.height) // 2))
    return canvas


def selected(counter: Counter, label: str, *, choice_limit: int, reject_limit: int) -> bool:
    limit = reject_limit if label == REJECT_LABEL else choice_limit
    return limit <= 0 or counter[label] < limit


def convert(
    *,
    labels_root: Path,
    images_root: Path,
    output_root: Path,
    choice_limit: int,
    reject_limit: int,
    minimum_side: int,
    padding_ratio: float,
    seed: int = 20260829,
    max_choice_per_writer: int = 8,
    max_reject_per_writer: int = 16,
) -> dict:
    from PIL import Image

    labels_root = labels_root.resolve()
    images_root = images_root.resolve()
    output_root = output_root.resolve()
    if not labels_root.is_dir() or not images_root.is_dir():
        raise ValueError("AI Hub label and image roots must exist")
    for label in (*CHOICE_LABELS, REJECT_LABEL):
        (output_root / label).mkdir(parents=True, exist_ok=True)
    image_index = build_image_index(images_root)
    counts: Counter = Counter()
    writer_counts: Counter = Counter()
    selected_writers = {label: set() for label in (*CHOICE_LABELS, REJECT_LABEL)}
    skipped: Counter = Counter()
    label_files = sorted(labels_root.rglob("*.json"))
    random.Random(seed).shuffle(label_files)
    for label_path in label_files:
        try:
            payload = json.loads(label_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            skipped["invalidJson"] += 1
            continue
        source = resolve_image(
            payload=payload,
            label_path=label_path,
            labels_root=labels_root,
            images_root=images_root,
            image_index=image_index,
        )
        if source is None:
            skipped["missingImage"] += 1
            continue
        boxes = normalized_boxes(payload)
        random.Random(f"{seed}:{label_path.relative_to(labels_root).as_posix()}").shuffle(boxes)
        images_metadata = payload.get("Images") if isinstance(payload, dict) else None
        writer = str(images_metadata.get("make_id") or "").strip() if isinstance(images_metadata, dict) else ""
        if not writer:
            writer = f"missing:{label_path.relative_to(labels_root).as_posix()}"
        with Image.open(source) as image:
            for position, box in enumerate(boxes):
                label = box["label"]
                if not selected(counts, label, choice_limit=choice_limit, reject_limit=reject_limit):
                    continue
                writer_limit = max_reject_per_writer if label == REJECT_LABEL else max_choice_per_writer
                if writer_limit > 0 and writer_counts[(writer, label)] >= writer_limit:
                    skipped["writerCap"] += 1
                    continue
                bounds = crop_box(box, width=image.width, height=image.height, padding_ratio=padding_ratio)
                if bounds is None or min(bounds[2] - bounds[0], bounds[3] - bounds[1]) < minimum_side:
                    skipped["tinyBox"] += 1
                    continue
                token = hashlib.sha256(
                    f"{label_path.relative_to(labels_root).as_posix()}\n{box['id']}\n{position}".encode("utf-8")
                ).hexdigest()[:24]
                target = output_root / label / f"{token}.png"
                if not target.exists():
                    ink_square(image, bounds).save(target, format="PNG", optimize=True)
                counts[label] += 1
                writer_counts[(writer, label)] += 1
                selected_writers[label].add(writer)
        if all(
            not selected(counts, label, choice_limit=choice_limit, reject_limit=reject_limit)
            for label in (*CHOICE_LABELS, REJECT_LABEL)
        ):
            break
    summary = {
        "schema": "student_test_aihub_choice_crops_v1",
        "source": "AI Hub OCR data (education), approved local copy",
        "labelFilesScanned": len(label_files),
        "selectionSeed": int(seed),
        "writerCaps": {
            "choicePerWriter": max(0, int(max_choice_per_writer)),
            "rejectPerWriter": max(0, int(max_reject_per_writer)),
        },
        "counts": {label: counts[label] for label in (*CHOICE_LABELS, REJECT_LABEL)},
        "selectedWriters": {label: len(selected_writers[label]) for label in (*CHOICE_LABELS, REJECT_LABEL)},
        "skipped": dict(sorted(skipped.items())),
        "answerKeyFieldsUsed": 0,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    args = parse_args()
    summary = convert(
        labels_root=args.labels,
        images_root=args.images,
        output_root=args.output,
        choice_limit=max(0, args.choice_limit_per_class),
        reject_limit=max(0, args.reject_limit),
        minimum_side=max(1, args.minimum_side),
        padding_ratio=max(0.0, args.padding_ratio),
        seed=args.seed,
        max_choice_per_writer=max(0, args.max_choice_per_writer),
        max_reject_per_writer=max(0, args.max_reject_per_writer),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
