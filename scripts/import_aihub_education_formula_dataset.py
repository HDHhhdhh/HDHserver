from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Final

from scripts.import_aihub_education_choice_dataset import (
    annotation_image,
    build_image_index,
    crop_box,
    resolve_image,
)


SUPPORTED_GRADES: Final = frozenset({"M_G3", "H_G1", "H_G2", "H_G3"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert one approved AI Hub education OCR grade into formula crops."
    )
    parser.add_argument("--grade", required=True, choices=sorted(SUPPORTED_GRADES))
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="Zero keeps every eligible crop.")
    parser.add_argument("--max-per-writer", type=int, default=200)
    parser.add_argument("--minimum-side", type=int, default=8)
    parser.add_argument("--padding-ratio", type=float, default=0.08)
    parser.add_argument("--maximum-label-length", type=int, default=160)
    parser.add_argument("--seed", type=int, default=20260829)
    return parser.parse_args()


def dataset_grade_code(payload: object) -> str:
    dataset = payload.get("Dataset") if isinstance(payload, dict) else None
    label_path = str(dataset.get("label_path") or "") if isinstance(dataset, dict) else ""
    pieces = [piece.strip().upper() for piece in label_path.replace("\\", "/").split("/") if piece.strip()]
    if len(pieces) >= 2 and pieces[-2] in {"M", "H"} and pieces[-1] in {"G1", "G2", "G3"}:
        return f"{pieces[-2]}_{pieces[-1]}"
    return ""


def normalized_formula_boxes(payload: object, *, maximum_label_length: int = 160) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("Bbox"), list):
        return []
    boxes: list[dict] = []
    for raw in payload["Bbox"]:
        if not isinstance(raw, dict) or str(raw.get("type") or "").strip() != "2":
            continue
        equation = re.sub(r"\s+", " ", str(raw.get("data") or "")).strip().strip("$")
        xs = raw.get("x")
        ys = raw.get("y")
        if (
            not equation
            or len(equation) > max(1, int(maximum_label_length))
            or not isinstance(xs, list)
            or not isinstance(ys, list)
            or not xs
            or not ys
        ):
            continue
        try:
            x_values = [float(value) for value in xs]
            y_values = [float(value) for value in ys]
        except (TypeError, ValueError):
            continue
        boxes.append(
            {
                "id": str(raw.get("id") or ""),
                "equation": equation,
                "left": min(x_values),
                "top": min(y_values),
                "right": max(x_values),
                "bottom": max(y_values),
            }
        )
    return boxes


def formula_kind(equation: str) -> str:
    if "\\frac" in equation:
        return "fraction"
    if "\\sqrt" in equation or "√" in equation:
        return "root"
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", equation):
        return "number"
    return "other"


def convert(
    *,
    grade: str,
    labels_root: Path,
    images_root: Path,
    output_root: Path,
    limit: int = 0,
    max_per_writer: int = 200,
    minimum_side: int = 8,
    padding_ratio: float = 0.08,
    maximum_label_length: int = 160,
    seed: int = 20260829,
) -> dict:
    from PIL import Image, ImageOps

    normalized_grade = str(grade or "").strip().upper()
    if normalized_grade not in SUPPORTED_GRADES:
        raise ValueError("AI Hub formula grade is unsupported")
    labels_root = labels_root.resolve()
    images_root = images_root.resolve()
    output_root = output_root.resolve()
    if not labels_root.is_dir() or not images_root.is_dir():
        raise ValueError("AI Hub label and image roots must exist")
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("AI Hub formula output must be empty")
    image_output = output_root / "images"
    image_output.mkdir(parents=True, exist_ok=True)
    image_index = build_image_index(images_root)
    label_files = sorted(labels_root.rglob("*.json"))
    random.Random(seed).shuffle(label_files)
    writer_counts: Counter = Counter()
    kinds: Counter = Counter()
    skipped: Counter = Counter()
    coordinate_frames: Counter = Counter()
    selected_writers: set[str] = set()
    records: list[dict] = []
    for label_path in label_files:
        if limit > 0 and len(records) >= limit:
            break
        try:
            payload = json.loads(label_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            skipped["invalidJson"] += 1
            continue
        if dataset_grade_code(payload) != normalized_grade:
            skipped["gradeMismatch"] += 1
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
        images_metadata = payload.get("Images") if isinstance(payload, dict) else None
        writer = str(images_metadata.get("make_id") or "").strip() if isinstance(images_metadata, dict) else ""
        if not writer:
            writer = f"missing:{label_path.relative_to(labels_root).as_posix()}"
        writer_hash = hashlib.sha256(f"{normalized_grade}:{writer}".encode("utf-8")).hexdigest()[:20]
        boxes = normalized_formula_boxes(payload, maximum_label_length=maximum_label_length)
        random.Random(f"{seed}:{label_path.relative_to(labels_root).as_posix()}").shuffle(boxes)
        with Image.open(source) as opened:
            try:
                image, frame, _orientation = annotation_image(opened, payload)
            except ValueError:
                skipped["imageGeometryMismatch"] += 1
                continue
            coordinate_frames[frame] += 1
            for position, box in enumerate(boxes):
                if limit > 0 and len(records) >= limit:
                    break
                if max_per_writer > 0 and writer_counts[writer_hash] >= max_per_writer:
                    skipped["writerCap"] += 1
                    continue
                bounds = crop_box(
                    box,
                    width=image.width,
                    height=image.height,
                    padding_ratio=max(0.0, padding_ratio),
                )
                if bounds is None or min(bounds[2] - bounds[0], bounds[3] - bounds[1]) < max(1, minimum_side):
                    skipped["tinyBox"] += 1
                    continue
                source_token = hashlib.sha256(
                    f"{label_path.relative_to(labels_root).as_posix()}\n{box['id']}\n{position}".encode("utf-8")
                ).hexdigest()
                filename = f"{source_token[:28]}.png"
                target = image_output / filename
                crop = ImageOps.autocontrast(ImageOps.grayscale(image.crop(bounds))).convert("RGB")
                crop.save(target, format="PNG", optimize=True)
                equation = box["equation"]
                records.append(
                    {
                        "image": f"images/{filename}",
                        "equation": equation,
                        "grade": normalized_grade,
                        "writerHash": writer_hash,
                        "sourceHash": source_token,
                    }
                )
                writer_counts[writer_hash] += 1
                selected_writers.add(writer_hash)
                kinds[formula_kind(equation)] += 1
    records.sort(key=lambda item: item["image"])
    samples_path = output_root / "samples.jsonl"
    samples_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    summary = {
        "schema": "student_test_aihub_formula_crops_v1",
        "source": "AI Hub OCR data (education), approved local copy",
        "attribution": "한국지능정보사회진흥원 AI Hub",
        "grade": normalized_grade,
        "labelFilesScanned": len(label_files),
        "selectionSeed": int(seed),
        "maximumPerWriter": max(0, int(max_per_writer)),
        "count": len(records),
        "selectedWriters": len(selected_writers),
        "formulaKinds": dict(sorted(kinds.items())),
        "skipped": dict(sorted(skipped.items())),
        "cropGeometryVersion": "annotation-frame-exif-v2",
        "imageCoordinateFrames": dict(sorted(coordinate_frames.items())),
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
        grade=args.grade,
        labels_root=args.labels,
        images_root=args.images,
        output_root=args.output,
        limit=max(0, args.limit),
        max_per_writer=max(0, args.max_per_writer),
        minimum_side=max(1, args.minimum_side),
        padding_ratio=max(0.0, args.padding_ratio),
        maximum_label_length=max(1, args.maximum_label_length),
        seed=args.seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
