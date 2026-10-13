from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.import_aihub_education_choice_dataset import (
    REJECT_LABEL,
    convert,
    image_filename,
    normalized_boxes,
)


def run() -> dict:
    from PIL import Image, ImageDraw

    assertions = 0
    payload = {
        "Images": {"identifier": "page001", "type": "png"},
        "Bbox": [
            {"id": 1, "data": "1", "x": [10, 10, 30, 30], "y": [10, 40, 10, 40]},
            {"id": 2, "data": "12", "x": [45, 45, 80, 80], "y": [10, 40, 10, 40]},
            {"id": 3, "data": "", "x": [1], "y": [1]},
        ],
    }
    boxes = normalized_boxes(payload)
    assert [box["label"] for box in boxes] == ["1", REJECT_LABEL]
    assert image_filename(payload) == "page001.png"
    assertions += 2

    with tempfile.TemporaryDirectory(prefix="student-test-aihub-import-") as temp_dir:
        root = Path(temp_dir)
        labels = root / "labels" / "nested"
        images = root / "images" / "nested"
        output = root / "output"
        labels.mkdir(parents=True)
        images.mkdir(parents=True)
        source = Image.new("RGB", (100, 60), "white")
        draw = ImageDraw.Draw(source)
        draw.text((12, 12), "1", fill="black")
        draw.text((48, 12), "12", fill="black")
        source.save(images / "page001.png")
        (labels / "page001.json").write_text(json.dumps(payload), encoding="utf-8")

        summary = convert(
            labels_root=root / "labels",
            images_root=root / "images",
            output_root=output,
            choice_limit=0,
            reject_limit=0,
            minimum_side=4,
            padding_ratio=0.1,
            seed=17,
            max_choice_per_writer=8,
            max_reject_per_writer=16,
        )
        assert summary["counts"]["1"] == 1 and summary["counts"][REJECT_LABEL] == 1
        assert summary["answerKeyFieldsUsed"] == 0
        assert summary["selectionSeed"] == 17
        assert summary["writerCaps"] == {"choicePerWriter": 8, "rejectPerWriter": 16}
        assert len(list((output / "1").glob("*.png"))) == 1
        assert len(list((output / REJECT_LABEL).glob("*.png"))) == 1
        assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["schema"] == "student_test_aihub_choice_crops_v1"
        with Image.open(next((output / "1").glob("*.png"))) as crop:
            assert crop.mode == "L" and crop.width == crop.height
        assertions += 8

    return {"name": "student-test-aihub-import", "assertions": assertions, "passed": True}


if __name__ == "__main__":
    result = run()
    print(f"{result['name']} passed: {result['assertions']} assertions")
